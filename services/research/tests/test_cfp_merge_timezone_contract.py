"""cfp_merge.merge against the 16 rows of the expected-outcomes table in docs/cfp-timezone-contract.md.

Each case is built exactly as the cfp_extract activity (features/cfp.py) builds the merge inputs:
  * `deterministic` is always a CfpExtraction (possibly with no deadline at all, rows 15-16);
  * `model` / `validation` are CfpExtraction / CfpValidation when the model pass ran, else None with
    both statuses set to a "not_performed: ..." reason (row 14);
  * the validator verdict is an ItemCheck keyed by the model deadline's index (0 here).

All rows use deadline_kind=camera_ready, date=2027-04-15, a quote that locates in the snapshot text.
Assertions follow the contract, not today's output. Rows where the current merge() diverges from the
contract are marked xfail(strict=True) with the divergence spelled out, so implementing the contract
flips them to XPASS failures and prompts removal of the markers.

Problem lists are compared as sorted lists: the contract fixes the texts, not their order.
"""

from __future__ import annotations

import pytest

from rp_contracts.cfp import (
    CfpExtraction,
    CfpValidation,
    ExtractedDeadline,
    ExtractedEdition,
    ItemCheck,
)
from rp_contracts.enums import DeadlineKind
from rp_research.agents.cfp_merge import merge
from rp_research.fetch.text import LocatedText, Segment

QUOTE = "Camera-ready deadline: April 15, 2027 at 23:59 PDT."
TEXT = "Important Dates\n" + QUOTE + "\n"
LT = LocatedText(TEXT, [Segment(0, 15, "h2", ["Important Dates"]),
                        Segment(16, 16 + len(QUOTE), "li", ["Important Dates"])], "Fixture", "text/html")
EDITION = ExtractedEdition(conference_name="Fixture Conference 2027", acronym=None, year=2027, location=None,
                           submission_url=None, publication_outlet=None, publisher=None, official_site_url=None)
DATE = "2027-04-15"
ISSUE = "timezone wording is ambiguous"
NOT_PERFORMED = "not_performed: provider_not_configured"

# Problem texts named in the contract.
P_TIME_ASSUMED = "time of day not stated; 23:59 assumed pending confirmation"
P_TZ_NOT_STATED = "timezone not stated in the source"
P_SINGLE = "found by a single extraction method; independent confirmation is required"
P_MODEL_ONLY_TZ = ("timezone '{v}' found only by the model-assisted pass; the deterministic pass found none in the "
                   "quoted sentence; confirm against the source")
P_DET_ONLY_TZ = ("timezone '{v}' found only by the deterministic pass; the model-assisted pass stated none; "
                 "confirm against the source")
P_TZ_CONFLICT = "extraction passes disagree on timezone: deterministic={a}; model_assisted={b}"
P_MODEL_ONLY_TIME = ("time '{v}' found only by the model-assisted pass; the deterministic pass found none in the "
                     "quoted sentence; confirm against the source")
P_DET_ONLY_TIME = ("time '{v}' found only by the deterministic pass; the model-assisted pass stated none; "
                   "confirm against the source")
P_TIME_CONFLICT = "extraction passes disagree on time: deterministic={a}; model_assisted={b}"


def validator(verdict: str) -> str:
    return f"independent validator: {verdict} - {ISSUE}"


def deadline(time: str | None, tz: str | None) -> ExtractedDeadline:
    return ExtractedDeadline(deadline_kind=DeadlineKind.CAMERA_READY, track=None, date=DATE, time=time,
                             timezone=tz, mandatory=None, quote=QUOTE, uncertainty=None)


def extraction(dl: ExtractedDeadline | None) -> CfpExtraction:
    return CfpExtraction(edition=EDITION, tracks=[], rules=[], deadlines=[dl] if dl else [], uncertainties=[])


def run(heur: tuple | None, model: tuple | None, verdict: str | None) -> dict:
    """heur/model are (time, tz) or None (pass found no deadline / model pass not performed)."""
    det = extraction(deadline(*heur) if heur else None)
    if model is None:
        return merge(LT, det, None, None, NOT_PERFORMED, NOT_PERFORMED)
    mod = extraction(deadline(*model))
    val = CfpValidation(checks=[ItemCheck(kind="deadline", index=0, verdict=verdict, issue=None if verdict == "supported" else ISSUE)],
                        missed_items=[]) if verdict else CfpValidation(checks=[], missed_items=[])
    return merge(LT, det, mod, val, "performed", "performed")


def xfail(today: str):
    return pytest.mark.xfail(strict=True, reason=f"contract not implemented in cfp_merge.merge; today: {today}")


NHR = "needs_human_resolution"
PDT_2359 = "2027-04-16T06:59:00+00:00"
AOE_2359 = "2027-04-16T11:59:00+00:00"
PDT_1100 = "2027-04-15T18:00:00+00:00"

# (row, heuristic (time, tz), model (time, tz) or None, verdict, expected tz, time, due_at, status, problems)
ROWS = [
    pytest.param(1, ("23:59", "PDT"), ("23:59", "PDT"), "supported",
                 "PDT", "23:59", PDT_2359, "validated", [], id="row01-agree-pdt-supported"),
    pytest.param(2, ("23:59", "PDT"), ("23:59", "PDT"), "unclear",
                 "PDT", "23:59", PDT_2359, NHR, [validator("unclear")], id="row02-agree-pdt-unclear"),
    pytest.param(3, (None, "AoE"), (None, "AoE"), "supported",
                 "AoE", None, AOE_2359, "validated", [], id="row03-agree-aoe-no-time"),
    pytest.param(4, (None, "PDT"), (None, "PDT"), "supported",
                 "PDT", None, PDT_2359, NHR, [P_TIME_ASSUMED], id="row04-agree-pdt-no-time"),
    pytest.param(5, (None, None), (None, None), "supported",
                 None, None, None, NHR, [P_TZ_NOT_STATED, P_TIME_ASSUMED], id="row05-both-none"),
    pytest.param(6, ("23:59", None), ("23:59", "AoE"), "supported",
                 None, "23:59", None, NHR, [P_MODEL_ONLY_TZ.format(v="AoE")], id="row06-model-only-tz-supported",
                 marks=xfail("model observation wins: tz='AoE', due_at computed, 'extraction passes disagree' problem")),
    pytest.param(7, ("23:59", None), ("23:59", "AoE"), "unclear",
                 None, "23:59", None, NHR, [P_MODEL_ONLY_TZ.format(v="AoE"), validator("unclear")],
                 id="row07-model-only-tz-unclear",
                 marks=xfail("model observation wins: tz='AoE', due_at computed, 'extraction passes disagree' problem")),
    pytest.param(8, ("23:59", None), ("23:59", "AoE"), "unsupported",
                 None, "23:59", None, NHR, [P_MODEL_ONLY_TZ.format(v="AoE"), validator("unsupported")],
                 id="row08-model-only-tz-unsupported",
                 marks=xfail("model observation wins: tz='AoE', due_at computed, 'extraction passes disagree' problem")),
    pytest.param(9, ("23:59", "PDT"), ("23:59", None), "supported",
                 "PDT", "23:59", PDT_2359, NHR, [P_DET_ONLY_TZ.format(v="PDT")], id="row09-heuristic-only-tz",
                 marks=xfail("model observation wins and drops the verbatim heuristic tz: tz=None, due_at=None, "
                             "false 'timezone not stated in the source' problem")),
    pytest.param(10, ("23:59", "PDT"), ("23:59", "AoE"), "supported",
                 "PDT", "23:59", PDT_2359, NHR, [P_TZ_CONFLICT.format(a="PDT", b="AoE")], id="row10-tz-conflict",
                 marks=xfail("model observation wins: tz='AoE', due_at from AoE, generic disagree text")),
    pytest.param(11, (None, "PDT"), ("23:59", "PDT"), "supported",
                 "PDT", None, PDT_2359, NHR, [P_MODEL_ONLY_TIME.format(v="23:59")], id="row11-model-only-time",
                 marks=xfail("model observation wins: time='23:59' filled in, generic disagree text")),
    pytest.param(12, ("23:59", "PDT"), (None, "PDT"), "supported",
                 "PDT", "23:59", PDT_2359, NHR, [P_DET_ONLY_TIME.format(v="23:59")], id="row12-heuristic-only-time",
                 marks=xfail("model observation wins and drops the heuristic time: time=None, false "
                             "'time of day not stated; 23:59 assumed' problem")),
    pytest.param(13, ("11:00", "PDT"), ("23:59", "PDT"), "supported",
                 "PDT", "11:00", PDT_1100, NHR, [P_TIME_CONFLICT.format(a="11:00", b="23:59")], id="row13-time-conflict",
                 marks=xfail("model observation wins: time='23:59', due_at from 23:59, generic disagree text")),
    pytest.param(14, (None, "AoE"), None, None,
                 "AoE", None, AOE_2359, NHR, [P_SINGLE], id="row14-heuristic-only-model-not-performed"),
    pytest.param(15, None, (None, "AoE"), "supported",
                 None, None, None, NHR, [P_MODEL_ONLY_TZ.format(v="AoE")], id="row15-model-only-deadline-tz",
                 marks=xfail("model-only carve-out: tz='AoE', due_at computed, status 'validated' with no problems")),
    pytest.param(16, None, ("23:59", None), "supported",
                 None, None, None, NHR, [P_MODEL_ONLY_TIME.format(v="23:59"), P_TZ_NOT_STATED],
                 id="row16-model-only-deadline-time",
                 marks=xfail("model-only deadline keeps time='23:59'; only 'timezone not stated in the source' recorded")),
]


@pytest.mark.parametrize("row,heur,model,verdict,exp_tz,exp_time,exp_due,exp_status,exp_problems", ROWS)
def test_contract_row(row, heur, model, verdict, exp_tz, exp_time, exp_due, exp_status, exp_problems):
    merged = run(heur, model, verdict)
    items = [i for i in merged["items"] if i["item_type"] == "deadline"]
    assert len(items) == 1, f"row {row}: expected exactly one merged deadline, got {items}"
    item = items[0]
    assert item["rule_key"] == "deadline.camera_ready" and item["date"] == DATE
    got = {"timezone": item["timezone"], "time": item["time"], "due_at": item["due_at"], "status": item["status"],
           "problems": sorted(item["problems"])}
    expected = {"timezone": exp_tz, "time": exp_time, "due_at": exp_due, "status": exp_status,
                "problems": sorted(exp_problems)}
    assert got == expected, f"row {row}"
