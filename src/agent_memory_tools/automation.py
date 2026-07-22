#!/usr/bin/env python3
"""Cross-agent lifecycle automation for project memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .local_model import LocalModel


def _root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def _run(module: str, *args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["python3", "-m", f"agent_memory_tools.{module}", *args],
        cwd=_root(), text=True, capture_output=True, check=False,
        env={**os.environ, "PROJECT_ROOT": str(_root())},
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:64] or "learning"


def _append_event(event: str, **data: object) -> None:
    path = _root() / "memory" / "lifecycle.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"event": event, "at": datetime.now(timezone.utc).isoformat(), **data}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _observation_path() -> Path:
    return _root() / "memory" / "observations.jsonl"


def _recent_observations(limit: int = 30) -> list[str]:
    path = _observation_path()
    if not path.exists():
        return []
    result: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            result.append(str(json.loads(line).get("text", "")))
        except json.JSONDecodeError:
            continue
    return [item for item in result if item]


def cmd_start(args: argparse.Namespace) -> int:
    blocks: list[str] = []
    search_config = load_config().get("search", {})
    code, output = _run(
        "search", "query", args.query,
        "--top", str(search_config.get("lifecycle_top", 8)),
        "--memory-confidence-min", str(search_config.get("lifecycle_memory_confidence_min", 7)),
        "--full", "--max-chars", str(search_config.get("lifecycle_max_chars_per_entry", 4000)),
    )
    if code == 0 and output and "No indexed entries" not in output:
        blocks.append(output)
    if args.complex:
        from .progress import create
        record = create(args.query, outcome=args.outcome, acceptance=args.acceptance, plan=args.plan)
        blocks.append(f"## Progress\nCreated `progress/{record['id']}.md` before execution.")
    _append_event("task_start", agent=args.agent, query=args.query)
    print("\n\n".join(blocks) if blocks else "No relevant project memory found.")
    return 0


def cmd_observe(args: argparse.Namespace) -> int:
    raw = args.text or (os.sys.stdin.read() if not os.sys.stdin.isatty() else "")
    if not raw.strip() or "<private>" in raw:
        return 0
    config = load_config()
    local = config.get("local_model", {})
    automation = config.get("automation", {})
    text = re.sub(r"\s+", " ", raw).strip()[:int(automation.get("observation_max_chars", 4000))]
    model = LocalModel.from_pi_config()
    if model and local.get("observation_compression", True):
        text = model.compress_observation(text) or text
    digest = hashlib.sha256(f"{args.agent}:{args.kind}:{text}".encode()).hexdigest()[:16]
    path = _observation_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    recent = path.read_text(encoding="utf-8").splitlines()[-100:] if path.exists() else []
    if any(f'"id": "{digest}"' in line for line in recent):
        return 0
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": digest, "at": datetime.now(timezone.utc).isoformat(),
            "agent": args.agent, "kind": args.kind, "text": text,
        }, ensure_ascii=False) + "\n")
    print(f"✓ Observation #{digest} captured")
    return 0


def _write_handoff(summary: str, decisions: str, remaining: str, failed: str) -> None:
    content = f"""# Handoff

Updated: {datetime.now(timezone.utc).isoformat()}

## Current state

{summary or 'No summary supplied.'}

## Decisions

{decisions or 'None recorded.'}

## Next steps

{remaining or 'None recorded.'}

## Failed approaches / pitfalls

{failed or 'None recorded.'}
"""
    (_root() / "HANDOFF.md").write_text(content, encoding="utf-8")


def _promote(learning: str, confidence: int, tags: str) -> list[str]:
    automation = load_config().get("automation", {})
    rule_min = int(automation.get("rule_promotion_min_confidence", 7))
    knowledge_min = int(automation.get("knowledge_promotion_min_confidence", 7))
    skill_min = int(automation.get("skill_promotion_min_confidence", 9))
    skill_tag = str(automation.get("skill_tag", "skill")).lower()
    if not learning:
        return []
    slug = _slug(learning)
    promoted: list[str] = []
    if confidence >= rule_min:
        rule = _root() / "memory" / "rules" / f"{slug}.md"
        rule.parent.mkdir(parents=True, exist_ok=True)
        rule.write_text(f"# Rule\n\n{learning}\n\nConfidence: {confidence}\nTags: {tags or 'general'}\n", encoding="utf-8")
        promoted.append(str(rule.relative_to(_root())))

    if confidence >= knowledge_min:
        knowledge = _root() / "wiki" / "concepts" / f"{slug}.md"
        knowledge.parent.mkdir(parents=True, exist_ok=True)
        if not knowledge.exists():
            knowledge.write_text(f"# {learning[:80]}\n\n{learning}\n\nSource: automated lifecycle promotion.\n", encoding="utf-8")
        promoted.append(str(knowledge.relative_to(_root())))

    if confidence >= skill_min and skill_tag in {tag.strip().lower() for tag in tags.split(",")}:
        skill = _root() / "skills" / slug / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(
            f"---\nname: {slug}\ndescription: Auto-promoted workflow from verified project memory.\n---\n\n# {learning[:80]}\n\n{learning}\n",
            encoding="utf-8",
        )
        promoted.append(str(skill.relative_to(_root())))
    return promoted


def cmd_end(args: argparse.Namespace) -> int:
    config = load_config()
    local = config.get("local_model", {})
    automation = config.get("automation", {})
    generic_summary = not args.summary or args.summary.endswith("session completed") or "pre-compress" in args.summary
    if generic_summary:
        model = LocalModel.from_pi_config()
        if model and local.get("session_summary", True):
            args.summary = model.summarize_session(_recent_observations()) or args.summary
    if args.learning:
        _run(
            "memory", "add", args.learning, "--confidence", str(args.confidence),
            "--source", f"agent:{args.agent}", "--tags", args.tags,
        )
    _run(
        "context", "save", "--description", args.summary,
        "--decisions", args.decisions, "--remaining", args.remaining,
        "--failed", args.failed,
    )
    _write_handoff(args.summary, args.decisions, args.remaining, args.failed)
    promoted = _promote(args.learning, args.confidence, args.tags)
    if automation.get("brain_sync_on_end", True):
        brain_code, brain_output = _run("brain", "sync")
    else:
        brain_code, brain_output = 0, "disabled by configuration"
    _append_event(
        "task_end", agent=args.agent, summary=args.summary,
        learning=args.learning, promoted=promoted, brain_synced=brain_code == 0,
    )
    print("✓ Context and HANDOFF.md saved")
    if promoted:
        print("✓ Promoted: " + ", ".join(promoted))
    if brain_code != 0:
        print("→ Brain sync skipped: " + (brain_output.splitlines()[-1] if brain_output else "not configured"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unified lifecycle automation for coding agents")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("query")
    start.add_argument("--agent", default="unknown")
    start.add_argument("--complex", action="store_true", help="Create the required detailed progress record")
    start.add_argument("--outcome", default="")
    start.add_argument("--acceptance", default="")
    start.add_argument("--plan", default="")
    end = sub.add_parser("end")
    end.add_argument("--agent", default="unknown")
    end.add_argument("--summary", default="Agent task completed")
    end.add_argument("--learning", default="")
    end.add_argument("--confidence", type=int, default=7)
    end.add_argument("--tags", default="general")
    end.add_argument("--decisions", default="")
    end.add_argument("--remaining", default="")
    end.add_argument("--failed", default="")
    observe = sub.add_parser("observe")
    observe.add_argument("--agent", default="unknown")
    observe.add_argument("--kind", default="tool")
    observe.add_argument("--text", default="")
    args = parser.parse_args(argv)
    commands = {"start": cmd_start, "end": cmd_end, "observe": cmd_observe}
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
