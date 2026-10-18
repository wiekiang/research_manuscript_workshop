"""M1 CFP import workflow: controlled fetch -> quarantine scan -> committed snapshot -> located text ->
deterministic + model extraction -> independent validation -> merge -> API ingestion."""

from __future__ import annotations

from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rp_contracts.cfp import CfpExtraction, CfpValidation
    from rp_contracts.hashing import content_hash, sha256_hex
    from rp_contracts.netpolicy import FetchBlocked
    from rp_contracts.scanning import scan
    from rp_contracts.tasks import QUEUE_FETCH, QUEUE_RESEARCH

    from ..agents import cfp_heuristics
    from ..agents.base import run_agent
    from ..agents.cfp import EXTRACTOR, VALIDATOR
    from ..agents.cfp_merge import merge, validation_items
    from ..api_client import ApiCallError, ApiClient
    from ..fetch.fetcher import ControlledFetcher, FetchFailed
    from ..fetch.text import LocatedText, extract
    from ..gateway import GatewayError, ModelGateway
    from ..gateway.providers import ProviderError
    from ..registry import register
    from ..temporal_types import TaskInput, TaskOutcome
    from ..workflows.base import run_task
    from .common import app_error, model_unavailable_reason

SNAPSHOT_TYPES = {"text/html", "application/xhtml+xml", "application/pdf", "text/plain"}


@activity.defn
async def cfp_fetch_snapshot(task_id: str, project_id: str, url: str, source_level: str) -> dict:
    try:
        res = await ControlledFetcher().fetch(url)
    except (FetchBlocked, FetchFailed) as exc:
        raise app_error(exc) from exc
    report = scan(res.content, res.media_type)
    if report.verdict == "rejected" or report.sniffed_type not in SNAPSHOT_TYPES:
        from temporalio.exceptions import ApplicationError

        raise ApplicationError(f"quarantine rejected the response: {report.flags or report.sniffed_type}",
                               report.to_dict(), type="quarantine_rejected", non_retryable=True)
    media = report.sniffed_type
    imh = sha256_hex(f"{url}|{sha256_hex(res.content)}".encode())
    async with ApiClient(task_id) as api:
        try:
            snap_art = await api.publish(project_id, "source_snapshot", res.content, media, imh, slot="snapshot",
                                         label=f"Snapshot of {res.final_url}"[:300],
                                         metadata={"requested_url": url, "final_url": res.final_url,
                                                   "retrieved_at": res.retrieved_at.isoformat(), "scan": report.to_dict()})
            lt = extract(res.content, media)
            text_art = await api.publish_json(project_id, "source_text", lt.to_dict(), imh, slot="text",
                                              depends_on=[snap_art.artifact_id], label="Located text")
            snap = await api.post("/v1/internal/cfp/snapshots", {
                "project_id": project_id, "url": url, "final_url": res.final_url, "artifact_id": snap_art.artifact_id,
                "text_artifact_id": text_art.artifact_id, "retrieved_at": res.retrieved_at.isoformat(),
                "http_status": res.status, "etag": res.headers.get("etag"),
                "last_modified": res.headers.get("last-modified"), "media_type": media,
                "scan_report": report.to_dict(), "hops": [h.__dict__ for h in res.hops],
                "source_level": source_level, "robots": res.robots})
            await api.record_usage(category="egress", provider="controlled_fetch", units=len(res.content),
                                   unit="bytes", stage="cfp_import")
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"snapshot_id": snap["id"], "text_artifact_id": text_art.artifact_id,
            "snapshot_artifact_id": snap_art.artifact_id, "source_url": res.final_url}


@activity.defn
async def cfp_prepare_supplied(task_id: str, project_id: str, snapshot_id: str) -> dict:
    async with ApiClient(task_id) as api:
        try:
            snap = await api.get(f"/v1/internal/cfp/snapshots/{snapshot_id}")
            data = await api.read_artifact(snap["artifact_id"])
            lt = extract(data, snap["media_type"])
            text_art = await api.publish_json(project_id, "source_text", lt.to_dict(), snap["content_hash"], slot="text",
                                              depends_on=[snap["artifact_id"]], label="Located text")
            await api.post(f"/v1/internal/cfp/snapshots/{snapshot_id}/text", {"text_artifact_id": text_art.artifact_id})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"snapshot_id": snapshot_id, "text_artifact_id": text_art.artifact_id,
            "snapshot_artifact_id": snap["artifact_id"], "source_url": snap.get("url")}


@activity.defn
async def cfp_extract(task_id: str, project_id: str, snapshot_id: str, text_artifact_id: str,
                      source_url: str | None) -> dict:
    async with ApiClient(task_id) as api:
        try:
            lt = LocatedText.from_dict(await api.read_json(text_artifact_id))
        except ApiCallError as exc:
            raise app_error(exc) from exc
        deterministic = cfp_heuristics.extract(lt)
        model: CfpExtraction | None = None
        validation: CfpValidation | None = None
        model_status = validator_status = "not_performed: model extraction unavailable"
        provenance: dict = {}
        try:
            gateway = ModelGateway(api)
            run = await run_agent(EXTRACTOR, gateway, {"source_text": lt.text, "source_url": source_url,
                                                       "input_artifact_ids": [text_artifact_id]}, scope=task_id)
            model = CfpExtraction.model_validate(run.output)
            model_status = "performed"
            provenance["extractor"] = run.provenance
            vrun = await run_agent(VALIDATOR, gateway, {"source_text": lt.text, "items": validation_items(model),
                                                        "input_artifact_ids": [text_artifact_id]}, scope=task_id)
            validation = CfpValidation.model_validate(vrun.output)
            validator_status = "performed"
            provenance["validator"] = vrun.provenance
        except (GatewayError, ProviderError) as exc:
            reason = model_unavailable_reason(exc)
            if reason is None:
                raise app_error(exc) from exc
            if model is None:
                model_status = reason
            validator_status = reason
        merged = merge(lt, deterministic, model, validation, model_status, validator_status)
        for item in merged["items"]:
            for o in item["observations"]:
                if o["method"] == "model_assisted" and "extractor" in provenance:
                    o["provider"] = provenance["extractor"]["provider"]
                    o["provenance_label"] = provenance["extractor"]["label"]
            if isinstance(item.get("second_pass"), dict) and "validator" in provenance:
                item["second_pass"]["provider"] = provenance["validator"]["provider"]
        merged["provenance"] = provenance
        imh = content_hash({"text": text_artifact_id, "merge": merged["merge_version"]})
        try:
            ex_art = await api.publish_json(project_id, "cfp_extraction", {
                "deterministic": {"version": cfp_heuristics.EXTRACTOR_VERSION, "output": deterministic.model_dump(mode="json")},
                "model": model.model_dump(mode="json") if model else None, "model_status": model_status,
                "validation": validation.model_dump(mode="json") if validation else None,
                "validator_status": validator_status, "provenance": provenance}, imh, slot="extraction",
                depends_on=[text_artifact_id], label="CFP extraction passes")
            val_art = await api.publish_json(project_id, "cfp_validation", merged, imh, slot="validation",
                                             depends_on=[ex_art.artifact_id], label="Reconciled CFP rules")
            res = await api.post(f"/v1/internal/projects/{project_id}/cfp/extraction", {
                "snapshot_id": snapshot_id, "extraction_artifact_id": ex_art.artifact_id,
                "validation_artifact_id": val_art.artifact_id, "merged": merged})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {**res, "extraction_artifact_id": ex_art.artifact_id, "validation_artifact_id": val_art.artifact_id,
            "passes": merged["passes"]}


FETCH_RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0,
                          maximum_interval=timedelta(minutes=5), maximum_attempts=4,
                          non_retryable_error_types=["fetch_blocked", "quarantine_rejected"])
WORK_RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0,
                         maximum_interval=timedelta(minutes=5), maximum_attempts=3)


@workflow.defn(name="CfpImportWorkflow")
class CfpImportWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            assert inp.project_id
            if inp.kind == "cfp_extract_supplied":
                snap = await workflow.execute_activity(
                    cfp_prepare_supplied, args=[inp.task_id, inp.project_id, inp.params["snapshot_id"]],
                    start_to_close_timeout=timedelta(minutes=5), retry_policy=WORK_RETRY)
            else:
                snap = await workflow.execute_activity(
                    cfp_fetch_snapshot, args=[inp.task_id, inp.project_id, inp.params["url"],
                                              inp.params.get("source_level", "track_cfp")],
                    task_queue=QUEUE_FETCH, start_to_close_timeout=timedelta(minutes=3), retry_policy=FETCH_RETRY)
            res = await workflow.execute_activity(
                cfp_extract, args=[inp.task_id, inp.project_id, snap["snapshot_id"], snap["text_artifact_id"],
                                   snap.get("source_url")],
                start_to_close_timeout=timedelta(minutes=20), retry_policy=WORK_RETRY)
            return TaskOutcome(state="succeeded",
                               output_artifact_ids=[snap["snapshot_artifact_id"], snap["text_artifact_id"],
                                                    res["extraction_artifact_id"], res["validation_artifact_id"]],
                               result={"edition_id": res.get("edition_id"), "open_items": res.get("open_items"),
                                       "passes": res.get("passes"), "items": res.get("items")})
        return await run_task(inp, body)


register(QUEUE_RESEARCH, workflows=[CfpImportWorkflow], activities=[cfp_prepare_supplied, cfp_extract])
register(QUEUE_FETCH, activities=[cfp_fetch_snapshot])
