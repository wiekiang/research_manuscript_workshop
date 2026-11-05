"""Run output shape: status, exit code, duration, image, argv, log and bounded stdout/stderr tails (sandbox faked)."""

from __future__ import annotations

from dataclasses import asdict

from rp_contracts.experiments import OUTPUT_DIR, ExperimentPlanIn
from rp_experiment import runner
from rp_experiment.runner import LOG_MAX_CHARS, RunOutput, execute
from rp_latex.sandbox import STDERR_FILE, STDOUT_FILE, SandboxResult, SandboxUnavailable, StreamTail

IMAGE = "python-sci@sha256:abc"
SHAPE = {"text", "total_bytes", "truncated"}


def plan(**over) -> ExperimentPlanIn:
    base = {"title": "toy study", "code_artifact_id": "c", "entrypoint": ["python", "main.py", "--seed", "{seed}"],
            "image": "python-sci:1", "seed": 3, "run_type": "confirmatory", "metrics": [{"name": "accuracy"}],
            "data_origin": "public data", "data_rights": "CC-BY", "limitations": "small",
            "limits": {"cpus": 1, "memory_mb": 512, "timeout_s": 60}}
    base.update(over)
    return ExperimentPlanIn.model_validate(base)


def install_fake_sandbox(monkeypatch, result: SandboxResult | None):
    """Replace DockerSandbox in the runner; records the construction arguments and the run call."""
    seen: dict = {}

    class Fake:
        def __init__(self, image, binary="docker", limits=None, uid=10001):
            seen.update(image=image, binary=binary, limits=limits)

        def run(self, files, script, collect, env=None, name=None):
            seen.update(files=files, script=script, collect=collect)
            if result is None:
                raise SandboxUnavailable("no runtime")
            return result

    monkeypatch.setattr(runner, "DockerSandbox", Fake)
    return seen


def test_successful_run_returns_streams_outputs_and_run_details(monkeypatch):
    out_tail = StreamTail(text="accuracy 0.75 numpy 2.3.0\n", total_bytes=26, truncated=False)
    err_tail = StreamTail(text="", total_bytes=0, truncated=False)
    res = SandboxResult(exit_code=0, timed_out=False, duration_s=2.5, stdout=out_tail, stderr=err_tail, image=IMAGE,
                        files={STDOUT_FILE: b"accuracy 0.75 numpy 2.3.0\n", STDERR_FILE: b"",
                               f"{OUTPUT_DIR}/metrics.json": b'{"accuracy": 0.75}',
                               f"{OUTPUT_DIR}/_environment.json": b'{"python": "3.13"}'})
    seen = install_fake_sandbox(monkeypatch, res)

    out = execute(plan(), IMAGE, b"print('hi')", {})

    assert out.status == "succeeded" and out.exit_code == 0 and out.duration_s == 2.5
    assert out.image == IMAGE and out.argv == ["python", "main.py", "--seed", "3"]
    assert out.stdout == out_tail and out.stderr == err_tail
    assert set(asdict(out)["stdout"]) == SHAPE == set(asdict(out)["stderr"])
    assert out.log == "accuracy 0.75 numpy 2.3.0\n", "stdout alone forms the log when stderr is empty"
    assert out.outputs == {f"{OUTPUT_DIR}/metrics.json": b'{"accuracy": 0.75}'}, "stream files are not outputs"
    assert out.environment == b'{"python": "3.13"}'
    assert seen["image"] == IMAGE and seen["limits"].timeout_s == 60 and seen["limits"].cpus == 1
    assert seen["files"] == {"main.py": b"print('hi')"} and seen["collect"] == [f"{OUTPUT_DIR}/*"]
    assert out.failure_reason is None
    # Regression: the environment manifest is copied before the program so failed runs record it too.
    assert seen["script"] == [f"mkdir -p {OUTPUT_DIR}", f"cp /opt/rp/environment.json {OUTPUT_DIR}/_environment.json",
                              "python main.py --seed 3"]


def test_failed_run_keeps_bounded_tails_and_a_combined_log(monkeypatch):
    full_err = b"Traceback (most recent call last):\n" + b"  File x\n" * 2000 + b"ValueError: bad seed\n"
    err_tail = StreamTail(text=full_err[-4000:].decode(), total_bytes=len(full_err), truncated=True)
    out_tail = StreamTail(text="loading data\n", total_bytes=13, truncated=False)
    res = SandboxResult(exit_code=1, timed_out=False, duration_s=0.4, stdout=out_tail, stderr=err_tail, image=IMAGE,
                        files={STDOUT_FILE: b"loading data\n", STDERR_FILE: full_err})
    install_fake_sandbox(monkeypatch, res)

    out = execute(plan(), IMAGE, b"raise ValueError('bad seed')", {})

    assert out.status == "failed" and out.exit_code == 1 and out.duration_s == 0.4 and out.image == IMAGE
    assert out.outputs == {} and out.environment is None
    assert out.stderr.truncated and len(out.stderr.text.encode()) <= 4000
    assert out.stderr.total_bytes == len(full_err) and out.stderr.text.endswith("ValueError: bad seed\n")
    assert out.stdout == out_tail
    assert out.log.startswith("loading data\n--- stderr ---\nTraceback") and out.log.endswith("ValueError: bad seed\n")
    assert len(out.log) <= LOG_MAX_CHARS
    assert out.failure_reason == "the program exited with code 1"


def test_timed_out_run_is_labelled_and_streams_are_empty(monkeypatch):
    res = SandboxResult(exit_code=124, timed_out=True, duration_s=60.0, image=IMAGE)
    install_fake_sandbox(monkeypatch, res)
    out = execute(plan(), IMAGE, b"while True: pass", {})
    assert out.status == "timed_out" and out.exit_code == 124 and out.duration_s == 60.0
    assert out.log == "" and out.stdout == StreamTail() and out.stderr == StreamTail()
    assert out.failure_reason == "the run exceeded its time limit of 60s"


def test_sandbox_unavailable_fails_closed_with_empty_streams(monkeypatch):
    install_fake_sandbox(monkeypatch, None)
    out = execute(plan(), IMAGE, b"", {})
    assert isinstance(out, RunOutput) and out.status == "sandbox_unavailable" and out.exit_code is None
    assert out.image == IMAGE and out.argv == ["python", "main.py", "--seed", "3"]
    assert out.stdout == StreamTail() and out.stderr == StreamTail()
    assert out.failure_reason == "container runtime is not available (fail closed): no runtime" == out.log
    assert out.duration_s is None and out.timed_out is False and out.streams_collected is False


def test_unreadable_outputs_after_exit_zero_fail_with_the_real_reason(monkeypatch):
    diag = "[sandbox] could not read outputs: sandbox output exceeds the size limit"
    res = SandboxResult(exit_code=0, timed_out=False, duration_s=12.0, image=IMAGE, files={},
                        output_error="sandbox output exceeds the size limit",
                        stderr=StreamTail(text=diag, total_bytes=len(diag), truncated=False))
    install_fake_sandbox(monkeypatch, res)
    out = execute(plan(), IMAGE, b"", {})
    assert out.status == "failed" and out.exit_code == 0 and out.outputs == {} and out.environment is None
    assert out.failure_reason == "the sandbox outputs could not be collected: sandbox output exceeds the size limit"
    assert out.log == "--- stderr ---\n" + diag, "runtime diagnostics reach the log when the stream files are missing"


def test_runtime_failure_before_the_program_ran_is_attributed_to_the_sandbox(monkeypatch):
    diag = "Unable to find image 'python-sci@sha256:abc' locally\n"
    res = SandboxResult(exit_code=125, timed_out=False, duration_s=0.2, image=IMAGE, files={},
                        stderr=StreamTail(text=diag, total_bytes=len(diag), truncated=False))
    install_fake_sandbox(monkeypatch, res)
    out = execute(plan(), IMAGE, b"", {})
    assert out.status == "failed" and out.exit_code == 125
    assert out.failure_reason == "the program exited with code 125"
    assert out.log == "--- stderr ---\n" + diag and out.stderr.text == diag


def test_timeout_diagnostic_reaches_the_log(monkeypatch):
    diag = "[sandbox] timed out after 60s; the container was killed and its output and files were not collected"
    res = SandboxResult(exit_code=124, timed_out=True, duration_s=60.0, image=IMAGE,
                        stderr=StreamTail(text=diag, total_bytes=len(diag), truncated=False))
    install_fake_sandbox(monkeypatch, res)
    out = execute(plan(), IMAGE, b"", {})
    assert out.status == "timed_out" and out.log == "--- stderr ---\n" + diag


def test_failed_program_still_records_the_environment(monkeypatch):
    res = SandboxResult(exit_code=2, timed_out=False, duration_s=1.0, image=IMAGE,
                        files={STDOUT_FILE: b"", STDERR_FILE: b"boom\n", f"{OUTPUT_DIR}/_environment.json": b"{}"})
    install_fake_sandbox(monkeypatch, res)
    out = execute(plan(), IMAGE, b"", {})
    assert out.status == "failed" and out.environment == b"{}" and out.outputs == {}
    assert out.log == "--- stderr ---\nboom\n" and out.failure_reason == "the program exited with code 2"


def test_execution_block_matches_the_compile_report_shape(monkeypatch):
    from rp_latex.sandbox import EXECUTION_FIELDS

    ok = SandboxResult(exit_code=0, timed_out=False, duration_s=2.5, image=IMAGE, argv=["docker", "run", IMAGE],
                       stdout=StreamTail(text="acc 0.75\n", total_bytes=9, truncated=False), streams_collected=True,
                       files={STDOUT_FILE: b"acc 0.75\n", STDERR_FILE: b"", f"{OUTPUT_DIR}/metrics.json": b"{}"})
    install_fake_sandbox(monkeypatch, ok)
    e = execute(plan(), IMAGE, b"", {}).execution().to_dict()
    assert set(e) == EXECUTION_FIELDS
    assert e == {"status": "succeeded", "exit_code": 0, "timed_out": False, "duration_s": 2.5, "image": IMAGE,
                 "argv": ["python", "main.py", "--seed", "3"],
                 "stdout": {"text": "acc 0.75\n", "total_bytes": 9, "truncated": False},
                 "stderr": {"text": "", "total_bytes": 0, "truncated": False}, "failure_reason": None,
                 "output_error": None, "streams_collected": True}

    timeout = SandboxResult(exit_code=124, timed_out=True, duration_s=60.0, image=IMAGE,
                            stderr=StreamTail(text="[sandbox] timed out after 60s", total_bytes=29, truncated=False))
    install_fake_sandbox(monkeypatch, timeout)
    e = execute(plan(), IMAGE, b"", {}).execution().to_dict()
    assert set(e) == EXECUTION_FIELDS and e["status"] == "timed_out" and e["timed_out"] is True and e["exit_code"] == 124
    assert e["failure_reason"] == "the run exceeded its time limit of 60s" and "timed out" in e["stderr"]["text"]

    unreadable = SandboxResult(exit_code=0, timed_out=False, duration_s=1.0, image=IMAGE, files={},
                               output_error="sandbox output exceeds the size limit")
    install_fake_sandbox(monkeypatch, unreadable)
    e = execute(plan(), IMAGE, b"", {}).execution().to_dict()
    assert e["status"] == "failed" and e["exit_code"] == 0 and e["output_error"] == "sandbox output exceeds the size limit"

    install_fake_sandbox(monkeypatch, None)
    e = execute(plan(), IMAGE, b"", {}).execution().to_dict()
    assert set(e) == EXECUTION_FIELDS and e["status"] == "sandbox_unavailable" and e["exit_code"] is None
    assert e["image"] == IMAGE and e["argv"] == ["python", "main.py", "--seed", "3"] and e["failure_reason"]


def test_corrupt_code_archive_is_a_failed_run_with_a_reason(monkeypatch):
    seen = install_fake_sandbox(monkeypatch, SandboxResult(exit_code=0, timed_out=False, duration_s=1.0))
    out = execute(plan(), IMAGE, b"PK\x03\x04not-really-a-zip", {})
    assert out.status == "failed" and out.exit_code is None and out.duration_s is None and out.outputs == {}
    assert out.failure_reason and out.failure_reason.startswith("the code archive could not be unpacked: ")
    assert out.log == out.failure_reason and "files" not in seen, "nothing was sent to the sandbox"
    e = out.execution().to_dict()
    assert e["status"] == "failed" and e["exit_code"] is None and e["image"] == IMAGE and e["argv"] == ["python", "main.py", "--seed", "3"]
    assert e["failure_reason"] == out.failure_reason and e["stdout"]["text"] == "" and e["stderr"]["text"] == ""
