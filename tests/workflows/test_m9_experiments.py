"""M9 acceptance: an approved plan bound to the frozen protocol runs in the no-network sandbox with recorded code,
image, input hashes, seed, logs and environment; a separate validator recomputes the metrics from raw outputs; a
rerun reproduces within the preset tolerance and the promoted result is labelled 'reproduced'. Unapproved plans do
not run; failed runs, network attempts and runs whose reported metrics disagree with their raw outputs are visible
and can never become findings."""

from __future__ import annotations

import pytest
from test_m4_literature import providers  # noqa: F401
from test_m5_contribution import (  # noqa: F401
    contribute,
    frozen_protocol,
    h1,
    open_cfp,
    project_at_direction_review,
    select,
)
from test_m6_manuscript import run_all

from rp_latex.sandbox import docker_available

pytestmark = [pytest.mark.temporal, pytest.mark.docker,
              pytest.mark.skipif(not docker_available(), reason="container runtime unavailable")]

LABELS = b"pipeline,y_true\nA,1\nB,0\nC,1\nD,0\nE,1\nF,0\nG,1\nH,0\n"
HONEST = b'''import csv, json, os, random, sys
import numpy as np
seed = int(sys.argv[sys.argv.index("--seed") + 1])
random.seed(seed)
rows = list(csv.DictReader(open("data/labels.csv")))
flip = set(random.sample(range(len(rows)), 2))
preds = [(int(r["y_true"]), 1 - int(r["y_true"]) if i in flip else int(r["y_true"])) for i, r in enumerate(rows)]
os.makedirs("out", exist_ok=True)
with open("out/predictions.csv", "w") as f:
    f.write("y_true,y_pred\\n" + "".join(f"{t},{p}\\n" for t, p in preds))
acc = float(np.mean([t == p for t, p in preds]))
json.dump({"accuracy": acc}, open("out/metrics.json", "w"))
print("accuracy", acc, "numpy", np.__version__)
'''
LYING = HONEST.replace(b'json.dump({"accuracy": acc}', b'json.dump({"accuracy": 0.99}')
NETWORK = b'''import socket
socket.create_connection(("1.1.1.1", 443), timeout=3)
print("network reachable")
'''


def plan_body(code_id, data_id, **over):
    body = {"title": "Restoration classifier on eight pipelines", "code_artifact_id": code_id, "code_path": "main.py",
            "entrypoint": ["python", "main.py", "--seed", "{seed}"],
            "inputs": [{"artifact_id": data_id, "path": "data/labels.csv", "data_nature": "empirical"}],
            "image": "python-sci:1", "seed": 7, "limits": {"cpus": 1, "memory_mb": 512, "timeout_s": 60},
            "run_type": "confirmatory", "metrics": [{"name": "accuracy"}], "tolerance": 1e-9, "sample_size": 8,
            "data_origin": "eight public R pipelines", "data_rights": "public source code (MIT/GPL)",
            "limitations": "small exploratory sample"}
    body.update(over)
    return body


async def approved_plan(u, pid, code_id, data_id, decl, **over):
    r = await u.post(f"/v1/projects/{pid}/experiment-plans", json=plan_body(code_id, data_id, **over))
    assert r.status_code == 201, r.text
    plan = r.json()
    r = await u.post(f"/v1/experiment-plans/{plan['id']}/approve", json={"declaration_accepted": True, "declaration_text": decl})
    assert r.status_code == 200, r.text
    return plan


async def run(u, env, pid, plan_id, rerun_of=None):
    r = await u.post(f"/v1/experiment-plans/{plan_id}/runs", json={"rerun_of": rerun_of})
    assert r.status_code == 202, r.text
    await run_all(u, env, pid)
    exp = (await u.get(f"/v1/projects/{pid}/experiments")).json()
    return next(x for p in exp["items"] for x in p["runs"] if x["id"] == r.json()["run_id"])


async def test_sandboxed_runs_recomputation_and_reproduction(client, temporal_env, open_cfp):  # noqa: F811
    u, pid, opp = await project_at_direction_review(client, temporal_env)
    assert (await select(u, pid, "empirical_quantitative", opp)).status_code == 201
    assert (await h1(u, pid, opp)).status_code == 200
    await frozen_protocol(u, pid, temporal_env, review="model")
    code = await contribute(u, pid, "main.py", HONEST, ctype="code")
    data = await contribute(u, pid, "labels.csv", LABELS, ctype="dataset")
    decl = (await u.get(f"/v1/projects/{pid}/experiments")).json()["plan_declaration"]

    # Plans are validated: allowlisted image, platform-built argv without shell syntax, capped limits.
    r = await u.post(f"/v1/projects/{pid}/experiment-plans", json=plan_body(code["artifact_id"], data["artifact_id"],
                                                                            image="ubuntu:latest"))
    assert r.status_code == 422 and any("allowlist" in p for p in r.json()["error"]["details"]["problems"])
    r = await u.post(f"/v1/projects/{pid}/experiment-plans", json=plan_body(
        code["artifact_id"], data["artifact_id"], entrypoint=["python", "main.py", "; curl evil"]))
    assert r.status_code == 422
    r = await u.post(f"/v1/projects/{pid}/experiment-plans", json=plan_body(code["artifact_id"], data["artifact_id"]))
    draft = r.json()
    r = await u.post(f"/v1/experiment-plans/{draft['id']}/runs", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "plan_not_approved"
    r = await u.post(f"/v1/experiment-plans/{draft['id']}/approve", json={"declaration_accepted": True, "declaration_text": decl})
    assert r.status_code == 200 and r.json()["status"] == "approved"

    first = await run(u, temporal_env, pid, draft["id"])
    assert first["status"] == "succeeded", first
    assert first["reported_metrics"] == {"accuracy": 0.75}
    assert first["recomputation"]["status"] == "passed" and first["recomputation"]["validator"].startswith("rp-experiment-validator")
    assert first["run_manifest_artifact_id"] and first["log_artifact_id"] and first["raw_output_artifact_id"]
    second = await run(u, temporal_env, pid, draft["id"], rerun_of=first["id"])
    assert second["status"] == "succeeded" and second["reproduction"]["match"], second

    # The run manifest records image, argv, hashes, seed, environment, no network and a rerun command.
    url = (await u.get(f"/v1/artifacts/{first['run_manifest_artifact_id']}/download-url")).json()["url"]
    m = (await u.get(url)).json()
    assert m["network"] == "none" and m["seed"] == 7 and m["argv"] == ["python", "main.py", "--seed", "7"]
    assert m["image_ref"].startswith("sha256:") and m["code_hash"] == draft["code_hash"]
    assert "numpy==2.3.3" in m["environment"]["packages"] and "rerun" in m["rerun_command"].lower()

    r = await u.post(f"/v1/experiment-runs/{first['id']}/promote")
    assert r.status_code == 201 and r.json()["rerun_documented"], r.text
    await run_all(u, temporal_env, pid)
    res = next(x for x in (await u.get(f"/v1/projects/{pid}/results")).json()["items"] if x["result_key"] == r.json()["result_key"])
    assert res["assurance_level"] == "reproduced", res
    assert (await u.post(f"/v1/experiment-runs/{first['id']}/promote")).status_code == 409

    # Network access is impossible inside the sandbox; the failed run is visible and cannot become a finding.
    net = await contribute(u, pid, "net.py", NETWORK, ctype="code")
    p2 = await approved_plan(u, pid, net["artifact_id"], data["artifact_id"], decl, code_path="net.py",
                             entrypoint=["python", "net.py"], run_type="exploratory")
    failed = await run(u, temporal_env, pid, p2["id"])
    assert failed["status"] == "failed" and failed["exit_code"] != 0 and failed["failure_reason"], failed
    assert failed["recomputation"]["status"] == "not_performed" and failed["reported_metrics"] is None
    r = await u.post(f"/v1/experiment-runs/{failed['id']}/promote")
    assert r.status_code == 409 and r.json()["error"]["code"] == "run_not_succeeded"
    log_url = (await u.get(f"/v1/artifacts/{failed['log_artifact_id']}/download-url")).json()["url"]
    assert b"network reachable" not in (await u.get(log_url)).content

    # Reported metrics that disagree with the raw outputs fail independent recomputation.
    lie = await contribute(u, pid, "lie.py", LYING, ctype="code")
    p3 = await approved_plan(u, pid, lie["artifact_id"], data["artifact_id"], decl, code_path="lie.py",
                             entrypoint=["python", "lie.py", "--seed", "{seed}"])
    lied = await run(u, temporal_env, pid, p3["id"])
    assert lied["status"] == "succeeded" and lied["recomputation"]["status"] == "failed", lied
    r = await u.post(f"/v1/experiment-runs/{lied['id']}/promote")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_recomputed"
