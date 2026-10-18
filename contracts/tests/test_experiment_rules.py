"""M9 plan validation, argv quoting, cost estimate and reproduction comparison."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rp_contracts.experiments import (
    ExperimentPlanIn,
    PlanLimits,
    argv_for,
    compare_metrics,
    estimate_cents,
    plan_problems,
    shell_command,
)

IMAGES = {"python-sci:1": "sha256:abc"}


def plan(**over):
    base = {"title": "toy study", "code_artifact_id": "c", "entrypoint": ["python", "main.py", "--seed", "{seed}"], "image": "python-sci:1",
            "seed": 3, "run_type": "confirmatory", "metrics": [{"name": "accuracy"}], "data_origin": "public data",
            "data_rights": "CC-BY", "limitations": "small"}
    base.update(over)
    return ExperimentPlanIn.model_validate(base)


def test_valid_plan_and_seed_substitution():
    p = plan()
    assert plan_problems(p, IMAGES) == [] and argv_for(p) == ["python", "main.py", "--seed", "3"]


def test_rejects_unlisted_image_shell_syntax_and_excess_limits():
    assert any("allowlist" in x for x in plan_problems(plan(image="ubuntu"), IMAGES))
    assert any("not allowed" in x for x in plan_problems(plan(entrypoint=["python", "x.py", "$(rm -rf /)"]), IMAGES))
    assert any("must start" in x for x in plan_problems(plan(entrypoint=["bash", "-c", "x"]), IMAGES))
    assert any("exceeds the cap" in x for x in plan_problems(plan(limits={"cpus": 64}), IMAGES))
    assert any("under out/" in x for x in plan_problems(plan(metrics_path="metrics.json"), IMAGES))


def test_paths_cannot_escape_the_workspace():
    with pytest.raises(ValidationError):
        plan(inputs=[{"artifact_id": "a", "path": "../../etc/passwd", "data_nature": "empirical"}])
    with pytest.raises(ValidationError):
        plan(code_path="/abs/main.py")


def test_arguments_are_quoted_for_the_sandbox_shell():
    assert shell_command(["python", "main.py", "a b"]) == "python main.py 'a b'"


def test_estimate_and_reproduction_comparison():
    assert estimate_cents(PlanLimits(cpus=2, timeout_s=600)) == 20
    ok = compare_metrics({"accuracy": 0.75}, {"accuracy": 0.75}, 1e-9)
    assert ok["match"]
    bad = compare_metrics({"accuracy": 0.75}, {"accuracy": 0.76}, 1e-3)
    assert not bad["match"] and not bad["rows"][0]["within_tolerance"]
    assert not compare_metrics({"accuracy": 0.75}, {}, 1e-3)["match"], "a missing rerun metric never matches"
