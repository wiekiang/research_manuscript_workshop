"""M2 discovery and CFP monitoring workflows."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rp_contracts.cfp import resolve_deadline
    from rp_contracts.hashing import content_hash, sha256_hex
    from rp_contracts.netpolicy import FetchBlocked
    from rp_contracts.ranking import ResearchProfile, score_candidate
    from rp_contracts.scanning import scan
    from rp_contracts.tasks import QUEUE_FETCH, QUEUE_RESEARCH

    from ..agents import cfp_heuristics
    from ..api_client import ApiCallError, ApiClient
    from ..fetch.fetcher import ControlledFetcher, FetchFailed
    from ..fetch.text import extract
    from ..registry import register
    from ..temporal_types import TaskInput, TaskOutcome
    from ..workflows.base import run_task
    from .cfp import SNAPSHOT_TYPES, cfp_extract
    from .common import app_error


def fetcher() -> ControlledFetcher:
    return ControlledFetcher()


@activity.defn
async def discovery_fetch_source(task_id: str, project_id: str, entry: dict) -> dict:
    """Fetch one curated official source (robots-respecting), commit the snapshot, summarise it."""
    url = (entry.get("cfp_urls") or [entry["homepage_url"]])[0]
    try:
        res = await fetcher().fetch(url, check_robots=True)
    except FetchBlocked as exc:
        return {"entry_id": entry["id"], "url": url, "failed": f"blocked: {exc.reason}"}
    except FetchFailed as exc:
        if exc.retryable:
            raise app_error(exc) from exc
        return {"entry_id": entry["id"], "url": url, "failed": f"{exc.reason} {exc.status or ''}".strip()}
    report = scan(res.content, res.media_type)
    if report.verdict == "rejected" or report.sniffed_type not in SNAPSHOT_TYPES:
        return {"entry_id": entry["id"], "url": url, "failed": f"quarantine rejected: {report.flags}"}
    imh = sha256_hex(f"discovery|{url}|{sha256_hex(res.content)}".encode())
    async with ApiClient(task_id) as api:
        try:
            art = await api.publish(project_id, "source_snapshot", res.content, report.sniffed_type, imh,
                                    slot=f"discovery:{entry['id']}", label=f"Discovery snapshot {res.final_url}"[:300],
                                    metadata={"requested_url": url, "final_url": res.final_url, "scan": report.to_dict(),
                                              "registry_entry": entry["series_key"], "robots": res.robots})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    lt = extract(res.content, report.sniffed_type)
    ex = cfp_heuristics.extract(lt)
    deadlines = []
    for d in ex.deadlines:
        r = resolve_deadline(d.date, d.time, d.timezone)
        deadlines.append({"kind": d.deadline_kind.value, "date": d.date, "timezone": d.timezone,
                          "due_at": r.due_at.isoformat() if r.due_at else None, "problems": r.problems})
    return {"entry_id": entry["id"], "url": res.final_url, "snapshot_artifact_id": art.artifact_id,
            "snapshot_hash": art.content_hash, "text": lt.text[:60000], "name": ex.edition.conference_name,
            "acronym": ex.edition.acronym or entry.get("acronym"), "year": ex.edition.year,
            "tracks": [t.name for t in ex.tracks], "deadlines": deadlines}


@activity.defn
async def discovery_rank(task_id: str, project_id: str, profile: dict, sources: list[dict], entries: list[dict]) -> dict:
    prof = ResearchProfile(**profile)
    by_id = {e["id"]: e for e in entries}
    now = datetime.now(UTC)
    candidates, failures = [], []
    for s in sources:
        if s.get("failed"):
            failures.append({"entry_id": s["entry_id"], "url": s["url"], "reason": s["failed"]})
            continue
        e = by_id[s["entry_id"]]
        full = next((d for d in s["deadlines"] if d["kind"] == "full_paper" and d["due_at"]), None)
        due = datetime.fromisoformat(full["due_at"]) if full else None
        text = s["text"] + " " + " ".join(e.get("keywords") or [])
        ranked = score_candidate(prof, key=e["series_key"], name=e["name"], acronym=s.get("acronym"), cfp_text=text,
                                 publisher=e.get("publisher"), location=None, full_paper_due=due,
                                 venue_verified=True, questionable=bool(e.get("questionable_evidence")), now=now)
        candidates.append({"registry_entry_id": e["id"], "dedupe_key": f"{e['series_key']}:{s.get('year') or 'unknown'}",
                           "name": s.get("name") or e["name"], "acronym": s.get("acronym"), "year": s.get("year"),
                           "official_url": s["url"], "snapshot_artifact_id": s["snapshot_artifact_id"],
                           "snapshot_hash": s["snapshot_hash"], "tracks": s["tracks"], "deadlines": s["deadlines"],
                           "location": None, "publisher": e.get("publisher"), "total_score": ranked.total,
                           "components": ranked.as_dict()["components"], "excluded": ranked.excluded,
                           "exclusion_reason": ranked.exclusion_reason,
                           "questionable_evidence": e.get("questionable_evidence") or []})
    async with ApiClient(task_id) as api:
        try:
            res = await api.post(f"/v1/internal/projects/{project_id}/discovery/results",
                                 {"candidates": candidates, "failures": failures})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {**res, "failures": failures}


@activity.defn
async def discovery_registry(task_id: str) -> list[dict]:
    async with ApiClient(task_id) as api:
        try:
            return (await api.get("/v1/internal/registry"))["items"]
        except ApiCallError as exc:
            raise app_error(exc) from exc


@activity.defn
async def cfp_monitor_fetch(task_id: str, project_id: str, params: dict) -> dict:
    """Conditional refetch of a target CFP. Returns {'changed': False} when nothing changed."""
    url = params["url"]
    try:
        res = await fetcher().fetch(url, etag=params.get("etag"), last_modified=params.get("last_modified"))
    except (FetchBlocked, FetchFailed) as exc:
        async with ApiClient(task_id) as api:
            await api.post(f"/v1/internal/projects/{project_id}/cfp/monitor-result",
                           {"outcome": "failed", "url": url, "detail": str(exc)})
        if isinstance(exc, FetchFailed) and exc.retryable:
            raise app_error(exc) from exc
        return {"changed": False, "outcome": "failed", "detail": str(exc)}
    async with ApiClient(task_id) as api:
        if res.not_modified or sha256_hex(res.content) == params.get("previous_hash"):
            outcome = "not_modified" if res.not_modified else "unchanged"
            await api.post(f"/v1/internal/projects/{project_id}/cfp/monitor-result", {"outcome": outcome, "url": url})
            return {"changed": False, "outcome": outcome}
        report = scan(res.content, res.media_type)
        if report.verdict == "rejected" or report.sniffed_type not in SNAPSHOT_TYPES:
            await api.post(f"/v1/internal/projects/{project_id}/cfp/monitor-result",
                           {"outcome": "failed", "url": url, "detail": f"quarantine rejected: {report.flags}"})
            return {"changed": False, "outcome": "failed"}
        imh = sha256_hex(f"{url}|{sha256_hex(res.content)}".encode())
        try:
            snap_art = await api.publish(project_id, "source_snapshot", res.content, report.sniffed_type, imh,
                                         slot="snapshot", label=f"Snapshot of {res.final_url}"[:300],
                                         metadata={"requested_url": url, "final_url": res.final_url, "scan": report.to_dict(),
                                                   "monitor": True})
            lt = extract(res.content, report.sniffed_type)
            text_art = await api.publish_json(project_id, "source_text", lt.to_dict(), imh, slot="text",
                                              depends_on=[snap_art.artifact_id], label="Located text")
            snap = await api.post("/v1/internal/cfp/snapshots", {
                "project_id": project_id, "url": url, "final_url": res.final_url, "artifact_id": snap_art.artifact_id,
                "text_artifact_id": text_art.artifact_id, "retrieved_at": res.retrieved_at.isoformat(),
                "http_status": res.status, "etag": res.headers.get("etag"), "last_modified": res.headers.get("last-modified"),
                "media_type": report.sniffed_type, "scan_report": report.to_dict(), "hops": [h.__dict__ for h in res.hops],
                "source_level": params.get("source_level", "track_cfp"), "robots": res.robots})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"changed": True, "snapshot_id": snap["id"], "text_artifact_id": text_art.artifact_id,
            "snapshot_artifact_id": snap_art.artifact_id, "url": res.final_url}


@activity.defn
async def cfp_monitor_record(task_id: str, project_id: str, url: str, snapshot_id: str, ingest: dict) -> None:
    changed = bool(ingest.get("changed_rules") or ingest.get("changed_deadlines"))
    async with ApiClient(task_id) as api:
        await api.post(f"/v1/internal/projects/{project_id}/cfp/monitor-result", {
            "outcome": "changed" if changed else "unchanged", "url": url, "snapshot_id": snapshot_id,
            "detail": f"rules: {ingest.get('changed_rules')}; deadlines: {ingest.get('changed_deadlines')}"})


RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=5),
                    maximum_attempts=4, non_retryable_error_types=["fetch_blocked", "quarantine_rejected"])


@workflow.defn(name="ConferenceDiscoveryWorkflow")
class ConferenceDiscoveryWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            entries = await workflow.execute_activity(discovery_registry, inp.task_id,
                                                      start_to_close_timeout=timedelta(minutes=1), retry_policy=RETRY)
            wanted = set(inp.params.get("registry_entry_ids") or [])
            entries = [e for e in entries if not wanted or e["id"] in wanted]
            sources = await asyncio.gather(*[
                workflow.execute_activity(discovery_fetch_source, args=[inp.task_id, inp.project_id, e],
                                          task_queue=QUEUE_FETCH, start_to_close_timeout=timedelta(minutes=3),
                                          retry_policy=RETRY) for e in entries])
            res = await workflow.execute_activity(discovery_rank, args=[inp.task_id, inp.project_id,
                                                                        inp.params["profile"], list(sources), entries],
                                                  start_to_close_timeout=timedelta(minutes=2), retry_policy=RETRY)
            return TaskOutcome(state="succeeded",
                               output_artifact_ids=[s["snapshot_artifact_id"] for s in sources if s.get("snapshot_artifact_id")],
                               result=res)
        return await run_task(inp, body)


@workflow.defn(name="CfpMonitorWorkflow")
class CfpMonitorWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            got = await workflow.execute_activity(cfp_monitor_fetch, args=[inp.task_id, inp.project_id, inp.params],
                                                  task_queue=QUEUE_FETCH, start_to_close_timeout=timedelta(minutes=3),
                                                  retry_policy=RETRY)
            if not got.get("changed"):
                return TaskOutcome(state="succeeded", result={"outcome": got.get("outcome")})
            ingest = await workflow.execute_activity(
                cfp_extract, args=[inp.task_id, inp.project_id, got["snapshot_id"], got["text_artifact_id"], got["url"]],
                start_to_close_timeout=timedelta(minutes=20), retry_policy=RETRY)
            await workflow.execute_activity(cfp_monitor_record, args=[inp.task_id, inp.project_id, got["url"],
                                                                      got["snapshot_id"], ingest],
                                            start_to_close_timeout=timedelta(minutes=1), retry_policy=RETRY)
            return TaskOutcome(state="succeeded", output_artifact_ids=[got["snapshot_artifact_id"]],
                               result={"outcome": "fetched", "changed_rules": ingest.get("changed_rules"),
                                       "changed_deadlines": ingest.get("changed_deadlines")})
        return await run_task(inp, body)


register(QUEUE_RESEARCH, workflows=[ConferenceDiscoveryWorkflow, CfpMonitorWorkflow],
         activities=[discovery_rank, discovery_registry, cfp_monitor_record])
register(QUEUE_FETCH, activities=[discovery_fetch_source, cfp_monitor_fetch])
_ = content_hash
