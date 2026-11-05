"""Failure summary for saved sandbox results (see docs/sandbox-execution-results.md).

Reads a JSON record that carries the ExecutionDetails block both workers serialize — a compile report,
a run manifest, a serialized RunOutput, or the bare block itself — and formats a short, human-readable
summary. Read-only: nothing here changes what the workers produce.
"""

from __future__ import annotations

import json
from typing import Any

from .sandbox import EXECUTION_FIELDS

# Records written before streams_collected existed lack it; it is the only optional field.
_REQUIRED_FIELDS = EXECUTION_FIELDS - {"streams_collected"}

# Markers stream_diagnostics() puts at the start of a synthesized compile log excerpt.
_SYNTHESIZED_EXCERPT = ("main.log was not collected:", "main.log was not produced", "--- sandbox ")


class NotASandboxRecord(ValueError):
    pass


def execution_block(record: dict[str, Any]) -> dict[str, Any]:
    """The ExecutionDetails dict inside `record`, or `record` itself when it is a bare block."""
    exe = record.get("execution")
    if isinstance(exe, dict) and _REQUIRED_FIELDS <= set(exe):
        return exe
    if _REQUIRED_FIELDS <= set(record):
        return record
    raise NotASandboxRecord("no ExecutionDetails block: expected an 'execution' key or the bare block "
                            f"(fields {', '.join(sorted(_REQUIRED_FIELDS))})")


def record_kind(record: dict[str, Any]) -> str:
    if "compiler_version" in record or "log_excerpt" in record:
        return "compile report"
    if "run_id" in record:
        return "run manifest"
    if "outputs" in record or "log" in record:
        return "run output"
    return "execution block"


def _log_source(record: dict[str, Any], exe: dict[str, Any], kind: str) -> str:
    """Where the human-readable log text came from, per the assembly rules in compile.py / runner.py."""
    if kind == "compile report":
        excerpt = record.get("log_excerpt") or ""
        if not excerpt:
            return "none (no log excerpt)"
        if excerpt.startswith(_SYNTHESIZED_EXCERPT):
            return "stderr/stdout tails only (main.log was not collected)"
        return "full main.log (last 60 lines in log_excerpt)"
    if exe["exit_code"] is None:
        return "none (the sandbox never ran)"
    # streams_collected records the fact directly; fall back to inference for records written before it.
    if "streams_collected" in exe:
        if exe["streams_collected"]:
            return "full stream files"
        return "stderr tail only (stream files were not collected)"
    # A run's log uses the full _sandbox.out/_sandbox.err files when the result archive came back;
    # on timeout or an unreadable archive only the stderr tail exists. When the serialized RunOutput
    # carries the log itself, compare directly instead of inferring.
    log = record.get("log")
    if isinstance(log, str):
        tail_only = "--- stderr ---\n" + exe["stderr"]["text"]
        if log == tail_only or log == exe["failure_reason"]:
            return "stderr tail only (stream files were not collected)"
        return "full stream files"
    if exe["timed_out"] or exe["output_error"]:
        return "stderr tail only (stream files were not collected)"
    return "full stream files"


def _tail_line(tail: dict[str, Any]) -> str:
    kept = len(str(tail.get("text", "")).encode())
    total = tail.get("total_bytes", 0)
    if tail.get("truncated"):
        return f"{total} B total, last {kept} B kept (truncated)"
    return f"{total} B (not truncated)"


def summarize(record: dict[str, Any]) -> str:
    exe = execution_block(record)
    kind = record_kind(record)
    argv = exe.get("argv") or []
    lines = [
        f"{kind} — status: {exe['status']}",
        f"reason:    {exe['failure_reason'] or '— (success)'}",
        f"exit code: {exe['exit_code'] if exe['exit_code'] is not None else '—'}"
        f"    timed out: {'yes' if exe['timed_out'] else 'no'}"
        f"    duration: {'—' if exe['duration_s'] is None else f'{exe['duration_s']:.2f} s'}",
        f"image:     {exe['image'] or '—'}",
        f"argv:      {' '.join(argv) if argv else '—'}",
        f"stdout:    {_tail_line(exe['stdout'])}",
        f"stderr:    {_tail_line(exe['stderr'])}",
        f"log from:  {_log_source(record, exe, kind)}",
    ]
    if exe.get("output_error"):
        lines.insert(2, f"outputs:   could not be read — {exe['output_error']}")
    return "\n".join(lines)


def main(paths: list[str]) -> int:
    if not paths:
        print("usage: sandbox_diag.py <report-or-run-output.json> [...]")
        return 2
    status = 0
    for i, path in enumerate(paths):
        if len(paths) > 1:
            print(("\n" if i else "") + f"== {path} ==")
        try:
            with open(path, "rb") as f:
                record = json.load(f)
            print(summarize(record))
        except (OSError, ValueError) as exc:  # includes JSONDecodeError and NotASandboxRecord
            print(f"{path}: {exc}")
            status = 1
    return status
