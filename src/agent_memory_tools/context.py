#!/usr/bin/env python3
"""
Context Save/Restore — 会话级状态持久化

用法:
    context save    --description "数据飞轮讨论" --decisions "d1,d2" --remaining "r1,r2" --failed "f1"
    context restore [--latest | --id ID]
    context list
    context show    [--latest | --id ID]

设计参考: gstack /context-save + /context-restore

数据格式 (contexts.jsonl):
    {
        "id": "uuid",
        "session_id": "PID-timestamp",
        "description": "数据飞轮讨论",
        "git": {
            "branch": "main",
            "commit": "abc1234",
            "dirty": true,
            "uncommitted_files": ["AGENTS.md", "knowledge/"]
        },
        "decisions": ["VQA不独立，吸收进Knowledge", "现状只按main分支"],
        "remaining_work": ["跑一次闭环验证", "更新飞书文档"],
        "failed_approaches": ["直接合入feat/vqa"],
        "artifacts": ["knowledge/gstack-skill-and-memory.md"],
        "created_at": "2026-06-03T14:30:00Z"
    }
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _home() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd()))


def _context_file() -> Path:
    p = _home() / "memory" / "contexts.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _save_all(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _git_info() -> dict:
    """采集当前 git 状态"""
    info = {"branch": "unknown", "commit": "unknown", "dirty": False, "uncommitted_files": []}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            info["branch"] = result.stdout.strip()

        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            info["commit"] = result.stdout.strip()

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            info["dirty"] = len(lines) > 0
            info["uncommitted_files"] = lines[:20]  # 最多 20 个
    except Exception:
        pass
    return info


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_save(args: argparse.Namespace) -> None:
    path = _context_file()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "id": str(uuid.uuid4())[:8],
        "session_id": f"{os.getpid()}-{int(datetime.now().timestamp())}",
        "description": args.description or "",
        "git": _git_info(),
        "decisions": [d.strip() for d in (args.decisions or "").split("|") if d.strip()],
        "remaining_work": [r.strip() for r in (args.remaining or "").split("|") if r.strip()],
        "failed_approaches": [f.strip() for f in (args.failed or "").split("|") if f.strip()],
        "artifacts": [a.strip() for a in (args.artifacts or "").split(",") if a.strip()],
        "created_at": now,
    }
    _append(path, record)
    print(f"✓ Context saved: {record['id']}")
    print(f"  branch={record['git']['branch']} dirty={record['git']['dirty']}")
    print(f"  decisions={len(record['decisions'])} remaining={len(record['remaining_work'])}")


def cmd_restore(args: argparse.Namespace) -> None:
    path = _context_file()
    records = _load_all(path)
    if not records:
        print("No saved contexts found.")
        return

    if args.id:
        target = next((r for r in records if r["id"] == args.id), None)
        if not target:
            print(f"Context {args.id} not found.")
            return
    else:
        target = records[-1]  # latest

    # 输出恢复信息
    print(f"=== Restoring context {target['id']} ===\n")
    print(f"Description: {target.get('description', 'N/A')}")
    git = target.get("git", {})
    print(f"Git: {git.get('branch', '?')} @ {git.get('commit', '?')} {'(dirty)' if git.get('dirty') else ''}")
    print()

    if target.get("decisions"):
        print("Decisions made:")
        for d in target["decisions"]:
            print(f"  ✓ {d}")
        print()

    if target.get("remaining_work"):
        print("Remaining work:")
        for r in target["remaining_work"]:
            print(f"  □ {r}")
        print()

    if target.get("failed_approaches"):
        print("Failed approaches (don't repeat):")
        for f in target["failed_approaches"]:
            print(f"  ✗ {f}")
        print()

    if target.get("artifacts"):
        print("Artifacts:")
        for a in target["artifacts"]:
            print(f"  📄 {a}")
        print()

    print(f"Saved at: {target.get('created_at', 'N/A')}")

    # 如果 git 分支不匹配，给出提示
    current_branch = _git_info().get("branch", "unknown")
    saved_branch = git.get("branch", "unknown")
    if current_branch != saved_branch:
        print(f"\n⚠️  Branch mismatch: saved={saved_branch}, current={current_branch}")
        print(f"   Run: git checkout {saved_branch}")


def cmd_list(args: argparse.Namespace) -> None:
    path = _context_file()
    records = _load_all(path)
    if not records:
        print("No saved contexts found.")
        return

    print(f"{len(records)} saved context(s):\n")
    for r in reversed(records[-20:]):  # 最近 20 条
        desc = r.get("description", "N/A")[:50]
        branch = r.get("git", {}).get("branch", "?")
        rem = len(r.get("remaining_work", []))
        print(f"  {r['id']}  {r.get('created_at', '')[:10]}  [{branch}]  {desc}  ({rem} remaining)")


def cmd_show(args: argparse.Namespace) -> None:
    path = _context_file()
    records = _load_all(path)
    if not records:
        print("No saved contexts found.")
        return

    if args.id:
        target = next((r for r in records if r["id"] == args.id), None)
    else:
        target = records[-1]

    if not target:
        print(f"Context not found.")
        return

    print(json.dumps(target, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Context Save/Restore — 会话级状态持久化",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # save
    p_save = sub.add_parser("save", help="保存当前会话上下文")
    p_save.add_argument("--description", default="", help="会话描述")
    p_save.add_argument("--decisions", default="", help="已做的决策，|分隔")
    p_save.add_argument("--remaining", default="", help="未完成的工作，|分隔")
    p_save.add_argument("--failed", default="", help="失败的尝试，|分隔")
    p_save.add_argument("--artifacts", default="", help="产出的文件，逗号分隔")

    # restore
    p_restore = sub.add_parser("restore", help="恢复上下文")
    p_restore.add_argument("--id", help="指定 context ID，默认恢复最新的")

    # list
    sub.add_parser("list", help="列出已保存的上下文")

    # show
    p_show = sub.add_parser("show", help="显示上下文详情")
    p_show.add_argument("--id", help="指定 context ID")

    args = parser.parse_args()
    commands = {
        "save": cmd_save,
        "restore": cmd_restore,
        "list": cmd_list,
        "show": cmd_show,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
