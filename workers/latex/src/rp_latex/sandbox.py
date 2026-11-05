"""No-network container sandbox for TeX (and, with another image, experiment) execution.

Isolation (PRODUCT_SPEC §2.12, §8): no network, read-only root filesystem, ephemeral tmpfs workspace, no host
mounts (inputs are streamed in as a tar on stdin and outputs streamed out as a tar on stdout), unprivileged
user, all capabilities dropped, no-new-privileges, CPU/memory/PID limits and a hard wall-clock timeout. The
command is a fixed argv chosen by the platform; model output is never executed as a command.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath


class SandboxUnavailable(Exception):
    """The container runtime could not be used, so nothing ran (fail closed). `cause` says why: the docker CLI
    is missing from PATH, `docker info` failed (daemon unreachable, permission denied), or the probe hung."""

    def __init__(self, cause: str):
        self.cause = cause
        super().__init__(f"container runtime is not available (fail closed): {cause}")


@dataclass
class Limits:
    cpus: float = 2.0
    memory_mb: int = 2048
    pids: int = 256
    timeout_s: int = 300
    workspace_mb: int = 1024
    output_max_bytes: int = 200 * 1024 * 1024
    tail_bytes: int = 4000  # bound kept per output stream in SandboxResult.stdout / .stderr


STDOUT_FILE = "_sandbox.out"
STDERR_FILE = "_sandbox.err"


@dataclass
class StreamTail:
    """Bounded tail of one output stream. stdout and stderr share this shape everywhere a sandbox result is
    surfaced (sandbox, LaTeX compile report, experiment run output)."""

    text: str = ""
    total_bytes: int = 0
    truncated: bool = False

    @classmethod
    def of(cls, data: bytes, max_bytes: int) -> StreamTail:
        keep = data[max(0, len(data) - max(0, max_bytes)):]
        return cls(text=keep.decode("utf-8", "replace"), total_bytes=len(data), truncated=len(keep) < len(data))


@dataclass
class ExecutionDetails:
    """The execution details every sandbox-backed result serializes under an `execution` key: the compile report
    and run manifest artifacts, and the compile-run and experiment-run API records. Both workers produce exactly
    this shape for successful and failed runs so callers never have to know which worker ran the job.

    `status` is the worker's own status vocabulary (compile: compiled | failed | unsupported | sandbox_unavailable;
    experiment: succeeded | failed | timed_out | sandbox_unavailable). `failure_reason` is None only on success.
    `output_error` is set when the container exited but its result archive could not be read."""

    status: str
    exit_code: int | None
    timed_out: bool
    duration_s: float | None
    image: str | None
    argv: list[str]
    stdout: StreamTail
    stderr: StreamTail
    failure_reason: str | None
    output_error: str | None = None
    streams_collected: bool = False  # the _sandbox.out/_sandbox.err files came back in the result archive

    def to_dict(self) -> dict:
        return asdict(self)


EXECUTION_FIELDS = frozenset(ExecutionDetails.__dataclass_fields__)


@dataclass
class SandboxResult:
    """Outcome of one sandboxed run.

    Failure semantics: `exit_code` is the runtime's exit status as observed (the script's `exit $rc`, a docker CLI
    code such as 125 when the container never started, 124 on timeout). `timed_out` runs are killed and their
    files and stream files are lost; the stderr tail says so. `output_error` is set when the container exited but
    its result archive could not be read (not a tar, unsafe member path, over the size limit): `files` is then
    empty even if `exit_code` is 0, and callers must treat the run as failed. Runtime diagnostics (docker CLI or
    daemon messages, tar extraction errors) are appended to the stderr tail after the script's own stderr.
    """

    exit_code: int
    timed_out: bool
    duration_s: float
    stdout: StreamTail = field(default_factory=StreamTail)
    stderr: StreamTail = field(default_factory=StreamTail)
    files: dict[str, bytes] = field(default_factory=dict)
    image: str = ""
    argv: list[str] = field(default_factory=list)
    output_error: str | None = None
    # True only when the workspace extracted and the step block started: the stream files were in the result
    # archive. False on timeout, on an unreadable archive, and when the runtime failed before the program ran.
    streams_collected: bool = False


def _safe_rel(path: str) -> str:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or not str(p) or "\x00" in path:
        raise ValueError(f"unsafe workspace path {path!r}")
    return str(p)


def build_tar(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for path, data in sorted(files.items()):
            info = tarfile.TarInfo(_safe_rel(path))
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def read_tar(data: bytes, max_bytes: int) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue  # symlinks/devices produced inside the sandbox are ignored
            rel = _safe_rel(m.name.lstrip("./") or m.name)
            total += m.size
            if total > max_bytes:
                raise ValueError("sandbox output exceeds the size limit")
            f = tf.extractfile(m)
            if f is not None:
                out[rel] = f.read()
    return out


PROBE_TIMEOUT_S = 15


def runtime_problem(binary: str = "docker") -> str | None:
    """None when the runtime answers `docker info`; otherwise a one-line diagnosis of why it cannot be used."""
    if shutil.which(binary) is None:
        return f"the {binary!r} CLI is not on PATH"
    try:
        proc = subprocess.run([binary, "info"], capture_output=True, timeout=PROBE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return f"`{binary} info` did not answer within {PROBE_TIMEOUT_S}s"
    except OSError as exc:
        return f"`{binary} info` could not be started: {exc}"
    if proc.returncode == 0:
        return None
    detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
    return f"`{binary} info` exited {proc.returncode}" + (f": {detail[-1][:300]}" if detail else "")


def docker_available(binary: str = "docker") -> bool:
    return runtime_problem(binary) is None


class DockerSandbox:
    def __init__(self, image: str, binary: str = "docker", limits: Limits | None = None, uid: int = 10001):
        self.image = image
        self.binary = binary
        self.limits = limits or Limits()
        self.uid = uid

    def run(self, files: dict[str, bytes], script: list[str], collect: list[str], env: dict[str, str] | None = None,
            name: str | None = None) -> SandboxResult:
        """Run `script` (fixed argv lists joined with &&) over `files`; return files matching `collect` globs."""
        problem = runtime_problem(self.binary)
        if problem is not None:
            raise SandboxUnavailable(problem)
        lim = self.limits
        # The script's stdout and stderr go to separate files inside the workspace so the container's stdout
        # carries only the result tar; both files come back in the tar and feed the bounded stream tails.
        inner = ("set -u; mkdir -p /work/in && cd /work/in && tar -xf - && { "
                 + " && ".join(script)
                 + f"; }} > /work/in/{STDOUT_FILE} 2> /work/in/{STDERR_FILE}; rc=$?; cd /work/in && "
                 + f"tar -cf - {STDOUT_FILE} {STDERR_FILE} " + " ".join(f"$(ls -d {g} 2>/dev/null)" for g in collect)
                 + " 2>/dev/null; exit $rc")
        argv = [self.binary, "run", "--rm", "-i", "--network", "none", "--read-only",
                "--tmpfs", f"/work:rw,exec,size={lim.workspace_mb}m,uid={self.uid},gid={self.uid}",
                "--tmpfs", f"/tmp:rw,size=256m,uid={self.uid},gid={self.uid}",  # noqa: S108 - container-private
                "--cpus", str(lim.cpus), "--memory", f"{lim.memory_mb}m", "--memory-swap", f"{lim.memory_mb}m",
                "--pids-limit", str(lim.pids), "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", f"{self.uid}:{self.uid}", "--workdir", "/work"]
        # Every container is named so that a timed-out run can be killed: killing the docker CLI client alone
        # leaves the container running in the daemon with no time bound.
        name = name or f"rp-sbx-{uuid.uuid4().hex[:12]}"
        argv += ["--name", name]
        for k, v in (env or {}).items():
            argv += ["-e", f"{k}={v}"]
        argv += [self.image, "sh", "-c", inner]
        start = time.monotonic()
        timed_out = False
        output_error: str | None = None
        try:
            proc = subprocess.run(argv, input=build_tar(files), capture_output=True, timeout=lim.timeout_s)
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            code, out, err = 124, b"", (exc.stderr or b"")
            self._kill(name)
            err += (f"\n[sandbox] timed out after {lim.timeout_s}s; the container was killed and its output "
                    "and files were not collected").encode()
        produced: dict[str, bytes] = {}
        stdout_bytes = b""
        if out:
            try:
                produced = read_tar(out, lim.output_max_bytes)
            except tarfile.TarError as exc:
                # Not a result tar at all: whatever the container printed is the only stdout we have.
                stdout_bytes = out
                output_error = f"the result archive is not a tar: {exc}"
            except ValueError as exc:  # unsafe member path or over the output size limit; the tar itself is valid
                output_error = str(exc)
            if output_error:
                err += f"\n[sandbox] could not read outputs: {output_error}".encode()
        # The script's streams stay in `files` (full, bounded by output_max_bytes) for callers that archive them;
        # the result carries a bounded tail of each. The runtime's own stderr (docker CLI/daemon diagnostics,
        # tar extraction errors) is appended to the script's stderr.
        stdout_bytes = produced.get(STDOUT_FILE, stdout_bytes)
        stderr_bytes = produced.get(STDERR_FILE, b"") + err
        return SandboxResult(exit_code=code, timed_out=timed_out, duration_s=round(time.monotonic() - start, 2),
                             stdout=StreamTail.of(stdout_bytes, lim.tail_bytes),
                             stderr=StreamTail.of(stderr_bytes, lim.tail_bytes), files=produced,
                             image=self.image, argv=argv[:-4] + [self.image, "sh", "-c", "<fixed script>"],
                             output_error=output_error,
                             streams_collected=STDOUT_FILE in produced or STDERR_FILE in produced)

    def _kill(self, name: str) -> None:
        try:
            subprocess.run([self.binary, "kill", name], capture_output=True, timeout=30)
        except (subprocess.TimeoutExpired, OSError):
            pass  # best effort; the container is --rm and the daemon reaps it once it exits
