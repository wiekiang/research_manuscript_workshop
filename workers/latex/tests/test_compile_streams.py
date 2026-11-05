"""The compile report carries the sandbox's stdout/stderr tails alongside the existing run details."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from rp_contracts.latexdoc import RenderOptions
from rp_latex.adapters import sample_document
from rp_latex.compile import compile_document, sample_figure_pdf
from rp_latex.sandbox import Limits, SandboxResult, SandboxUnavailable, StreamTail

IMAGE = "rp-latex-sandbox:test"
SHAPE = {"text", "total_bytes", "truncated"}


class FakeSandbox:
    def __init__(self, result: SandboxResult | None):
        self.result = result
        self.calls = 0

    def run(self, files, script, collect, env=None, name=None):
        self.calls += 1
        if self.result is None:
            raise SandboxUnavailable("the 'docker' CLI is not on PATH")
        return self.result


def compile_with(box):
    return compile_document(family="acmart", template_files={}, protected={}, requires_generation=False,
                            generation_inputs=[], bib_style="ACM-Reference-Format", doc=sample_document(),
                            opts=RenderOptions(), figures={}, sandbox=box)


def test_successful_compile_reports_stream_tails_and_run_details():
    out_tail = StreamTail(text="Latexmk: All targets (main.pdf) are up-to-date\n", total_bytes=48, truncated=False)
    err_tail = StreamTail(text="", total_bytes=0, truncated=False)
    res = SandboxResult(exit_code=0, timed_out=False, duration_s=4.2, stdout=out_tail, stderr=err_tail, image=IMAGE,
                        argv=["docker", "run", IMAGE, "sh", "-c", "<fixed script>"],
                        files={"main.pdf": sample_figure_pdf(), "_latexmk.rc": b"0\n",
                               "main.log": b"Output written on main.pdf (1 page).\n"})
    out = compile_with(FakeSandbox(res))
    r = out.report
    assert r.status == "compiled" and r.exit_code == 0 and not r.timed_out
    assert r.duration_s == 4.2 and r.image == IMAGE and r.pages == 1
    assert r.stdout == out_tail and r.stderr == err_tail
    d = r.to_dict()
    assert set(d["stdout"]) == SHAPE == set(d["stderr"]), "both streams serialize with the same field shape"
    assert d["stdout"] == asdict(out_tail) and d["stderr"]["total_bytes"] == 0


def test_failed_compile_keeps_bounded_stream_tails():
    err_text = ("x" * 3980) + "\n! LaTeX Error: File `acmart.cls' not found.\n"
    err_tail = StreamTail(text=err_text[-4000:], total_bytes=25_000, truncated=True)
    out_tail = StreamTail(text="Latexmk: Errors, so I did not complete making targets\n", total_bytes=12_000, truncated=True)
    res = SandboxResult(exit_code=12, timed_out=False, duration_s=1.5, stdout=out_tail, stderr=err_tail, image=IMAGE,
                        files={"_latexmk.rc": b"12\n", "main.log": b"! LaTeX Error: File `acmart.cls' not found.\n"})
    r = compile_with(FakeSandbox(res)).report
    assert r.status == "failed" and r.exit_code == 12 and r.duration_s == 1.5 and r.image == IMAGE
    assert r.check("compile.success").status == "failed"
    assert r.stderr.truncated and len(r.stderr.text.encode()) <= 4000 and r.stderr.total_bytes == 25_000
    assert r.stderr.text.endswith("File `acmart.cls' not found.\n")
    assert r.stdout.truncated and r.stdout.total_bytes == 12_000
    assert r.to_dict()["stderr"]["truncated"] is True


def test_sandbox_unavailable_leaves_empty_stream_tails():
    r = compile_with(FakeSandbox(None)).report
    assert r.status == "sandbox_unavailable" and r.exit_code is None and r.image is None
    assert r.stdout == StreamTail() and r.stderr == StreamTail()
    assert set(r.to_dict()["stdout"]) == SHAPE


def test_runtime_failure_before_latexmk_reports_the_sandbox_exit_code_and_diagnostic():
    err = StreamTail(text="Unable to find image 'rp-latex-sandbox:test' locally\ndocker: pull access denied\n",
                     total_bytes=80, truncated=False)
    res = SandboxResult(exit_code=125, timed_out=False, duration_s=0.3, stderr=err, image=IMAGE, files={})
    r = compile_with(FakeSandbox(res)).report
    assert r.status == "failed" and r.exit_code == 125, "no fabricated latexmk exit code when latexmk never ran"
    assert r.errors == ["the sandbox exited with code 125 before latexmk reported a result: "
                        "Unable to find image 'rp-latex-sandbox:test' locally | docker: pull access denied"]
    c = r.check("compile.success")
    assert c.status == "failed" and c.detail == "the sandbox failed before compilation ran"
    assert c.evidence["errors"] == r.errors and r.stderr == err


def test_unreadable_outputs_after_a_clean_exit_are_a_failure_with_a_reason():
    res = SandboxResult(exit_code=0, timed_out=False, duration_s=9.0, image=IMAGE, files={},
                        output_error="sandbox output exceeds the size limit",
                        stderr=StreamTail(text="[sandbox] could not read outputs: sandbox output exceeds the size limit",
                                          total_bytes=70, truncated=False))
    r = compile_with(FakeSandbox(res)).report
    assert r.status == "failed" and r.exit_code == 0 and r.duration_s == 9.0
    assert r.errors == ["sandbox outputs could not be read: sandbox output exceeds the size limit"]
    assert r.check("compile.success").detail == "sandbox outputs could not be read"
    assert r.to_dict()["errors"] == r.errors


class LimitedSandbox(FakeSandbox):
    def __init__(self, result):
        super().__init__(result)
        self.limits = Limits(timeout_s=300)


def test_timeout_without_main_log_keeps_the_stream_tails_as_log_and_excerpt():
    out_tail = StreamTail(text="Latexmk: applying rule 'pdflatex'...\nRunning 'pdflatex main.tex'\n", total_bytes=66, truncated=False)
    err_tail = StreamTail(text="\n[sandbox] timed out after 300s; the container was killed and its output and files were "
                               "not collected", total_bytes=110, truncated=False)
    res = SandboxResult(exit_code=124, timed_out=True, duration_s=300.0, image=IMAGE, files={}, stdout=out_tail, stderr=err_tail)
    out = compile_with(LimitedSandbox(res))
    r = out.report
    assert r.status == "failed" and r.timed_out and r.exit_code == 124 and r.pages is None
    assert r.check("compile.success").detail == "timed out"
    assert r.errors == ["compilation timed out after 300s; the container was killed before main.log could be collected "
                        "(last output: Running 'pdflatex main.tex')"]
    assert r.failure_reason == r.errors[0]
    assert r.check("compile.success").evidence["errors"] == r.errors
    # Regression: the excerpt and the published log used to be empty strings because main.log never came back.
    assert r.log_excerpt.startswith("main.log was not collected: the compile timed out")
    assert "--- sandbox stdout tail ---\nLatexmk: applying rule 'pdflatex'...\nRunning 'pdflatex main.tex'" in r.log_excerpt
    assert "--- sandbox stderr tail ---\n[sandbox] timed out after 300s" in r.log_excerpt
    assert out.log and out.log.splitlines()[-60:] == r.log_excerpt.splitlines(), "the compile_log artifact gets the same text"
    assert r.to_dict()["log_excerpt"] == r.log_excerpt and r.to_dict()["execution"]["failure_reason"] == r.errors[0]


def test_timeout_with_silent_streams_still_explains_itself():
    res = SandboxResult(exit_code=124, timed_out=True, duration_s=60.0, image=IMAGE, files={})
    out = compile_with(FakeSandbox(res))
    assert out.report.errors == ["compilation timed out; the container was killed before main.log could be collected"]
    assert out.report.log_excerpt == "main.log was not collected: the compile timed out and the container was killed."
    assert out.log == out.report.log_excerpt + "\n"


def test_runtime_failure_without_main_log_uses_stderr_for_the_excerpt_and_marks_truncation():
    err = StreamTail(text="x" * 20 + "\ndocker: Error response from daemon: OCI runtime create failed\n",
                     total_bytes=9000, truncated=True)
    res = SandboxResult(exit_code=125, timed_out=False, duration_s=0.2, image=IMAGE, files={}, stderr=err)
    r = compile_with(FakeSandbox(res)).report
    assert r.exit_code == 125 and r.errors[0].startswith("the sandbox exited with code 125 before latexmk reported a result: ")
    assert r.log_excerpt.startswith("main.log was not produced and the sandbox printed nothing") is False
    assert r.log_excerpt.startswith(f"--- sandbox stderr tail (last {len(err.text.encode())} of 9000 bytes) ---")
    assert r.log_excerpt.endswith("OCI runtime create failed")


def test_unreadable_outputs_excerpt_names_the_archive_problem():
    res = SandboxResult(exit_code=0, timed_out=False, duration_s=1.0, image=IMAGE, files={},
                        output_error="sandbox output exceeds the size limit",
                        stderr=StreamTail(text="[sandbox] could not read outputs: sandbox output exceeds the size limit",
                                          total_bytes=70, truncated=False))
    r = compile_with(FakeSandbox(res)).report
    assert r.log_excerpt.startswith("main.log was not collected: sandbox output exceeds the size limit.")
    assert "--- sandbox stderr tail ---" in r.log_excerpt


def test_normal_failure_excerpt_is_still_the_main_log_tail():
    main_log = b"This is pdfTeX\n" + b"".join(f"line {i}\n".encode() for i in range(100)) + b"! Undefined control sequence.\nl.5 \\foo\n"
    res = SandboxResult(exit_code=0, timed_out=False, duration_s=3.0, image=IMAGE,
                        files={"_latexmk.rc": b"12\n", "main.log": main_log},
                        stderr=StreamTail(text="Latexmk: Errors, so I did not complete making targets\n", total_bytes=55, truncated=False))
    out = compile_with(FakeSandbox(res))
    r = out.report
    assert r.status == "failed" and r.exit_code == 12 and r.errors == ["! Undefined control sequence."]
    assert r.failure_reason == "compilation failed: ! Undefined control sequence."
    lines = r.log_excerpt.splitlines()
    assert len(lines) == 60 and lines[-2:] == ["! Undefined control sequence.", "l.5 \\foo"] and lines[0] == "line 42"
    assert "sandbox" not in r.log_excerpt, "when main.log exists the excerpt is the TeX log, not the stream tails"
    assert out.log == main_log.decode()
    assert r.stderr.text.startswith("Latexmk: Errors"), "the stderr tail is still available separately"


def test_latexmk_exit_code_wins_when_it_reported():
    res = SandboxResult(exit_code=0, timed_out=False, duration_s=3.0, image=IMAGE,
                        files={"_latexmk.rc": b"12\n", "main.log": b"! Emergency stop.\n"})
    r = compile_with(FakeSandbox(res)).report
    assert r.exit_code == 12 and r.status == "failed" and r.check("compile.success").detail == "compilation failed"
    assert r.errors == ["! Emergency stop."]
    garbage = SandboxResult(exit_code=0, timed_out=False, duration_s=3.0, image=IMAGE, files={"_latexmk.rc": b"??"})
    assert compile_with(FakeSandbox(garbage)).report.exit_code == 1


def test_execution_block_is_serialized_for_success_and_failure():
    from rp_latex.sandbox import EXECUTION_FIELDS

    ok = SandboxResult(exit_code=0, timed_out=False, duration_s=4.2, image=IMAGE,
                       argv=["docker", "run", IMAGE, "sh", "-c", "<fixed script>"],
                       stdout=StreamTail(text="done\n", total_bytes=5, truncated=False), streams_collected=True,
                       files={"main.pdf": sample_figure_pdf(), "_latexmk.rc": b"0\n", "main.log": b""})
    d = compile_with(FakeSandbox(ok)).report.to_dict()
    assert set(d["execution"]) == EXECUTION_FIELDS
    assert d["execution"] == {"status": "compiled", "exit_code": 0, "timed_out": False, "duration_s": 4.2, "image": IMAGE,
                              "argv": ["docker", "run", IMAGE, "sh", "-c", "<fixed script>"],
                              "stdout": {"text": "done\n", "total_bytes": 5, "truncated": False},
                              "stderr": {"text": "", "total_bytes": 0, "truncated": False},
                              "failure_reason": None, "output_error": None, "streams_collected": True}

    bad = SandboxResult(exit_code=0, timed_out=False, duration_s=1.0, image=IMAGE, argv=["docker", "run"],
                        files={"_latexmk.rc": b"12\n", "main.log": b"! Emergency stop.\n"},
                        stderr=StreamTail(text="x" * 10, total_bytes=50, truncated=True))
    d = compile_with(FakeSandbox(bad)).report.to_dict()
    assert set(d["execution"]) == EXECUTION_FIELDS
    assert d["execution"]["status"] == "failed" and d["execution"]["exit_code"] == 12
    assert d["execution"]["failure_reason"] == "compilation failed: ! Emergency stop."
    assert d["execution"]["stderr"] == {"text": "x" * 10, "total_bytes": 50, "truncated": True}
    assert d["failure_reason"] == d["execution"]["failure_reason"] and d["argv"] == ["docker", "run"]

    for res, reason in ((None, "container runtime is not available (fail closed): the 'docker' CLI is not on PATH"),):
        d = compile_with(FakeSandbox(res)).report.to_dict()
        e = d["execution"]
        assert set(e) == EXECUTION_FIELDS and e["status"] == "sandbox_unavailable" and e["exit_code"] is None
        assert e["failure_reason"] == reason and e["argv"] == [] and e["image"] is None  # FakeSandbox has no image


def test_unsupported_template_has_a_failure_reason_in_its_execution_block():
    out = compile_document(family="nope", template_files={}, protected={}, requires_generation=False, generation_inputs=[],
                           bib_style="plain", doc=sample_document(), opts=RenderOptions(), figures={}, sandbox=FakeSandbox(None))
    e = out.report.to_dict()["execution"]
    assert e["status"] == "unsupported" and "no adapter" in e["failure_reason"] and e["exit_code"] is None


class UnavailableSandbox(FakeSandbox):
    image = "rp-latex-sandbox:1"

    def __init__(self, cause):
        super().__init__(None)
        self.cause = cause

    def run(self, files, script, collect, env=None, name=None):
        raise SandboxUnavailable(self.cause)


@pytest.mark.parametrize("cause", ["the 'docker' CLI is not on PATH",
                                   "`docker info` exited 1: Cannot connect to the Docker daemon. Is the docker daemon running?",
                                   "`docker info` did not answer within 15s"])
def test_unavailable_runtime_report_keeps_the_probe_diagnosis(cause):
    out = compile_with(UnavailableSandbox(cause))
    r = out.report
    msg = f"container runtime is not available (fail closed): {cause}"
    assert r.status == "sandbox_unavailable" and r.failure_reason == msg and r.errors == [msg]
    assert r.check("compile.success").status == "not_performed" and r.check("compile.success").detail == msg
    # Nothing ran: no exit code is invented, no duration, no argv, empty tails; the image is still recorded.
    e = r.to_dict()["execution"]
    assert e["exit_code"] is None and e["timed_out"] is False and e["duration_s"] is None and e["streams_collected"] is False
    assert e["image"] == "rp-latex-sandbox:1" and e["argv"] == [] and e["output_error"] is None
    assert e["stdout"] == {"text": "", "total_bytes": 0, "truncated": False} == e["stderr"]
    # The diagnosis is also the log, so a compile_log artifact is published instead of nothing.
    assert out.log == msg and r.log_excerpt == msg and out.pdf is None


def test_unavailable_runtime_block_matches_the_experiment_runner():
    from rp_contracts.experiments import ExperimentPlanIn
    from rp_experiment import runner as exp_runner

    cause = "`docker info` exited 1: Cannot connect to the Docker daemon"
    compile_block = compile_with(UnavailableSandbox(cause)).report.execution().to_dict()

    class Fake:
        def __init__(self, image, binary="docker", limits=None, uid=10001):
            pass

        def run(self, *a, **k):
            raise SandboxUnavailable(cause)

    plan = ExperimentPlanIn.model_validate({"title": "toy study", "code_artifact_id": "c", "entrypoint": ["python", "main.py"],
                                            "image": "python-sci:1", "seed": 3, "run_type": "confirmatory",
                                            "metrics": [{"name": "accuracy"}], "data_origin": "public data",
                                            "data_rights": "CC-BY", "limitations": "small"})
    orig = exp_runner.DockerSandbox
    exp_runner.DockerSandbox = Fake
    try:
        run_block = exp_runner.execute(plan, "python-sci@sha256:abc", b"x", {}).execution().to_dict()
    finally:
        exp_runner.DockerSandbox = orig
    # Only the fields that legitimately differ: the image each was asked to use and what "argv" means per worker
    # (compile: redacted docker argv, none before a run; experiment: the planned program argv).
    for b in (compile_block, run_block):
        b.pop("image"), b.pop("argv")
    assert compile_block == run_block
