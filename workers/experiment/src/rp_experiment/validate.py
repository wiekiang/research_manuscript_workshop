"""Independent validator: recompute key metrics from a run's raw outputs, separately from the run's own report."""

from __future__ import annotations

import json

from rp_contracts.contribution import MetricValue, ResultManifest, recompute_from_predictions
from rp_contracts.experiments import ExperimentPlanIn

VALIDATOR_VERSION = "rp-experiment-validator/1"


def reported_metrics(outputs: dict[str, bytes], plan: ExperimentPlanIn) -> tuple[dict[str, float] | None, str | None]:
    raw = outputs.get(plan.metrics_path)
    if raw is None:
        return None, f"{plan.metrics_path} was not produced"
    try:
        data = json.loads(raw)
        return {m.name: float(data[m.name]) for m in plan.metrics}, None
    except (ValueError, KeyError, TypeError) as exc:
        return None, f"{plan.metrics_path} is not a JSON object with the planned metrics: {exc}"


def recompute(plan: ExperimentPlanIn, outputs: dict[str, bytes], protocol: dict) -> dict:
    reported, problem = reported_metrics(outputs, plan)
    preds = outputs.get(plan.predictions_path)
    if reported is None or preds is None:
        return {"status": "not_performed", "detail": problem or f"{plan.predictions_path} was not produced",
                "validator": VALIDATOR_VERSION, "checks": []}
    manifest = ResultManifest(title=plan.title, protocol_version=protocol["version"], protocol_hash=protocol["hash"],
                              data_origin=plan.data_origin, data_rights=plan.data_rights, methods="platform run",
                              metrics=[MetricValue(name=m.name, value=reported[m.name], condition=m.condition,
                                                   unit="proportion") for m in plan.metrics],
                              limitations=plan.limitations, sample_size=plan.sample_size)
    checks = recompute_from_predictions(manifest, preds)
    ok = bool(checks) and all(c.status == "passed" for c in checks)
    return {"status": "passed" if ok else "failed", "reported": reported, "validator": VALIDATOR_VERSION,
            "checks": [c.__dict__ for c in checks],
            "detail": "every planned metric was recomputed from the raw predictions" if ok
            else "recomputation disagreed with the run's reported metrics or could not be performed"}
