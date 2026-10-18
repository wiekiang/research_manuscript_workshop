"""Reconcile extraction passes into source-linked rule candidates (PRODUCT_SPEC §2.2).

Inputs: the deterministic pass (always), the model extraction pass (when the provider is enabled), and the
independent model validation pass. Each candidate carries its verbatim quote, a locator verified against the
snapshot text, which methods found it, whether the passes agree, the validator verdict and every problem found.

Status:
  validated               found by >=2 independent methods with matching values, quote verified, no problems
  needs_human_resolution  any contradiction, unverified quote, single-pass blocking item, missing/ambiguous
                          timezone, validator doubt, or an AI-use policy (which always needs human interpretation)
  extracted               non-blocking single-pass item with a verified quote
"""

from __future__ import annotations

import re
from typing import Any

from rp_contracts.cfp import (
    BLOCKING_CATEGORIES,
    DEFAULT_GOVERNS,
    CfpExtraction,
    CfpValidation,
    RuleCategory,
    resolve_deadline,
)
from rp_contracts.enums import DeadlineKind

from ..fetch.text import LocatedText, find_quote

MERGE_VERSION = "cfp-merge/1"


def norm_track(name: str | None) -> str | None:
    if not name:
        return None
    s = re.sub(r"\b(track|papers?|submissions?)\b", "", name.lower())
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s or None


def _norm_value(v: str | None) -> str | None:
    if v is None:
        return None
    return re.sub(r"[^a-z0-9]+", "", v.lower()) or None


def _verify_quote(lt: LocatedText, quote: str | None) -> tuple[dict | None, str | None]:
    if not quote:
        return None, "no quote supplied"
    span = find_quote(lt, quote)
    if span is None:
        return None, "quote not found verbatim in the source snapshot"
    return lt.locator(*span), None


def merge(lt: LocatedText, deterministic: CfpExtraction, model: CfpExtraction | None,
          validation: CfpValidation | None, model_status: str, validator_status: str) -> dict[str, Any]:
    items: dict[tuple, dict[str, Any]] = {}

    def add(method: str, kind: str, key: tuple, payload: dict[str, Any], quote: str):
        locator, qerr = _verify_quote(lt, quote)
        entry = items.setdefault(key, {"item_type": kind, "methods": [], "observations": [], **payload})
        entry["methods"].append(method)
        entry["observations"].append({"method": method, "quote": quote, "locator": locator, "quote_problem": qerr,
                                      "value": payload.get("value"), "date": payload.get("date"),
                                      "time": payload.get("time"), "timezone": payload.get("timezone"),
                                      "value_text": payload.get("value_text")})

    for method, ex in (("deterministic", deterministic), ("model_assisted", model)):
        if ex is None:
            continue
        for r in ex.rules:
            key = ("rule", r.rule_key, norm_track(r.track))
            add(method, "rule", key, {"rule_key": r.rule_key, "category": r.category.value, "track": r.track,
                                      "value_text": r.value_text, "value": r.value, "unit": r.unit,
                                      "blocking": r.blocking or r.category in BLOCKING_CATEGORIES,
                                      "uncertainty": r.uncertainty}, r.quote)
        for d in ex.deadlines:
            key = ("deadline", d.deadline_kind.value, norm_track(d.track))
            add(method, "deadline", key, {"rule_key": f"deadline.{d.deadline_kind.value}", "category": "deadline",
                                          "deadline_kind": d.deadline_kind.value, "track": d.track,
                                          "date": d.date, "time": d.time, "timezone": d.timezone,
                                          "mandatory": d.mandatory, "blocking": True,
                                          "value_text": d.quote, "value": d.date, "unit": None,
                                          "uncertainty": d.uncertainty}, d.quote)

    # Validator verdicts are keyed on the numbering used when the validation call was built (model items first).
    verdicts: dict[tuple, dict] = {}
    if validation is not None and model is not None:
        for c in validation.checks:
            try:
                if c.kind == "rule":
                    r = model.rules[c.index]
                    verdicts[("rule", r.rule_key, norm_track(r.track))] = c.model_dump()
                else:
                    d = model.deadlines[c.index]
                    verdicts[("deadline", d.deadline_kind.value, norm_track(d.track))] = c.model_dump()
            except IndexError:
                continue

    out = []
    for key, e in items.items():
        problems: list[str] = []
        obs = e["observations"]
        located = [o for o in obs if o["locator"]]
        for o in obs:
            if o["quote_problem"]:
                problems.append(f"{o['method']}: {o['quote_problem']}")
        methods = sorted(set(e["methods"]))
        agreement = "single_pass"
        if len(methods) >= 2:
            if e["item_type"] == "deadline":
                vals = {(o["date"], o["time"], (o["timezone"] or "").upper() or None) for o in obs}
            else:
                vals = {_norm_value(o["value"]) for o in obs if o["value"] is not None}
            agreement = "agreed" if len(vals) <= 1 else "conflict"
            if agreement == "conflict":
                problems.append("extraction passes disagree: " + "; ".join(
                    f"{o['method']}={o['date'] if e['item_type'] == 'deadline' else o['value']}"
                    + (f" {o['time'] or ''} {o['timezone'] or ''}" if e["item_type"] == "deadline" else "") for o in obs))
        verdict = verdicts.get(key)
        if verdict:
            if verdict["verdict"] != "supported":
                problems.append(f"independent validator: {verdict['verdict']} - {verdict.get('issue') or 'no detail'}")
        elif "model_assisted" in methods and validator_status == "performed":
            problems.append("independent validator returned no verdict for this item")
        chosen = next((o for o in obs if o["method"] == "model_assisted" and o["locator"]), None) or \
            (located[0] if located else obs[0])
        rec: dict[str, Any] = {k: v for k, v in e.items() if k not in ("methods", "observations")}
        rec.update({"methods": methods, "agreement": agreement, "observations": obs,
                    "quote": chosen["quote"], "locator": chosen["locator"],
                    "second_pass": verdict or {"verdict": "not_performed" if validator_status != "performed" else "no_verdict"}})
        if chosen["method"] == "model_assisted":
            rec.update({"value": chosen["value"], "value_text": chosen["value_text"] or rec["value_text"]})
        if e["item_type"] == "deadline":
            src = chosen
            res = resolve_deadline(src["date"] or "", src["time"], src["timezone"])
            rec.update({"date": src["date"], "time": src["time"], "timezone": src["timezone"],
                        "due_at": res.due_at.isoformat() if res.due_at else None,
                        "governs_actions": [a.value for a in DEFAULT_GOVERNS[DeadlineKind(e["deadline_kind"])]]})
            problems += res.problems
        if e.get("category") == RuleCategory.AI_POLICY.value:
            problems.append("AI-use policy requires the researcher's interpretation of scope and disclosure")
        if e["blocking"] and agreement == "single_pass" and not problems:
            if "model_assisted" in methods and verdict and verdict["verdict"] == "supported":
                pass  # model extraction independently validated by the second pass
            else:
                problems.append("found by a single extraction method; independent confirmation is required")
        if not located:
            status = "needs_human_resolution"
        elif problems:
            status = "needs_human_resolution"
        elif agreement == "agreed" or (verdict and verdict["verdict"] == "supported"):
            status = "validated"
        else:
            status = "extracted" if not e["blocking"] else "needs_human_resolution"
        rec["problems"] = problems
        rec["status"] = status
        out.append(rec)

    edition = (model.edition if model else deterministic.edition).model_dump()
    tracks = {}
    for ex in (model, deterministic):
        if ex is None:
            continue
        for t in ex.tracks:
            tracks.setdefault(norm_track(t.name) or t.name.lower(), t.model_dump())
    return {
        "merge_version": MERGE_VERSION,
        "edition": edition,
        "tracks": list(tracks.values()),
        "items": sorted(out, key=lambda r: (r["item_type"], r["rule_key"], r.get("track") or "")),
        "passes": {"deterministic": "performed", "model_extraction": model_status, "independent_validation": validator_status},
        "missed_items": validation.missed_items if validation else [],
        "uncertainties": (model.uncertainties if model else []) + deterministic.uncertainties,
    }


def validation_items(model: CfpExtraction) -> list[dict[str, Any]]:
    items = [{"kind": "rule", "index": i, "claim": {"rule": r.rule_key, "track": r.track, "statement": r.value_text,
                                                    "value": r.value, "quote": r.quote}}
             for i, r in enumerate(model.rules)]
    items += [{"kind": "deadline", "index": i, "claim": {"kind": d.deadline_kind.value, "track": d.track,
                                                         "date": d.date, "time": d.time, "timezone": d.timezone,
                                                         "quote": d.quote}}
              for i, d in enumerate(model.deadlines)]
    return items
