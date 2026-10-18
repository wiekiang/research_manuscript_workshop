"""Execute an approved experiment plan inside the no-network sandbox and collect raw outputs.

The workspace contains only the plan's code and inputs (by hash). The argv is built by the platform from the plan
and every argument is shell-quoted. The image's environment manifest is copied into the outputs.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from rp_contracts.experiments import OUTPUT_DIR, ExperimentPlanIn, argv_for, shell_command
from rp_latex.sandbox import DockerSandbox, Limits, SandboxResult, SandboxUnavailable

__all__ = ["RunOutput", "SandboxUnavailable", "execute", "workspace_files"]


@dataclass
class RunOutput:
    status: str  # succeeded | failed | timed_out | sandbox_unavailable
    exit_code: int | None
    duration_s: float
    log: str
    outputs: dict[str, bytes] = field(default_factory=dict)
    environment: bytes | None = None
    argv: list[str] = field(default_factory=list)
    image: str = ""


def workspace_files(plan: ExperimentPlanIn, code: bytes, inputs: dict[str, bytes]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if code[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(code)) as z:
            for info in z.infolist():
                if not info.is_dir():
                    files[info.filename] = z.read(info)
    else:
        files[plan.code_path] = code
    files.update(inputs)
    return files


def execute(plan: ExperimentPlanIn, image_ref: str, code: bytes, inputs: dict[str, bytes], binary: str = "docker") -> RunOutput:
    argv = argv_for(plan)
    sb = DockerSandbox(image_ref, binary=binary, limits=Limits(cpus=plan.limits.cpus, memory_mb=plan.limits.memory_mb,
                                                                 timeout_s=plan.limits.timeout_s))
    steps = [f"mkdir -p {OUTPUT_DIR}", shell_command(argv), f"cp /opt/rp/environment.json {OUTPUT_DIR}/_environment.json"]
    try:
        res: SandboxResult = sb.run(workspace_files(plan, code, inputs), steps, collect=[f"{OUTPUT_DIR}/*"])
    except SandboxUnavailable:
        return RunOutput("sandbox_unavailable", None, 0.0, "container runtime unavailable (fail closed)", argv=argv,
                         image=image_ref)
    log = res.files.pop("_sandbox.log", b"").decode("utf-8", errors="replace")
    env = res.files.pop(f"{OUTPUT_DIR}/_environment.json", None)
    status = "timed_out" if res.timed_out else ("succeeded" if res.exit_code == 0 else "failed")
    return RunOutput(status, res.exit_code, res.duration_s, log[-200_000:], res.files, env, argv, image_ref)
