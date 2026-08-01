"""Accumulate repeated workflows and promote them into durable project assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from .config import load_config

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]


def _root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def _ledger_path() -> Path:
    return _root() / "memory" / "patterns.json"


def _lock_path() -> Path:
    return _root() / "memory" / "patterns.lock"


def _slug(value: str) -> str:
    readable = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48] or "repeated-pattern"
    return f"{readable}-{_key(value)[:8]}"


def _key(value: str) -> str:
    normalized = re.sub(r"\d+", "#", value.casefold())
    normalized = re.sub(r"[^\w\u3400-\u9fff]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:20]


def _terms(value: str) -> set[str]:
    normalized = value.casefold()
    terms = set(re.findall(r"[a-z0-9_]+", normalized))
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        terms.update(run[index:index + 2] for index in range(max(1, len(run) - 1)))
    return terms


def _matching_key(records: dict[str, dict[str, object]], text: str) -> str:
    exact = _key(text)
    if exact in records:
        return exact
    target = _terms(text)
    if not target:
        return exact
    threshold = float(load_config().get("patterns", {}).get("similarity_threshold", 0.72))
    best_key = exact
    best_score = 0.0
    for key, item in records.items():
        existing_text = str(item.get("text", ""))
        existing = _terms(existing_text)
        union = target | existing
        lexical = len(target & existing) / len(union) if union else 0
        sequence = SequenceMatcher(None, text.casefold(), existing_text.casefold()).ratio()
        score = max(lexical, sequence)
        if score > best_score:
            best_key, best_score = key, score
    return best_key if best_score >= threshold else exact


def is_procedural(text: str) -> bool:
    minimum = int(load_config().get("patterns", {}).get("candidate_min_chars", 24))
    if len(text.strip()) < minimum:
        return False
    return bool(re.search(
        r"\b(always|before|after|then|whenever|every time|first|finally)\b|"
        r"(每次|始终|总是|先.+(?:再|然后)|之后|以前|最后)",
        text,
        flags=re.IGNORECASE,
    ))


def _load() -> dict[str, dict[str, object]]:
    try:
        value = json.loads(_ledger_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _save(records: dict[str, dict[str, object]]) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _promote_knowledge(record: dict[str, object]) -> str:
    text = str(record["text"])
    path = _root() / "wiki" / "concepts" / f"{_slug(text)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            f"# {text[:80]}\n\n{text}\n\n"
            f"Observed repeatedly across {record['occurrences']} lifecycle events.\n\n"
            "Source: automated repeated-pattern promotion.\n",
            encoding="utf-8",
        )
    return str(path.relative_to(_root()))


def _workflow_steps(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,|;|\bthen\b|\bafter that\b|然后|再|接着)\s*", text, flags=re.IGNORECASE)
    return [part.strip().rstrip(".。") for part in parts if part.strip()]


def _promote_skill(record: dict[str, object]) -> str:
    text = str(record["text"])
    slug = _slug(text)
    path = _root() / "skills" / slug / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    steps = _workflow_steps(text)
    workflow = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, 1))
    if not path.exists():
        path.write_text(
            "---\n"
            f"name: {slug}\n"
            f"description: {json.dumps(f'Apply this project workflow when a task matches: {text[:120]}', ensure_ascii=False)}\n"
            "---\n\n"
            f"# {text[:80]}\n\n"
            "<!-- agent-memory-tools:pattern-promotion -->\n\n"
            f"Promoted after {record['occurrences']} distinct lifecycle events showed the same workflow.\n\n"
            "## Workflow\n\n"
            f"{workflow}\n\n"
            "## Verification\n\n"
            "Confirm every step completed and record any exception as new pattern evidence.\n",
            encoding="utf-8",
        )
    return str(path.relative_to(_root()))


def _record_locked(text: str, *, source: str, tags: str, confidence: int) -> dict[str, object]:
    config = load_config().get("patterns", {})
    records = _load()
    key = _matching_key(records, text)
    item = records.get(key, {
        "text": text, "occurrences": 0, "sources": [], "tags": [],
        "confidence_max": 0, "promoted": [], "first_seen": datetime.now(timezone.utc).isoformat(),
    })
    sources = list(item.get("sources", []))
    evidence_ids = list(item.get("evidence_ids", []))
    evidence = source or datetime.now(timezone.utc).isoformat()
    evidence_id = hashlib.sha256(evidence.encode()).hexdigest()
    if evidence_id not in evidence_ids:
        evidence_ids.append(evidence_id)
        sources.append(evidence)
    item["evidence_ids"] = evidence_ids
    item["occurrences"] = len(evidence_ids)
    item["sources"] = sources[-20:]
    item["tags"] = sorted(set(item.get("tags", [])) | {part.strip() for part in tags.split(",") if part.strip()})
    item["confidence_max"] = max(int(item.get("confidence_max", 0)), confidence)
    item["last_seen"] = datetime.now(timezone.utc).isoformat()
    promoted = list(item.get("promoted", []))
    signal_tags = {str(tag).casefold() for tag in config.get("skill_signal_tags", [])}
    item_tags = {str(tag).casefold() for tag in item.get("tags", [])}
    wants_knowledge = int(item["occurrences"]) >= int(config.get("knowledge_min_occurrences", 3))
    wants_skill = int(item["occurrences"]) >= int(config.get("skill_min_occurrences", 5)) and bool(signal_tags & item_tags)
    targets = [name for name, wanted in (("knowledge", wants_knowledge), ("skill", wants_skill)) if wanted]
    allowed = True
    if targets:
        from .governance import ensure_pattern_candidate, verify_repeated_pattern
        if not ensure_pattern_candidate(
            str(item["text"]), source=source,
            tags=[str(value) for value in item.get("tags", [])], confidence=confidence,
        ):
            allowed = False
        allowed = verify_repeated_pattern(
            str(item["text"]), evidence=[str(value) for value in item.get("sources", [])], targets=targets,
        ) if allowed else False
    if allowed and wants_knowledge and "knowledge" not in promoted:
        item["knowledge_path"] = _promote_knowledge(item)
        promoted.append("knowledge")
    if allowed and wants_skill and "skill" not in promoted:
        item["skill_path"] = _promote_skill(item)
        promoted.append("skill")
    item["promoted"] = promoted
    records[key] = item
    _save(records)
    return item


def record(text: str, *, source: str = "", tags: str = "", confidence: int = 0) -> dict[str, object] | None:
    text = re.sub(r"\s+", " ", text).strip()
    if not text or re.search(r"<\s*private(?:\s[^>]*)?>", text, flags=re.IGNORECASE):
        return None
    config = load_config().get("patterns", {})
    if not config.get("enabled", True):
        return None
    if is_procedural(text):
        tags = f"{tags},workflow" if tags else "workflow"
    lock = _lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    with _portable_lock(lock):
        return _record_locked(text, source=source, tags=tags, confidence=confidence)


@contextmanager
def _portable_lock(path: Path):
    with open(path, "a+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        else:  # pragma: no cover - exercised on Windows
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)
            else:  # pragma: no cover - exercised on Windows
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Track and promote repeated project workflows")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("record")
    add.add_argument("text")
    add.add_argument("--source", default="")
    add.add_argument("--tags", default="")
    add.add_argument("--confidence", type=int, default=0)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.command == "record":
        item = record(args.text, source=args.source, tags=args.tags, confidence=args.confidence)
        if item:
            print(f"✓ Pattern: {item['occurrences']} occurrences; promoted: {', '.join(item['promoted']) or 'candidate'}")
        return 0
    records = sorted(_load().values(), key=lambda item: int(item.get("occurrences", 0)), reverse=True)
    if not records:
        print("No repeated patterns recorded.")
        return 0
    for item in records:
        paths = [str(item.get(name)) for name in ("knowledge_path", "skill_path") if item.get(name)]
        print(
            f"{item['occurrences']} occurrences | {', '.join(item.get('promoted', [])) or 'candidate'} "
            f"| confidence {item.get('confidence_max', 0)} | {item['text']}"
            + (f" | {', '.join(paths)}" if paths else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
