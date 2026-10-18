"""Mount routers contributed by milestone feature modules (M1..M10)."""

from __future__ import annotations

import importlib

from fastapi import FastAPI

from rp_contracts import API_PREFIX

FEATURE_MODULES: list[str] = ["cfp", "discovery", "templates", "literature", "opportunities", "method", "results", "manuscript", "review", "submission", "experiments", "synthesis", "model_settings"]


def mount(app: FastAPI) -> None:
    for name in FEATURE_MODULES:
        module = importlib.import_module(f"rp_api.features.{name}")
        app.include_router(module.router, prefix=API_PREFIX)
