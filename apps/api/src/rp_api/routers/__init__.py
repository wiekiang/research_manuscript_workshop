from __future__ import annotations

from fastapi import FastAPI

from rp_contracts import API_PREFIX


def mount_all(app: FastAPI) -> None:
    from . import artifacts, auth, costs, internal, ledger, meta, projects

    app.include_router(meta.root_router)
    for module in (meta, auth, projects, artifacts, ledger, costs, internal):
        app.include_router(module.router, prefix=API_PREFIX)
    app.include_router(auth.ws_router, prefix=API_PREFIX)

    # Milestone modules register their own routers (and gate evaluators) when present.
    from . import milestones

    milestones.mount(app)
