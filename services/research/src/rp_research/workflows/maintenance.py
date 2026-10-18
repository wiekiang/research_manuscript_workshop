from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from ..activities import common as acts
    from .base import act_opts


@workflow.defn(name="ReconcileWorkflow")
class ReconcileWorkflow:
    """Run by a Temporal Schedule (see `rp-worker schedules`); safe to run concurrently with uploads."""

    @workflow.run
    async def run(self) -> dict:
        return await workflow.execute_activity(acts.run_reconciler, **act_opts(timedelta(minutes=10)))
