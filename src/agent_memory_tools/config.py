"""Project-level configuration for agent-memory-tools."""

from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "local_model": {
        "enabled": True,
        "provider": "local-gemma",
        "model": "",
        "timeout_seconds": 12,
        "observation_compression": True,
        "session_summary": True,
    },
    "automation": {
        "rule_promotion_min_confidence": 7,
        "knowledge_promotion_min_confidence": 7,
        "skill_promotion_min_confidence": 9,
        "skill_tag": "skill",
        "brain_sync_on_end": True,
        "observation_max_chars": 4000,
        "observation_search_limit": 5,
    },
    "codex": {
        "watcher_enabled": True,
        "watch_poll_seconds": 1,
    },
    "skills": {
        "install_common": True,
        "enabled": [
            "teach",
            "diagnose-systematically",
            "develop-test-first",
            "verify-before-completion",
            "plan-and-execute",
            "run-verified-agent-loop",
            "recall-project-memory",
            "capture-project-learning",
            "handoff-session",
            "maintain-project-knowledge",
        ],
        "targets": ["codex", "claude", "pi", "agy", "gemini"],
    },
}


def project_root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def config_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "memory" / "config.json"


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(root: Path | None = None) -> dict[str, Any]:
    path = config_path(root)
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        user = {}
    return _merge(DEFAULT_CONFIG, user if isinstance(user, dict) else {})


def write_default(root: Path, *, force: bool = False) -> None:
    path = config_path(root)
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")


def _parse_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def cmd_set(key: str, value: str) -> int:
    config = load_config()
    cursor: dict[str, Any] = config
    parts = key.split(".")
    for part in parts[:-1]:
        child = cursor.setdefault(part, {})
        if not isinstance(child, dict):
            raise SystemExit(f"Cannot set {key}: {part} is not an object")
        cursor = child
    cursor[parts[-1]] = _parse_value(value)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"✓ {key} = {json.dumps(cursor[parts[-1]], ensure_ascii=False)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent memory project configuration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    setter = sub.add_parser("set")
    setter.add_argument("key")
    setter.add_argument("value")
    args = parser.parse_args(argv)
    if args.command == "show":
        print(json.dumps(load_config(), indent=2))
        return 0
    return cmd_set(args.key, args.value)


if __name__ == "__main__":
    raise SystemExit(main())
