"""Write generated contracts: OpenAPI, JSON Schemas for shared models, required copy, state machine table."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel

from rp_contracts import CONTRACTS_VERSION, artifacts, cfp, copy, events
from rp_contracts.state_machine import transition_table

from .config import REPO_ROOT

SCHEMA_MODELS: list[type[BaseModel]] = [
    events.EventEnvelope, artifacts.ReservationRequest, artifacts.CommitRequest, artifacts.ArtifactOut,
    cfp.CfpExtraction, cfp.CfpValidation, cfp.DeadlineResolution,
]


def _extra_models() -> list[type[BaseModel]]:
    out: list[type[BaseModel]] = []
    for mod in ("methods", "literature", "manuscript", "review", "submission", "experiments"):
        try:
            m = __import__(f"rp_contracts.{mod}", fromlist=["EXPORT"])
            out += list(getattr(m, "EXPORT", []))
        except ImportError:
            continue
    return out


def export(out: str | None = None) -> Path:
    os.environ.setdefault("RP_ENVIRONMENT", "test")
    root = Path(out) if out else REPO_ROOT / "contracts" / "schemas"
    root.mkdir(parents=True, exist_ok=True)
    from .main import create_app

    (root / "openapi.json").write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
    for model in SCHEMA_MODELS + _extra_models():
        (root / f"{model.__name__}.schema.json").write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n")
    (root / "copy.json").write_text(json.dumps(copy.all_copy(), indent=2, ensure_ascii=False) + "\n")
    (root / "state_machine.json").write_text(json.dumps({"contracts_version": CONTRACTS_VERSION,
                                                         "transitions": transition_table()}, indent=2) + "\n")
    (root / "artifact_kinds.json").write_text(json.dumps({k: {"media_types": list(v.media_types), "max_bytes": v.max_bytes,
                                                              "worker_producible": v.worker_producible}
                                                          for k, v in artifacts.ARTIFACT_KINDS.items()}, indent=2) + "\n")
    return root
