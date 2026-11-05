"""Sandbox result shape: bounded stdout/stderr tails, exit code, duration, image and argv (runtime mocked)."""

from __future__ import annotations

import subprocess

import pytest

from rp_latex import sandbox as sb
from rp_latex.compile import default_sandbox
from rp_latex.sandbox import (
    STDERR_FILE,
    STDOUT_FILE,
    DockerSandbox,
    Limits,
    StreamTail,
    build_tar,
    docker_available,
)

IMAGE = "rp-latex-sandbox:test"


def image_present(image: str) -> bool:
    if not docker_available():
        return False
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0


def fake_runtime(monkeypatch, *, returncode=0, stdout=b"", stderr=b"", timeout=False):
    """Replace `docker` with a stub and record the argv and inner script it was given."""
    calls: list[list[str]] = []

    def run(argv, **kw):
        calls.append(argv)
        if timeout:
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"), stderr=stderr)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(sb, "runtime_problem", lambda binary="docker": None)
    monkeypatch.setattr(sb.subprocess, "run", run)
    return calls


def test_stream_tail_is_bounded_and_reports_truncation():
    assert StreamTail.of(b"", 10) == StreamTail(text="", total_bytes=0, truncated=False)
    assert StreamTail.of(b"short", 10) == StreamTail(text="short", total_bytes=5, truncated=False)
    t = StreamTail.of(b"x" * 100 + b"END", 5)
    assert t == StreamTail(text="xxEND", total_bytes=103, truncated=True)
    assert StreamTail.of(b"abc", 0) == StreamTail(text="", total_bytes=3, truncated=True)
    assert StreamTail.of("é".encode()[:1], 10).text == "�", "a cut UTF-8 sequence never raises"


def test_successful_run_returns_both_streams_files_and_run_details(monkeypatch):
    produced = build_tar({STDOUT_FILE: b"Output written on main.pdf (3 pages).\n", STDERR_FILE: b"",
                          "main.pdf": b"%PDF-1.4 fake"})
    calls = fake_runtime(monkeypatch, returncode=0, stdout=produced)
    box = DockerSandbox(IMAGE, limits=Limits(tail_bytes=4000, timeout_s=30))

    res = box.run({"main.tex": b"\\documentclass{article}"}, ["latexmk main.tex"], collect=["main.pdf"], name="job-1")

    assert res.exit_code == 0 and not res.timed_out and res.duration_s >= 0
    assert res.image == IMAGE
    assert res.stdout == StreamTail(text="Output written on main.pdf (3 pages).\n", total_bytes=38, truncated=False)
    assert res.stderr == StreamTail(text="", total_bytes=0, truncated=False)
    assert res.files["main.pdf"] == b"%PDF-1.4 fake"
    assert STDOUT_FILE in res.files and STDERR_FILE in res.files, "full streams stay available to callers"
    # argv keeps the isolation flags but replaces the inner script with a placeholder.
    assert res.argv[:4] == ["docker", "run", "--rm", "-i"] and ["--network", "none"] == res.argv[4:6]
    assert res.argv[-4:] == [IMAGE, "sh", "-c", "<fixed script>"] and "--name" in res.argv
    assert res.argv.count(IMAGE) == 1, "the redacted argv names the image exactly once"
    assert res.argv[:-1] == calls[0][:-1], "only the inner script is redacted"
    # The real inner script separates the two streams into the files the result reads back.
    inner = calls[0][-1]
    assert f"> /work/in/{STDOUT_FILE} 2> /work/in/{STDERR_FILE}" in inner
    assert f"tar -cf - {STDOUT_FILE} {STDERR_FILE} " in inner and "2>&1" not in inner


def test_failed_run_keeps_bounded_tails_of_both_streams(monkeypatch):
    big_out = b"".join(f"progress line {i}\n".encode() for i in range(1000))
    big_err = b"x" * 9000 + b"\n! Emergency stop.\n"
    produced = build_tar({STDOUT_FILE: big_out, STDERR_FILE: big_err})
    fake_runtime(monkeypatch, returncode=1, stdout=produced, stderr=b"docker: container exited\n")
    lim = Limits(tail_bytes=1024)

    res = DockerSandbox(IMAGE, limits=lim).run({"main.tex": b""}, ["latexmk main.tex"], collect=["main.pdf"])

    assert res.exit_code == 1 and not res.timed_out and res.image == IMAGE
    assert "main.pdf" not in res.files
    for stream in (res.stdout, res.stderr):
        assert len(stream.text.encode()) <= lim.tail_bytes
        assert stream.truncated
    assert res.stdout.total_bytes == len(big_out) and res.stdout.text.endswith("progress line 999\n")
    # The runtime's own stderr is appended to the script's stderr, and the tail keeps the end of the stream.
    assert res.stderr.total_bytes == len(big_err) + len(b"docker: container exited\n")
    assert res.stderr.text.endswith("! Emergency stop.\ndocker: container exited\n")


def test_timeout_kills_the_named_container_and_says_output_was_lost(monkeypatch):
    calls = fake_runtime(monkeypatch, timeout=True, stderr=b"partial")
    res = DockerSandbox(IMAGE, limits=Limits(timeout_s=1)).run({}, ["sleep 10"], collect=[])
    assert res.timed_out and res.exit_code == 124 and res.files == {} and res.output_error is None
    assert res.stdout == StreamTail()
    assert res.stderr.text.startswith("partial\n[sandbox] timed out after 1s") and "not collected" in res.stderr.text
    # Regression: without a caller-supplied name the container used to outlive the killed docker client.
    run_argv, kill_argv = calls
    name = run_argv[run_argv.index("--name") + 1]
    assert name.startswith("rp-sbx-") and kill_argv == ["docker", "kill", name]
    assert res.argv[res.argv.index("--name") + 1] == name


def test_timeout_kill_failures_are_swallowed(monkeypatch):
    def run(argv, **kw):
        if argv[1] == "kill":
            raise OSError("daemon went away")
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(sb, "runtime_problem", lambda binary="docker": None)
    monkeypatch.setattr(sb.subprocess, "run", run)
    res = DockerSandbox(IMAGE, limits=Limits(timeout_s=1)).run({}, ["sleep 10"], collect=[])
    assert res.timed_out and res.exit_code == 124 and "[sandbox] timed out after 1s" in res.stderr.text


def test_oversized_archive_is_an_output_error_not_a_success(monkeypatch):
    produced = build_tar({STDOUT_FILE: b"done\n", STDERR_FILE: b"", "big.bin": b"x" * 2048})
    fake_runtime(monkeypatch, returncode=0, stdout=produced)
    res = DockerSandbox(IMAGE, limits=Limits(output_max_bytes=1024)).run({}, ["true"], collect=["big.bin"])
    assert res.exit_code == 0 and not res.timed_out
    assert res.output_error == "sandbox output exceeds the size limit" and res.files == {}
    assert res.stdout == StreamTail(), "a valid but oversized tar is never shown as program output"
    assert res.stderr.text.strip() == "[sandbox] could not read outputs: sandbox output exceeds the size limit"


def test_unsafe_member_path_is_an_output_error(monkeypatch):
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("out/../escape.txt")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    fake_runtime(monkeypatch, returncode=0, stdout=buf.getvalue())
    res = DockerSandbox(IMAGE).run({}, ["true"], collect=[])
    assert res.output_error and "unsafe workspace path" in res.output_error and res.files == {}


def test_non_tar_output_is_surfaced_in_the_stdout_tail(monkeypatch):
    fake_runtime(monkeypatch, returncode=0, stdout=b"unexpected banner from the image\n")
    res = DockerSandbox(IMAGE).run({}, ["true"], collect=[])
    assert res.files == {} and res.exit_code == 0
    assert res.output_error and res.output_error.startswith("the result archive is not a tar")
    assert res.stdout.text == "unexpected banner from the image\n" and not res.stdout.truncated
    assert "[sandbox] could not read outputs: the result archive is not a tar" in res.stderr.text


def test_runtime_failure_keeps_docker_exit_code_and_diagnostics(monkeypatch):
    fake_runtime(monkeypatch, returncode=125, stdout=b"",
                 stderr=b"Unable to find image 'rp-latex-sandbox:test' locally\ndocker: pull access denied\n")
    res = DockerSandbox(IMAGE).run({"main.tex": b""}, ["latexmk main.tex"], collect=["main.pdf"])
    assert res.exit_code == 125 and not res.timed_out and res.files == {} and res.output_error is None
    assert res.stdout == StreamTail() and res.stderr.text.startswith("Unable to find image")


def test_streams_collected_distinguishes_program_exits_from_runtime_failures(monkeypatch):
    # Program ran and failed: the stream files are in the result tar, so streams_collected is true.
    produced = build_tar({STDOUT_FILE: b"hello\n", STDERR_FILE: b"failing\n"})
    fake_runtime(monkeypatch, returncode=125, stdout=produced)
    ran = DockerSandbox(IMAGE).run({}, ["./prog"], collect=[])
    assert ran.exit_code == 125 and ran.streams_collected is True

    # Runtime failed before the program (missing image): same exit code, no result tar, flag false.
    fake_runtime(monkeypatch, returncode=125, stdout=b"", stderr=b"Unable to find image\n")
    never = DockerSandbox(IMAGE).run({}, ["./prog"], collect=[])
    assert never.exit_code == 125 and never.streams_collected is False

    # Timeout and unreadable archive also lose the stream files.
    fake_runtime(monkeypatch, timeout=True)
    assert DockerSandbox(IMAGE, limits=Limits(timeout_s=1)).run({}, ["./prog"], collect=[]).streams_collected is False
    fake_runtime(monkeypatch, returncode=0, stdout=build_tar({STDOUT_FILE: b"x", "big.bin": b"y" * 2048}))
    big = DockerSandbox(IMAGE, limits=Limits(output_max_bytes=1024)).run({}, ["./prog"], collect=["big.bin"])
    assert big.output_error and big.streams_collected is False


def test_fails_closed_when_runtime_is_missing(monkeypatch):
    monkeypatch.setattr(sb, "runtime_problem", lambda binary="docker": "the 'docker' CLI is not on PATH")
    with pytest.raises(sb.SandboxUnavailable) as info:
        DockerSandbox(IMAGE).run({}, ["true"], collect=[])
    assert info.value.cause == "the 'docker' CLI is not on PATH"
    assert str(info.value) == "container runtime is not available (fail closed): the 'docker' CLI is not on PATH"


def test_runtime_problem_names_each_cause(monkeypatch):
    """The probe keeps the diagnosis instead of collapsing every cause into one boolean."""
    monkeypatch.setattr(sb.shutil, "which", lambda b: None)
    assert sb.runtime_problem("dockerx") == "the 'dockerx' CLI is not on PATH"

    monkeypatch.setattr(sb.shutil, "which", lambda b: "/usr/bin/docker")
    calls = []

    def info(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, b"", b"Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                                                            b"Is the docker daemon running?\n")

    monkeypatch.setattr(sb.subprocess, "run", info)
    assert sb.runtime_problem() == ("`docker info` exited 1: Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
                                    "Is the docker daemon running?")
    assert calls == [["docker", "info"]] and sb.docker_available() is False

    monkeypatch.setattr(sb.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, b"", b""))
    assert sb.runtime_problem() == "`docker info` exited 1"

    def hang(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(sb.subprocess, "run", hang)
    assert sb.runtime_problem() == f"`docker info` did not answer within {sb.PROBE_TIMEOUT_S}s"

    def denied(argv, **kw):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(sb.subprocess, "run", denied)
    assert sb.runtime_problem().startswith("`docker info` could not be started: [Errno 13] Permission denied")

    monkeypatch.setattr(sb.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, b"", b""))
    assert sb.runtime_problem() is None and sb.docker_available() is True


def test_unreachable_daemon_cause_reaches_run_callers(monkeypatch):
    monkeypatch.setattr(sb.shutil, "which", lambda b: "/usr/bin/docker")
    monkeypatch.setattr(sb.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, b"", b"permission denied while trying to connect\n"))
    with pytest.raises(sb.SandboxUnavailable) as info:
        DockerSandbox(IMAGE).run({"a": b"x"}, ["true"], collect=[])
    assert info.value.cause == "`docker info` exited 1: permission denied while trying to connect"


@pytest.mark.docker
@pytest.mark.skipif(not image_present(default_sandbox().image), reason="sandbox image not present")
def test_real_timeout_leaves_no_running_container():
    box = default_sandbox()
    box.limits = Limits(timeout_s=2, memory_mb=256)
    res = box.run({}, ["sleep 60"], collect=[])
    assert res.timed_out and res.exit_code == 124
    name = res.argv[res.argv.index("--name") + 1]
    ps = subprocess.run(["docker", "ps", "-q", "--filter", f"name=^{name}$"], capture_output=True, text=True)
    assert ps.stdout.strip() == "", f"container {name} is still running"


@pytest.mark.docker
@pytest.mark.skipif(not image_present(default_sandbox().image), reason="sandbox image not present")
def test_real_container_streams_collected_exit_codes_and_tails():
    """Real-container counterpart of the stubbed streams_collected test: a program exiting 125, a docker-level
    125 (missing image), and a timeout."""
    image = default_sandbox().image

    # A child process exits 125 after writing to both streams: the files still come back.
    ran = DockerSandbox(image, limits=Limits(timeout_s=60, memory_mb=512)).run(
        {}, ["echo out-line", "sh -c 'echo err-line >&2; exit 125'"], collect=[])
    assert (ran.exit_code, ran.timed_out, ran.streams_collected) == (125, False, True)
    assert ran.stdout.text == "out-line\n" and not ran.stdout.truncated
    assert ran.stderr.text == "err-line\n" and not ran.stderr.truncated
    assert ran.output_error is None and STDOUT_FILE in ran.files

    # The runtime fails with the same exit code before anything runs: no archive, docker's message in stderr.
    never = DockerSandbox("rp-latex-sandbox:no-such-tag", limits=Limits(timeout_s=60)).run({}, ["echo hi"], collect=[])
    assert (never.exit_code, never.timed_out, never.streams_collected) == (125, False, False)
    assert never.files == {} and never.stdout == StreamTail()
    assert "rp-latex-sandbox:no-such-tag" in never.stderr.text and never.stderr.total_bytes > 0

    # A timeout kills the container: archive lost, the stderr tail says so.
    slept = DockerSandbox(image, limits=Limits(timeout_s=2, memory_mb=512)).run({}, ["echo started", "sleep 30"], collect=[])
    assert (slept.exit_code, slept.timed_out, slept.streams_collected) == (124, True, False)
    assert slept.stdout == StreamTail() and slept.files == {}
    assert "[sandbox] timed out after 2s" in slept.stderr.text and "not collected" in slept.stderr.text
