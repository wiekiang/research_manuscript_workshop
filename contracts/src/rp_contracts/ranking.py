"""Conference relevance ranking (PRODUCT_SPEC §2.1).

Ranking shows component scores and their uncertainty, never a single authoritative reputation claim.
Components: topic_fit, method_fit, venue_confidence, time_to_complete, deadline_slack, cost.
Text similarity uses a deterministic hashed bag-of-words embedding (`hashing-bow-v1`): it is lexical, local,
reproducible and never sends text to a third party. It is labelled as such wherever it is shown.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, Field

EMBEDDING_MODEL = "hashing-bow-v1"
DIM = 384
STOP = set("""a an and are as at be by for from has have in into is it its of on or that the their this to was were
will with we our you your can may must should paper papers submission submissions conference workshop track call
research study studies new including such other about also more these those which who all any been not""".split())


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z0-9\-]{1,30}", (text or "").lower())
    out = [w.strip("-") for w in words if w not in STOP and len(w) > 2]
    return out + [f"{a}_{b}" for a, b in zip(out, out[1:], strict=False)]


def stem(w: str) -> str:
    for suf in ("ations", "ation", "ities", "ity", "ing", "ies", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def term_coverage(profile_text: str, doc_text: str) -> tuple[float, list[str]]:
    """Share of the profile's (stemmed) terms present in the document, with a bonus for shared bigrams."""
    p_uni = {stem(t) for t in tokens(profile_text) if "_" not in t}
    d_tok = tokens(doc_text)
    d_uni = {stem(t) for t in d_tok if "_" not in t}
    p_bi = {"_".join(stem(x) for x in t.split("_")) for t in tokens(profile_text) if "_" in t}
    d_bi = {"_".join(stem(x) for x in t.split("_")) for t in d_tok if "_" in t}
    if not p_uni:
        return 0.0, []
    matched = sorted(p_uni & d_uni)
    cov = len(matched) / len(p_uni)
    bonus = 0.25 * (len(p_bi & d_bi) / len(p_bi)) if p_bi else 0.0
    return min(1.0, cov + bonus), matched


def embed(text: str, dim: int = DIM) -> list[float]:
    v = [0.0] * dim
    for t in tokens(text):
        h = int.from_bytes(hashlib.blake2b(t.encode(), digest_size=8).digest(), "big")
        v[h % dim] += 1.0 if (h >> 63) & 1 == 0 else -1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


class ResearchProfile(BaseModel):
    topics: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    travel_budget: float | None = None
    currency: str = "USD"
    desired_venues: list[str] = Field(default_factory=list)
    lead_time_weeks: int | None = None
    preferred_publishers: list[str] = Field(default_factory=list)
    excluded_venues: list[str] = Field(default_factory=list)


@dataclass
class Component:
    name: str
    score: float | None  # 0..1, None = unknown
    uncertainty: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class RankedCandidate:
    key: str
    total: float
    components: list[Component]
    excluded: bool = False
    exclusion_reason: str | None = None

    def as_dict(self) -> dict:
        return {"key": self.key, "total": self.total, "components": [asdict(c) for c in self.components],
                "excluded": self.excluded, "exclusion_reason": self.exclusion_reason}


WEIGHTS = {"topic_fit": 0.35, "method_fit": 0.15, "venue_confidence": 0.15, "time_to_complete": 0.15,
           "deadline_slack": 0.1, "cost": 0.1}


def score_candidate(profile: ResearchProfile, *, key: str, name: str, acronym: str | None, cfp_text: str,
                    publisher: str | None, location: str | None, full_paper_due: datetime | None,
                    venue_verified: bool, questionable: bool, now: datetime | None = None) -> RankedCandidate:
    now = now or datetime.now(UTC)
    comps: list[Component] = []
    profile_text = " ".join(profile.topics)
    if not profile_text or not cfp_text:
        comps.append(Component("topic_fit", None, "no topics in profile or no CFP text"))
    else:
        cov, matched = term_coverage(profile_text, cfp_text)
        comps.append(Component("topic_fit", round(cov, 3),
                               "lexical coverage of your profile terms in the official CFP text; semantic relevance "
                               "is not assessed", [f"shared terms: {', '.join(matched[:10]) or 'none'}"]))
    if profile.methods:
        low = cfp_text.lower()
        hits = [m for m in profile.methods if m.lower() in low]
        comps.append(Component("method_fit", round(len(hits) / len(profile.methods), 3),
                               "keyword presence of profile methods in the CFP text",
                               [f"mentioned: {', '.join(hits) or 'none'}"]))
    else:
        comps.append(Component("method_fit", None, "no methods in profile"))
    vc = 0.5 + (0.4 if venue_verified else 0.0) - (0.4 if questionable else 0.0)
    pub_ev = []
    if publisher and profile.preferred_publishers and any(p.lower() in publisher.lower() for p in profile.preferred_publishers):
        vc += 0.1
        pub_ev.append(f"preferred publisher {publisher}")
    comps.append(Component("venue_confidence", round(max(0.0, min(1.0, vc)), 3),
                           "based on registry verification and recorded evidence only; not a reputation judgement",
                           (["source verified in the curated registry"] if venue_verified else ["source not verified"])
                           + (["evidence-backed concern recorded (see evidence)"] if questionable else []) + pub_ev))
    if full_paper_due is None:
        comps += [Component("time_to_complete", None, "full-paper deadline unknown"),
                  Component("deadline_slack", None, "full-paper deadline unknown")]
    else:
        days = (full_paper_due - now).total_seconds() / 86400
        need = (profile.lead_time_weeks or 8) * 7
        ttc = 0.0 if days <= 0 else min(1.0, days / max(need, 1))
        comps.append(Component("time_to_complete", round(ttc, 3),
                               f"{days:.0f} days until the full-paper deadline vs {need} days needed "
                               f"({'profile' if profile.lead_time_weeks else 'default 8 weeks'})"))
        slack = days - need
        comps.append(Component("deadline_slack", round(max(0.0, min(1.0, slack / 60)), 3) if days > 0 else 0.0,
                               f"{slack:.0f} days of slack" if days > 0 else "deadline has passed"))
    if profile.travel_budget is None:
        comps.append(Component("cost", None, "no travel budget in profile"))
    elif not location:
        comps.append(Component("cost", None, "location unknown; travel cost cannot be estimated"))
    else:
        geo_match = any(g.lower() in location.lower() for g in profile.geography) if profile.geography else False
        comps.append(Component("cost", 0.8 if geo_match else 0.5,
                               "coarse proxy: within preferred geography or not; fees/travel are not priced",
                               [f"location {location}"]))
    known = [(WEIGHTS[c.name], c.score) for c in comps if c.score is not None]
    wsum = sum(w for w, _ in known)
    total = round(sum(w * s for w, s in known) / wsum, 3) if wsum else 0.0
    excluded = False
    reason = None
    names = {name.lower(), (acronym or "").lower()} - {""}
    if any(x.lower() in names for x in profile.excluded_venues):
        excluded, reason = True, "excluded in research profile"
    if full_paper_due is not None and full_paper_due < now:
        reason = (reason + "; " if reason else "") + "full-paper deadline has passed"
    return RankedCandidate(key, total, comps, excluded, reason)


def precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    top = ranked[:k]
    return sum(1 for r in top if r in relevant) / max(len(top), 1)


def ndcg_at_k(ranked: list[str], gains: dict[str, float], k: int) -> float:
    dcg = sum(gains.get(r, 0.0) / math.log2(i + 2) for i, r in enumerate(ranked[:k]))
    ideal = sorted(gains.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0
