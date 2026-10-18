"""Local Claude CLI provider: isolation flags, output parsing and the local-only rule (a fake CLI stands in)."""

from __future__ import annotations

import json
import stat

import pytest

from rp_research import config
from rp_research.gateway.providers import ClaudeCliProvider, ProviderError

FAKE = """#!/usr/bin/env python3
import json, os, sys
rec = {"argv": sys.argv[1:], "cwd": os.getcwd(), "cwd_files": os.listdir("."), "stdin": sys.stdin.read(),
       "has_api_key": "ANTHROPIC_API_KEY" in os.environ}
open(os.environ["FAKE_RECORD"], "w").write(json.dumps(rec))
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "ok":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "{}",
                      "structured_output": {"answer": 2}, "usage": {"input_tokens": 3, "cache_creation_input_tokens": 10,
                      "output_tokens": 5}, "modelUsage": {"claude-opus-5-5": {}}, "stop_reason": "end_turn"}))
elif mode == "error":
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "usage limit reached"}))
else:
    sys.stderr.write("Not logged in. Please run /login\\n"); sys.exit(1)
"""


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    exe = tmp_path / "claude"
    exe.write_text(FAKE)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("RP_WORKER_ENVIRONMENT", "local")
    monkeypatch.setenv("RP_WORKER_CLAUDE_CLI_PATH", str(exe))
    monkeypatch.setenv("FAKE_RECORD", str(tmp_path / "record.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-used")
    config.get_worker_settings.cache_clear()
    yield tmp_path
    config.get_worker_settings.cache_clear()


SCHEMA = {"type": "object", "properties": {"answer": {"type": "integer"}}, "required": ["answer"], "additionalProperties": False}


async def test_runs_isolated_and_returns_structured_output(fake_cli):
    p = ClaudeCliProvider()
    resp = await p.complete(system="SYS", messages=[{"role": "user", "content": "What is 1+1?"}], schema=SCHEMA,
                            max_tokens=100, agent="t", fixture_key=None)
    assert json.loads(resp.text) == {"answer": 2} and resp.model == "claude-opus-5-5"
    assert resp.input_tokens == 13 and resp.output_tokens == 5
    rec = json.loads((fake_cli / "record.json").read_text())
    a = rec["argv"]
    assert a[a.index("--tools") + 1] == "" and "--strict-mcp-config" in a and "--no-session-persistence" in a
    assert a[a.index("--setting-sources") + 1] == "" and a[a.index("--system-prompt") + 1] == "SYS"
    assert json.loads(a[a.index("--json-schema") + 1]) == SCHEMA and "--bare" not in a
    assert rec["cwd_files"] == [] and "rp-claude-cli-" in rec["cwd"], "runs in an empty directory (no project memory)"
    assert rec["stdin"] == "What is 1+1?" and rec["has_api_key"] is False, "uses the CLI login, not an API key"


async def test_errors_map_to_provider_errors(fake_cli, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "error")
    with pytest.raises(ProviderError) as e:
        await ClaudeCliProvider().complete(system="S", messages=[{"role": "user", "content": "x"}], schema=SCHEMA,
                                           max_tokens=10, agent="t", fixture_key=None)
    assert e.value.code == "provider_rate_limited"
    monkeypatch.setenv("FAKE_MODE", "auth")
    with pytest.raises(ProviderError) as e:
        await ClaudeCliProvider().complete(system="S", messages=[{"role": "user", "content": "x"}], schema=SCHEMA,
                                           max_tokens=10, agent="t", fixture_key=None)
    assert e.value.code == "provider_auth_failed"


def test_refused_outside_local(fake_cli, monkeypatch):
    for env in ("test", "staging", "production"):
        monkeypatch.setenv("RP_WORKER_ENVIRONMENT", env)
        config.get_worker_settings.cache_clear()
        with pytest.raises(ProviderError, match="local-only"):
            ClaudeCliProvider()


def test_project_choice_selects_provider(fake_cli, monkeypatch):
    from rp_research.gateway.providers import AnthropicProvider, FixtureProvider, get_provider

    assert isinstance(get_provider({"provider": "claude_cli"}), ClaudeCliProvider)
    p = get_provider({"provider": "anthropic", "api_key": "sk-ant-test-" + "x" * 32})
    assert isinstance(p, AnthropicProvider) and p.client.api_key.endswith("xxxx")
    with pytest.raises(ProviderError, match="not connected"):
        get_provider({"provider": "anthropic", "error": "the project owner's Anthropic key is not connected"})
    monkeypatch.setenv("RP_WORKER_MODEL_PROVIDER", "fixture")
    config.get_worker_settings.cache_clear()
    assert isinstance(get_provider({"provider": None}), FixtureProvider), "no choice -> worker default"
