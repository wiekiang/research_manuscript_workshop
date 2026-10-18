"""rp-worker: run Temporal workers for one or more task queues, or install schedules.

  rp-worker run --queues research-main,controlled-fetch
  rp-worker schedules         # create/update the artifact reconciler schedule
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
)
from temporalio.worker import Worker

from rp_contracts.tasks import QUEUE_EXPERIMENT, QUEUE_FETCH, QUEUE_LATEX, QUEUE_RESEARCH

from .config import get_worker_settings
from .registry import ACTIVITIES, WORKFLOWS, load_features

log = logging.getLogger("rp_worker")


async def connect() -> Client:
    s = get_worker_settings()
    return await Client.connect(s.temporal_address, namespace=s.temporal_namespace)


async def run(queues: list[str]) -> None:
    load_features()
    client = await connect()
    workers = [Worker(client, task_queue=q, workflows=WORKFLOWS[q], activities=ACTIVITIES[q],
                      max_concurrent_activities=8 if q in (QUEUE_LATEX, QUEUE_EXPERIMENT) else 32)
               for q in queues]
    log.info("starting workers for %s", queues)
    await asyncio.gather(*(w.run() for w in workers))


async def install_schedules() -> None:
    client = await connect()
    schedule = Schedule(
        action=ScheduleActionStartWorkflow("ReconcileWorkflow", id="maintenance-reconcile", task_queue=QUEUE_RESEARCH),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
    )
    try:
        await client.create_schedule("artifact-reconciler", schedule)
    except Exception as exc:  # noqa: BLE001 - already exists
        log.info("schedule exists or could not be created: %s", exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="rp-worker")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--queues", default=",".join([QUEUE_RESEARCH, QUEUE_FETCH]))
    sub.add_parser("schedules")
    args = parser.parse_args()
    if args.cmd == "run":
        asyncio.run(run([q.strip() for q in args.queues.split(",") if q.strip()]))
    else:
        asyncio.run(install_schedules())
