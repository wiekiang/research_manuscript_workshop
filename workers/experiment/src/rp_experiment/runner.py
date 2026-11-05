"""Execute an approved experiment plan inside the no-network sandbox and collect raw outputs.

The workspace contains only the plan's code and inputs (by hash). The argv is built by the platform from the plan
and every argument is shell-quoted. The image's environment manifest is copied into the outputs.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

from rp_contracts.experiments import OUTPUT_DIR, ExperimentPlanIn, argv_for, shell_command
from rp_latex.sandbox import (
    STDERR_FILE,
    STDOUT_FILE,
    DockerSandbox,
    ExecutionDetails,
    Limits,
    SandboxResult,
    SandboxUnavailable,
    StreamTail,
)

__all__ = ["RunOutput", "SandboxUnavailable", "execute", "workspace_files"]


@dataclass
class RunOutput:
    """Failure semantics: `status` is `succeeded` only when the program exited 0 and its outputs were collected.
    `exit_code` is what the sandbox observed (None when it never ran; 124 on timeout; the program's code
    otherwise, or a docker CLI code when the container never started). `failure_reason` is set for every status
    other than `succeeded` and names the actual cause, so a `failed` run with exit code 0 (outputs could not be
    read) is never described as a program failure."""

    status: str  # succeeded | failed | timed_out | sandbox_unavailable
    exit_code: int | None
    duration_s: float | None  # None when nothing ran (sandbox unavailable, unusable code archive)
    log: str
    outputs: dict[str, bytes] = field(default_factory=dict)
    environment: bytes | None = None
    argv: list[str] = field(default_factory=list)
    image: str = ""
    stdout: StreamTail = field(default_factory=StreamTail)  # bounded tail of the program's stdout
    stderr: StreamTail = field(default_factory=StreamTail)  # same shape; includes sandbox runtime diagnostics
    failure_reason: str | None = None
    timed_out: bool = False
    output_error: str | None = None
    streams_collected: bool = False

    def execution(self) -> ExecutionDetails:
        """The same execution block the LaTeX compile report serializes; see ExecutionDetails."""
        return ExecutionDetails(status=self.status, exit_code=self.exit_code, timed_out=self.timed_out,
                                duration_s=self.duration_s, image=self.image or None, argv=list(self.argv),
                                stdout=self.stdout, stderr=self.stderr, failure_reason=self.failure_reason,
                                output_error=self.output_error, streams_collected=self.streams_collected)


LOG_MAX_CHARS = 200_000


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
    # The environment manifest is copied before the program runs so it is recorded for failed runs too, and so a
    # missing manifest in the image fails before the program rather than being attributed to it.
    steps = [f"mkdir -p {OUTPUT_DIR}", f"cp /opt/rp/environment.json {OUTPUT_DIR}/_environment.json", shell_command(argv)]
    try:
        files = workspace_files(plan, code, inputs)
    except zipfile.BadZipFile as exc:
        reason = f"the code archive could not be unpacked: {exc}"
        return RunOutput("failed", None, None, reason, argv=argv, image=image_ref, failure_reason=reason)
    try:
        res: SandboxResult = sb.run(files, steps, collect=[f"{OUTPUT_DIR}/*"])
    except SandboxUnavailable as exc:
        # Same convention as the compile report: no exit code, no duration, empty tails, the probe's diagnosis as
        # reason and log. The planned program argv and image are known and recorded.
        return RunOutput("sandbox_unavailable", None, None, str(exc), argv=argv, image=image_ref, failure_reason=str(exc))
    stdout = res.files.pop(STDOUT_FILE, b"").decode("utf-8", errors="replace")
    # When the stream files did not come back (timeout, unreadable archive, a step failed before the program
    # ran) the stderr tail is all the diagnostics there are, so it becomes the log's stderr section.
    stderr = (res.files.pop(STDERR_FILE).decode("utf-8", errors="replace") if STDERR_FILE in res.files
              else res.stderr.text)
    log = stdout + (("\n" if stdout and not stdout.endswith("\n") else "") + "--- stderr ---\n" + stderr if stderr else "")
    env = res.files.pop(f"{OUTPUT_DIR}/_environment.json", None)
    if res.timed_out:
        status, reason = "timed_out", f"the run exceeded its time limit of {plan.limits.timeout_s}s"
    elif res.output_error:
        status, reason = "failed", f"the sandbox outputs could not be collected: {res.output_error}"
    elif res.exit_code != 0:
        status, reason = "failed", f"the program exited with code {res.exit_code}"
    else:
        status, reason = "succeeded", None
    return RunOutput(status, res.exit_code, res.duration_s, log[-LOG_MAX_CHARS:], res.files, env, argv, image_ref,
                     stdout=res.stdout, stderr=res.stderr, failure_reason=reason, timed_out=res.timed_out,
                     output_error=res.output_error, streams_collected=res.streams_collected)
