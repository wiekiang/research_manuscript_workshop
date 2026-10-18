"""Per-project coordinator workflow (workflow ID `project-{id}`).

Receives every project-scoped outbox event as a signal (deduplicated on event_id), raises
`approval.required` notifications when the project waits on a human gate, and continues-as-new to bound
history. It never writes canonical state: human gates are completed only through the API's approval endpoints.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from ..activities import common as acts
    from .base import act_opts

HUMAN_GATE_STATES = {"TARGET_REVIEW", "DIRECTION_REVIEW", "PROTOCOL_REVIEW", "OUTCOME_REVIEW", "FINAL_APPROVAL"}
MAX_EVENTS_BEFORE_CONTINUE = 400


@workflow.defn(name="ProjectWorkflow")
class ProjectWorkflow:
    def __init__(self) -> None:
        self._pending: list[dict] = []
        self._seen: list[str] = []
        self._processed = 0
        self._state: str | None = None
        self._closed = False

    @workflow.signal
    def event(self, envelope: dict) -> None:
        eid = envelope.get("event_id")
        if eid and eid not in self._seen and all(p.get("event_id") != eid for p in self._pending):
            self._pending.append(envelope)

    @workflow.query
    def status(self) -> dict:
        return {"state": self._state, "processed": self._processed, "closed": self._closed}

    @workflow.run
    async def run(self, project_id: str, seen: list[str] | None = None) -> dict:
        self._seen = list(seen or [])
        while not self._closed:
            try:
                await workflow.wait_condition(lambda: bool(self._pending), timeout=timedelta(days=1))
            except TimeoutError:
                # Durable daily timer: CFP change monitoring and deadline reminders (never approvals).
                await workflow.execute_activity(acts.project_daily_tick, project_id, **act_opts())
                continue
            while self._pending:
                env = self._pending.pop(0)
                await self._handle(project_id, env)
                self._seen.append(env["event_id"])
                self._seen = self._seen[-500:]
                self._processed += 1
            if self._processed >= MAX_EVENTS_BEFORE_CONTINUE and not self._closed:
                workflow.continue_as_new(args=[project_id, self._seen[-200:]])
        return {"project_id": project_id, "final_state": self._state, "events": self._processed}

    async def _handle(self, project_id: str, env: dict) -> None:
        etype = env.get("type")
        payload = env.get("payload") or {}
        if etype == "state.changed":
            self._state = payload.get("to")
            if self._state in HUMAN_GATE_STATES:
                await workflow.execute_activity(acts.notify_approval_required,
                                                args=[project_id, self._state, env["event_id"]], **act_opts())
            if self._state == "CANCELLED":
                self._closed = True
        elif etype == "project.control" and payload.get("action") == "cancel":
            self._closed = True
