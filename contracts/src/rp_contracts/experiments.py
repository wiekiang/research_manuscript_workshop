"""Platform-executed computational experiments (PRODUCT_SPEC §2.9, M9).

Only an approved plan bound to the frozen (H2) protocol runs, inside the no-network sandbox with a pinned image
digest, immutable input hashes, a fixed seed, resource limits and a platform-chosen argv. Each run produces raw
outputs, logs, an environment manifest and a rerun command. A separate validator recomputes key metrics from raw
outputs. Failed runs are recorded and can never populate results; synthetic/simulated inputs are labelled.
"""

from __future__ import annotations

import math
import re
import shlex
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ALLOWED_INTERPRETERS = {"python"}
MAX_LIMITS = {"cpus": 4.0, "memory_mb": 8192, "timeout_s": 3600}
CENTS_PER_CPU_MINUTE = 1  # documented internal compute rate used for budget estimates (DEPLOYMENT.md)
OUTPUT_DIR = "out"
SAFE_ARG = re.compile(r"^[A-Za-z0-9_.,=:/+-]{1,200}$")


def _safe_path(p: str) -> str:
    pp = PurePosixPath(p)
    if pp.is_absolute() or ".." in pp.parts or not p or "\x00" in p:
        raise ValueError(f"unsafe path {p!r}")
    return str(pp)


class PlanInput(BaseModel):
    artifact_id: str
    path: str = Field(description="where the file appears in the sandbox workspace, e.g. data/train.csv")
    data_nature: Literal["empirical", "synthetic", "simulated"]

    @field_validator("path")
    @classmethod
    def _p(cls, v: str) -> str:
        return _safe_path(v)


class PlanLimits(BaseModel):
    cpus: float = Field(default=1.0, gt=0)
    memory_mb: int = Field(default=1024, ge=128)
    timeout_s: int = Field(default=600, ge=10)


class MetricSpec(BaseModel):
    name: str
    condition: str | None = None


class ExperimentPlanIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    code_artifact_id: str
    code_path: str = Field(default="main.py", description="script path inside the workspace (zip archives are unpacked)")
    entrypoint: list[str] = Field(description="argv, e.g. ['python', 'main.py', '--seed', '{seed}']")
    inputs: list[PlanInput] = Field(default_factory=list)
    image: str = Field(description="allowlisted image key, e.g. python-sci:1")
    seed: int = Field(ge=0, le=2**31 - 1)
    limits: PlanLimits = Field(default_factory=PlanLimits)
    run_type: Literal["exploratory", "confirmatory"]
    metrics: list[MetricSpec] = Field(min_length=1)
    tolerance: float = Field(default=1e-9, ge=0, description="absolute tolerance for rerun agreement")
    predictions_path: str = Field(default="out/predictions.csv")
    metrics_path: str = Field(default="out/metrics.json")
    sample_size: int | None = None
    data_origin: str = Field(min_length=3)
    data_rights: str = Field(min_length=3)
    limitations: str = Field(min_length=3)

    @field_validator("code_path", "predictions_path", "metrics_path")
    @classmethod
    def _paths(cls, v: str) -> str:
        return _safe_path(v)


def plan_problems(p: ExperimentPlanIn, images: dict[str, str]) -> list[str]:
    out = []
    if p.image not in images:
        out.append(f"image {p.image} is not on the sandbox allowlist {sorted(images)}")
    if not p.entrypoint or p.entrypoint[0] not in ALLOWED_INTERPRETERS:
        out.append(f"the entrypoint must start with one of {sorted(ALLOWED_INTERPRETERS)}")
    for a in p.entrypoint[1:]:
        if a != "{seed}" and not SAFE_ARG.match(a):
            out.append(f"argument {a!r} contains characters that are not allowed")
    for k, cap in MAX_LIMITS.items():
        if getattr(p.limits, k) > cap:
            out.append(f"limit {k}={getattr(p.limits, k)} exceeds the cap {cap}")
    if not p.predictions_path.startswith(OUTPUT_DIR + "/") or not p.metrics_path.startswith(OUTPUT_DIR + "/"):
        out.append(f"outputs must be written under {OUTPUT_DIR}/")
    return out


def argv_for(p: ExperimentPlanIn) -> list[str]:
    return [a.replace("{seed}", str(p.seed)) for a in p.entrypoint]


def shell_command(argv: list[str]) -> str:
    """The sandbox joins steps with a shell; every argument is quoted so plan text can never become shell syntax."""
    return " ".join(shlex.quote(a) for a in argv)


def estimate_cents(limits: PlanLimits) -> int:
    return max(1, math.ceil(limits.cpus * limits.timeout_s / 60 * CENTS_PER_CPU_MINUTE))


def rerun_command(plan_id: str) -> str:
    return f"POST /v1/experiment-plans/{plan_id}/runs  {{\"rerun_of\": \"<run id>\"}}  (same image digest, inputs, code, seed)"


def compare_metrics(a: dict[str, float], b: dict[str, float], tolerance: float) -> dict:
    keys = sorted(set(a) | set(b))
    rows = []
    for k in keys:
        x, y = a.get(k), b.get(k)
        ok = x is not None and y is not None and abs(float(x) - float(y)) <= tolerance
        rows.append({"metric": k, "first": x, "rerun": y, "difference": None if x is None or y is None else abs(float(x) - float(y)),
                     "within_tolerance": ok})
    return {"tolerance": tolerance, "rows": rows, "match": bool(rows) and all(r["within_tolerance"] for r in rows)}


EXPORT = [ExperimentPlanIn]
