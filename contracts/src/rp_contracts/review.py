"""Independent review contracts (PRODUCT_SPEC §2.11, §2.12).

Four logical functions review one committed manuscript version and freeze their reports separately before the
meta-review sees any of them:

* scientific   - model-assisted review of question, protocol, evidence, contribution and conclusions
* citation_evidence - opens the stored source for every unique critical claim/evidence pair (and a documented
  risk-based sample of noncritical ones) and meaning-checks every linked span
* technical    - recomputes metrics from raw outputs where they were supplied and reports assurance levels
* compliance   - reads the official CFP snapshot rules and the compile report of the same version

A check whose source or raw artifact is unavailable is ``not_performed`` and never ``passed``. Review is
diagnostic: no acceptance score is produced.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from .textmatch import find_span

Severity = Literal["blocker", "major", "minor", "suggestion"]
ReviewFunction = Literal["scientific", "citation_evidence", "technical", "compliance"]
FUNCTIONS: tuple[str, ...] = ("scientific", "citation_evidence", "technical", "compliance")
SCIENTIFIC_GATE_FUNCTIONS = ("scientific", "citation_evidence", "technical")
Resolution = Literal["fixed", "accepted_risk", "rejected_with_reason"]
MAX_REVISION_CYCLES = 2
CheckStatus = Literal["passed", "failed", "manual_check", "not_performed", "warning"]


class Finding(BaseModel):
    function: ReviewFunction
    severity: Severity
    category: str
    title: str
    rationale: str
    check: str = Field(description="how to reproduce the check")
    proposed_fix: str | None = None
    span_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- model IO
class ScientificFindingOut(BaseModel):
    severity: Severity
    category: Literal["question", "protocol", "evidence", "contribution", "conclusions", "other"]
    issue: str
    rationale: str
    check: str
    proposed_fix: str
    span_ids: list[str]
    claim_ids: list[str]


class ScientificReviewOutput(BaseModel):
    question: str = Field(description="assessment of the research question and its framing")
    protocol: str
    evidence: str
    contribution: str
    conclusions: str
    findings: list[ScientificFindingOut]


class SpanMeaning(BaseModel):
    span_id: str
    verdict: Literal["faithful", "scope_drift", "strength_overstated", "unsupported", "contradicted"]
    rationale: str
    suggested_wording: str | None


class MeaningCheckOutput(BaseModel):
    spans: list[SpanMeaning]


VERDICT_SEVERITY = {"faithful": None, "scope_drift": "major", "strength_overstated": "major", "unsupported": "blocker",
                    "contradicted": "blocker"}


# --------------------------------------------------------------------------- sampling
SAMPLING_RULE = {
    "id": "risk-sample-v1",
    "description": "Every critical claim is checked. Noncritical claims: all when there are at most 5; otherwise "
                   "max(5, ceil(20%)) selected in order of sha256(manuscript_hash|claim_key). Unchecked claims are listed.",
}


def sample_noncritical(claim_keys: list[str], seed: str) -> tuple[list[str], list[str]]:
    keys = sorted(set(claim_keys))
    if len(keys) <= 5:
        return keys, []
    n = max(5, math.ceil(0.2 * len(keys)))
    order = sorted(keys, key=lambda k: hashlib.sha256(f"{seed}|{k}".encode()).hexdigest())
    chosen = sorted(order[:n])
    return chosen, sorted(set(keys) - set(chosen))


# --------------------------------------------------------------------------- deterministic source checks
NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)")


def check_literature_source(quote: str, source_text: str | None) -> dict[str, Any]:
    if source_text is None:
        return {"status": "not_performed", "detail": "the stored source text is unavailable; the passage could not be opened"}
    if find_span(source_text, quote) is None:
        return {"status": "failed", "detail": "the cited passage was not found in the stored source text"}
    return {"status": "passed", "detail": "passage located verbatim in the stored source text"}


def check_result_source(proposition: str, metrics: list[dict] | None) -> dict[str, Any]:
    if metrics is None:
        return {"status": "not_performed", "detail": "the result artifact could not be opened"}
    allowed: set[float] = set()
    for m in metrics:
        for k in ("value", "n", "numerator", "denominator", "ci_low", "ci_high"):
            if m.get(k) is not None:
                allowed.add(round(float(m[k]), 4))
                if k == "value" and float(m[k]) <= 1:
                    allowed.add(round(float(m[k]) * 100, 4))
    nums = {round(float(x), 4) for x in NUM.findall(proposition)}
    missing = sorted(n for n in nums if n not in allowed)
    if missing:
        return {"status": "failed", "detail": f"numbers in the claim are not in the result artifact: {missing}"}
    return {"status": "passed", "detail": "every number in the claim matches the committed result artifact"}


def check_key(claim_proposition: str, source_hash: str | None, span_texts: list[str]) -> str:
    """A prior check may be reused only while the claim, source version and span meaning inputs are unchanged."""
    basis = "\x1f".join([claim_proposition, source_hash or "-", *sorted(span_texts)])
    return hashlib.sha256(basis.encode()).hexdigest()


# --------------------------------------------------------------------------- compliance (reads official rules)
class ComplianceCheck(BaseModel):
    id: str
    status: CheckStatus
    detail: str
    blocking: bool = True
    rule_id: str | None = None
    quote: str | None = None
    source: str | None = None


def evaluate_compliance(*, rules: list[dict], compile_run: dict | None, manuscript: dict, template: dict | None,
                        cfp_available: bool) -> list[ComplianceCheck]:
    """rules: [{id, rule_key, value, value_text, quote, quote_in_snapshot, blocking, snapshot_url}];
    compile_run: {status, checks{id: status}, pages, options}; manuscript: {abstract_words, sections{key: bool}}."""
    out: list[ComplianceCheck] = []
    if not cfp_available:
        out.append(ComplianceCheck(id="cfp.official_rules", status="not_performed",
                                   detail="no confirmed official CFP snapshot for the target venue/track"))
    if template is None:
        out.append(ComplianceCheck(id="template.confirmed", status="not_performed",
                                   detail="no confirmed official template"))
    else:
        out.append(ComplianceCheck(id="template.confirmed", status="passed",
                                   detail=f"confirmed {template.get('family')} template, archive {template.get('archive_hash', '')[:12]}"))
    if compile_run is None:
        out.append(ComplianceCheck(id="compile.current_version", status="not_performed",
                                   detail="no compile run for the current manuscript version"))
        checks: dict[str, str] = {}
    else:
        checks = compile_run.get("checks") or {}
        ok = compile_run.get("status") == "compiled"
        out.append(ComplianceCheck(id="compile.current_version", status="passed" if ok else "failed",
                                   detail=f"compile status {compile_run.get('status')}, {compile_run.get('pages')} pages"))
        for cid in ("citations.resolved", "figures.render", "template.protected_unchanged", "compile.shell_escape_disabled"):
            if cid in checks:
                out.append(ComplianceCheck(id=cid, status=_map(checks[cid]), detail=f"compile check {cid}: {checks[cid]}"))
    for r in rules:
        src = dict(rule_id=r["id"], quote=r.get("quote"), source=r.get("snapshot_url"), blocking=bool(r.get("blocking", True)))
        if not r.get("quote_in_snapshot"):
            out.append(ComplianceCheck(id=f"rule:{r['rule_key']}", status="not_performed",
                                       detail="the rule's quote was not found in the official snapshot text; re-extract", **src))
            continue
        key, val = r["rule_key"], r.get("value")
        if key == "length.page_limit":
            if compile_run is None or compile_run.get("pages") is None:
                out.append(ComplianceCheck(id="rule:length.page_limit", status="not_performed", detail="no page count", **src))
            elif not (val or "").isdigit():
                out.append(ComplianceCheck(id="rule:length.page_limit", status="manual_check",
                                           detail=f"page limit not machine-readable: {r.get('value_text')}", **src))
            else:
                excl = any(x["rule_key"] == "length.reference_pages" for x in rules)
                pages = int(compile_run["pages"])
                if pages <= int(val):
                    out.append(ComplianceCheck(id="rule:length.page_limit", status="passed",
                                               detail=f"{pages} pages <= {val}", **src))
                elif excl:
                    out.append(ComplianceCheck(id="rule:length.page_limit", status="manual_check",
                                               detail=f"{pages} pages total exceeds {val}; references may be excluded - "
                                                      "confirm the body length", **src))
                else:
                    out.append(ComplianceCheck(id="rule:length.page_limit", status="failed",
                                               detail=f"{pages} pages > {val}; shorten without removing essential findings", **src))
        elif key == "abstract.word_limit" and (val or "").isdigit():
            w = manuscript.get("abstract_words", 0)
            out.append(ComplianceCheck(id="rule:abstract.word_limit", status="passed" if w <= int(val) else "failed",
                                       detail=f"abstract has {w} words (limit {val})", **src))
        elif key == "anonymization.mode":
            if (val or "").lower() in ("double_blind", "double-blind", "anonymous"):
                if compile_run is None:
                    st, d = "not_performed", "no compile run to check anonymization"
                elif not (compile_run.get("options") or {}).get("anonymous"):
                    st, d = "failed", "the venue requires anonymous submission; compile the anonymized variant"
                else:
                    st = _map(checks.get("anonymization.no_identity_leak", "not_performed"))
                    d = f"identity-leak scan: {checks.get('anonymization.no_identity_leak', 'not performed')}"
                out.append(ComplianceCheck(id="rule:anonymization.mode", status=st, detail=d, **src))
                out.append(ComplianceCheck(id="anonymization.visual_inspection", status="manual_check",
                                           detail="inspect figures, acknowledgements and self-citations by eye", **src))
            else:
                out.append(ComplianceCheck(id="rule:anonymization.mode", status="passed",
                                           detail=f"anonymization mode: {val or r.get('value_text')}", **src))
        elif key in ("format.layout", "template.family"):
            fam = (template or {}).get("family")
            text = f"{val or ''} {r.get('value_text') or ''}".lower()
            if fam and fam.lower() in text:
                out.append(ComplianceCheck(id=f"rule:{key}", status="passed", detail=f"template family {fam} matches", **src))
            else:
                out.append(ComplianceCheck(id=f"rule:{key}", status="manual_check",
                                           detail=f"confirm the template ({fam}) satisfies: {r.get('value_text') or val}", **src))
        elif r.get("blocking"):
            out.append(ComplianceCheck(id=f"rule:{key}", status="manual_check",
                                       detail=f"not machine-checkable: {r.get('value_text') or val}", **src))
    return out


def _map(s: str) -> CheckStatus:
    return s if s in ("passed", "failed", "manual_check", "not_performed", "warning") else "manual_check"


def compliance_findings(checks: list[ComplianceCheck]) -> list[Finding]:
    out = []
    for c in checks:
        if c.status in ("failed", "not_performed") and c.blocking:
            out.append(Finding(function="compliance", severity="blocker", category="venue_compliance",
                               title=f"{c.id}: {c.status}", rationale=c.detail, check=f"compliance check {c.id}",
                               proposed_fix=None, rule_ids=[c.rule_id] if c.rule_id else []))
    return out


# --------------------------------------------------------------------------- meta-review
def meta_review(reports: dict[str, dict]) -> dict[str, Any]:
    """Consolidate frozen reports. reports: function -> {status, findings[], assessed_ok{span_ids, claim_ids}}."""
    counts = {f: {s: 0 for s in ("blocker", "major", "minor", "suggestion")} for f in reports}
    flagged_spans: dict[str, set[str]] = {}
    flagged_claims: dict[str, set[str]] = {}
    for f, r in reports.items():
        for x in r.get("findings", []):
            counts[f][x["severity"]] += 1
            if x["severity"] in ("blocker", "major"):
                for s in x.get("span_ids", []):
                    flagged_spans.setdefault(s, set()).add(f)
                for c in x.get("claim_ids", []):
                    flagged_claims.setdefault(c, set()).add(f)
    disagreements = []
    for f, r in reports.items():
        ok = r.get("assessed_ok") or {}
        for s in ok.get("span_ids", []):
            if s in flagged_spans and f not in flagged_spans[s]:
                disagreements.append({"span_id": s, "flagged_by": sorted(flagged_spans[s]), "judged_ok_by": f})
        for c in ok.get("claim_ids", []):
            if c in flagged_claims and f not in flagged_claims[c]:
                disagreements.append({"claim_id": c, "flagged_by": sorted(flagged_claims[c]), "judged_ok_by": f})
    not_performed = [{"function": f, "detail": r.get("not_performed_detail")} for f, r in reports.items()
                     if r.get("status") == "not_performed"]
    return {"counts": counts, "disagreements": disagreements, "not_performed": not_performed,
            "note": "AI review is diagnostic; it is not an acceptance decision."}


EXPORT = [ScientificReviewOutput, MeaningCheckOutput, Finding, ComplianceCheck]
