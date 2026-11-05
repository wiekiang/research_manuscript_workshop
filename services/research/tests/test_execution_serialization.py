"""Sandbox execution details survive the research service: the run manifest and compile report artifacts and the
internal status/compile-run posts all carry the same `execution` block for successful and failed runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rp_latex.compile import CompileOutput, CompileReport
from rp_latex.sandbox import EXECUTION_FIELDS, StreamTail
from rp_research.features import experiments as exp_mod
from rp_research.features import templates as tpl_mod

ACM = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "templates" / "acmart.zip"
IMAGE = "python-sci@sha256:" + "b" * 64
CODE = b"print('hi')\n"
SPEC = {"title": "toy study", "code_artifact_id": "code-1", "code_path": "main.py",
        "entrypoint": ["python", "main.py", "--seed", "{seed}"], "image": "python-sci:1", "seed": 7,
        "run_type": "confirmatory", "metrics": [{"name": "accuracy"}], "data_origin": "public", "data_rights": "CC-BY",
        "limitations": "small", "limits": {"cpus": 1, "memory_mb": 512, "timeout_s": 60}}


class FakeApi:
    """Records every publish and post; answers the reads each activity performs."""

    def __init__(self, reads: dict, artifacts: dict[str, bytes]):
        self.reads, self.artifacts = reads, artifacts
        self.published: list[tuple[str, object]] = []
        self.posts: list[tuple[str, dict]] = []
        self.n = 0

    def __call__(self, task_id):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, path, **params):
        return self.reads[path]

    async def read_artifact(self, artifact_id):
        return self.artifacts[artifact_id]

    read_artifact_bytes = read_artifact

    async def publish(self, project_id, kind, data, media_type, imh, **kw):
        self.n += 1
        self.published.append((kind, data))
        return SimpleNamespace(artifact_id=f"art-{kind}-{self.n}")

    async def publish_json(self, project_id, kind, obj, imh, **kw):
        self.n += 1
        self.published.append((kind, json.loads(json.dumps(obj))))
        return SimpleNamespace(artifact_id=f"art-{kind}-{self.n}")

    async def post(self, path, body):
        self.posts.append((path, json.loads(json.dumps(body))))
        return {"id": "run-1", "status": body.get("status")}

    async def record_usage(self, **body):
        return {}

    def published_json(self, kind):
        return next(obj for k, obj in self.published if k == kind)

    def posted(self, suffix):
        """The last post to a path (the run is first marked running, then given its terminal status)."""
        return [body for path, body in self.posts if path.endswith(suffix)][-1]


def run_output(status, **over):
    from rp_experiment.runner import RunOutput

    base = {"status": status, "exit_code": 0, "duration_s": 2.5, "log": "acc 0.75\n", "argv": ["python", "main.py", "--seed", "7"],
            "image": IMAGE, "stdout": StreamTail(text="acc 0.75\n", total_bytes=9, truncated=False),
            "outputs": {"out/metrics.json": b'{"accuracy": 0.75}'}, "environment": b'{"packages": ["numpy==2.3.3"]}',
            "streams_collected": True}
    base.update(over)
    return RunOutput(**base)


def experiment_api():
    state = {"status": "running", "plan_status": "approved", "spec": SPEC, "code_hash": hashlib.sha256(CODE).hexdigest(),
             "input_hashes": {}, "image_ref": IMAGE, "plan_id": "plan-1", "synthetic": False, "protocol": {"version": 1},
             "plan_artifact_id": "art-plan", "rerun_of": None}
    return FakeApi({"/v1/internal/experiment-runs/run-1": state}, {"code-1": CODE})


@pytest.mark.parametrize("case", ["succeeded", "failed", "timed_out", "exit_zero_unreadable", "sandbox_unavailable",
                                  "runtime_never_started"])
async def test_experiment_run_manifest_and_status_carry_the_execution_block(monkeypatch, case):
    outputs = {
        "succeeded": run_output("succeeded"),
        "sandbox_unavailable": run_output("sandbox_unavailable", exit_code=None, duration_s=None, outputs={}, environment=None,
                                          streams_collected=False, stdout=StreamTail(),
                                          log="container runtime is not available (fail closed): the 'docker' CLI is not on PATH",
                                          failure_reason="container runtime is not available (fail closed): the 'docker' CLI is not on PATH"),
        "runtime_never_started": run_output("failed", exit_code=125, outputs={}, environment=None, stdout=StreamTail(), streams_collected=False,
                                            log="--- stderr ---\nUnable to find image\n",
                                            failure_reason="the program exited with code 125",
                                            stderr=StreamTail(text="Unable to find image\n", total_bytes=21, truncated=False)),
        "failed": run_output("failed", exit_code=1, outputs={}, failure_reason="the program exited with code 1",
                             stderr=StreamTail(text="Traceback\nValueError\n", total_bytes=9000, truncated=True)),
        "timed_out": run_output("timed_out", exit_code=124, timed_out=True, duration_s=60.0, outputs={}, environment=None, streams_collected=False,
                                failure_reason="the run exceeded its time limit of 60s",
                                stderr=StreamTail(text="[sandbox] timed out after 60s", total_bytes=29, truncated=False)),
        "exit_zero_unreadable": run_output("failed", exit_code=0, outputs={}, environment=None, streams_collected=False,
                                           output_error="sandbox output exceeds the size limit",
                                           failure_reason="the sandbox outputs could not be collected: sandbox output exceeds the size limit"),
    }
    out = outputs[case]
    api = experiment_api()
    monkeypatch.setattr(exp_mod, "ApiClient", api)
    monkeypatch.setattr(exp_mod, "execute", lambda plan, image_ref, code, inputs: out)

    result = await exp_mod.experiment_execute("task-1", "proj-1", "run-1")

    expected = out.execution().to_dict()
    assert set(expected) == EXECUTION_FIELDS
    manifest = api.published_json("run_manifest")
    status_post = api.posted("/experiment-runs/run-1/status")
    assert manifest["execution"] == expected, "the manifest keeps the sandbox's full execution details"
    assert status_post["execution"] == expected, "the API record receives the identical block"
    # Pre-existing top-level details stay consistent with the block.
    assert (manifest["exit_code"], manifest["duration_s"], manifest["argv"], manifest["image_ref"]) == \
        (expected["exit_code"], expected["duration_s"], expected["argv"], expected["image"])
    assert (status_post["exit_code"], status_post["duration_s"]) == (expected["exit_code"], expected["duration_s"])
    assert result["status"] == manifest["status"] == status_post["status"] == out.status
    assert manifest["failure_reason"] == status_post["failure_reason"] == out.failure_reason
    if out.status == "succeeded":
        assert status_post["reported_metrics"] == {"accuracy": 0.75} and expected["failure_reason"] is None
    else:
        assert status_post["reported_metrics"] is None and expected["failure_reason"]
    # Every caller-visible execution detail is present and non-null where the sandbox had one.
    assert expected["stdout"]["text"] == out.stdout.text and expected["stderr"]["text"] == out.stderr.text
    assert expected["image"] == IMAGE and expected["timed_out"] == out.timed_out and expected["output_error"] == out.output_error
    # The log artifact is always published, even when the sandbox never ran.
    kinds = [k for k, _ in api.published]
    assert kinds.count("experiment_log") == 1 and ("experiment_raw_output" in kinds) == bool(out.outputs)
    log_bytes = next(d for k, d in api.published if k == "experiment_log")
    assert log_bytes == out.log.encode()


async def test_runner_exception_marks_the_run_failed_with_a_diagnosis_then_propagates(monkeypatch):
    api = experiment_api()
    monkeypatch.setattr(exp_mod, "ApiClient", api)

    def boom(plan, image_ref, code, inputs):
        raise RuntimeError("docker: OSError while spawning")

    monkeypatch.setattr(exp_mod, "execute", boom)
    with pytest.raises(RuntimeError, match="OSError while spawning"):
        await exp_mod.experiment_execute("task-1", "proj-1", "run-1")

    statuses = [b["status"] for p, b in api.posts if p.endswith("/status")]
    assert statuses == ["running", "failed"], "the run never stays in `running` after a worker exception"
    post = api.posted("/status")
    reason = "the worker could not execute the run: RuntimeError: docker: OSError while spawning"
    assert post["failure_reason"] == reason and post["exit_code"] is None and post["duration_s"] is None
    e = post["execution"]
    assert set(e) == EXECUTION_FIELDS and e["status"] == "failed" and e["failure_reason"] == reason
    assert e["image"] == IMAGE and e["argv"] == ["python", "main.py", "--seed", "7"] and e["exit_code"] is None
    assert post["log_artifact_id"] and next(d for k, d in api.published if k == "experiment_log") == reason.encode()
    assert not any(k == "run_manifest" for k, _ in api.published), "no manifest is fabricated for a run that never executed"


async def test_metrics_problem_is_the_run_reason_while_execution_keeps_the_sandbox_view(monkeypatch):
    out = run_output("succeeded", outputs={"out/other.txt": b"x"})
    api = experiment_api()
    monkeypatch.setattr(exp_mod, "ApiClient", api)
    monkeypatch.setattr(exp_mod, "execute", lambda plan, image_ref, code, inputs: out)
    await exp_mod.experiment_execute("task-1", "proj-1", "run-1")
    manifest, post = api.published_json("run_manifest"), api.posted("/status")
    assert manifest["status"] == post["status"] == "failed"
    assert manifest["failure_reason"] == post["failure_reason"] == "out/metrics.json was not produced"
    assert manifest["execution"]["status"] == "succeeded" and manifest["execution"]["failure_reason"] is None
    assert manifest["execution"]["exit_code"] == 0 == post["exit_code"]


def compile_report(status, **over):
    base = {"status": status, "family": "acmart", "options": {}, "exit_code": 0, "duration_s": 4.2, "image": "rp-latex-sandbox:1",
            "argv": ["docker", "run", "rp-latex-sandbox:1", "sh", "-c", "<fixed script>"], "pages": 3}
    base.update(over)
    return CompileReport(**base)


@pytest.mark.parametrize("status,over", [
    ("compiled", {}),
    ("failed", {"exit_code": 12, "pages": None, "errors": ["! Emergency stop."], "failure_reason": "compilation failed: ! Emergency stop.",
                "stderr": StreamTail(text="! Emergency stop.\n", total_bytes=7000, truncated=True)}),
    ("failed", {"exit_code": 124, "timed_out": True, "pages": None, "failure_reason": "timed out"}),
    ("sandbox_unavailable", {"exit_code": None, "duration_s": None, "image": None, "argv": [], "pages": None,
                             "failure_reason": "container runtime is not available"}),
])
async def test_sample_compile_report_and_compile_run_carry_the_execution_block(monkeypatch, status, over):
    report = compile_report(status, **over)
    api = FakeApi({"/v1/internal/projects/proj-1/templates/tpl-1": {"archive_artifact_id": "arch", "archive_hash": "a" * 64}},
                  {"arch": ACM.read_bytes()})
    monkeypatch.setattr(tpl_mod, "ApiClient", api)
    monkeypatch.setattr(tpl_mod, "default_sandbox", lambda image: None)
    monkeypatch.setattr(tpl_mod, "compile_document", lambda **kw: CompileOutput(report, b"%PDF" if status == "compiled" else None,
                                                                                "log", {"main.tex": b""}))

    result = await tpl_mod.template_sample_compile("task-1", "proj-1", "tpl-1", {"mode": "submission"})

    expected = report.execution().to_dict()
    assert set(expected) == EXECUTION_FIELDS
    artifact = api.published_json("compile_report")
    post = api.posted("/compile-runs")
    assert artifact["execution"] == expected and post["execution"] == expected
    assert artifact["exit_code"] == expected["exit_code"] and artifact["timed_out"] == expected["timed_out"]
    assert post["status"] == artifact["status"] == result["status"] == status
    assert post["errors"] == artifact["errors"][:20]
    assert (expected["failure_reason"] is None) == (status == "compiled")
