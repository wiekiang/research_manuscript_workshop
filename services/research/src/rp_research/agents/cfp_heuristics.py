"""Deterministic CFP extraction pass (method = deterministic).

Independent of any model: finds deadlines (with kind, date, time, timezone) and common policy rules using
patterns over located text. Every item quotes a verbatim sentence of the source. It is deliberately
conservative; anything it cannot classify is left for the model pass or the researcher.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from rp_contracts.cfp import (
    CfpExtraction,
    ExtractedDeadline,
    ExtractedEdition,
    ExtractedRule,
    ExtractedTrack,
    RuleCategory,
)
from rp_contracts.enums import DeadlineKind

from ..fetch.text import LocatedText

EXTRACTOR_VERSION = "cfp-heuristics/1"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
     "december"], start=1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
DATE_PATTERNS = [
    re.compile(MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*[-–]\s*\d{1,2})?,?\s+(\d{4})", re.I),
    re.compile(r"(\d{1,2})(?:st|nd|rd|th)?(?:\s*[-–]\s*\d{1,2})?\s+" + MON + r",?\s+(\d{4})", re.I),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
]
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?)?", re.I)
TZ_RE = re.compile(r"\b(AoE|Anywhere on Earth|(?:UTC|GMT)\s*[+-−]\s*\d{1,2}(?::\d{2})?|UTC|GMT|[A-Z]{2,4}T)\b")

KIND_RULES: list[tuple[DeadlineKind, re.Pattern]] = [
    (DeadlineKind.CAMERA_READY, re.compile(r"camera[- ]ready", re.I)),
    (DeadlineKind.REBUTTAL, re.compile(r"rebuttal|author response", re.I)),
    (DeadlineKind.NOTIFICATION, re.compile(r"notification|acceptance notice|decisions?\b", re.I)),
    (DeadlineKind.ARTIFACT, re.compile(r"artifact", re.I)),
    (DeadlineKind.ABSTRACT_REGISTRATION, re.compile(r"abstract", re.I)),
    (DeadlineKind.SUPPLEMENTARY, re.compile(r"supplementary", re.I)),
    (DeadlineKind.AUTHOR_REGISTRATION, re.compile(r"author registration|registration deadline|early registration", re.I)),
    (DeadlineKind.FULL_PAPER, re.compile(r"paper submission|full paper|submission deadline|papers? due|submissions? due|manuscript", re.I)),
]

RULE_PATTERNS: list[tuple[str, RuleCategory, re.Pattern, bool]] = [
    ("anonymization.mode", RuleCategory.ANONYMIZATION, re.compile(r"double[- ]blind|single[- ]blind|triple[- ]blind|anonymi[sz]ed submissions?|must be anonymous", re.I), True),
    ("ai_policy.statement", RuleCategory.AI_POLICY, re.compile(r"generative ai|large language model|\bllms?\b|chatgpt|ai[- ]generated|ai tools|ai[- ]assisted", re.I), True),
    ("dual_submission.policy", RuleCategory.DUAL_SUBMISSION, re.compile(r"dual submission|simultaneously submitted|concurrently submitted|under review elsewhere|submitted elsewhere", re.I), True),
    ("prior_publication.policy", RuleCategory.PRIOR_PUBLICATION, re.compile(r"previously published|not been published|prior publication|published elsewhere", re.I), True),
    ("preprint.policy", RuleCategory.PREPRINT, re.compile(r"arxiv|preprint", re.I), True),
    ("supplementary.policy", RuleCategory.SUPPLEMENTARY, re.compile(r"supplementary material", re.I), True),
    ("ethics.requirement", RuleCategory.ETHICS, re.compile(r"\bethic|\birb\b|institutional review|human subjects", re.I), True),
    ("conflicts_of_interest.policy", RuleCategory.CONFLICTS_OF_INTEREST, re.compile(r"conflicts? of interest", re.I), False),
    ("fees.statement", RuleCategory.FEES, re.compile(r"registration fee|fee of|publication fee|apc\b", re.I), False),
    ("submission_system.name", RuleCategory.SUBMISSION_SYSTEM, re.compile(r"easychair|hotcrp|openreview|microsoft cmt|\bcmt\b|precision ?conference|softconf", re.I), False),
    ("citation_style.rule", RuleCategory.CITATION_STYLE, re.compile(r"citation style|reference style|references must", re.I), False),
]
TEMPLATE_RE = re.compile(r"acmart|sigconf|acm (?:master|primary)[^.]{0,30}template|ieeetran|ieee (?:conference )?template|"
                         r"\blncs\b|lecture notes in computer science|springer[^.]{0,20}template|latex template", re.I)
PAGES_RE = re.compile(r"(\d{1,2})\s*(?:-\s*)?pages?\b", re.I)
WORDS_RE = re.compile(r"abstract[^.]{0,80}?(\d{2,4})\s*words", re.I)


def _sentences(text: str) -> list[tuple[int, str]]:
    out, start = [], 0
    for m in re.finditer(r"(?<=[.!?;])\s+(?=[A-Z(])", text):
        out.append((start, text[start:m.start()]))
        start = m.end()
    out.append((start, text[start:]))
    return [(s, t) for s, t in out if t.strip()]


def _quote(sentence: str) -> str:
    return sentence.strip()[:300]


def _parse_date(m: re.Match, pattern_index: int) -> str | None:
    try:
        if pattern_index == 0:
            mon = MONTHS[_mkey(m.group(1))]
            day, year = int(m.group(2)), int(m.group(3))
        elif pattern_index == 1:
            day, mon, year = int(m.group(1)), MONTHS[_mkey(m.group(2))], int(m.group(3))
        else:
            year, mon, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(year, mon, day).isoformat()
    except (KeyError, ValueError):
        return None


def _mkey(s: str) -> str:
    s = s.lower().rstrip(".")
    return "sept" if s.startswith("sept") else s[:3]


def _find_dates(s: str) -> list[tuple[int, str]]:
    found = []
    for i, pat in enumerate(DATE_PATTERNS):
        for m in pat.finditer(s):
            d = _parse_date(m, i)
            if d:
                found.append((m.start(), d))
    return sorted(found)


def _time_and_tz(s: str) -> tuple[str | None, str | None]:
    t = None
    tm = TIME_RE.search(s)
    if tm:
        hh, mm, ap = int(tm.group(1)), tm.group(2), (tm.group(3) or "").lower().replace(".", "")
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        t = f"{hh:02d}:{mm}"
    tz = None
    zm = TZ_RE.search(s)
    if zm and zm.group(1).upper() not in {"ACM", "IEEE", "LNCS", "PDF", "URL", "TBA", "TBD", "WWW", "AT", "IT"}:
        tz = zm.group(1).replace("−", "-")
    return t, tz


def _track_for(section: list[str], tracks: list[str]) -> str | None:
    for heading in reversed(section):
        for t in tracks:
            if t.lower() in heading.lower():
                return t
    return None


def extract(lt: LocatedText) -> CfpExtraction:
    tracks: list[ExtractedTrack] = []
    track_names: list[str] = []
    for seg in lt.segments:
        if seg.kind.startswith("h") or seg.kind == "heading":
            txt = lt.text[seg.start:seg.end]
            if re.search(r"\btrack\b|\bpapers\b", txt, re.I) and len(txt) < 120 and txt not in track_names:
                track_names.append(txt)
                tracks.append(ExtractedTrack(name=txt, description=None, paper_types=[], submission_categories=[],
                                             quote=txt))
    deadlines: list[ExtractedDeadline] = []
    rules: list[ExtractedRule] = []
    seen_rules: set[tuple[str, str | None]] = set()
    seen_dl: set[tuple[str, str | None, str]] = set()
    topics: list[str] = []
    for seg in lt.segments:
        seg_text = lt.text[seg.start:seg.end]
        track = _track_for(seg.section, track_names)
        if any("topic" in h.lower() for h in seg.section[-1:]) and seg.kind == "li":
            topics.append(seg_text)
        for _, sentence in _sentences(seg_text):
            dates = _find_dates(sentence)
            if dates:
                kind = next((k for k, pat in KIND_RULES if pat.search(sentence)), None)
                if kind is not None:
                    t, tz = _time_and_tz(sentence)
                    key = (kind.value, track, dates[0][1])
                    if key not in seen_dl:
                        seen_dl.add(key)
                        deadlines.append(ExtractedDeadline(
                            deadline_kind=kind, track=track, date=dates[0][1], time=t, timezone=tz,
                            mandatory=True if kind in (DeadlineKind.ABSTRACT_REGISTRATION, DeadlineKind.FULL_PAPER) and re.search(r"mandatory|required|must", sentence, re.I) else None,
                            quote=_quote(sentence),
                            uncertainty="date range: first date used" if re.search(r"\d\s*[-–]\s*\d", sentence) else None))
            for key, cat, pat, blocking in RULE_PATTERNS:
                if pat.search(sentence) and (key, track) not in seen_rules:
                    seen_rules.add((key, track))
                    value = None
                    if key == "anonymization.mode":
                        low = sentence.lower()
                        value = ("double_blind" if "double" in low else "single_blind" if "single" in low
                                 else "triple_blind" if "triple" in low else "anonymized")
                    rules.append(ExtractedRule(rule_key=key, category=cat, track=track, value_text=_quote(sentence),
                                               value=value, unit=None, blocking=blocking, quote=_quote(sentence),
                                               uncertainty="heuristic match; interpretation required"))
            if TEMPLATE_RE.search(sentence) and ("template.family", track) not in seen_rules:
                seen_rules.add(("template.family", track))
                low = sentence.lower()
                fam = ("acm_acmart" if "acm" in low or "acmart" in low or "sigconf" in low else
                       "ieee_ieeetran" if "ieee" in low else "springer_lncs" if "lncs" in low or "lecture notes" in low
                       else "latex_unspecified")
                rules.append(ExtractedRule(rule_key="template.family", category=RuleCategory.TEMPLATE, track=track,
                                           value_text=_quote(sentence), value=fam, unit=None, blocking=True,
                                           quote=_quote(sentence), uncertainty=None))
            pm = PAGES_RE.search(sentence)
            if pm and re.search(r"limit|maximum|up to|at most|not exceed|no more than|must be|length", sentence, re.I) \
                    and ("length.page_limit", track) not in seen_rules:
                seen_rules.add(("length.page_limit", track))
                excl = "excluding references" if re.search(r"excluding|not including|plus|additional pages? for references", sentence, re.I) else None
                rules.append(ExtractedRule(rule_key="length.page_limit", category=RuleCategory.LENGTH, track=track,
                                           value_text=_quote(sentence), value=pm.group(1), unit="pages", blocking=True,
                                           quote=_quote(sentence), uncertainty=excl))
            wm = WORDS_RE.search(sentence)
            if wm and ("abstract.word_limit", track) not in seen_rules:
                seen_rules.add(("abstract.word_limit", track))
                rules.append(ExtractedRule(rule_key="abstract.word_limit", category=RuleCategory.ABSTRACT, track=track,
                                           value_text=_quote(sentence), value=wm.group(1), unit="words", blocking=True,
                                           quote=_quote(sentence), uncertainty=None))
    if topics:
        rules.append(ExtractedRule(rule_key="topics.list", category=RuleCategory.TOPICS, track=None,
                                   value_text="; ".join(topics)[:2000], value=None, unit=None, blocking=False,
                                   quote=topics[0][:300], uncertainty=None))
    years = Counter(int(y) for y in re.findall(r"\b(20[2-4]\d)\b", lt.text))
    title = lt.title or (lt.text.split("\n", 1)[0] if lt.text else "Unknown conference")
    acr = re.search(r"\b([A-Z][A-Za-z]{1,12})\s?['’]?\s?(20\d\d|\d\d)\b", title)
    edition = ExtractedEdition(conference_name=title[:300], acronym=acr.group(1) if acr else None,
                               year=years.most_common(1)[0][0] if years else None, location=None, submission_url=None,
                               publication_outlet=None, publisher=None, official_site_url=None)
    return CfpExtraction(edition=edition, tracks=tracks, rules=rules, deadlines=deadlines,
                         uncertainties=["deterministic pass: rules are pattern matches and require interpretation"])
