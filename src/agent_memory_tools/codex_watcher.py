"""Incrementally ingest Codex JSONL transcripts into the shared lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import automation
from .config import load_config, project_root


def _state_path() -> Path:
    return project_root() / "memory" / "codex-watch-state.json"


def _pid_path() -> Path:
    return project_root() / "memory" / "codex-watcher.pid"


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"offsets": {}, "sessions": {}}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _files() -> list[Path]:
    root = Path.home() / ".codex" / "sessions"
    return sorted(root.glob("**/*.jsonl"), key=lambda path: path.stat().st_mtime)


def _payload_text(payload: dict[str, Any]) -> str:
    return str(payload.get("message") or payload.get("output") or "")


def _handle(item: dict[str, Any], session: dict[str, Any]) -> None:
    payload = item.get("payload") or {}
    outer = item.get("type")
    kind = payload.get("type")
    if outer == "session_meta":
        session["cwd"] = str(payload.get("cwd", ""))
        session["id"] = str(payload.get("id", ""))
        return
    if Path(session.get("cwd", ".")).resolve() != project_root():
        return
    if outer == "event_msg" and kind == "user_message":
        session["query"] = _payload_text(payload)[:500]
        automation.begin_task("codex", session["query"], session_id=str(session.get("id", "")))
    elif outer == "response_item" and kind == "function_call":
        call_id = str(payload.get("call_id", ""))
        session.setdefault("calls", {})[call_id] = {
            "name": payload.get("name"), "arguments": payload.get("arguments"),
        }
    elif outer == "response_item" and kind == "function_call_output":
        call_id = str(payload.get("call_id", ""))
        call = session.setdefault("calls", {}).pop(call_id, {})
        text = json.dumps({**call, "output": payload.get("output")}, ensure_ascii=False)
        automation.cmd_observe(argparse.Namespace(
            agent="codex", session_id=str(session.get("id", "")), kind="tool", text=text,
        ))
    elif outer == "event_msg" and kind == "task_complete":
        summary = str(payload.get("last_agent_message") or "codex session completed")[:4000]
        automation.cmd_end(argparse.Namespace(
            agent="codex", session_id=str(session.get("id", "")),
            summary=summary, learning="", confidence=7, tags="general",
            decisions="", remaining="", failed="",
        ))


def run_once(*, start_at_end: bool = False) -> int:
    state = _load_state()
    offsets = state.setdefault("offsets", {})
    sessions = state.setdefault("sessions", {})
    for path in _files():
        key = str(path)
        size = path.stat().st_size
        if key not in offsets and start_at_end:
            offsets[key] = size
            continue
        offset = min(int(offsets.get(key, 0)), size)
        session = sessions.setdefault(key, {})
        with open(path, encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                try:
                    _handle(json.loads(line), session)
                except (json.JSONDecodeError, OSError, ValueError):
                    continue
            offsets[key] = f.tell()
    _save_state(state)
    return 0


def _running() -> bool:
    try:
        pid = int(_pid_path().read_text())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def cmd_start() -> int:
    if _running():
        print("Codex watcher already running")
        return 0
    run_once(start_at_end=True)
    log = project_root() / "memory" / "codex-watcher.log"
    env = {**os.environ, "PROJECT_ROOT": str(project_root())}
    with open(log, "a", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "agent_memory_tools.codex_watcher", "watch"],
            cwd=project_root(), env=env, stdout=output, stderr=output,
            start_new_session=True,
        )
    _pid_path().write_text(str(process.pid), encoding="utf-8")
    print(f"✓ Codex watcher started (pid={process.pid})")
    return 0


def cmd_stop() -> int:
    if not _running():
        print("Codex watcher is not running")
        return 0
    pid = int(_pid_path().read_text())
    os.kill(pid, signal.SIGTERM)
    _pid_path().unlink(missing_ok=True)
    print("✓ Codex watcher stopped")
    return 0


def watch() -> int:
    interval = float(load_config().get("codex", {}).get("watch_poll_seconds", 1))
    while True:
        run_once()
        time.sleep(max(interval, 0.2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex transcript lifecycle watcher")
    parser.add_argument("command", choices=["start", "stop", "status", "once", "watch"])
    args = parser.parse_args(argv)
    if args.command == "start": return cmd_start()
    if args.command == "stop": return cmd_stop()
    if args.command == "status":
        print("running" if _running() else "stopped")
        return 0 if _running() else 1
    if args.command == "once": return run_once()
    return watch()


if __name__ == "__main__":
    raise SystemExit(main())
