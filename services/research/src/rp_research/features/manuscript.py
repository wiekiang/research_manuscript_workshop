"""M6 workflows: section generation against a frozen brief/base version, and sandboxed manuscript compilation."""

from __future__ import annotations

from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rp_contracts.hashing import content_hash
    from rp_contracts.latexdoc import ManuscriptDocument, RenderOptions
    from rp_contracts.manuscript import ManuscriptContent, ManuscriptSection, Paragraph, Span
    from rp_contracts.tasks import QUEUE_LATEX, QUEUE_RESEARCH
    from rp_latex.compile import compile_document, default_sandbox

    from ..agents.base import run_agent
    from ..agents.writer import WRITER
    from ..api_client import ApiCallError, ApiClient
    from ..config import get_worker_settings
    from ..gateway import GatewayError, ModelGateway
    from ..gateway.providers import ProviderError
    from ..registry import register
    from ..temporal_types import TaskInput, TaskOutcome
    from ..workflows.base import run_task
    from .common import app_error, model_unavailable_reason
    from .templates import prepare, source_bundle


def to_section(draft: dict) -> ManuscriptSection:
    return ManuscriptSection(
        key=draft["key"], heading=draft["heading"], tables=draft.get("tables", []),
        paragraphs=[Paragraph(spans=[Span(span_id="", origin="ai", **sp) for sp in p["spans"]]) for p in draft["paragraphs"]])


@activity.defn
async def manuscript_generate(task_id: str, project_id: str, manuscript_id: str, instructions: str | None) -> dict:
    async with ApiClient(task_id) as api:
        g = await api.get(f"/v1/internal/manuscripts/{manuscript_id}/generation/{task_id}")
        if g["status"] != "pending":
            return {"status": g["status"], "candidate_id": g["candidate_id"]}
        brief = g["brief"]
        base = ManuscriptContent.model_validate(g["base_content"])
        headings = {s["key"]: s["heading"] for s in brief["section_plan"]}
        drafts, problems, provenance = {}, [], []
        try:
            for key in g["sections"]:
                run = await run_agent(WRITER, ModelGateway(api),
                                      {"brief": brief, "section": {"key": key, "heading": headings[key]},
                                       "instructions": instructions,
                                       "input_artifact_ids": [g["brief_artifact_id"], g["base_artifact_id"]]},
                                      scope=f"{task_id}:{key}")
                drafts[key] = run.output
                problems += [f"{key}: {p}" for p in run.problems]
                provenance.append({"section": key, **run.provenance})
        except (GatewayError, ProviderError) as exc:
            reason = model_unavailable_reason(exc)
            if reason is None:
                raise app_error(exc) from exc
            await api.post(f"/v1/internal/manuscripts/{manuscript_id}/candidates/{task_id}",
                           {"status": "failed", "error": reason})
            return {"status": "failed", "reason": reason}
        content = ManuscriptContent.model_validate(base.model_dump())
        content.mode = brief["mode"]
        for key, d in drafts.items():
            new = to_section(d)
            cur = content.section(key)
            if cur is None:
                content.sections.append(new)
            else:
                content.sections[content.sections.index(cur)] = new
        rationale = {k: {"rationale": d["rationale"], "open_questions": d["open_questions"]} for k, d in drafts.items()}
        payload = {"manuscript_id": manuscript_id, "base_version_id": g["base_version_id"], "sections": g["sections"],
                   "content": content.model_dump(mode="json"), "rationale": rationale, "validation_problems": problems,
                   "provenance": provenance}
        art = await api.publish_json(project_id, "generation_candidate", payload, g["input_manifest_hash"], slot="candidate",
                                     depends_on=[g["brief_artifact_id"], g["base_artifact_id"]],
                                     label=f"Generated draft of {', '.join(g['sections'])} (base v{g['base_version_number']})")
        c = await api.post(f"/v1/internal/manuscripts/{manuscript_id}/candidates/{task_id}",
                           {"artifact_id": art.artifact_id, "rationale": {**rationale, "_validation_problems": problems},
                            "provenance": {"sections": provenance}})
    return {"status": c["status"], "candidate_id": c["id"], "artifact_id": art.artifact_id, "problems": problems}


@activity.defn
async def manuscript_compile(task_id: str, project_id: str, params: dict) -> dict:
    """Render the committed manuscript version into the confirmed template and compile it in the no-network sandbox."""
    opts = RenderOptions(mode="submission", anonymous=params.get("anonymous", True), bib_mode=params.get("bib_mode", "bibtex"))
    async with ApiClient(task_id) as api:
        try:
            tpl = await api.get(f"/v1/internal/projects/{project_id}/templates/{params['template_id']}")
            archive = await api.read_artifact(tpl["archive_artifact_id"])
            r = await api.get(f"/v1/internal/projects/{project_id}/manuscript-render",
                              version_id=params["manuscript_version_id"], anonymous=str(opts.anonymous).lower())
            figures = {name: await api.read_artifact(aid) for name, aid in r["figures"].items()}
        except ApiCallError as exc:
            raise app_error(exc) from exc
        m, files, protected, gen = prepare(archive)
        doc = ManuscriptDocument.model_validate(r["document"])
        out = compile_document(family=m.family, template_files=files, protected=protected,
                               requires_generation=m.requires_generation, generation_inputs=gen, bib_style=m.bibtex_style,
                               doc=doc, opts=opts, figures=figures,
                               sandbox=default_sandbox(get_worker_settings().latex_image),
                               identity_terms=r["identity_terms"] if opts.anonymous else None,
                               page_limit=r["page_limit"], page_limit_excludes_references=r["page_limit_excludes_references"],
                               abstract_word_limit=r["abstract_word_limit"])
        report = {**out.report.to_dict(), "manuscript_version": r["version_number"], "manuscript_hash": r["content_hash"]}
        imh = content_hash({"archive": tpl["archive_hash"], "version": r["content_hash"], "options": opts.model_dump()})
        slot = f"manuscript:{r['version_number']}:{int(opts.anonymous)}:{opts.bib_mode}"
        try:
            rep = await api.publish_json(project_id, "compile_report", report, imh, slot=f"{slot}:report",
                                         depends_on=[tpl["archive_artifact_id"]],
                                         label=f"Manuscript v{r['version_number']} compile report")
            pdf_id = log_id = None
            if out.pdf:
                pdf_id = (await api.publish(project_id, "compiled_pdf", out.pdf, "application/pdf", imh, slot=f"{slot}:pdf",
                                            depends_on=[rep.artifact_id],
                                            label=f"Manuscript v{r['version_number']} PDF")).artifact_id
            if out.log:
                log_id = (await api.publish(project_id, "compile_log", out.log.encode(), "text/plain", imh,
                                            slot=f"{slot}:log", label="Compile log")).artifact_id
            bundle = source_bundle({**out.source_files, **{f"figures/{k}": v for k, v in figures.items()}})
            bundle_id = (await api.publish(project_id, "latex_source_bundle", bundle, "application/zip", imh,
                                           slot=f"{slot}:bundle", label="Manuscript LaTeX source")).artifact_id
            run = await api.post(f"/v1/internal/projects/{project_id}/compile-runs", {
                "template_id": params["template_id"], "kind": "manuscript", "options": opts.model_dump(),
                "status": out.report.status, "report_artifact_id": rep.artifact_id, "pdf_artifact_id": pdf_id,
                "log_artifact_id": log_id, "source_bundle_artifact_id": bundle_id,
                "checks": [{"id": c["id"], "status": c["status"], "detail": c["detail"]} for c in report["checks"]],
                "pages": out.report.pages, "errors": out.report.errors[:20],
                "manuscript_version_id": params["manuscript_version_id"]})
            if out.report.duration_s:
                await api.record_usage(category="tex_compile", provider="latex_sandbox", units=out.report.duration_s,
                                       unit="seconds", stage="manuscript_compile")
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"compile_run_id": run["id"], "status": out.report.status, "report_artifact_id": rep.artifact_id,
            "pdf_artifact_id": pdf_id, "pages": out.report.pages}


RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=2),
                    maximum_attempts=3)


@workflow.defn(name="ManuscriptGenerationWorkflow")
class ManuscriptGenerationWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            p = inp.params
            res = await workflow.execute_activity(manuscript_generate,
                                                  args=[inp.task_id, inp.project_id, p["manuscript_id"], p.get("instructions")],
                                                  start_to_close_timeout=timedelta(minutes=30), retry_policy=RETRY)
            if res["status"] == "failed":
                return TaskOutcome(state="failed_terminal", error_code="model_unavailable", error_message=res.get("reason"), result=res)
            return TaskOutcome(state="succeeded", output_artifact_ids=[res["artifact_id"]] if res.get("artifact_id") else [],
                               result=res)
        return await run_task(inp, body)


register(QUEUE_RESEARCH, workflows=[ManuscriptGenerationWorkflow], activities=[manuscript_generate])
register(QUEUE_LATEX, activities=[manuscript_compile])
