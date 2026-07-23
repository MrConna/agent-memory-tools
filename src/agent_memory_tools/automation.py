#!/usr/bin/env python3
"""Cross-agent lifecycle automation for project memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import uuid
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


def _active_task_path(agent: str) -> Path:
    digest = hashlib.sha256(agent.encode()).hexdigest()[:16]
    return _root() / "memory" / "active-tasks" / f"{digest}.txt"


def _completed_task_path(identity: str) -> Path:
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return _root() / "memory" / "completed-tasks" / f"{digest}.json"


def _session_key(args: argparse.Namespace) -> str:
    return str(
        getattr(args, "session_id", "")
        or os.environ.get("AGENT_MEMORY_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CODEX_THREAD_ID")
        or args.agent
    )


def _active_task(agent: str) -> str:
    try:
        return _active_task_path(agent).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _set_active_task(agent: str, task_id: str | None) -> None:
    path = _active_task_path(agent)
    if task_id:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(task_id + "\n", encoding="utf-8")
        os.replace(temporary, path)
    else:
        path.unlink(missing_ok=True)


def begin_task(agent: str, query: str, *, session_id: str = "", task_id: str = "") -> str:
    identity = session_id or agent
    task_id = task_id or uuid.uuid4().hex
    _set_active_task(identity, task_id)
    _completed_task_path(identity).unlink(missing_ok=True)
    _append_event("task_start", agent=agent, query=query, session_id=session_id, task_id=task_id)
    return task_id


def _observation_path() -> Path:
    return _root() / "memory" / "observations.jsonl"


def _recent_observations(limit: int = 30) -> list[str]:
    return [str(item.get("text", "")) for item in _recent_observation_records(limit) if item.get("text")]


def _recent_observation_records(limit: int = 30) -> list[dict[str, object]]:
    path = _observation_path()
    if not path.exists():
        return []
    result: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                result.append(item)
        except json.JSONDecodeError:
            continue
    return result


def _canonical_action(text: str) -> str:
    try:
        item = json.loads(text)
    except json.JSONDecodeError:
        return re.sub(r"\s+", " ", text).strip()[:160]
    if not isinstance(item, dict):
        return re.sub(r"\s+", " ", text).strip()[:160]
    name = str(item.get("name") or item.get("tool_name") or item.get("toolName") or "").strip()
    arguments = item.get("arguments") or item.get("tool_input") or item.get("toolInput") or item.get("args") or ""
    try:
        arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError:
        pass
    if name in {"exec_command", "shell", "bash"} and isinstance(arguments, dict):
        command = str(arguments.get("cmd") or arguments.get("command") or "").strip()
        executable = command.split()[0] if command else ""
        return f"{name} {executable}".strip()
    return name


def _payload_session_id(raw: str) -> str:
    try:
        item = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(item, dict):
        return ""
    session = item.get("session")
    nested = session.get("id", "") if isinstance(session, dict) else ""
    return str(item.get("session_id") or item.get("sessionId") or nested or "")


def cmd_start(args: argparse.Namespace) -> int:
    if not getattr(args, "session_id", "") and not os.sys.stdin.isatty():
        args.session_id = _payload_session_id(os.sys.stdin.read())
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
    begin_task(args.agent, args.query, session_id=_session_key(args))
    print("\n\n".join(blocks) if blocks else "No relevant project memory found.")
    return 0


def cmd_observe(args: argparse.Namespace) -> int:
    raw = args.text or (os.sys.stdin.read() if not os.sys.stdin.isatty() else "")
    if not getattr(args, "session_id", ""):
        args.session_id = _payload_session_id(raw)
    if not raw.strip() or re.search(r"<\s*private(?:\s[^>]*)?>", raw, flags=re.IGNORECASE):
        return 0
    config = load_config()
    local = config.get("local_model", {})
    automation = config.get("automation", {})
    text = re.sub(r"\s+", " ", raw).strip()[:int(automation.get("observation_max_chars", 4000))]
    model = LocalModel.from_pi_config()
    if model and local.get("observation_compression", True):
        text = model.compress_observation(text) or text
    task_id = _active_task(_session_key(args))
    path = _observation_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    recent = path.read_text(encoding="utf-8").splitlines()[-100:] if path.exists() else []
    base = f"{args.agent}:{task_id}:{args.kind}:{text}"
    occurrence = 0
    if task_id:
        for line in recent:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                item.get("agent") == args.agent and item.get("task_id") == task_id
                and item.get("kind") == args.kind and item.get("text") == text
            ):
                occurrence += 1
    digest = hashlib.sha256(f"{base}:{occurrence}".encode()).hexdigest()[:16]
    if any(f'"id": "{digest}"' in line for line in recent):
        return 0
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": digest, "at": datetime.now(timezone.utc).isoformat(),
            "agent": args.agent, "kind": args.kind, "text": text,
            "task_id": task_id,
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
    tag_set = {tag.strip().lower() for tag in tags.split(",")}
    if not learning or not automation.get("single_event_verified_promotion", True) or "verified" not in tag_set:
        return []
    slug = _slug(learning)
    promoted: list[str] = []
    if confidence >= rule_min:
        rule = _root() / "memory" / "rules" / f"{slug}.md"
        rule.parent.mkdir(parents=True, exist_ok=True)
        if not rule.exists():
            rule.write_text(f"# Rule\n\n{learning}\n\nConfidence: {confidence}\nTags: {tags or 'general'}\n", encoding="utf-8")
        promoted.append(str(rule.relative_to(_root())))

    if confidence >= knowledge_min:
        knowledge = _root() / "wiki" / "concepts" / f"{slug}.md"
        knowledge.parent.mkdir(parents=True, exist_ok=True)
        if not knowledge.exists():
            knowledge.write_text(f"# {learning[:80]}\n\n{learning}\n\nSource: automated lifecycle promotion.\n", encoding="utf-8")
        promoted.append(str(knowledge.relative_to(_root())))

    if confidence >= skill_min and skill_tag in tag_set:
        skill = _root() / "skills" / slug / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        if not skill.exists():
            skill.write_text(
                f"---\nname: {slug}\ndescription: Auto-promoted workflow from verified project memory.\n---\n\n# {learning[:80]}\n\n{learning}\n",
                encoding="utf-8",
            )
        promoted.append(str(skill.relative_to(_root())))
    return promoted


def cmd_end(args: argparse.Namespace) -> int:
    if not getattr(args, "session_id", "") and not os.sys.stdin.isatty():
        args.session_id = _payload_session_id(os.sys.stdin.read())
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
    from .patterns import is_procedural, record
    session_key = _session_key(args)
    task_id = _active_task(session_key)
    summary_digest = hashlib.sha256(args.summary.encode()).hexdigest()
    if not task_id:
        try:
            completed = json.loads(_completed_task_path(session_key).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            completed = {}
        if completed.get("summary_digest") == summary_digest:
            task_id = str(completed.get("task_id", ""))
    pattern_text = args.learning
    pattern_tags = args.tags
    pattern_config = config.get("patterns", {})
    if (
        not pattern_text
        and pattern_config.get("capture_procedural_summaries", True)
        and is_procedural(args.summary)
    ):
        pattern_text = args.summary
        pattern_tags = f"{args.tags},workflow"
    if pattern_text:
        pattern = record(
            pattern_text,
            source=task_id or f"{args.agent}:{args.summary}",
            tags=pattern_tags,
            confidence=args.confidence,
        )
        if pattern:
            promoted.extend(
                str(pattern.get(name, ""))
                for name in ("knowledge_path", "skill_path")
                if pattern.get(name) and str(pattern.get(name)) not in promoted
            )
    task_observations = [
        item for item in _recent_observation_records()
        if task_id and item.get("task_id") == task_id and item.get("kind") in {"tool", "before-tool"}
    ]
    if len(task_observations) >= 2:
        actions: list[str] = []
        for item in task_observations:
            action = _canonical_action(str(item.get("text", "")))
            if action and (not actions or actions[-1] != action):
                actions.append(action)
        workflow = " then ".join(actions)
        if workflow:
            action_pattern = record(
                workflow, source=task_id, tags="workflow,observed-actions", confidence=5,
            )
            if action_pattern:
                promoted.extend(
                    str(action_pattern.get(name, ""))
                    for name in ("knowledge_path", "skill_path")
                    if action_pattern.get(name) and str(action_pattern.get(name)) not in promoted
                )
    if automation.get("brain_sync_on_end", True):
        brain_code, brain_output = _run("brain", "sync")
    else:
        brain_code, brain_output = 0, "disabled by configuration"
    _append_event(
        "task_end", agent=args.agent, task_id=task_id, summary=args.summary,
        learning=args.learning, promoted=promoted, brain_synced=brain_code == 0,
    )
    _set_active_task(session_key, None)
    completed_path = _completed_task_path(session_key)
    completed_path.parent.mkdir(parents=True, exist_ok=True)
    completed_path.write_text(
        json.dumps({"task_id": task_id, "summary_digest": summary_digest}, indent=2) + "\n",
        encoding="utf-8",
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
    start.add_argument("--session-id", default="")
    start.add_argument("--complex", action="store_true", help="Create the required detailed progress record")
    start.add_argument("--outcome", default="")
    start.add_argument("--acceptance", default="")
    start.add_argument("--plan", default="")
    end = sub.add_parser("end")
    end.add_argument("--agent", default="unknown")
    end.add_argument("--session-id", default="")
    end.add_argument("--summary", default="Agent task completed")
    end.add_argument("--learning", default="")
    end.add_argument("--confidence", type=int, default=7)
    end.add_argument("--tags", default="general")
    end.add_argument("--decisions", default="")
    end.add_argument("--remaining", default="")
    end.add_argument("--failed", default="")
    observe = sub.add_parser("observe")
    observe.add_argument("--agent", default="unknown")
    observe.add_argument("--session-id", default="")
    observe.add_argument("--kind", default="tool")
    observe.add_argument("--text", default="")
    args = parser.parse_args(argv)
    commands = {"start": cmd_start, "end": cmd_end, "observe": cmd_observe}
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
