#!/usr/bin/env python3
"""
Agent health monitoring.

Detects loop patterns in agent session files so that interrupted sessions can
be diagnosed on resume.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PI_SESSIONS_ROOT = Path.home() / ".pi" / "agent" / "sessions"


@dataclass
class LoopPattern:
    type: str
    count: int
    description: str
    last_timestamp: str | None = None


@dataclass
class HealthReport:
    session_id: str
    total_turns: int
    recent_turns: int
    loop_patterns: list[LoopPattern]
    is_healthy: bool
    summary: str


def _parse_session_file(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _find_session_file(session_id: str) -> Path | None:
    if not PI_SESSIONS_ROOT.exists():
        return None
    for project_dir in PI_SESSIONS_ROOT.iterdir():
        if not project_dir.is_dir():
            continue
        for f in project_dir.iterdir():
            if f.is_file() and session_id in f.name:
                return f
            if f.is_dir() and session_id in f.name:
                # pi sometimes stores sessions as directories with a jsonl inside.
                for inner in f.iterdir():
                    if inner.is_file() and inner.suffix == ".jsonl" and session_id in inner.name:
                        return inner
    return None


def _extract_tool_calls(events: list[dict[str, Any]]) -> list[tuple[str, str, str | None]]:
    """Return list of (tool_name, normalized_arguments_json, timestamp) from assistant turns."""
    calls: list[tuple[str, str, str | None]] = []
    for event in events:
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if isinstance(content, dict):
            content = [content]
        if not isinstance(content, list):
            continue
        ts = event.get("timestamp")
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "toolCall":
                name = block.get("name") or "unknown"
                args = block.get("arguments", {})
                # Normalize dict ordering for comparison.
                args_key = json.dumps(args, ensure_ascii=False, sort_keys=True)
                calls.append((name, args_key, ts))
    return calls


def _extract_errors(events: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
    """Return list of (tool_name, timestamp) for tool results that look like errors."""
    errors: list[tuple[str, str | None]] = []
    for event in events:
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        if msg.get("role") != "toolResult":
            continue
        content = msg.get("content", [])
        if isinstance(content, dict):
            content = [content]
        if not isinstance(content, list):
            continue
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        text = "\n".join(text_parts)
        if text.startswith("[error]") or "error:" in text.lower() or "Traceback" in text:
            errors.append((msg.get("toolName") or "unknown", event.get("timestamp")))
    return errors


def _detect_repeated_tool_calls(calls: list[tuple[str, str, str | None]], threshold: int = 3) -> LoopPattern | None:
    if len(calls) < threshold:
        return None
    # Look at the last `threshold` calls.
    recent = calls[-threshold:]
    names = [c[0] for c in recent]
    args_keys = [c[1] for c in recent]
    if len(set(names)) == 1 and len(set(args_keys)) == 1:
        return LoopPattern(
            type="repeated_tool_call",
            count=threshold,
            description=f"Assistant called `{names[0]}` {threshold} times in a row with identical arguments",
            last_timestamp=recent[-1][2],
        )
    return None


def _detect_error_loop(errors: list[tuple[str, str | None]], threshold: int = 3) -> LoopPattern | None:
    if len(errors) < threshold:
        return None
    recent = errors[-threshold:]
    names = [e[0] for e in recent]
    if len(set(names)) >= 1:
        counter = Counter(names)
        most_common = counter.most_common(1)[0]
        return LoopPattern(
            type="error_loop",
            count=threshold,
            description=f"Last {threshold} tool results were errors; most common failing tool: `{most_common[0]}`",
            last_timestamp=recent[-1][1],
        )
    return None


def _detect_no_progress(events: list[dict[str, Any]], recent_turns: int = 10) -> LoopPattern | None:
    """Detect if recent assistant turns only contain toolCalls and no final text response."""
    assistant_turns = [e for e in events if e.get("type") == "message" and e.get("message", {}).get("role") == "assistant"]
    if len(assistant_turns) < recent_turns:
        return None
    recent = assistant_turns[-recent_turns:]
    text_responses = 0
    for event in recent:
        content = event.get("message", {}).get("content", [])
        if isinstance(content, dict):
            content = [content]
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                text_responses += 1
                break
    if text_responses == 0:
        return LoopPattern(
            type="no_progress",
            count=recent_turns,
            description=f"Last {recent_turns} assistant turns produced no text response (only tool calls)",
            last_timestamp=recent[-1].get("timestamp"),
        )
    return None


def check_session(session_id: str, *, recent_turns: int = 10, loop_threshold: int = 3) -> HealthReport:
    path = _find_session_file(session_id)
    if not path:
        return HealthReport(
            session_id=session_id,
            total_turns=0,
            recent_turns=0,
            loop_patterns=[],
            is_healthy=False,
            summary=f"Session file not found for {session_id}",
        )

    events = _parse_session_file(path)
    assistant_turns = [e for e in events if e.get("type") == "message" and e.get("message", {}).get("role") == "assistant"]
    total_turns = len(assistant_turns)

    calls = _extract_tool_calls(events)
    errors = _extract_errors(events)

    patterns: list[LoopPattern] = []
    repeated = _detect_repeated_tool_calls(calls, threshold=loop_threshold)
    if repeated:
        patterns.append(repeated)
    error_loop = _detect_error_loop(errors, threshold=loop_threshold)
    if error_loop:
        patterns.append(error_loop)
    no_progress = _detect_no_progress(events, recent_turns=recent_turns)
    if no_progress:
        patterns.append(no_progress)

    is_healthy = not patterns
    if is_healthy:
        summary = f"Session {session_id} looks healthy ({total_turns} assistant turns)."
    else:
        names = ", ".join(p.type for p in patterns)
        summary = f"Session {session_id} shows potential loops: {names}."

    return HealthReport(
        session_id=session_id,
        total_turns=total_turns,
        recent_turns=min(recent_turns, total_turns),
        loop_patterns=patterns,
        is_healthy=is_healthy,
        summary=summary,
    )


def cmd_check(args: argparse.Namespace) -> int:
    session_id = args.session_id
    if not session_id:
        session_id = os.environ.get("PI_SESSION_ID", "")
    if not session_id:
        print("session-command: missing session id; pass --session-id or set PI_SESSION_ID", file=sys.stderr)
        return 2

    report = check_session(session_id, recent_turns=args.recent_turns, loop_threshold=args.loop_threshold)
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0 if report.is_healthy and report.total_turns > 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent health monitoring.")
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="Check a session for loop patterns")
    check_p.add_argument("--session-id", help="pi session id (or set PI_SESSION_ID)")
    check_p.add_argument("--recent-turns", type=int, default=10, help="Number of recent turns to analyze")
    check_p.add_argument("--loop-threshold", type=int, default=3, help="Consecutive repeats to flag as loop")
    check_p.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
