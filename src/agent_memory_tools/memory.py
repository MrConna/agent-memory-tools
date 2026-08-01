#!/usr/bin/env python3
"""
Memory CLI — 结构化项目记忆管理工具

用法:
    memory add       "模式描述" --confidence 9 --source review --tags api,error --files src/api.ts
    memory search    "关键词或语义"
    memory list      [--confidence-min 7] [--source review] [--tag api]
    memory prune     [--stale] [--confidence-max 3] [--dry-run]
    memory check     [--stale]  # 检查引用文件是否还存在
    memory export    [--format jsonl|md]  # 导出给团队共享
    memory apply     # 其他 Skill 调用：搜索与当前上下文相关的 learning 并展示

数据格式 (learnings.jsonl):
    每行一条 JSON:
    {
        "id": "uuid",
        "pattern": "API responses always wrapped in {data, error} envelope",
        "confidence": 9,           // 0-10, ≥7 自动应用于推荐, <4 仅展示
        "source": "review",        // 哪个 Skill/场景产生的
        "tags": ["api", "error-handling"],
        "files": ["src/api/handler.ts"],
        "context": "所有 API handler 统一用 envelope 包装",  // 可选，补充说明
        "created_at": "2026-06-03T10:30:00Z",
        "last_referenced": "2026-06-03T14:22:00Z",
        "reference_count": 3,       // 被 apply 命中次数
        "stale": false              // check 命令标记
    }

设计参考: gstack learnings.jsonl + GBrain
"""

import argparse
import json
import os
import re
import sys
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .learning_store import atomic_write, locked


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _home() -> Path:
    """项目根目录，优先用 PROJECT_ROOT 环境变量，否则用 cwd"""
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd()))


def _learnings_file() -> Path:
    """learnings.jsonl 路径"""
    p = _home() / "memory" / "learnings.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Core data operations
# ---------------------------------------------------------------------------

def _load_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"WARN: line {i} invalid JSON, skipping", file=sys.stderr)
    return records


def _save_all(path: Path, records: list[dict]) -> None:
    atomic_write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def _mutate_all(path: Path, mutate: Callable[[list[dict]], None]) -> list[dict]:
    """Reload, mutate, and atomically replace learnings under the shared lock."""
    with locked(path):
        records = _load_all(path)
        mutate(records)
        _save_all(path, records)
        return records


def _append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_add(args: argparse.Namespace) -> None:
    path = _learnings_file()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "id": str(uuid.uuid4())[:8],
        "pattern": args.pattern,
        "confidence": args.confidence,
        "source": args.source or "manual",
        "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
        "files": [f.strip() for f in (args.files or "").split(",") if f.strip()],
        "context": args.context or "",
        "created_at": now,
        "last_referenced": now,
        "reference_count": 0,
        "stale": False,
    }
    from .governance import governed
    record = governed(record)
    _append(path, record)
    print(f"✓ Added [{record['confidence']}/10] {record['pattern'][:80]}")
    print(f"  id={record['id']} tags={record['tags']}")


def cmd_search(args: argparse.Namespace) -> None:
    path = _learnings_file()
    records = _load_all(path)
    if not records:
        print("No learnings found.")
        return

    query = args.query.lower()
    keywords = query.split()

    scored = []
    for r in records:
        if r.get("stale") and not args.include_stale:
            continue
        text = f"{r['pattern']} {' '.join(r.get('tags', []))} {r.get('context', '')}".lower()
        hits = sum(1 for kw in keywords if kw in text)
        if hits == 0:
            continue
        # 综合分数 = 关键词命中数 * 置信度权重
        score = hits * (r.get("confidence", 5) / 10)
        scored.append((score, r))

    if not scored:
        print(f"No learnings match '{args.query}'")
        return

    scored.sort(key=lambda x: (-x[0], -x[1].get("confidence", 0)))

    # 更新 last_referenced 和 reference_count
    updated_ids = set()
    for _, r in scored[:5]:
        r["last_referenced"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r["reference_count"] = r.get("reference_count", 0) + 1
        updated_ids.add(r["id"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    def update_references(current: list[dict]) -> None:
        for item in current:
            if item.get("id") in updated_ids:
                item["last_referenced"] = now
                item["reference_count"] = item.get("reference_count", 0) + 1
    records = _mutate_all(path, update_references)
    by_id = {item.get("id"): item for item in records}
    scored = [(score, by_id.get(item.get("id"), item)) for score, item in scored]

    print(f"Found {len(scored)} learning(s), showing top {min(len(scored), 10)}:\n")
    for score, r in scored[:10]:
        conf = r.get("confidence", 0)
        stale_mark = " [STALE]" if r.get("stale") else ""
        ref_mark = f" (referenced {r.get('reference_count', 0)}x)" if r.get("reference_count", 0) > 0 else ""
        print(f"  [{conf}/10]{stale_mark} {r['pattern']}")
        if r.get("context"):
            print(f"           {r['context'][:100]}")
        if r.get("tags"):
            print(f"           tags: {', '.join(r['tags'])}")
        if r.get("files"):
            print(f"           files: {', '.join(r['files'][:3])}")
        print()


def cmd_list(args: argparse.Namespace) -> None:
    path = _learnings_file()
    records = _load_all(path)
    if not records:
        print("No learnings found.")
        return

    filtered = records
    if args.confidence_min is not None:
        filtered = [r for r in filtered if r.get("confidence", 0) >= args.confidence_min]
    if args.source:
        filtered = [r for r in filtered if r.get("source") == args.source]
    if args.tag:
        filtered = [r for r in filtered if args.tag in r.get("tags", [])]
    if not args.include_stale:
        filtered = [r for r in filtered if not r.get("stale")]

    # 按置信度降序
    filtered.sort(key=lambda r: -r.get("confidence", 0))

    high = sum(1 for r in filtered if r.get("confidence", 0) >= 7)
    med = sum(1 for r in filtered if 4 <= r.get("confidence", 0) < 7)
    low = sum(1 for r in filtered if r.get("confidence", 0) < 4)
    stale = sum(1 for r in filtered if r.get("stale"))

    print(f"{len(filtered)} learnings (high={high}, medium={med}, low={low}, stale={stale})\n")

    for r in filtered:
        conf = r.get("confidence", 0)
        stale_mark = " [STALE]" if r.get("stale") else ""
        print(f"  [{conf}/10]{stale_mark} {r['pattern'][:80]}")
    print()


def cmd_check(args: argparse.Namespace) -> None:
    """检查引用的文件是否还存在，标记 stale"""
    path = _learnings_file()
    records = _load_all(path)
    if not records:
        print("No learnings found.")
        return

    project_root = _home()
    newly_stale: list[dict] = []
    def refresh(current: list[dict]) -> None:
        for r in current:
            if not r.get("files"):
                continue
            all_exist = all((project_root / f if not os.path.isabs(f) else Path(f)).exists() for f in r["files"])
            was_stale = r.get("stale", False)
            r["stale"] = not all_exist
            if r["stale"] and not was_stale:
                newly_stale.append(r)
    records = _mutate_all(path, refresh)
    for r in newly_stale:
        print(f"  ✗ STALE: {r['pattern'][:60]} — file(s) deleted")
    stale_count = len(newly_stale)
    total_stale = sum(1 for r in records if r.get("stale"))
    print(f"\n{stale_count} newly stale, {total_stale} total stale out of {len(records)}")


def cmd_prune(args: argparse.Namespace) -> None:
    path = _learnings_file()
    records = _load_all(path)
    if not records:
        print("No learnings found.")
        return

    to_remove = set()
    for i, r in enumerate(records):
        if args.stale and r.get("stale"):
            to_remove.add(i)
        if args.confidence_max is not None and r.get("confidence", 0) <= args.confidence_max:
            to_remove.add(i)

    if not to_remove:
        print("Nothing to prune.")
        return

    if args.dry_run:
        print(f"Would prune {len(to_remove)} learning(s):")
        for i in sorted(to_remove):
            r = records[i]
            print(f"  [{r.get('confidence', 0)}/10] {r['pattern'][:80]}{' [STALE]' if r.get('stale') else ''}")
        return

    remove_ids = {records[i].get("id") for i in to_remove}
    def remove(current: list[dict]) -> None:
        current[:] = [r for r in current if r.get("id") not in remove_ids]
    kept = _mutate_all(path, remove)
    print(f"✓ Pruned {len(to_remove)} learning(s), {len(kept)} remaining")


def cmd_export(args: argparse.Namespace) -> None:
    path = _learnings_file()
    records = _load_all(path)
    if not records:
        print("No learnings found.")
        return

    if args.format == "jsonl":
        for r in records:
            if not args.include_stale and r.get("stale"):
                continue
            print(json.dumps(r, ensure_ascii=False))
    elif args.format == "md":
        print("# Project Learnings\n")
        high = [r for r in records if r.get("confidence", 0) >= 7 and not r.get("stale")]
        med = [r for r in records if 4 <= r.get("confidence", 0) < 7 and not r.get("stale")]
        low = [r for r in records if r.get("confidence", 0) < 4 and not r.get("stale")]
        stale = [r for r in records if r.get("stale")]

        if high:
            print(f"## High Confidence ({len(high)})\n")
            for r in high:
                tags = ", ".join(r.get("tags", []))
                print(f"- **[{r['confidence']}/10]** {r['pattern']}")
                if r.get("context"):
                    print(f"  - {r['context']}")
                if tags:
                    print(f"  - tags: {tags}")
                print()
        if med:
            print(f"## Medium Confidence ({len(med)})\n")
            for r in med:
                tags = ", ".join(r.get("tags", []))
                print(f"- **[{r['confidence']}/10]** {r['pattern']}")
                if r.get("context"):
                    print(f"  - {r['context']}")
                print()
        if low:
            print(f"## Low Confidence ({len(low)})\n")
            for r in low:
                print(f"- **[{r['confidence']}/10]** {r['pattern']}")
                print()
        if stale:
            print(f"## Stale ({len(stale)})\n")
            for r in stale:
                print(f"- ~~{r['pattern']}~~ [STALE]")
                print()
    else:
        print(f"Unknown format: {args.format}", file=sys.stderr)
        sys.exit(1)


def cmd_apply(args: argparse.Namespace) -> None:
    """供其他 Skill 调用：搜索与当前上下文相关的 learning 并返回匹配结果"""
    path = _learnings_file()
    records = _load_all(path)

    # 只自动应用高置信度且非 stale 的
    applicable = [r for r in records if r.get("confidence", 0) >= 7 and not r.get("stale")]

    if not applicable:
        if args.json:
            print("[]")
        return

    query = (args.query or "").lower()
    if not query:
        if args.json:
            print(json.dumps(applicable[:5], ensure_ascii=False))
        else:
            print(f"{len(applicable)} high-confidence learnings available. Use --query to search.")
        return

    keywords = query.split()
    scored = []
    for r in applicable:
        text = f"{r['pattern']} {' '.join(r.get('tags', []))} {r.get('context', '')}".lower()
        hits = sum(1 for kw in keywords if kw in text)
        if hits > 0:
            scored.append((hits * r["confidence"], r))

    scored.sort(key=lambda x: -x[0])

    # 更新引用计数；锁内重新加载，避免覆盖并发治理字段。
    updated_ids = {r.get("id") for _, r in scored[:3]}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    def update_references(current: list[dict]) -> None:
        for item in current:
            if item.get("id") in updated_ids:
                item["last_referenced"] = now
                item["reference_count"] = item.get("reference_count", 0) + 1
    records = _mutate_all(path, update_references)
    by_id = {item.get("id"): item for item in records}
    scored = [(score, by_id.get(item.get("id"), item)) for score, item in scored]

    if args.json:
        print(json.dumps([r for _, r in scored[:5]], ensure_ascii=False))
    else:
        if scored:
            print("Prior learning applied:")
            for _, r in scored[:3]:
                print(f"  → [{r['confidence']}/10] {r['pattern']}")
        else:
            print("No applicable learnings found.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memory CLI — 结构化项目记忆管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="添加一条 learning")
    p_add.add_argument("pattern", help="模式描述")
    p_add.add_argument("--confidence", type=int, default=7, help="置信度 0-10 (default: 7)")
    p_add.add_argument("--source", default="manual", help="来源 Skill/场景")
    p_add.add_argument("--tags", default="", help="逗号分隔的标签")
    p_add.add_argument("--files", default="", help="逗号分隔的关联文件路径")
    p_add.add_argument("--context", default="", help="补充说明")

    # search
    p_search = sub.add_parser("search", help="搜索 learnings")
    p_search.add_argument("query", help="搜索关键词")
    p_search.add_argument("--include-stale", action="store_true", help="包含 stale 条目")

    # list
    p_list = sub.add_parser("list", help="列出 learnings")
    p_list.add_argument("--confidence-min", type=int, help="最低置信度过滤")
    p_list.add_argument("--source", help="按来源过滤")
    p_list.add_argument("--tag", help="按标签过滤")
    p_list.add_argument("--include-stale", action="store_true", help="包含 stale 条目")

    # check
    p_check = sub.add_parser("check", help="检查引用文件是否存在，标记 stale")

    # prune
    p_prune = sub.add_parser("prune", help="清理 learnings")
    p_prune.add_argument("--stale", action="store_true", help="清理 stale 条目")
    p_prune.add_argument("--confidence-max", type=int, help="清理低于此置信度的条目")
    p_prune.add_argument("--dry-run", action="store_true", help="只显示不执行")

    # export
    p_export = sub.add_parser("export", help="导出 learnings")
    p_export.add_argument("--format", choices=["jsonl", "md"], default="md", help="导出格式")
    p_export.add_argument("--include-stale", action="store_true", help="包含 stale 条目")

    # apply
    p_apply = sub.add_parser("apply", help="供其他 Skill 调用：搜索匹配的 high-confidence learnings")
    p_apply.add_argument("--query", default="", help="当前上下文关键词")
    p_apply.add_argument("--json", action="store_true", help="JSON 输出（供程序消费）")

    args = parser.parse_args()

    commands = {
        "add": cmd_add,
        "search": cmd_search,
        "list": cmd_list,
        "check": cmd_check,
        "prune": cmd_prune,
        "export": cmd_export,
        "apply": cmd_apply,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
