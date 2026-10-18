"""Which workflows/activities each task queue's worker hosts. Milestone modules add themselves here."""

from __future__ import annotations

from rp_contracts.tasks import QUEUE_EXPERIMENT, QUEUE_FETCH, QUEUE_LATEX, QUEUE_RESEARCH

from .activities import common
from .workflows.maintenance import ReconcileWorkflow
from .workflows.project import ProjectWorkflow

COMMON_ACTIVITIES = [common.task_started, common.task_finished, common.task_progress, common.project_runnable,
                     common.request_transition, common.notify_approval_required, common.run_reconciler,
                     common.project_daily_tick]

WORKFLOWS: dict[str, list] = {QUEUE_RESEARCH: [ProjectWorkflow, ReconcileWorkflow], QUEUE_FETCH: [],
                              QUEUE_LATEX: [], QUEUE_EXPERIMENT: []}
ACTIVITIES: dict[str, list] = {QUEUE_RESEARCH: list(COMMON_ACTIVITIES), QUEUE_FETCH: list(COMMON_ACTIVITIES),
                               QUEUE_LATEX: list(COMMON_ACTIVITIES), QUEUE_EXPERIMENT: list(COMMON_ACTIVITIES)}


def register(queue: str, workflows: list | None = None, activities: list | None = None) -> None:
    """Idempotent, name-based registration (the workflow sandbox re-executes feature modules)."""
    from temporalio import workflow

    if workflow.unsafe.in_sandbox():
        return
    for w in workflows or []:
        if all(x.__name__ != w.__name__ for x in WORKFLOWS[queue]):
            WORKFLOWS[queue].append(w)
    for a in activities or []:
        if all(x.__name__ != a.__name__ for x in ACTIVITIES[queue]):
            ACTIVITIES[queue].append(a)


def load_features() -> None:
    """Import milestone feature packages so they register their workflows/activities."""
    import importlib

    for name in FEATURES:
        importlib.import_module(f"rp_research.features.{name}")


FEATURES: list[str] = ["cfp", "discovery", "templates", "literature", "method", "manuscript", "review", "submission", "experiments"]
