"""Detailed, artifact-aware progress records for complex tasks."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path


def _root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60] or "task"


def _path(task_id: str) -> Path:
    return _root() / "progress" / f"{task_id}.json"


def _render(record: dict[str, object]) -> str:
    artifacts = record.get("artifacts", []) or []
    events = record.get("events", []) or []
    lines = [
        f"# {record['title']}", "",
        f"- ID: `{record['id']}`", f"- Status: **{record['status']}**",
        f"- Created: {record['created_at']}", f"- Updated: {record['updated_at']}", "",
        "## Outcome", "", str(record.get("outcome") or "Not defined."), "",
        "## Acceptance checks", "", str(record.get("acceptance") or "Not defined."), "",
        "## Plan", "", str(record.get("plan") or "Not defined."), "",
        "## Artifacts", "",
    ]
    if artifacts:
        lines.extend(f"- `{item}`" for item in artifacts)
    else:
        lines.append("- None yet.")
    lines.extend(["", "## Progress log", ""])
    if events:
        lines.extend(f"- {event['at']} — {event['message']}" for event in events)
    else:
        lines.append("- No updates yet.")
    return "\n".join(lines) + "\n"


def save(record: dict[str, object]) -> None:
    directory = _root() / "progress"
    directory.mkdir(parents=True, exist_ok=True)
    record["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _path(str(record["id"])).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / f"{record['id']}.md").write_text(_render(record), encoding="utf-8")


def create(title: str, *, outcome: str = "", acceptance: str = "", plan: str = "") -> dict[str, object]:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    task_id = f"{datetime.now():%Y%m%d-%H%M%S}-{_slug(title)}"
    record: dict[str, object] = {
        "id": task_id, "title": title, "status": "in_progress", "outcome": outcome,
        "acceptance": acceptance, "plan": plan, "artifacts": [],
        "events": [{"at": now, "message": "Progress record created before task execution."}],
        "created_at": now, "updated_at": now,
    }
    save(record)
    (_root() / "progress" / "active").write_text(task_id + "\n", encoding="utf-8")
    return record


def load(task_id: str = "") -> dict[str, object]:
    if not task_id:
        task_id = (_root() / "progress" / "active").read_text(encoding="utf-8").strip()
    return json.loads(_path(task_id).read_text(encoding="utf-8"))


def update(task_id: str = "", *, message: str = "", status: str = "", artifact: str = "") -> dict[str, object]:
    record = load(task_id)
    if status:
        record["status"] = status
    if artifact and artifact not in record["artifacts"]:
        record["artifacts"].append(artifact)
    if message:
        record["events"].append({"at": datetime.now().astimezone().isoformat(timespec="seconds"), "message": message})
    save(record)
    return record


def list_records() -> list[dict[str, object]]:
    records = []
    for path in sorted((_root() / "progress").glob("*.json"), reverse=True):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maintain detailed progress for complex tasks")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("title")
    start.add_argument("--outcome", default="")
    start.add_argument("--acceptance", default="")
    start.add_argument("--plan", default="")
    change = sub.add_parser("update")
    change.add_argument("--id", default="")
    change.add_argument("--message", default="")
    change.add_argument("--status", choices=["in_progress", "blocked", "completed"], default="")
    change.add_argument("--artifact", default="")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    if args.command == "start":
        record = create(args.title, outcome=args.outcome, acceptance=args.acceptance, plan=args.plan)
        print(f"✓ Progress started: {record['id']}")
    elif args.command == "update":
        record = update(args.id, message=args.message, status=args.status, artifact=args.artifact)
        print(f"✓ Progress updated: {record['id']}")
    else:
        for record in list_records():
            print(f"{record['status']:11} {record['id']}  {record['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
