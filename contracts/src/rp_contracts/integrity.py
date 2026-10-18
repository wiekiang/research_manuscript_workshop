"""Research integrity engine (PRODUCT_SPEC §2.13): deterministic cross-stage checks over one manuscript version.

Fail-closed: fabricated or mismatched references, missing critical provenance, unresolved ethics/rights issues and
mismatched results are ``failed`` and block. Uncertainty that cannot be resolved automatically is ``warning`` or
``manual_check`` and requires a signed human decision. The report never certifies integrity and the text-overlap
check is explicitly limited to sources stored in the project.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from .contribution import EthicsRightsDeclaration, ethics_blockers

Status = Literal["passed", "failed", "warning", "manual_check", "not_performed"]
ENGINE_VERSION = "rp-integrity/1"
DISCLAIMER = ("This report lists the checks performed, their scope and limitations. It does not certify research "
              "integrity, and the text-overlap check is not comprehensive plagiarism detection.")

VERIFIED_WORDING = re.compile(r"\b(independently (checked|verified|validated)|verified|validated|confirmed|reproduc\w*)\b", re.I)
REPRODUCED_WORDING = re.compile(r"\b(reproduc\w*|replicat\w*)\b", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
WORD = re.compile(r"[a-z0-9]+")


class IntegrityCheck(BaseModel):
    id: str
    title: str
    status: Status
    detail: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    scope: str
    limitations: str | None = None
    blocking: bool = True

    @property
    def requires_decision(self) -> bool:
        return self.status in ("warning", "manual_check")


def _shingles(text: str, n: int = 8) -> set[tuple[str, ...]]:
    w = WORD.findall(text.lower())
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def run_integrity(b: dict[str, Any]) -> list[IntegrityCheck]:
    """b keys: spans[{span_id, section, kind, text, origin, claim_ids, result_keys, issues}], bibliography
    [{cite_key, identity_status, retracted, doi}], results{key: {assurance, protocol_hash, data_origin, data_rights,
    assessment_blockers, failed_checks}}, frozen_protocol_hash, protocol{ethics_rights, after_data_inspection_amendments},
    contributions[{title, pii_classification, rights_statement}], figures[{file_name, artifact_id, committed}],
    sources[{id, text}], template{license_note}, authors_emails[], declarations (None until recorded) {coi, funding,
    ai_use, ethics_statement}."""
    out: list[IntegrityCheck] = []
    spans = b.get("spans", [])

    bib = b.get("bibliography", [])
    bad = [e["cite_key"] for e in bib if e.get("identity_status") != "verified"]
    retracted = [e["cite_key"] for e in bib if e.get("retracted")]
    out.append(IntegrityCheck(
        id="references.identity", title="Fabricated or mismatched references",
        status="failed" if bad or retracted else "passed",
        detail=(f"unverified identity: {bad}; " if bad else "") + (f"retracted: {retracted}" if retracted else "")
        or f"all {len(bib)} bibliography entries have registry-verified identities",
        evidence={"entries": len(bib), "unverified": bad, "retracted": retracted}, scope="bibliography of this version"))

    unsupported = [s["span_id"] for s in spans if any(i["code"] in ("unsupported_factual_span", "unknown_claim",
                                                                      "unverified_claim", "unknown_result")
                                                      for i in s.get("issues", []))]
    out.append(IntegrityCheck(
        id="claims.supported", title="Unsupported claims", status="failed" if unsupported else "passed",
        detail=f"{len(unsupported)} factual span(s) lack verified claim/result support" if unsupported
        else "every factual span cites a verified claim or committed result",
        evidence={"span_ids": unsupported}, scope="all spans of this version"))

    results = b.get("results", {})
    overstated = []
    for s in spans:
        for rk in s.get("result_keys", []):
            r = results.get(rk)
            if r is None:
                continue
            if r["assurance"] == "declared" and VERIFIED_WORDING.search(s["text"]):
                overstated.append({"span_id": s["span_id"], "result": rk, "assurance": "declared"})
            elif r["assurance"] in ("declared", "internally_consistent", "independently_checked") and REPRODUCED_WORDING.search(s["text"]):
                overstated.append({"span_id": s["span_id"], "result": rk, "assurance": r["assurance"]})
    out.append(IntegrityCheck(
        id="results.wording_vs_assurance", title="Result wording matches assurance level",
        status="failed" if overstated else "passed",
        detail=f"{len(overstated)} span(s) describe supplied results more strongly than their assurance level" if overstated
        else "result wording stays within each result's assurance level",
        evidence={"overstated": overstated}, scope="spans citing results"))

    frozen = b.get("frozen_protocol_hash")
    prov = []
    mismatch = []
    for rk, r in results.items():
        missing = [k for k in ("data_origin", "data_rights") if not r.get(k)]
        if r.get("protocol_hash") != frozen:
            missing.append("bound to the frozen protocol")
        if r.get("assessment_blockers"):
            missing.append("assessment blockers: " + "; ".join(r["assessment_blockers"]))
        if missing:
            prov.append({"result": rk, "missing": missing})
        if r.get("failed_checks"):
            mismatch.append({"result": rk, "failed_checks": r["failed_checks"]})
    out.append(IntegrityCheck(
        id="results.provenance", title="Critical result provenance", status="failed" if prov else "passed",
        detail=f"{len(prov)} result(s) lack critical provenance" if prov else f"{len(results)} result(s) have origin, rights and frozen-protocol binding",
        evidence={"problems": prov}, scope="committed results cited or approved at H3"))
    out.append(IntegrityCheck(
        id="results.consistency", title="Manipulated or mismatched results", status="failed" if mismatch else "passed",
        detail=f"recomputation disagreed for {[m['result'] for m in mismatch]}" if mismatch
        else "no recomputation disagreed with a supplied value",
        evidence={"mismatches": mismatch}, scope="results with raw outputs",
        limitations="Results supplied only as aggregates cannot be recomputed; their assurance level stays 'declared'."))

    pii = [c["title"] for c in b.get("contributions", []) if c.get("pii_classification") not in (None, "none")]
    author_emails = {e.lower() for e in b.get("authors_emails", [])}
    leaked = sorted({m for s in spans for m in EMAIL.findall(s["text"]) if m.lower() not in author_emails})
    out.append(IntegrityCheck(
        id="data.leakage", title="Personal or confidential data leakage",
        status="failed" if leaked else ("manual_check" if pii else "passed"),
        detail=(f"e-mail addresses in the manuscript: {leaked}" if leaked else
                f"contributions classified as containing personal data: {pii}; confirm none is disclosed" if pii
                else "no contribution is classified as personal data and no e-mail addresses appear in the text"),
        evidence={"pii_contributions": pii, "emails": leaked}, scope="manuscript text and contribution classifications",
        limitations="Pattern-based; it cannot detect every form of personal or confidential data."))

    sources = b.get("sources", [])
    src_sh = [(s["id"], _shingles(s["text"])) for s in sources]
    overlaps = []
    for s in spans:
        sh = _shingles(s["text"])
        if len(sh) < 3:
            continue
        for sid, ssh in src_sh:
            shared = len(sh & ssh) / len(sh)
            if shared >= 0.5:
                overlaps.append({"span_id": s["span_id"], "source_id": sid, "shared": round(shared, 2)})
                break
    out.append(IntegrityCheck(
        id="text.overlap", title="Duplicate or preexisting text", status="warning" if overlaps else "passed",
        detail=f"{len(overlaps)} span(s) largely reuse wording from stored sources; quote and cite or rephrase" if overlaps
        else f"no span reuses most of its wording from the {len(sources)} stored source text(s)",
        evidence={"overlaps": overlaps, "sources_compared": len(sources)}, scope="spans vs. sources stored in this project",
        limitations=f"Compared only against {len(sources)} source text(s) stored in this project; this is not "
                    "comprehensive plagiarism detection."))

    figs = b.get("figures", [])
    badfig = [f["file_name"] for f in figs if not f.get("committed")]
    out.append(IntegrityCheck(
        id="figures.provenance", title="Image provenance", status="failed" if badfig else "passed",
        detail=f"figures without a committed source artifact: {badfig}" if badfig
        else (f"{len(figs)} figure(s) come from committed artifacts" if figs else "the manuscript has no figures"),
        evidence={"figures": [f["file_name"] for f in figs]}, scope="figures in this version"))

    norights = [c["title"] for c in b.get("contributions", []) if not c.get("rights_statement")]
    lic_warn = not (b.get("template") or {}).get("license_note")
    out.append(IntegrityCheck(
        id="licenses", title="License and rights restrictions",
        status="failed" if norights else ("warning" if lic_warn else "passed"),
        detail=(f"contributions without a rights statement: {norights}" if norights else
                "the template has no recorded license note" if lic_warn else
                "contributions carry rights statements and the template license is recorded"),
        evidence={"missing_rights": norights}, scope="contributions and template"))

    proto = b.get("protocol") or {}
    eth = proto.get("ethics_rights")
    blockers = ethics_blockers(EthicsRightsDeclaration.model_validate(eth) if eth else None)
    out.append(IntegrityCheck(
        id="ethics.rights", title="Ethics and rights declarations", status="failed" if blockers else "passed",
        detail="; ".join(blockers) if blockers else "the frozen protocol's ethics/rights declaration is complete",
        evidence={"blockers": blockers}, scope="frozen protocol",
        limitations="The platform records declarations; it does not grant or verify ethics approval."))

    dev = proto.get("after_data_inspection_amendments") or []
    out.append(IntegrityCheck(
        id="protocol.deviations", title="Protocol deviations", status="warning" if dev else "passed",
        detail=f"{len(dev)} amendment(s) were made after data inspection; disclose them" if dev
        else "no amendment was made after data inspection", evidence={"amendments": dev}, scope="protocol history"))

    d = b.get("declarations")
    ai_spans = sum(1 for s in spans if s.get("origin") == "ai")
    if d is None:
        out.append(IntegrityCheck(
            id="declarations", title="COI, funding, ethics and AI-use disclosures", status="not_performed",
            detail="author disclosures have not been recorded yet", scope="author records and disclosures"))
    else:
        missing = [k for k in ("competing_interests", "funding") if not d.get(k)]
        if ai_spans and not d.get("ai_use"):
            missing.append(f"AI-use disclosure ({ai_spans} AI-drafted spans)")
        out.append(IntegrityCheck(
            id="declarations", title="COI, funding, ethics and AI-use disclosures", status="failed" if missing else "passed",
            detail=f"missing: {missing}" if missing else "competing interests, funding and AI-use disclosures are recorded",
            evidence={"ai_drafted_spans": ai_spans}, scope="author records and disclosures",
            limitations="Venue AI-use policies must be read by the researcher; the platform does not interpret them."))
    return out


def summarize(checks: list[IntegrityCheck], decisions: dict[str, dict] | None = None) -> dict[str, Any]:
    decisions = decisions or {}
    failed = [c.id for c in checks if c.status in ("failed", "not_performed") and c.blocking]
    undecided = [c.id for c in checks if c.requires_decision and c.id not in decisions]
    return {"failed": failed, "awaiting_decision": undecided, "passed": not failed and not undecided,
            "engine": ENGINE_VERSION, "disclaimer": DISCLAIMER}


EXPORT = [IntegrityCheck]
