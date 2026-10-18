"""M7 workflows: four independently frozen review functions, deterministic meta-review, research-integrity report."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rp_contracts.contribution import ResultManifest, recompute_from_predictions
    from rp_contracts.hashing import content_hash
    from rp_contracts.integrity import ENGINE_VERSION, run_integrity
    from rp_contracts.review import (
        VERDICT_SEVERITY,
        Finding,
        check_key,
        check_literature_source,
        check_result_source,
        compliance_findings,
        evaluate_compliance,
        meta_review,
        sample_noncritical,
    )
    from rp_contracts.tasks import QUEUE_RESEARCH
    from rp_contracts.textmatch import find_span

    from ..agents.base import run_agent
    from ..agents.reviewers import MEANING, SCIENTIFIC
    from ..api_client import ApiCallError, ApiClient
    from ..gateway import GatewayError, ModelGateway
    from ..gateway.providers import ProviderError
    from ..registry import register
    from ..temporal_types import TaskInput, TaskOutcome
    from ..workflows.base import run_task
    from .common import app_error, model_unavailable_reason


def as_json(data: Any) -> Any:
    """The API client returns parsed JSON for JSON artifacts and bytes otherwise."""
    return data if isinstance(data, (dict, list)) else json.loads(data)


def text_of(data: Any) -> str:
    if isinstance(data, dict):
        return data.get("text") or ""
    try:
        obj = json.loads(data)
        if isinstance(obj, dict) and isinstance(obj.get("text"), str):
            return obj["text"]
    except (ValueError, UnicodeDecodeError):
        pass
    return data.decode("utf-8", errors="replace")


async def _read_text(api: ApiClient, artifact_id: str | None, cache: dict[str, str | None]) -> str | None:
    if not artifact_id:
        return None
    if artifact_id not in cache:
        try:
            cache[artifact_id] = text_of(await api.read_artifact(artifact_id))
        except ApiCallError:
            cache[artifact_id] = None
    return cache[artifact_id]


# --------------------------------------------------------------------------- functions
async def scientific(api: ApiClient, inp: dict, scope: str) -> dict:
    try:
        run = await run_agent(SCIENTIFIC, ModelGateway(api), inp, scope=scope)
    except (GatewayError, ProviderError) as exc:
        reason = model_unavailable_reason(exc)
        if reason is None:
            raise app_error(exc) from exc
        return {"status": "not_performed", "findings": [], "summary": {"reason": reason}, "provenance": {}}
    out = run.output
    findings = [Finding(function="scientific", severity=f["severity"], category=f["category"], title=f["issue"],
                        rationale=f["rationale"], check=f["check"], proposed_fix=f["proposed_fix"],
                        span_ids=f["span_ids"], claim_ids=f["claim_ids"]) for f in out["findings"]]
    return {"status": "performed", "findings": findings, "provenance": run.provenance,
            "summary": {k: out[k] for k in ("question", "protocol", "evidence", "contribution", "conclusions")}
            | {"validation_problems": run.problems}}


async def citation_evidence(api: ApiClient, inp: dict, scope: str) -> dict:
    items = inp["claims"]
    critical = [c["key"] for c in items if c.get("critical")]
    sampled, unchecked = sample_noncritical([c["key"] for c in items if not c.get("critical") and not c.get("missing")],
                                            inp["content_digest"])
    selected = set(critical) | set(sampled)
    findings: list[Finding] = []
    checks, ok_spans, ok_claims, reused, model_used = [], [], [], 0, False
    cache: dict[str, str | None] = {}
    partial = False
    for c in items:
        if c.get("missing"):
            findings.append(Finding(function="citation_evidence", severity="blocker", category="source_not_performed",
                                    title=f"{c['key']} is cited but not registered", rationale="unknown claim key",
                                    check="claim registry lookup", claim_ids=[c["key"]]))
            continue
        if c["key"] not in selected:
            continue
        spans = c["spans"]
        src_results, evidence_texts, source_hashes = [], [], []
        for e in c["evidence"]:
            if e["type"] == "passage":
                text = await _read_text(api, e.get("source_artifact_id"), cache)
                r = check_literature_source(e["quote"], text)
                src_results.append(r)
                evidence_texts.append(f"\"{e['quote']}\" ({e['paper_title']})")
                source_hashes.append(e.get("source_hash") or "-")
            else:
                metrics = None
                if e.get("artifact_id"):
                    try:
                        manifest = as_json(await api.read_artifact(e["artifact_id"]))
                        metrics = [m for m in manifest.get("metrics", []) if not e.get("metric") or m["name"] == e["metric"]]
                    except ApiCallError:
                        metrics = None
                r = check_result_source(c["proposition"], metrics)
                src_results.append(r)
                evidence_texts.append(f"result {e['result_key']}: metrics={json.dumps(metrics)}; assurance={e.get('assurance')}; "
                                      f"wording limits={e.get('wording_limits')}")
                source_hashes.append(e.get("artifact_id") or "-")
        if not src_results:
            src = {"status": "not_performed", "detail": "the claim has no linked evidence to open"}
        elif any(r["status"] == "passed" for r in src_results):
            src = next(r for r in src_results if r["status"] == "passed")
        elif any(r["status"] == "failed" for r in src_results):
            src = next(r for r in src_results if r["status"] == "failed")
        else:
            src = src_results[0]
        key = check_key(c["proposition"], "|".join(sorted(source_hashes)), [s["text"] for s in spans])
        prior = inp["prior_checks"].get(key)
        meaning: list[dict] = []
        if src["status"] != "passed":
            partial = partial or src["status"] == "not_performed"
            findings.append(Finding(
                function="citation_evidence", severity="blocker" if c.get("critical") else "major",
                category="source_not_performed" if src["status"] == "not_performed" else "source_failed",
                title=f"{c['key']}: source check {src['status']}", rationale=src["detail"],
                check="open the stored source and locate the cited passage or result", claim_ids=[c["key"]],
                span_ids=[s["span_id"] for s in spans]))
        elif prior is not None and prior["source_status"] == "passed":
            meaning, reused = prior["meaning"], reused + 1
        elif spans:
            model_used = True
            try:
                run = await run_agent(MEANING, ModelGateway(api), {"key": c["key"], "proposition": c["proposition"],
                                                                   "evidence_text": "\n".join(evidence_texts), "spans": spans},
                                      scope=f"{scope}:{c['key']}")
                meaning = run.output["spans"]
            except (GatewayError, ProviderError) as exc:
                reason = model_unavailable_reason(exc)
                if reason is None:
                    raise app_error(exc) from exc
                partial = True
                meaning = [{"span_id": s["span_id"], "verdict": "not_performed", "rationale": reason,
                            "suggested_wording": None} for s in spans]
                findings.append(Finding(function="citation_evidence", severity="blocker" if c.get("critical") else "major",
                                        category="meaning_not_performed", title=f"{c['key']}: meaning check not performed",
                                        rationale=reason, check="meaning check of linked spans", claim_ids=[c["key"]],
                                        span_ids=[s["span_id"] for s in spans]))
        for mv in meaning:
            sev = VERDICT_SEVERITY.get(mv["verdict"])
            if mv["verdict"] == "faithful":
                ok_spans.append(mv["span_id"])
            elif sev:
                findings.append(Finding(function="citation_evidence", severity=sev, category=mv["verdict"],
                                        title=f"{c['key']}: span {mv['verdict'].replace('_', ' ')}", rationale=mv["rationale"],
                                        check="compare the span with the claim and the opened evidence",
                                        proposed_fix=mv.get("suggested_wording"), span_ids=[mv["span_id"]],
                                        claim_ids=[c["key"]]))
        if src["status"] == "passed" and all(m["verdict"] == "faithful" for m in meaning):
            ok_claims.append(c["key"])
        checks.append({"claim_key": c["key"], "check_key": key, "critical": bool(c.get("critical")),
                       "selection": "critical" if c.get("critical") else "sampled", "source_status": src["status"],
                       "source_detail": src["detail"], "meaning": meaning, "reused": prior is not None and bool(meaning),
                       "method": "deterministic+model_assisted" if meaning else "deterministic"})
    return {"status": "partial" if partial else "performed", "findings": findings, "claim_checks": checks,
            "assessed_ok": {"span_ids": ok_spans, "claim_ids": ok_claims},
            "summary": {"critical_checked": sorted(critical), "noncritical_sampled": sampled,
                        "unchecked_noncritical": unchecked, "sampling_rule": inp["sampling_rule"]["id"],
                        "reused_checks": reused, "model_assisted": model_used}}


async def technical(api: ApiClient, inp: dict, scope: str) -> dict:
    findings: list[Finding] = []
    per = {}
    for rk, r in sorted(inp["results"].items()):
        manifest = ResultManifest.model_validate({k: v for k, v in r["manifest"].items() if k in ResultManifest.model_fields})
        pred = next((f for f in manifest.files if f.role == "predictions"), None)
        if pred is None:
            per[rk] = {"assurance": r["assurance"], "recomputation": "not_performed",
                       "detail": "no raw outputs supplied; the result stays at its recorded assurance level"}
            continue
        try:
            data = await api.read_artifact(pred.artifact_id)
        except ApiCallError:
            per[rk] = {"assurance": r["assurance"], "recomputation": "not_performed", "detail": "raw outputs unavailable"}
            if rk in inp["cited_result_keys"]:
                findings.append(Finding(function="technical", severity="major", category="raw_output_unavailable",
                                        title=f"{rk}: raw outputs could not be opened", rationale="recomputation impossible",
                                        check="open the predictions artifact", artifact_ids=[pred.artifact_id]))
            continue
        outcomes = recompute_from_predictions(manifest, data)
        failed = [o for o in outcomes if o.status == "failed"]
        per[rk] = {"assurance": r["assurance"], "recomputation": "failed" if failed else "passed",
                   "checks": [o.__dict__ for o in outcomes]}
        for o in failed:
            findings.append(Finding(function="technical", severity="blocker", category="metric_mismatch",
                                    title=f"{rk}: {o.id} disagrees with the reported value", rationale=o.detail,
                                    check=f"recompute {o.id} from the supplied predictions", artifact_ids=[pred.artifact_id]))
    for rk in inp["cited_result_keys"]:
        r = inp["results"].get(rk)
        if r and r["assessment_blockers"]:
            findings.append(Finding(function="technical", severity="blocker", category="result_blocked",
                                    title=f"{rk} has assessment blockers", rationale="; ".join(r["assessment_blockers"]),
                                    check="result assurance assessment"))
    # M9: reproducibility checks are mandatory for platform-executed studies.
    for rk in inp["cited_result_keys"]:
        r = inp["results"].get(rk)
        if r and r["manifest"].get("origin") == "platform_run":
            if not r["manifest"].get("rerun_record"):
                findings.append(Finding(function="technical", severity="major", category="reproducibility_not_documented",
                                        title=f"{rk}: platform run without a documented reproduction rerun",
                                        rationale="platform-executed results need a rerun within the preset tolerance",
                                        check="rerun the approved plan and promote the original run again"))
            elif r["manifest"].get("synthetic_or_simulated"):
                findings.append(Finding(function="technical", severity="minor", category="synthetic_data",
                                        title=f"{rk}: synthetic or simulated inputs", rationale="must be labelled as such",
                                        check="inspect the plan's input data nature"))
    if inp.get("frozen_protocol_hash") is None and inp["results"]:
        findings.append(Finding(function="technical", severity="blocker", category="protocol",
                                title="no frozen protocol", rationale="results are not bound to an H2-approved protocol",
                                check="protocol freeze record"))
    return {"status": "performed", "findings": findings, "summary": {"results": per}}


async def compliance(api: ApiClient, inp: dict, scope: str) -> dict:
    cache: dict[str, str | None] = {}
    rules = []
    for r in inp["rules"]:
        text = await _read_text(api, r.get("snapshot_text_artifact_id"), cache)
        rules.append({**r, "quote_in_snapshot": bool(text and r.get("quote") and find_span(text, r["quote"]) is not None)})
    checks = evaluate_compliance(rules=rules, compile_run=inp["compile_run"], manuscript=inp["manuscript"],
                                 template=inp["template"], cfp_available=inp["cfp_available"])
    status = "performed" if inp["cfp_available"] and inp["compile_run"] and inp["template"] else "partial"
    return {"status": status, "findings": compliance_findings(checks),
            "summary": {"checks": [c.model_dump() for c in checks], "rules_read": len(rules),
                        "snapshots_opened": len([v for v in cache.values() if v is not None])}}


FN = {"scientific": scientific, "citation_evidence": citation_evidence, "technical": technical, "compliance": compliance}


@activity.defn
async def review_function(task_id: str, project_id: str, round_id: str, function: str) -> dict:
    async with ApiClient(task_id) as api:
        try:
            inp = await api.get(f"/v1/internal/reviews/{round_id}/inputs/{function}")
            res = await FN[function](api, inp, f"{task_id}:{function}")
            deps = [inp["manuscript_artifact_id"]]
            if function == "compliance":
                deps += [x for x in (inp.get("ruleset_artifact_id"), (inp.get("template") or {}).get("archive_artifact_id"),
                                     (inp.get("compile_run") or {}).get("report_artifact_id")) if x]
            findings = [f.model_dump(mode="json") for f in res["findings"]]
            report = {"function": function, "manuscript_version": inp["manuscript_version"], "status": res["status"],
                      "summary": res.get("summary", {}), "findings": findings, "claim_checks": res.get("claim_checks", []),
                      "provenance": res.get("provenance", {}), "inputs_digest": content_hash(inp)}
            art = await api.publish_json(project_id, "compliance_report" if function == "compliance" else "review_report",
                                         report, content_hash({"round": round_id, "function": function}), slot=f"{round_id}:{function}",
                                         depends_on=deps, label=f"{function} review of v{inp['manuscript_version']}")
            await api.post(f"/v1/internal/reviews/{round_id}/reports/{function}", {
                "status": res["status"], "artifact_id": art.artifact_id, "findings": findings,
                "summary": res.get("summary", {}), "assessed_ok": res.get("assessed_ok", {}),
                "input_hashes": {"inputs": report["inputs_digest"], "manuscript": inp["content_digest"]},
                "provenance": res.get("provenance", {}), "claim_checks": res.get("claim_checks", [])})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"function": function, "status": res["status"], "findings": len(findings), "artifact_id": art.artifact_id}


@activity.defn
async def review_meta(task_id: str, project_id: str, round_id: str) -> dict:
    async with ApiClient(task_id) as api:
        try:
            reps = (await api.get(f"/v1/internal/reviews/{round_id}/frozen-reports"))["reports"]
            meta = meta_review(reps)
            art = await api.publish_json(project_id, "meta_review", meta, content_hash({"round": round_id, "meta": 1}),
                                         slot=f"{round_id}:meta", depends_on=[r["artifact_id"] for r in reps.values()],
                                         label="Meta-review")
            await api.post(f"/v1/internal/reviews/{round_id}/meta", {"artifact_id": art.artifact_id, "meta": meta})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"artifact_id": art.artifact_id, "disagreements": len(meta["disagreements"])}


@activity.defn
async def integrity_run(task_id: str, project_id: str, report_id: str) -> dict:
    async with ApiClient(task_id) as api:
        try:
            b = await api.get(f"/v1/internal/integrity-reports/{report_id}/bundle")
            cache: dict[str, str | None] = {}
            b["sources"] = [{"id": sid, "text": t} for sid in b.pop("source_artifact_ids")
                            if (t := await _read_text(api, sid, cache)) is not None]
            checks = run_integrity(b)
            payload: dict[str, Any] = {"engine": ENGINE_VERSION, "manuscript_version": b["manuscript_version"],
                                       "checks": [c.model_dump() for c in checks]}
            art = await api.publish_json(project_id, "integrity_report", payload, content_hash({"report": report_id}),
                                         slot=f"integrity:{report_id}", depends_on=[b["manuscript_artifact_id"]],
                                         label=f"Research integrity report (v{b['manuscript_version']})")
            await api.post(f"/v1/internal/integrity-reports/{report_id}",
                           {"artifact_id": art.artifact_id, "checks": payload["checks"]})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"artifact_id": art.artifact_id, "failed": [c.id for c in checks if c.status == "failed"]}


RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=2),
                    maximum_attempts=3)


@workflow.defn(name="ReviewWorkflow")
class ReviewWorkflow:
    """Functions run concurrently and freeze their own reports; the meta-review starts only afterwards."""

    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            rid = inp.params["round_id"]
            results = await asyncio.gather(*[
                workflow.execute_activity(review_function, args=[inp.task_id, inp.project_id, rid, f],
                                          start_to_close_timeout=timedelta(minutes=30), retry_policy=RETRY)
                for f in inp.params["functions"]])
            meta = await workflow.execute_activity(review_meta, args=[inp.task_id, inp.project_id, rid],
                                                   start_to_close_timeout=timedelta(minutes=5), retry_policy=RETRY)
            return TaskOutcome(state="succeeded", output_artifact_ids=[r["artifact_id"] for r in results] + [meta["artifact_id"]],
                               result={"reports": results, "meta": meta})
        return await run_task(inp, body)


@workflow.defn(name="IntegrityWorkflow")
class IntegrityWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            r = await workflow.execute_activity(integrity_run, args=[inp.task_id, inp.project_id, inp.params["report_id"]],
                                                start_to_close_timeout=timedelta(minutes=15), retry_policy=RETRY)
            return TaskOutcome(state="succeeded", output_artifact_ids=[r["artifact_id"]], result=r)
        return await run_task(inp, body)


register(QUEUE_RESEARCH, workflows=[ReviewWorkflow, IntegrityWorkflow], activities=[review_function, review_meta, integrity_run])
