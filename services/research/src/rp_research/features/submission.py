"""M8 workflow: build the version-locked export package from the signed content manifest. Nothing is submitted."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rp_contracts.hashing import content_hash, sha256_hex
    from rp_contracts.tasks import QUEUE_LATEX

    from ..api_client import ApiCallError, ApiClient
    from ..registry import register
    from ..temporal_types import TaskInput, TaskOutcome
    from ..workflows.base import run_task
    from .common import app_error


def build_zip(files: dict[str, bytes]) -> bytes:
    """Deterministic ZIP (fixed timestamps, sorted members) so identical content gives an identical checksum."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[name])
    return buf.getvalue()


@activity.defn
async def package_build(task_id: str, project_id: str, package_id: str) -> dict:
    async with ApiClient(task_id) as api:
        try:
            spec = await api.get(f"/v1/internal/packages/{package_id}/spec")
            files: dict[str, bytes] = {}
            entries = []
            for item in spec["items"]:
                data = await api.read_artifact_bytes(item["artifact_id"])
                digest = hashlib.sha256(data).hexdigest()
                files[item["path"]] = data
                entries.append({"path": item["path"], "role": item["role"], "artifact_id": item["artifact_id"],
                                "sha256": digest, "matches_signed_hash": digest == item["sha256"]})
            for name, text in spec["inline"].items():
                files[name] = text.encode()
                entries.append({"path": name, "role": "generated", "sha256": sha256_hex(files[name])})
            manifest = {"package": spec["name"], "approved": spec["approved"],
                        "content_manifest_hash": spec.get("content_manifest_hash"), "files": entries,
                        "note": "Prepared for human export; the platform does not submit to any venue."}
            files["provenance-manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True).encode()
            data = build_zip(files)
            art = await api.publish(project_id, "export_package", data, "application/zip",
                                    content_hash({"package": package_id}), slot=f"package:{package_id}",
                                    label=spec["name"])
            res = await api.post(f"/v1/internal/packages/{package_id}", {"artifact_id": art.artifact_id, "manifest": manifest})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"artifact_id": art.artifact_id, "status": res["status"], "problems": res["problems"],
            "transition": res.get("transition")}


RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=2),
                    maximum_attempts=3)


@workflow.defn(name="PackageWorkflow")
class PackageWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            r = await workflow.execute_activity(package_build, args=[inp.task_id, inp.project_id, inp.params["package_id"]],
                                                start_to_close_timeout=timedelta(minutes=10), retry_policy=RETRY)
            return TaskOutcome(state="succeeded", output_artifact_ids=[r["artifact_id"]], result=r)
        return await run_task(inp, body)


register(QUEUE_LATEX, workflows=[PackageWorkflow], activities=[package_build])
