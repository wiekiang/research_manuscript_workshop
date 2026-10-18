"""Model providers behind the gateway.

* anthropic: Claude via the official SDK, structured outputs (`output_config.format`), adaptive thinking with an
  explicit effort, server-side refusal fallbacks, and an explicit refusal check.
* fixture:   deterministic recorded responses for automated tests and local demos. It never invents output; a
  missing recording is an error.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..config import get_worker_settings


class ProviderError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str | None = None


class Provider(Protocol):
    name: str
    model: str

    async def complete(self, *, system: str, messages: list[dict[str, Any]], schema: dict[str, Any], max_tokens: int,
                       agent: str, fixture_key: str | None) -> ProviderResponse: ...


def _dump_missing(agent: str, fixture_key: str, system: str, messages: list) -> None:
    """Dev/test aid: with RP_FIXTURE_MISSING_DIR set, capture an unrecorded request so a recording can be written."""
    dump = os.environ.get("RP_FIXTURE_MISSING_DIR")
    if dump:
        Path(dump, agent).mkdir(parents=True, exist_ok=True)
        Path(dump, agent, f"{fixture_key}.request.json").write_text(json.dumps(
            {"agent": agent, "fixture_key": fixture_key, "system": system, "messages": messages}, indent=1))


class FixtureProvider:
    name = "fixture"
    model = "fixture-recorded-1"

    def __init__(self, root: Path):
        self.root = root

    async def complete(self, *, system, messages, schema, max_tokens, agent, fixture_key) -> ProviderResponse:
        if not fixture_key:
            raise ProviderError("fixture_missing", f"no fixture key supplied for agent {agent}")
        path = self.root / agent / f"{fixture_key}.json"
        if not path.is_file() or not path.resolve().is_relative_to(self.root.resolve()):
            _dump_missing(agent, fixture_key, system, messages)
            raise ProviderError("fixture_missing", f"no recorded fixture response for {agent}/{fixture_key}")
        data = json.loads(path.read_text())
        # A repair turn may select an alternative recording (used to test the repair path).
        if len(messages) > 1 and "repair_output" in data:
            out = data["repair_output"]
        else:
            out = data["output"]
        text = out if isinstance(out, str) else json.dumps(out)
        return ProviderResponse(text=text, input_tokens=sum(len(str(m["content"])) for m in messages) // 4,
                                output_tokens=len(text) // 4, model=self.model, stop_reason="end_turn")


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        import anthropic

        s = get_worker_settings()
        key = api_key or (s.anthropic_api_key.get_secret_value() if s.anthropic_api_key else None)
        if key is None:
            raise ProviderError("provider_not_configured", "no Anthropic API key: connect one in account settings")
        self.model = s.anthropic_model
        self.effort = s.anthropic_effort
        self._anthropic = anthropic
        self.client = anthropic.AsyncAnthropic(api_key=key,
                                               timeout=s.model_timeout_seconds, max_retries=2)

    async def complete(self, *, system, messages, schema, max_tokens, agent, fixture_key) -> ProviderResponse:
        a = self._anthropic
        try:
            async with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                msg = await stream.get_final_message()
        except a.RateLimitError as exc:
            raise ProviderError("provider_rate_limited", str(exc), retryable=True) from exc
        except (a.AuthenticationError, a.PermissionDeniedError) as exc:
            raise ProviderError("provider_auth_failed", str(exc)) from exc
        except a.BadRequestError as exc:
            raise ProviderError("provider_bad_request", str(exc)) from exc
        except a.APIStatusError as exc:
            raise ProviderError("provider_error", str(exc), retryable=exc.status_code >= 500) from exc
        except a.APIConnectionError as exc:
            raise ProviderError("provider_unreachable", str(exc), retryable=True) from exc
        if msg.stop_reason == "refusal":
            category = getattr(getattr(msg, "stop_details", None), "category", None)
            raise ProviderError("model_refusal", f"the model declined this request (category: {category})")
        if msg.stop_reason == "max_tokens":
            raise ProviderError("model_output_truncated", "output hit the token ceiling before completing")
        text = next((b.text for b in msg.content if b.type == "text"), "")
        return ProviderResponse(text=text, input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens,
                                model=msg.model, stop_reason=msg.stop_reason)


class ClaudeCliProvider:
    """Personal, local-only provider: the operator's installed Claude CLI and its own login.

    Anthropic's Agent SDK documentation states that, unless previously approved, third-party developers may not
    offer claude.ai login or rate limits in their products and should use API keys. This provider therefore runs
    only with ``RP_WORKER_ENVIRONMENT=local`` on the operator's own machine (the API enforces the same rule), never
    for a deployment other people use. Each call runs ``claude -p`` with every tool disabled, no MCP servers, no
    settings or project memory (empty working directory), no saved session, the gateway's own system prompt and
    CLI-validated JSON schema output.
    """

    name = "claude_cli"

    def __init__(self):
        s = get_worker_settings()
        if s.environment != "local":
            raise ProviderError("provider_not_configured",
                                "the Claude CLI provider is personal and local-only; use an API key for deployments")
        if shutil.which(s.claude_cli_path) is None:
            raise ProviderError("provider_not_configured", f"Claude CLI not found ({s.claude_cli_path})")
        self.cli = s.claude_cli_path
        self.model = s.claude_cli_model or "account-default"
        self.timeout = s.model_timeout_seconds

    @staticmethod
    def _prompt(messages: list[dict[str, Any]]) -> str:
        if len(messages) == 1:
            return messages[0]["content"]
        parts = []
        for m in messages:
            label = "Your previous answer" if m["role"] == "assistant" else "Request"
            parts.append(f"## {label}\n{m['content']}")
        return "\n\n".join(parts)

    def argv(self, system: str, schema: dict[str, Any]) -> list[str]:
        args = [self.cli, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
                "--system-prompt", system, "--tools", "", "--strict-mcp-config", "--no-session-persistence",
                "--setting-sources", ""]
        if self.model != "account-default":
            args += ["--model", self.model]
        return args

    async def complete(self, *, system, messages, schema, max_tokens, agent, fixture_key) -> ProviderResponse:
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        with tempfile.TemporaryDirectory(prefix="rp-claude-cli-") as cwd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self.argv(system, schema), cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                out, err = await asyncio.wait_for(proc.communicate(self._prompt(messages).encode()), self.timeout)
            except TimeoutError as exc:
                proc.kill()
                raise ProviderError("provider_timeout", "the Claude CLI did not answer in time", retryable=True) from exc
            except OSError as exc:
                raise ProviderError("provider_not_configured", f"cannot start the Claude CLI: {exc}") from exc
        try:
            d = json.loads(out)
        except ValueError as exc:
            msg = (err or out).decode(errors="replace")[-500:]
            code = "provider_auth_failed" if "log" in msg.lower() and "in" in msg.lower() else "provider_error"
            raise ProviderError(code, f"Claude CLI failed (exit {proc.returncode}): {msg}") from exc
        if d.get("is_error") or d.get("subtype") != "success":
            text = str(d.get("result") or d.get("subtype"))[:500]
            code = "provider_rate_limited" if "limit" in text.lower() else "provider_error"
            raise ProviderError(code, f"Claude CLI reported an error: {text}", retryable=code == "provider_rate_limited")
        if d.get("structured_output") is None:
            raise ProviderError("model_output_truncated", "the Claude CLI returned no structured output")
        u = d.get("usage") or {}
        model = next(iter(d.get("modelUsage") or {}), self.model)
        return ProviderResponse(text=json.dumps(d["structured_output"]),
                                input_tokens=int(u.get("input_tokens", 0)) + int(u.get("cache_creation_input_tokens", 0))
                                + int(u.get("cache_read_input_tokens", 0)),
                                output_tokens=int(u.get("output_tokens", 0)), model=model, stop_reason=d.get("stop_reason"))


_override: Provider | None = None


def set_provider(provider: Provider | None) -> None:
    global _override
    _override = provider


def get_provider(choice: dict[str, Any] | None = None) -> Provider:
    """The project's chosen provider (from the API) or, when the project has no choice, the worker default."""
    if _override is not None:
        return _override
    s = get_worker_settings()
    name = (choice or {}).get("provider") or s.model_provider
    if (choice or {}).get("error"):
        raise ProviderError("provider_not_configured", choice["error"])
    if name == "anthropic":
        return AnthropicProvider(api_key=(choice or {}).get("api_key"))
    if name == "claude_cli":
        return ClaudeCliProvider()
    if s.environment == "production":
        raise ProviderError("provider_not_configured", "the fixture provider cannot be used in production")
    return FixtureProvider(s.fixture_dir)
