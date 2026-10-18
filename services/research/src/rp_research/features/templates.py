"""M3 template import, safe analysis and sandboxed sample compilation."""

from __future__ import annotations

import io
import zipfile
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rp_contracts.hashing import content_hash, sha256_hex
    from rp_contracts.latexdoc import RenderOptions
    from rp_contracts.netpolicy import FetchBlocked
    from rp_contracts.scanning import sniff
    from rp_contracts.tasks import QUEUE_FETCH, QUEUE_LATEX, QUEUE_RESEARCH
    from rp_latex.adapters import sample_document
    from rp_latex.archive import ArchiveRejected, analyze, read_members
    from rp_latex.compile import compile_document, default_sandbox, sample_figure_pdf

    from ..api_client import ApiCallError, ApiClient
    from ..config import get_worker_settings
    from ..fetch.fetcher import ControlledFetcher, FetchFailed
    from ..registry import register
    from ..temporal_types import TaskInput, TaskOutcome
    from ..workflows.base import run_task
    from .common import app_error

ZIP_TYPES = {"application/zip", "application/x-zip-compressed", "application/octet-stream"}


def fetcher() -> ControlledFetcher:
    return ControlledFetcher()


@activity.defn
async def template_fetch(task_id: str, project_id: str, url: str) -> dict:
    try:
        res = await fetcher().fetch(url, accept_types=ZIP_TYPES, max_bytes=50 * 1024 * 1024)
    except (FetchBlocked, FetchFailed) as exc:
        raise app_error(exc) from exc
    if sniff(res.content) != "application/zip":
        from temporalio.exceptions import ApplicationError

        raise ApplicationError("the official link did not return a ZIP archive; supply the file with its declared "
                               "origin instead", type="not_a_zip", non_retryable=True)
    async with ApiClient(task_id) as api:
        try:
            art = await api.publish(project_id, "template_archive", res.content, "application/zip",
                                    sha256_hex(res.content), slot="archive", label=f"Template from {res.final_url}"[:300],
                                    metadata={"source_url": url, "final_url": res.final_url,
                                              "retrieved_at": res.retrieved_at.isoformat(),
                                              "hops": [h.__dict__ for h in res.hops]})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"archive_artifact_id": art.artifact_id, "retrieved_at": res.retrieved_at.isoformat()}


@activity.defn
async def template_analyze(task_id: str, project_id: str, template_id: str, archive_artifact_id: str,
                           retrieved_at: str | None) -> dict:
    async with ApiClient(task_id) as api:
        try:
            data = await api.read_artifact(archive_artifact_id)
            try:
                manifest = analyze(data)
            except ArchiveRejected as exc:
                return await api.post(f"/v1/internal/projects/{project_id}/templates/{template_id}/analysis",
                                      {"archive_artifact_id": archive_artifact_id, "rejected_reasons": exc.reasons,
                                       "retrieved_at": retrieved_at})
            mdict = manifest.to_dict()
            art = await api.publish_json(project_id, "template_manifest", mdict, sha256_hex(data), slot="manifest",
                                         depends_on=[archive_artifact_id], label=f"Template manifest ({manifest.family})")
            return await api.post(f"/v1/internal/projects/{project_id}/templates/{template_id}/analysis",
                                  {"archive_artifact_id": archive_artifact_id, "manifest_artifact_id": art.artifact_id,
                                   "manifest": mdict, "retrieved_at": retrieved_at})
        except ApiCallError as exc:
            raise app_error(exc) from exc


def prepare(data: bytes) -> tuple:
    m = analyze(data)
    files = read_members(data, m.root)
    strip = (m.root + "/") if m.root else ""
    protected = {p[len(strip):]: h for p, h in m.protected_hashes().items() if p.startswith(strip)}
    gen = [g[len(strip):] for g in m.generation_inputs]
    return m, files, protected, gen


def source_bundle(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()


@activity.defn
async def template_sample_compile(task_id: str, project_id: str, template_id: str, options: dict) -> dict:
    """Compile the fixed sample document in the template inside the no-network sandbox."""
    opts = RenderOptions(**options)
    async with ApiClient(task_id) as api:
        try:
            tpl = await api.get(f"/v1/internal/projects/{project_id}/templates/{template_id}")
            data = await api.read_artifact(tpl["archive_artifact_id"])
        except ApiCallError as exc:
            raise app_error(exc) from exc
        m, files, protected, gen = prepare(data)
        figures = {"sample-figure.pdf": sample_figure_pdf()}
        out = compile_document(family=m.family, template_files=files, protected=protected,
                               requires_generation=m.requires_generation, generation_inputs=gen,
                               bib_style=m.bibtex_style, doc=sample_document(), opts=opts, figures=figures,
                               sandbox=default_sandbox(get_worker_settings().latex_image))
        report = out.report.to_dict()
        imh = content_hash({"archive": tpl["archive_hash"], "options": opts.model_dump(), "kind": "sample"})
        slot = f"sample:{opts.mode}:{int(opts.anonymous)}:{opts.bib_mode}"
        try:
            rep = await api.publish_json(project_id, "compile_report", report, imh, slot=f"{slot}:report",
                                         depends_on=[tpl["archive_artifact_id"]], label=f"Sample compile report ({slot})")
            pdf_id = log_id = None
            if out.pdf:
                pdf_id = (await api.publish(project_id, "compiled_pdf", out.pdf, "application/pdf", imh, slot=f"{slot}:pdf",
                                            depends_on=[rep.artifact_id], label="Sample PDF")).artifact_id
            if out.log:
                log_id = (await api.publish(project_id, "compile_log", out.log.encode(), "text/plain", imh,
                                            slot=f"{slot}:log", label="Compile log")).artifact_id
            bundle = source_bundle({**out.source_files, **{f"figures/{k}": v for k, v in figures.items()}})
            bundle_id = (await api.publish(project_id, "latex_source_bundle", bundle, "application/zip", imh,
                                           slot=f"{slot}:bundle", label="Generated source (adapter output)")).artifact_id
            run = await api.post(f"/v1/internal/projects/{project_id}/compile-runs", {
                "template_id": template_id, "kind": "sample", "options": opts.model_dump(), "status": out.report.status,
                "report_artifact_id": rep.artifact_id, "pdf_artifact_id": pdf_id, "log_artifact_id": log_id,
                "source_bundle_artifact_id": bundle_id,
                "checks": [{"id": c["id"], "status": c["status"], "detail": c["detail"]} for c in report["checks"]],
                "pages": out.report.pages, "errors": out.report.errors[:20]})
            if out.report.duration_s:
                await api.record_usage(category="tex_compile", provider="latex_sandbox", units=out.report.duration_s,
                                       unit="seconds", stage="template_sample")
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"compile_run_id": run["id"], "status": out.report.status, "report_artifact_id": rep.artifact_id,
            "pdf_artifact_id": pdf_id}


RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=2),
                    maximum_attempts=3, non_retryable_error_types=["fetch_blocked", "not_a_zip"])


@workflow.defn(name="TemplateImportWorkflow")
class TemplateImportWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            p = inp.params
            retrieved = None
            archive = p.get("archive_artifact_id")
            if not archive:
                got = await workflow.execute_activity(template_fetch, args=[inp.task_id, inp.project_id, p["url"]],
                                                      task_queue=QUEUE_FETCH, start_to_close_timeout=timedelta(minutes=3),
                                                      retry_policy=RETRY)
                archive, retrieved = got["archive_artifact_id"], got["retrieved_at"]
            tpl = await workflow.execute_activity(template_analyze, args=[inp.task_id, inp.project_id, p["template_id"],
                                                                          archive, retrieved],
                                                  task_queue=QUEUE_LATEX, start_to_close_timeout=timedelta(minutes=2),
                                                  retry_policy=RETRY)
            outputs = [archive]
            results = []
            if tpl.get("supported"):
                variants = [{"anonymous": False, "bib_mode": "bibtex" if "bibtex" in tpl["bib_modes"] else "biber"},
                            {"anonymous": True, "bib_mode": "bibtex" if "bibtex" in tpl["bib_modes"] else "biber"}]
                if "biber" in tpl["bib_modes"] and "bibtex" in tpl["bib_modes"]:
                    variants.append({"anonymous": False, "bib_mode": "biber"})
                for v in variants:
                    r = await workflow.execute_activity(
                        template_sample_compile, args=[inp.task_id, inp.project_id, p["template_id"],
                                                       {"mode": p.get("mode", "submission"), **v}],
                        task_queue=QUEUE_LATEX, start_to_close_timeout=timedelta(minutes=10), retry_policy=RETRY)
                    results.append(r)
                    outputs.append(r["report_artifact_id"])
            return TaskOutcome(state="succeeded", output_artifact_ids=outputs,
                               result={"template_status": tpl.get("status"), "family": tpl.get("family"),
                                       "compiles": [{"status": r["status"]} for r in results]})
        return await run_task(inp, body)


@workflow.defn(name="CompileWorkflow")
class CompileWorkflow:
    """template_compile (sample) and manuscript_compile (M6/M7) both run here on the LaTeX queue."""

    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            p = inp.params
            if inp.kind == "template_compile":
                r = await workflow.execute_activity(template_sample_compile,
                                                    args=[inp.task_id, inp.project_id, p["template_id"], p["options"]],
                                                    task_queue=QUEUE_LATEX, start_to_close_timeout=timedelta(minutes=10),
                                                    retry_policy=RETRY)
                return TaskOutcome(state="succeeded", output_artifact_ids=[r["report_artifact_id"]], result=r)
            r = await workflow.execute_activity("manuscript_compile", args=[inp.task_id, inp.project_id, p],
                                                task_queue=QUEUE_LATEX, start_to_close_timeout=timedelta(minutes=10),
                                                retry_policy=RETRY)
            return TaskOutcome(state="succeeded", output_artifact_ids=[r["report_artifact_id"]], result=r)
        return await run_task(inp, body)


register(QUEUE_RESEARCH, workflows=[TemplateImportWorkflow])
register(QUEUE_LATEX, workflows=[CompileWorkflow], activities=[template_analyze, template_sample_compile])
register(QUEUE_FETCH, activities=[template_fetch])
