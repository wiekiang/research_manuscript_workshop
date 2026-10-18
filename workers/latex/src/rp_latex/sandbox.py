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
from dataclasses import dataclass, field
from pathlib import PurePosixPath


class SandboxUnavailable(Exception):
    pass


@dataclass
class Limits:
    cpus: float = 2.0
    memory_mb: int = 2048
    pids: int = 256
    timeout_s: int = 300
    workspace_mb: int = 1024
    output_max_bytes: int = 200 * 1024 * 1024


@dataclass
class SandboxResult:
    exit_code: int
    timed_out: bool
    duration_s: float
    stdout_tail: str
    stderr_tail: str
    files: dict[str, bytes] = field(default_factory=dict)
    image: str = ""
    argv: list[str] = field(default_factory=list)


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


def docker_available(binary: str = "docker") -> bool:
    if shutil.which(binary) is None:
        return False
    try:
        return subprocess.run([binary, "info"], capture_output=True, timeout=15).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


class DockerSandbox:
    def __init__(self, image: str, binary: str = "docker", limits: Limits | None = None, uid: int = 10001):
        self.image = image
        self.binary = binary
        self.limits = limits or Limits()
        self.uid = uid

    def run(self, files: dict[str, bytes], script: list[str], collect: list[str], env: dict[str, str] | None = None,
            name: str | None = None) -> SandboxResult:
        """Run `script` (fixed argv lists joined with &&) over `files`; return files matching `collect` globs."""
        if not docker_available(self.binary):
            raise SandboxUnavailable("container runtime is not available; compilation is disabled (fail closed)")
        lim = self.limits
        # Script output goes to a log inside the workspace so stdout carries only the result tar.
        inner = ("set -u; mkdir -p /work/in && cd /work/in && tar -xf - && { "
                 + " && ".join(script)
                 + "; } > /work/in/_sandbox.log 2>&1; rc=$?; cd /work/in && "
                 + "tar -cf - _sandbox.log " + " ".join(f"$(ls -d {g} 2>/dev/null)" for g in collect)
                 + " 2>/dev/null; exit $rc")
        argv = [self.binary, "run", "--rm", "-i", "--network", "none", "--read-only",
                "--tmpfs", f"/work:rw,exec,size={lim.workspace_mb}m,uid={self.uid},gid={self.uid}",
                "--tmpfs", f"/tmp:rw,size=256m,uid={self.uid},gid={self.uid}",  # noqa: S108 - container-private
                "--cpus", str(lim.cpus), "--memory", f"{lim.memory_mb}m", "--memory-swap", f"{lim.memory_mb}m",
                "--pids-limit", str(lim.pids), "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", f"{self.uid}:{self.uid}", "--workdir", "/work"]
        if name:
            argv += ["--name", name]
        for k, v in (env or {}).items():
            argv += ["-e", f"{k}={v}"]
        argv += [self.image, "sh", "-c", inner]
        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(argv, input=build_tar(files), capture_output=True, timeout=lim.timeout_s)
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            code, out, err = 124, b"", (exc.stderr or b"")
            if name:
                subprocess.run([self.binary, "kill", name], capture_output=True)
        produced: dict[str, bytes] = {}
        if out:
            try:
                produced = read_tar(out, lim.output_max_bytes)
            except (tarfile.TarError, ValueError) as exc:
                err += f"\n[sandbox] could not read outputs: {exc}".encode()
        return SandboxResult(exit_code=code, timed_out=timed_out, duration_s=round(time.monotonic() - start, 2),
                             stdout_tail="", stderr_tail=err.decode("utf-8", "replace")[-4000:], files=produced,
                             image=self.image, argv=argv[:-3] + [self.image, "sh", "-c", "<fixed script>"])
