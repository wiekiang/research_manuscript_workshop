"""M3 acceptance through the platform: a researcher-supplied official template with recorded origin is analysed
safely, compiles in the sandbox (standard, double-blind, Biber), protected files stay unchanged, and the template
mode is confirmed. An unsafe archive fails closed; an unsupported one is labelled not_submission_ready."""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import pytest
from conftest import drain_outbox, make_project, make_user
from temporalio.worker import Worker

from rp_contracts.tasks import QUEUE_FETCH, QUEUE_LATEX, QUEUE_RESEARCH
from rp_latex.sandbox import docker_available
from rp_research.registry import ACTIVITIES, WORKFLOWS, load_features

pytestmark = [pytest.mark.temporal, pytest.mark.docker,
              pytest.mark.skipif(not docker_available(), reason="container runtime unavailable")]
FIX = Path(__file__).resolve().parents[2] / "tests/fixtures/templates"
load_features()


def workers(env):
    return [Worker(env.client, task_queue=q, workflows=WORKFLOWS[q], activities=ACTIVITIES[q])
            for q in (QUEUE_RESEARCH, QUEUE_FETCH, QUEUE_LATEX)]


async def wait_task(u, env, pid, kind, timeout=240):
    ws = workers(env)
    async with ws[0], ws[1], ws[2]:
        await drain_outbox(env)
        for _ in range(timeout * 10):
            tasks = [t for t in (await u.get(f"/v1/projects/{pid}/tasks")).json()["items"] if t["kind"] == kind]
            if tasks and tasks[0]["state"] in ("succeeded", "failed_terminal"):
                return tasks[0]
            await asyncio.sleep(0.1)
    raise AssertionError(f"{kind} did not finish")


async def upload(u, pid, data: bytes, name="acmart.zip"):
    r = await u.post(f"/v1/projects/{pid}/templates/upload", files={"file": (name, data, "application/zip")},
                     data={"declared_origin_url": "https://mirrors.ctan.org/macros/latex/contrib/acmart.zip",
                           "origin_statement": "Official ACM consolidated template distribution (CTAN).",
                           "mode": "submission", "license_note": "LPPL 1.3c", "attest_official": "true"})
    assert r.status_code == 202, r.text
    return r.json()["template_id"]


async def test_official_template_validates_and_is_confirmed(client, temporal_env):
    u = await make_user(client)
    p = await make_project(u)
    tid = await upload(u, p["id"], (FIX / "acmart.zip").read_bytes())
    task = await wait_task(u, temporal_env, p["id"], "template_import")
    assert task["state"] == "succeeded", task
    tpl = next(t for t in (await u.get(f"/v1/projects/{p['id']}/templates")).json()["items"] if t["id"] == tid)
    assert tpl["family"] == "acmart" and tpl["status"] == "validated" and set(tpl["bib_modes"]) == {"bibtex", "biber"}
    assert any(f["protected"] and f["path"].endswith("acmart.dtx") for f in tpl["files"])
    runs = tpl["compile_runs"]
    assert len(runs) == 3 and all(r["status"] == "compiled" for r in runs), runs
    anon = next(r for r in runs if r["options"]["anonymous"])
    assert {c["id"]: c["status"] for c in anon["checks"]}["anonymization.no_identity_leak"] == "passed"
    assert all({c["id"]: c["status"] for c in r["checks"]}["template.protected_unchanged"] == "passed" for r in runs)
    assert tpl["cfp_consistency"]["status"] == "manual_check"
    r = await u.post(f"/v1/projects/{p['id']}/templates/{tid}/confirm", json={"declaration_accepted": True,
                                                                              "overleaf_export_allowed": True})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    usage = (await u.get(f"/v1/projects/{p['id']}/usage")).json()
    assert any(c["category"] == "tex_compile" for c in usage["by_category"])


async def test_unsafe_and_unsupported_templates(client, temporal_env):
    u = await make_user(client)
    p = await make_project(u)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../escape.sty", "x")
    bad = await upload(u, p["id"], buf.getvalue(), "evil.zip")
    await wait_task(u, temporal_env, p["id"], "template_import")
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as z:
        z.writestr("template.docx", "PK-not-latex")
    word = await upload(u, p["id"], buf2.getvalue(), "word.zip")
    for _ in range(3):
        items = {t["id"]: t for t in (await u.get(f"/v1/projects/{p['id']}/templates")).json()["items"]}
        if items[word]["status"] != "analyzing":
            break
        await wait_task(u, temporal_env, p["id"], "template_import")
    assert items[bad]["status"] == "rejected" and "traversal" in " ".join(items[bad]["unsupported_reasons"])
    assert items[word]["status"] == "unsupported" and items[word]["label"] == "not_submission_ready"
    r = await u.post(f"/v1/projects/{p['id']}/templates/{word}/confirm", json={"declaration_accepted": True})
    assert r.status_code == 422
