"""CFP interpretation contracts (PRODUCT_SPEC §2.2) and deterministic deadline/timezone resolution."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta, timezone
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from .enums import DeadlineKind, IntendedAction


class RuleCategory(StrEnum):
    TOPICS = "topics"
    PAPER_TYPES = "paper_types"
    LENGTH = "length"
    ABSTRACT = "abstract"
    FORMAT = "format"
    TEMPLATE = "template"
    ANONYMIZATION = "anonymization"
    CITATION_STYLE = "citation_style"
    SUPPLEMENTARY = "supplementary"
    ARTIFACT = "artifact"
    CONFLICTS_OF_INTEREST = "conflicts_of_interest"
    ETHICS = "ethics"
    PRIOR_PUBLICATION = "prior_publication"
    DUAL_SUBMISSION = "dual_submission"
    PREPRINT = "preprint"
    AI_POLICY = "ai_policy"
    AI_DISCLOSURE = "ai_disclosure"
    FEES = "fees"
    SUBMISSION_SYSTEM = "submission_system"
    OTHER = "other"


# Categories whose rules block the CFP gate until a human confirms them.
BLOCKING_CATEGORIES = {
    RuleCategory.LENGTH, RuleCategory.ABSTRACT, RuleCategory.FORMAT, RuleCategory.TEMPLATE,
    RuleCategory.ANONYMIZATION, RuleCategory.SUPPLEMENTARY, RuleCategory.ETHICS, RuleCategory.PRIOR_PUBLICATION,
    RuleCategory.DUAL_SUBMISSION, RuleCategory.PREPRINT, RuleCategory.AI_POLICY, RuleCategory.AI_DISCLOSURE,
    RuleCategory.PAPER_TYPES,
}


class SourceLevel(StrEnum):
    """Precedence: current track CFP -> conference author instructions -> publisher policy -> template docs."""

    TRACK_CFP = "track_cfp"
    CONFERENCE_INSTRUCTIONS = "conference_instructions"
    PUBLISHER_POLICY = "publisher_policy"
    TEMPLATE_DOCUMENTATION = "template_documentation"


PRECEDENCE = [SourceLevel.TRACK_CFP, SourceLevel.CONFERENCE_INSTRUCTIONS, SourceLevel.PUBLISHER_POLICY,
              SourceLevel.TEMPLATE_DOCUMENTATION]


class ExtractedEdition(BaseModel):
    conference_name: str
    acronym: str | None
    year: int | None
    location: str | None
    submission_url: str | None
    publication_outlet: str | None
    publisher: str | None
    official_site_url: str | None


class ExtractedTrack(BaseModel):
    name: str
    description: str | None
    paper_types: list[str]
    submission_categories: list[str]
    quote: str | None


class ExtractedRule(BaseModel):
    rule_key: str = Field(description="dotted key, e.g. length.page_limit or anonymization.mode")
    category: RuleCategory
    track: str | None = Field(description="track name the rule applies to, or null for conference-wide")
    value_text: str = Field(description="the rule restated precisely, without adding requirements")
    value: str | None = Field(description="machine value when obvious (e.g. 8, double_blind), else null")
    unit: str | None
    blocking: bool
    quote: str = Field(description="verbatim snippet from the source (at most ~300 characters)")
    uncertainty: str | None


class ExtractedDeadline(BaseModel):
    deadline_kind: DeadlineKind
    track: str | None
    date: str = Field(description="YYYY-MM-DD exactly as stated")
    time: str | None = Field(description="HH:MM 24h if stated, else null")
    timezone: str | None = Field(description="timezone exactly as written (e.g. AoE, UTC-12, PDT), else null")
    mandatory: bool | None
    quote: str
    uncertainty: str | None


class CfpExtraction(BaseModel):
    edition: ExtractedEdition
    tracks: list[ExtractedTrack]
    rules: list[ExtractedRule]
    deadlines: list[ExtractedDeadline]
    uncertainties: list[str]


class ItemCheck(BaseModel):
    kind: str = Field(description="rule or deadline")
    index: int
    verdict: str = Field(description="supported | unsupported | unclear")
    issue: str | None


class CfpValidation(BaseModel):
    checks: list[ItemCheck]
    missed_items: list[str]


# Which intended actions each deadline kind governs (M8 deadline policy evaluator default; editable per rule).
DEFAULT_GOVERNS: dict[DeadlineKind, list[IntendedAction]] = {
    DeadlineKind.ABSTRACT_REGISTRATION: [IntendedAction.ABSTRACT_REGISTRATION, IntendedAction.NEW_SUBMISSION],
    DeadlineKind.FULL_PAPER: [IntendedAction.NEW_SUBMISSION],
    DeadlineKind.SUPPLEMENTARY: [IntendedAction.NEW_SUBMISSION],
    DeadlineKind.REBUTTAL: [IntendedAction.REBUTTAL],
    DeadlineKind.NOTIFICATION: [],
    DeadlineKind.CAMERA_READY: [IntendedAction.CAMERA_READY],
    DeadlineKind.AUTHOR_REGISTRATION: [IntendedAction.AUTHOR_REGISTRATION],
    DeadlineKind.ARTIFACT: [IntendedAction.ARTIFACT_SUBMISSION],
    DeadlineKind.OTHER: [],
}

FIXED_OFFSETS = {
    "AOE": -12, "ANYWHERE ON EARTH": -12, "UTC": 0, "GMT": 0, "Z": 0, "PST": -8, "PDT": -7, "MST": -7, "MDT": -6,
    "EST": -5, "EDT": -4, "CET": 1, "CEST": 2, "EET": 2, "EEST": 3, "JST": 9, "KST": 9, "AEST": 10, "AEDT": 11,
    "NZST": 12, "NZDT": 13, "HST": -10, "AKST": -9, "AKDT": -8, "WET": 0, "WEST": 1, "SGT": 8, "HKT": 8,
}
AMBIGUOUS = {"IST", "CST", "BST", "AST", "ECT", "MSK?"}


class DeadlineResolution(BaseModel):
    due_at: datetime | None
    timezone_label: str | None
    problems: list[str]


def resolve_deadline(date_s: str, time_s: str | None, tz_s: str | None) -> DeadlineResolution:
    """Convert a stated deadline to UTC. Never guesses a missing or ambiguous timezone."""
    problems: list[str] = []
    try:
        d = date.fromisoformat(date_s)
    except ValueError:
        return DeadlineResolution(due_at=None, timezone_label=tz_s, problems=[f"unparseable date {date_s!r}"])
    tzinfo = None
    label = tz_s.strip() if tz_s else None
    if not label:
        problems.append("timezone not stated in the source")
    else:
        key = label.upper().replace("(", "").replace(")", "").strip()
        m = re.fullmatch(r"(?:UTC|GMT)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", key)
        if key in AMBIGUOUS:
            problems.append(f"timezone abbreviation {label!r} is ambiguous")
        elif key in FIXED_OFFSETS:
            tzinfo = timezone(timedelta(hours=FIXED_OFFSETS[key]))
        elif m:
            sign = -1 if m.group(1) == "-" else 1
            tzinfo = timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0)))
        else:
            try:
                tzinfo = ZoneInfo(label)
            except (ZoneInfoNotFoundError, ValueError):
                problems.append(f"unrecognised timezone {label!r}")
    if time_s:
        try:
            hh, mm = time_s.strip().split(":")[:2]
            t = time(int(hh) % 24, int(mm[:2]))
            if int(hh) == 24:
                t = time(23, 59)
        except (ValueError, IndexError):
            problems.append(f"unparseable time {time_s!r}")
            t = time(23, 59)
    else:
        t = time(23, 59)
        if not (label and label.upper().replace("(", "").replace(")", "") in ("AOE", "ANYWHERE ON EARTH")):
            problems.append("time of day not stated; 23:59 assumed pending confirmation")
    if tzinfo is None:
        return DeadlineResolution(due_at=None, timezone_label=label, problems=problems)
    return DeadlineResolution(due_at=datetime.combine(d, t, tzinfo).astimezone(UTC), timezone_label=label,
                              problems=problems)
