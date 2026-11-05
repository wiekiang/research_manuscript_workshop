"""The diagnostic summary renders every execution detail for successful and failed records."""

from __future__ import annotations

import pytest

from rp_contracts.latexdoc import RenderOptions
from rp_latex.adapters import sample_document
from rp_latex.compile import compile_document, sample_figure_pdf
from rp_latex.diagnostics import NotASandboxRecord, execution_block, summarize
from rp_latex.sandbox import SandboxResult, StreamTail


class Box:
    def __init__(self, result):
        self.result = result

    def run(self, files, script, collect, env=None, name=None):
        return self.result


def compile_record(res) -> dict:
    return compile_document(family="acmart", template_files={}, protected={}, requires_generation=False,
                            generation_inputs=[], bib_style="ACM-Reference-Format", doc=sample_document(),
                            opts=RenderOptions(), figures={}, sandbox=Box(res)).report.to_dict()


def test_successful_compile_report_summary():
    res = SandboxResult(exit_code=0, timed_out=False, duration_s=4.2, image="rp-latex-sandbox:1",
                        argv=["docker", "run", "rp-latex-sandbox:1", "sh", "-c", "<fixed script>"],
                        stdout=StreamTail(text="done\n", total_bytes=5, truncated=False),
                        files={"main.pdf": sample_figure_pdf(), "_latexmk.rc": b"0\n",
                               "main.log": b"Output written on main.pdf (1 page).\n"})
    s = summarize(compile_record(res))
    assert s.splitlines()[0] == "compile report — status: compiled"
    assert "reason:    — (success)" in s
    assert "exit code: 0    timed out: no    duration: 4.20 s" in s
    assert "image:     rp-latex-sandbox:1" in s
    assert "argv:      docker run rp-latex-sandbox:1 sh -c <fixed script>" in s
    assert "stdout:    5 B (not truncated)" in s and "stderr:    0 B (not truncated)" in s
    assert "log from:  full main.log (last 60 lines in log_excerpt)" in s


def test_timed_out_compile_report_shows_tail_only_log_and_truncation():
    res = SandboxResult(exit_code=124, timed_out=True, duration_s=300.0, image="rp-latex-sandbox:1", files={},
                        stdout=StreamTail(text="Running 'pdflatex'\n", total_bytes=19, truncated=False),
                        stderr=StreamTail(text="x" * 4000, total_bytes=9000, truncated=True))
    s = summarize(compile_record(res))
    assert "status: failed" in s and "timed out: yes" in s and "exit code: 124" in s
    assert "stderr:    9000 B total, last 4000 B kept (truncated)" in s
    assert "log from:  stderr/stdout tails only (main.log was not collected)" in s


def test_run_output_summaries(monkeypatch):
    from dataclasses import asdict

    from rp_experiment.runner import RunOutput

    ok = RunOutput("succeeded", 0, 2.5, "acc 0.75\n--- stderr ---\nUserWarning\n",
                   outputs={"out/metrics.json": b"{}"}, argv=["python", "main.py", "--seed", "7"],
                   image="python-sci@sha256:abc", stdout=StreamTail(text="acc 0.75\n", total_bytes=9, truncated=False),
                   stderr=StreamTail(text="UserWarning\n", total_bytes=12, truncated=False), streams_collected=True)
    rec = {**asdict(ok), "execution": ok.execution().to_dict()}
    rec.pop("outputs")  # bytes are not JSON; the saved form carries hashes elsewhere
    s = summarize(rec)
    assert s.splitlines()[0] == "run output — status: succeeded"
    assert "log from:  full stream files" in s

    timed = RunOutput("timed_out", 124, 60.0, "--- stderr ---\n[sandbox] timed out after 60s", image="img",
                      argv=["python", "main.py"], failure_reason="the run exceeded its time limit of 60s",
                      timed_out=True, stderr=StreamTail(text="[sandbox] timed out after 60s", total_bytes=29, truncated=False))
    s = summarize({**asdict(timed), "outputs": {}, "execution": timed.execution().to_dict()})
    assert "reason:    the run exceeded its time limit of 60s" in s
    assert "log from:  stderr tail only (stream files were not collected)" in s

    msg = "container runtime is not available (fail closed): the 'docker' CLI is not on PATH"
    never = RunOutput("sandbox_unavailable", None, None, msg, image="img", argv=["python", "main.py"], failure_reason=msg)
    s = summarize({**asdict(never), "outputs": {}, "execution": never.execution().to_dict()})
    assert "exit code: —    timed out: no    duration: —" in s and f"reason:    {msg}" in s
    assert "log from:  none (the sandbox never ran)" in s

    unreadable = RunOutput("failed", 0, 1.0, "--- stderr ---\n[sandbox] could not read outputs", image="img",
                           argv=["python", "main.py"], output_error="sandbox output exceeds the size limit",
                           failure_reason="the sandbox outputs could not be collected: sandbox output exceeds the size limit",
                           stderr=StreamTail(text="[sandbox] could not read outputs", total_bytes=31, truncated=False))
    s = summarize({**asdict(unreadable), "outputs": {}, "execution": unreadable.execution().to_dict()})
    assert "outputs:   could not be read — sandbox output exceeds the size limit" in s
    assert "log from:  stderr tail only (stream files were not collected)" in s


def test_run_manifest_and_bare_block_are_recognized():
    exe = {"status": "failed", "exit_code": 1, "timed_out": False, "duration_s": 0.4, "image": "img",
           "argv": ["python", "main.py"], "stdout": {"text": "", "total_bytes": 0, "truncated": False},
           "stderr": {"text": "boom\n", "total_bytes": 5, "truncated": False},
           "failure_reason": "the program exited with code 1", "output_error": None}
    s = summarize({"run_id": "r1", "seed": 7, "execution": exe})
    assert s.splitlines()[0] == "run manifest — status: failed"
    assert "log from:  full stream files" in s, "a block without the field falls back to the old inference"
    # With streams_collected the manifest distinguishes a pre-program runtime failure (exit 125, no files).
    pre = {**exe, "exit_code": 125, "streams_collected": False}
    assert "log from:  stderr tail only (stream files were not collected)" in summarize({"run_id": "r1", "execution": pre})
    assert "log from:  full stream files" in summarize({"run_id": "r1", "execution": {**exe, "streams_collected": True}})
    assert summarize(exe).splitlines()[0] == "execution block — status: failed"
    assert execution_block({"execution": exe}) is exe
    with pytest.raises(NotASandboxRecord):
        summarize({"status": "failed"})
