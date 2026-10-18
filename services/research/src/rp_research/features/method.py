"""M5 workflows: independent methodology review (model-assisted) and deterministic supplied-result assessment."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rp_contracts.contribution import MethodologyReview, ResultManifest, assess
    from rp_contracts.hashing import content_hash
    from rp_contracts.tasks import QUEUE_RESEARCH

    from ..agents.base import AgentSpec, run_agent
    from ..api_client import ApiClient
    from ..gateway import GatewayError, ModelCall, ModelGateway
    from ..gateway.core import wrap_untrusted
    from ..gateway.providers import ProviderError
    from ..registry import register
    from ..temporal_types import TaskInput, TaskOutcome
    from ..workflows.base import run_task
    from .common import app_error, model_unavailable_reason

ASSESSOR_VERSION = "rp-result-assessor/1"
REVIEW_SYSTEM = """You are an independent methodology reviewer. Assess whether the frozen-to-be protocol can answer the
stated research question with the selected study type. Identify concrete issues (blocker/major/minor/suggestion)
with section, rationale and a proposed fix; threats to validity; ethics or rights concerns that need an explicit
declaration or external approval; and cost/compute concerns. Do not rewrite the protocol and do not approve it."""


def build_review(inputs: dict[str, Any]) -> ModelCall:
    p = inputs["protocol"]
    body = (f"Research question: {p.get('research_question')}\nIntended contribution: {p.get('intended_contribution')}\n"
            f"Study type: {p['definition']['title']} (required sections: {p['definition']['protocol_sections']})\n\n"
            + wrap_untrusted(json.dumps({"sections": p["sections"], "ethics_rights": p["ethics_rights"],
                                         "compute_estimate": p["compute_estimate"]}, indent=1), "protocol"))
    return ModelCall(agent="methodology_reviewer", prompt_version="method-review-1", system=REVIEW_SYSTEM, user=body,
                     output_model=MethodologyReview, data_classification="internal", data_kinds=["unpublished_manuscript"],
                     max_tokens=8000, fixture_key=p["content_hash"])


REVIEWER = AgentSpec("methodology_reviewer", "method-review-1", MethodologyReview, build_review)


@activity.defn
async def methodology_review(task_id: str, project_id: str, protocol_id: str) -> dict:
    async with ApiClient(task_id) as api:
        p = await api.get(f"/v1/internal/projects/{project_id}/protocols/{protocol_id}")
        try:
            run = await run_agent(REVIEWER, ModelGateway(api), {"protocol": p}, scope=task_id)
        except (GatewayError, ProviderError) as exc:
            reason = model_unavailable_reason(exc)
            if reason is None:
                raise app_error(exc) from exc
            await api.post(f"/v1/internal/projects/{project_id}/protocols/{protocol_id}/review",
                           {"status": "not_performed", "reason": reason})
            return {"status": reason}
        art = await api.publish_json(project_id, "methodology_review", {**run.output, "provenance": run.provenance},
                                     content_hash({"protocol": p["content_hash"]}), slot="review",
                                     depends_on=[p["artifact_id"]], label=f"Methodology review (protocol v{p['version']})")
        await api.post(f"/v1/internal/projects/{project_id}/protocols/{protocol_id}/review",
                       {"status": "performed", "review": run.output, "artifact_id": art.artifact_id})
    return {"status": "performed", "issues": len(run.output["issues"]), "artifact_id": art.artifact_id}


@activity.defn
async def assess_result(task_id: str, project_id: str, result_id: str) -> dict:
    async with ApiClient(task_id) as api:
        r = await api.get(f"/v1/internal/projects/{project_id}/results/{result_id}")
        manifest = ResultManifest.model_validate({k: v for k, v in r["manifest"].items() if k in ResultManifest.model_fields})
        pred_file = next((f for f in manifest.files if f.role == "predictions"), None)
        predictions = await api.read_artifact(pred_file.artifact_id) if pred_file else None
        res = assess(manifest, predictions=predictions if isinstance(predictions, bytes) else None,
                     protocol_frozen_hash=r.get("frozen_protocol_hash"))
        art = await api.publish_json(project_id, "result_assessment", {**res.as_dict(), "assessor": ASSESSOR_VERSION,
                                                                      "result_key": r["result_key"]},
                                     content_hash({"result": r["artifact_id"], "assessor": ASSESSOR_VERSION}),
                                     slot=f"assessment:{result_id}", depends_on=[r["artifact_id"]],
                                     label=f"Assurance assessment {r['result_key']}")
        await api.post(f"/v1/internal/projects/{project_id}/results/{result_id}/assessment",
                       {"artifact_id": art.artifact_id, "assessment": res.as_dict(), "assessor": ASSESSOR_VERSION})
    return {"level": res.level.value, "blockers": res.blockers, "artifact_id": art.artifact_id}


RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=2),
                    maximum_attempts=3)


@workflow.defn(name="MethodologyReviewWorkflow")
class MethodologyReviewWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            res = await workflow.execute_activity(methodology_review, args=[inp.task_id, inp.project_id,
                                                                            inp.params["protocol_id"]],
                                                  start_to_close_timeout=timedelta(minutes=15), retry_policy=RETRY)
            return TaskOutcome(state="succeeded", output_artifact_ids=[res["artifact_id"]] if res.get("artifact_id") else [],
                               result=res)
        return await run_task(inp, body)


@workflow.defn(name="ResultAssessmentWorkflow")
class ResultAssessmentWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            res = await workflow.execute_activity(assess_result, args=[inp.task_id, inp.project_id, inp.params["result_id"]],
                                                  start_to_close_timeout=timedelta(minutes=10), retry_policy=RETRY)
            return TaskOutcome(state="succeeded", output_artifact_ids=[res["artifact_id"]], result=res)
        return await run_task(inp, body)


register(QUEUE_RESEARCH, workflows=[MethodologyReviewWorkflow, ResultAssessmentWorkflow],
         activities=[methodology_review, assess_result])
