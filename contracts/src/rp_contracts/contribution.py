"""M5 contracts: ethics/rights declaration, supplied-result manifests and the deterministic assurance assessor,
methodology review agent output, and the research contribution validation matrix (PRODUCT_SPEC §2.4, §2.7–§2.9).

Assurance levels describe available checking, never scientific truth:
  declared               researcher attested; no independent check possible
  internally_consistent  documented deterministic consistency checks on the supplied aggregates pass
  independently_checked  a separate validator recomputed the metrics from supplied raw data and they match
  reproduced             a documented rerun matched preset tolerances (M9 platform runs or recorded reruns)
A level is never promoted from model confidence or from a polished table alone.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from .enums import ASSURANCE_ORDER, AssuranceLevel


class InstitutionalApproval(BaseModel):
    required: bool
    status: Literal["obtained", "pending", "not_required", "not_applicable"]
    body: str | None = None
    reference: str | None = None
    document_artifact_id: str | None = None


class EthicsRightsDeclaration(BaseModel):
    involves_human_participants: bool
    personal_data: bool
    sensitive_data: bool
    restricted_datasets: bool
    data_licences: list[str] = Field(default_factory=list)
    third_party_rights_notes: str | None = None
    institutional_approval: InstitutionalApproval
    consent_procedure: str | None = None
    deidentification_plan: str | None = None
    declaration_text_accepted: bool = False


ETHICS_DECLARATION_TEXT = (
    "I declare the ethics, privacy and rights status of this protocol accurately. The platform does not grant ethics "
    "approval; any required institutional approval has been obtained by me or my institution and is recorded here."
)


def ethics_blockers(d: EthicsRightsDeclaration | None) -> list[str]:
    if d is None:
        return ["the ethics and rights declaration is missing"]
    out = []
    if not d.declaration_text_accepted:
        out.append("accept the ethics and rights declaration")
    needs = d.involves_human_participants or d.personal_data or d.sensitive_data
    if needs and not d.institutional_approval.required:
        out.append("human participants or personal/sensitive data normally require institutional approval; "
                   "record the approval or the official reason it is not required")
    if d.institutional_approval.required and d.institutional_approval.status != "obtained":
        out.append("the required institutional approval has not been obtained (the platform cannot grant it)")
    if d.institutional_approval.status == "obtained" and not (d.institutional_approval.reference or
                                                              d.institutional_approval.document_artifact_id):
        out.append("record the approval reference or upload the approval document")
    if (d.personal_data or d.sensitive_data) and not d.deidentification_plan:
        out.append("describe the de-identification/handling plan for personal data")
    if d.restricted_datasets and not d.data_licences:
        out.append("list the licences or agreements for restricted datasets")
    return out


class MetricValue(BaseModel):
    name: str = Field(description="e.g. accuracy, f1, precision, recall, mae, rmse, mean, count, proportion")
    value: float
    unit: str | None = Field(description="e.g. proportion, percent, seconds, count")
    n: int | None = None
    condition: str | None = Field(default=None, description="arm/condition/model the value belongs to")
    ci_low: float | None = None
    ci_high: float | None = None
    numerator: int | None = None
    denominator: int | None = None


class ResultFile(BaseModel):
    role: Literal["raw_data", "predictions", "code", "environment", "analysis_script", "figure", "other"]
    artifact_id: str
    description: str | None = None


class ResultManifest(BaseModel):
    title: str
    protocol_version: int
    protocol_hash: str
    data_origin: str
    data_rights: str
    methods: str
    metrics: list[MetricValue]
    sample_size: int | None = None
    collected_at: str | None = None
    exclusions: str | None = None
    limitations: str
    files: list[ResultFile] = Field(default_factory=list)
    run_type: Literal["exploratory", "confirmatory"] = "confirmatory"
    synthetic_or_simulated: bool = False
    rerun_record: dict | None = Field(default=None, description="documented rerun: values + tolerance (for 'reproduced')")
    attestation_accepted: bool = False


RESULT_ATTESTATION = ("I attest that these results were produced as described, follow the frozen protocol version "
                      "named here, and that the files and values are complete to my knowledge; missing items are "
                      "stated. Synthetic or simulated data is labelled as such.")


@dataclass
class CheckOutcome:
    id: str
    status: str  # passed | failed | not_performed
    detail: str
    evidence: dict = field(default_factory=dict)


PROPORTION_METRICS = {"accuracy", "precision", "recall", "f1", "proportion", "specificity", "auc", "rate"}


def _is_prop(m: MetricValue) -> bool:
    return m.name.lower() in PROPORTION_METRICS or (m.unit or "").lower() in ("proportion", "percent", "%")


def consistency_checks(manifest: ResultManifest) -> list[CheckOutcome]:
    out: list[CheckOutcome] = []
    for i, m in enumerate(manifest.metrics):
        tag = f"{m.name}[{m.condition or i}]"
        if not math.isfinite(m.value):
            out.append(CheckOutcome(f"finite:{tag}", "failed", "value is not finite"))
            continue
        if _is_prop(m):
            upper = 100 if (m.unit or "").lower() in ("percent", "%") else 1
            ok = 0 <= m.value <= upper
            out.append(CheckOutcome(f"range:{tag}", "passed" if ok else "failed",
                                    f"{m.value} within [0, {upper}]" if ok else f"{m.value} outside [0, {upper}]"))
        if m.n is not None:
            out.append(CheckOutcome(f"n_positive:{tag}", "passed" if m.n > 0 else "failed", f"n={m.n}"))
        if m.numerator is not None and m.denominator:
            ratio = m.numerator / m.denominator
            scaled = ratio * (100 if (m.unit or "").lower() in ("percent", "%") else 1)
            ok = abs(scaled - m.value) <= 0.005 * (100 if (m.unit or "").lower() in ("percent", "%") else 1)
            out.append(CheckOutcome(f"ratio:{tag}", "passed" if ok else "failed",
                                    f"{m.numerator}/{m.denominator} = {scaled:.4f} vs reported {m.value}"))
        if m.ci_low is not None and m.ci_high is not None:
            ok = m.ci_low <= m.value <= m.ci_high
            out.append(CheckOutcome(f"ci:{tag}", "passed" if ok else "failed",
                                    f"[{m.ci_low}, {m.ci_high}] {'contains' if ok else 'excludes'} {m.value}"))
        if manifest.sample_size is not None and m.n is not None and m.n > manifest.sample_size:
            out.append(CheckOutcome(f"n_le_sample:{tag}", "failed", f"n={m.n} exceeds sample size {manifest.sample_size}"))
        if m.unit is None:
            out.append(CheckOutcome(f"unit:{tag}", "failed", "no unit/denominator recorded"))
    return out


def _metric(name: str, y_true: list[str], y_pred: list[str]) -> float | None:
    n = len(y_true)
    if n == 0:
        return None
    name = name.lower()
    if name == "accuracy":
        return sum(a == b for a, b in zip(y_true, y_pred, strict=True)) / n
    labels = sorted(set(y_true) | set(y_pred))
    if name in ("precision", "recall", "f1") and len(labels) == 2:
        pos = "1" if "1" in labels else labels[-1]
        tp = sum(a == pos and b == pos for a, b in zip(y_true, y_pred, strict=True))
        fp = sum(a != pos and b == pos for a, b in zip(y_true, y_pred, strict=True))
        fn = sum(a == pos and b != pos for a, b in zip(y_true, y_pred, strict=True))
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return {"precision": p, "recall": r, "f1": (2 * p * r / (p + r)) if p + r else 0.0}[name]
    if name in ("mae", "rmse"):
        try:
            diffs = [float(a) - float(b) for a, b in zip(y_true, y_pred, strict=True)]
        except ValueError:
            return None
        return sum(abs(d) for d in diffs) / n if name == "mae" else math.sqrt(sum(d * d for d in diffs) / n)
    return None


def recompute_from_predictions(manifest: ResultManifest, predictions_csv: bytes, tolerance: float = 1e-3) -> list[CheckOutcome]:
    """Independent recomputation of declared metrics from raw predictions (columns: y_true, y_pred[, condition])."""
    try:
        rows = list(csv.DictReader(io.StringIO(predictions_csv.decode("utf-8"))))
    except UnicodeDecodeError:
        return [CheckOutcome("recompute:parse", "failed", "predictions file is not UTF-8 CSV")]
    if not rows or not {"y_true", "y_pred"} <= set(rows[0].keys()):
        return [CheckOutcome("recompute:parse", "failed", "predictions CSV needs y_true and y_pred columns")]
    out = []
    for m in manifest.metrics:
        sel = [r for r in rows if m.condition is None or r.get("condition", m.condition) == m.condition]
        val = _metric(m.name, [r["y_true"] for r in sel], [r["y_pred"] for r in sel])
        if val is None:
            out.append(CheckOutcome(f"recompute:{m.name}[{m.condition}]", "not_performed",
                                    f"metric {m.name} cannot be recomputed from predictions"))
            continue
        reported = m.value / 100 if (m.unit or "").lower() in ("percent", "%") else m.value
        ok = abs(val - reported) <= tolerance
        out.append(CheckOutcome(f"recompute:{m.name}[{m.condition}]", "passed" if ok else "failed",
                                f"recomputed {val:.4f} vs reported {reported:.4f} (tolerance {tolerance})",
                                {"recomputed": val, "reported": reported, "n": len(sel)}))
        if m.n is not None and m.n != len(sel):
            out.append(CheckOutcome(f"recompute:n[{m.name}]", "failed", f"predictions have {len(sel)} rows, n={m.n}"))
    return out


@dataclass
class AssuranceResult:
    level: AssuranceLevel
    checks: list[CheckOutcome]
    missing: list[str]
    impossible_checks: list[str]
    wording_limits: list[str]
    blockers: list[str]

    def as_dict(self) -> dict:
        return {"level": self.level.value, "checks": [c.__dict__ for c in self.checks], "missing": self.missing,
                "impossible_checks": self.impossible_checks, "wording_limits": self.wording_limits,
                "blockers": self.blockers}


WORDING = {
    AssuranceLevel.DECLARED: "Report as results supplied and attested by the authors; do not describe them as "
                             "independently checked or reproduced.",
    AssuranceLevel.INTERNALLY_CONSISTENT: "Results passed internal consistency checks; they were not independently "
                                          "recomputed or reproduced.",
    AssuranceLevel.INDEPENDENTLY_CHECKED: "Key metrics were recomputed from the supplied raw outputs; the experiment "
                                          "itself was not re-run.",
    AssuranceLevel.REPRODUCED: "A documented rerun matched within the preset tolerances.",
}


def assess(manifest: ResultManifest, *, predictions: bytes | None, protocol_frozen_hash: str | None) -> AssuranceResult:
    blockers, missing, impossible = [], [], []
    if not manifest.attestation_accepted:
        blockers.append("researcher attestation missing")
    if protocol_frozen_hash is None:
        blockers.append("no frozen (H2-approved) protocol: results cannot be accepted against an unapproved revision")
    elif manifest.protocol_hash != protocol_frozen_hash:
        blockers.append("the manifest names a protocol revision that is not the frozen, approved one")
    if not manifest.data_rights.strip():
        blockers.append("data rights/provenance not declared")
    roles = {f.role for f in manifest.files}
    for need, label in (("raw_data", "raw data"), ("predictions", "raw predictions/outputs"), ("code", "analysis code"),
                        ("environment", "environment details")):
        if need not in roles:
            missing.append(label)
    checks = consistency_checks(manifest)
    level = AssuranceLevel.DECLARED
    cross = [c for c in checks if c.id.split(":")[0] in ("ratio", "ci", "n_le_sample")]
    if checks and cross and all(c.status == "passed" for c in checks):
        level = AssuranceLevel.INTERNALLY_CONSISTENT
    elif not cross:
        impossible.append("internal consistency cannot be checked: no numerators/denominators, intervals or sample "
                          "sizes that cross-check the reported values")
    if predictions is not None:
        rc = recompute_from_predictions(manifest, predictions)
        checks += rc
        if level == AssuranceLevel.INTERNALLY_CONSISTENT and rc and all(c.status in ("passed",) for c in rc):
            level = AssuranceLevel.INDEPENDENTLY_CHECKED
    else:
        impossible.append("independent recomputation impossible: no raw predictions supplied")
    if manifest.rerun_record:
        rr = manifest.rerun_record
        ok = all(abs(float(rr.get("values", {}).get(m.name, math.inf)) - m.value) <= float(rr.get("tolerance", 0))
                 for m in manifest.metrics)
        checks.append(CheckOutcome("rerun:match", "passed" if ok else "failed",
                                   f"documented rerun {'matches' if ok else 'does not match'} within tolerance",
                                   {"rerun": rr}))
        if ok and level == AssuranceLevel.INDEPENDENTLY_CHECKED:
            level = AssuranceLevel.REPRODUCED
    else:
        impossible.append("reproduction not documented")
    if any(c.status == "failed" for c in checks):
        level = AssuranceLevel.DECLARED
        blockers.append("a consistency or recomputation check failed; review the anomaly before H3")
    wording = [WORDING[level]]
    if manifest.synthetic_or_simulated:
        wording.append("Data are synthetic/simulated and must be labelled as such; they cannot stand in for empirical findings.")
    if manifest.run_type == "exploratory":
        wording.append("Exploratory run: do not present as confirmatory evidence.")
    return AssuranceResult(level, checks, missing, impossible, wording, blockers)


def max_level(levels: list[AssuranceLevel]) -> AssuranceLevel:
    return max(levels, key=ASSURANCE_ORDER.index) if levels else AssuranceLevel.DECLARED


# --------------------------------------------------------------------------- methodology review agent
class MethodIssue(BaseModel):
    severity: Literal["blocker", "major", "minor", "suggestion"]
    section: str
    issue: str
    rationale: str
    proposed_fix: str


class MethodologyReview(BaseModel):
    can_answer_question: Literal["yes", "partially", "no", "unclear"]
    issues: list[MethodIssue]
    threats_to_validity: list[str]
    ethics_flags: list[str]
    cost_flags: list[str]


# --------------------------------------------------------------------------- contribution validation matrix
OUTCOMES = ("supported", "partially_supported", "not_supported", "inconclusive")
GAP_RESOLUTIONS = ("addressed", "partially_addressed", "not_addressed", "inconclusive")


class MatrixRow(BaseModel):
    rq_index: int
    research_question: str
    intended_novelty: str
    intended_contribution: str
    success_criterion: str
    evidence_ids: list[str] = Field(default_factory=list)
    validity_assessment: str | None = None
    outcome: Literal["supported", "partially_supported", "not_supported", "inconclusive"] | None = None
    limitations: str | None = None
    h3_decision: Literal["accepted", "revise"] | None = None


EXPORT = [EthicsRightsDeclaration, ResultManifest, MethodologyReview, MatrixRow]
