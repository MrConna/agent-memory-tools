"""Rebuildable SQLite B-tree and FTS5 index over project agent knowledge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass
class Entry:
    key: str
    kind: str
    title: str
    content: str
    summary: str = ""
    tags: str = ""
    source: str = ""
    path: str = ""
    confidence: int = 0
    status: str = ""
    created_at: str = ""
    updated_at: str = ""
    stale: int = 0
    metadata: str = "{}"


def _root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def _db_path() -> Path:
    return _root() / "memory" / "index.db"


def _vector_path() -> Path:
    return _root() / "memory" / "index-vectors.npz"


def _vector_failure_path() -> Path:
    return _root() / "memory" / "index-vectors.failed.json"


def _source_files() -> list[Path]:
    root = _root()
    files = [
        root / "memory" / "learnings.jsonl",
        root / "memory" / "contexts.jsonl",
        root / "memory" / "observations.jsonl",
        root / "memory" / "patterns.json",
        root / "memory" / "config.json",
    ]
    for directory in (
        root / "memory" / "wiki" / "pages", root / "wiki", root / "knowledge",
        root / "memory" / "rules", root / "memory" / "concepts",
        root / "memory" / "entities", root / "skills", root / "progress",
        root / ".codex" / "skills", root / ".claude" / "skills",
        root / ".pi" / "skills", root / ".agy" / "skills", root / ".gemini" / "skills",
    ):
        if directory.exists():
            files.extend(directory.rglob("*.md"))
            if directory == root / "progress":
                files.extend(directory.glob("*.json"))
    return sorted({path.resolve() for path in files if path.exists() and path.is_file()})


def _source_stat_signature() -> str:
    digest = hashlib.sha256()
    for path in _source_files():
        stat = path.stat()
        digest.update(f"{_relative(path)}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()


def _source_content_signature() -> str:
    digest = hashlib.sha256()
    for path in _source_files():
        digest.update(f"{_relative(path)}\0".encode())
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\n")
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_root()))
    except ValueError:
        return str(path.resolve())


def _markdown_title(text: str, fallback: str) -> str:
    return next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), fallback)


def _summary(text: str, limit: int = 240) -> str:
    return " ".join(
        line.strip() for line in text.splitlines()
        if line.strip() and not line.startswith(("#", "---"))
    )[:limit]


def _json_text(item: dict[str, object], fields: Iterable[str]) -> str:
    values = []
    for field in fields:
        value = item.get(field, "")
        if isinstance(value, list):
            values.extend(str(part) for part in value)
        elif isinstance(value, dict):
            values.append(json.dumps(value, ensure_ascii=False))
        elif value:
            values.append(str(value))
    return "\n".join(values)


def _memory_entries() -> Iterable[Entry]:
    path = _root() / "memory" / "learnings.jsonl"
    for item in _read_jsonl(path):
        pattern = str(item.get("pattern", ""))
        yield Entry(
            key=f"memory:{item.get('id', hashlib.sha1(pattern.encode()).hexdigest()[:12])}",
            kind="memory", title=pattern[:120] or "Untitled memory",
            content=_json_text(item, ("pattern", "context", "tags", "files")),
            summary=str(item.get("context", ""))[:240],
            tags=" ".join(str(tag) for tag in item.get("tags", [])),
            source=str(item.get("source", "")), path=_relative(path),
            confidence=int(item.get("confidence", 0) or 0),
            status="stale" if item.get("stale") else "active",
            created_at=str(item.get("created_at", "")),
            updated_at=str(item.get("last_referenced", "")),
            stale=int(bool(item.get("stale"))), metadata=json.dumps(item, ensure_ascii=False),
        )


def _context_entries() -> Iterable[Entry]:
    path = _root() / "memory" / "contexts.jsonl"
    for item in _read_jsonl(path):
        title = str(item.get("description", "")) or "Saved context"
        yield Entry(
            key=f"context:{item.get('id', hashlib.sha1(title.encode()).hexdigest()[:12])}",
            kind="context", title=title, content=_json_text(
                item, ("description", "decisions", "remaining_work", "failed_approaches", "artifacts", "git")
            ), summary="; ".join(str(x) for x in item.get("remaining_work", []))[:240],
            source=str(item.get("session_id", "")), path=_relative(path), status="saved",
            created_at=str(item.get("created_at", "")), updated_at=str(item.get("created_at", "")),
            metadata=json.dumps(item, ensure_ascii=False),
        )


def _observation_entries() -> Iterable[Entry]:
    path = _root() / "memory" / "observations.jsonl"
    for item in _read_jsonl(path):
        content = str(item.get("text", ""))
        yield Entry(
            key=f"observation:{item.get('id', hashlib.sha1(content.encode()).hexdigest()[:12])}",
            kind="observation", title=content[:120] or "Observation", content=content,
            summary=content[:240], source=str(item.get("agent", "")), path=_relative(path),
            status=str(item.get("kind", "observed")), created_at=str(item.get("at", "")),
            updated_at=str(item.get("at", "")), metadata=json.dumps(item, ensure_ascii=False),
        )


def _pattern_entries() -> Iterable[Entry]:
    path = _root() / "memory" / "patterns.json"
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(records, dict):
        return
    for key, item in records.items():
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", ""))
        yield Entry(
            key=f"pattern:{key}", kind="pattern", title=text[:120] or "Repeated pattern",
            content=_json_text(item, ("text", "tags", "promoted", "sources")),
            summary=f"{item.get('occurrences', 0)} occurrences; promoted: {', '.join(item.get('promoted', [])) or 'candidate'}",
            tags=" ".join(str(tag) for tag in item.get("tags", [])),
            source="lifecycle", path=_relative(path),
            confidence=int(item.get("confidence_max", 0) or 0),
            status="promoted" if item.get("promoted") else "candidate",
            created_at=str(item.get("first_seen", "")), updated_at=str(item.get("last_seen", "")),
            metadata=json.dumps(item, ensure_ascii=False),
        )


def _markdown_entries() -> Iterable[Entry]:
    roots = (
        ("knowledge", _root() / "memory" / "wiki" / "pages"),
        ("knowledge", _root() / "wiki"),
        ("knowledge", _root() / "knowledge"),
        ("rule", _root() / "memory" / "rules"),
        ("knowledge", _root() / "memory" / "concepts"),
        ("entity", _root() / "memory" / "entities"),
        ("skill", _root() / "skills"),
        ("skill", _root() / ".codex" / "skills"),
        ("skill", _root() / ".claude" / "skills"),
        ("skill", _root() / ".pi" / "skills"),
        ("skill", _root() / ".agy" / "skills"),
        ("skill", _root() / ".gemini" / "skills"),
    )
    seen: set[str] = set()
    skill_names: set[str] = set()
    for kind, directory in roots:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.md")):
            display = _relative(path)
            if display in seen:
                continue
            skill_name = path.parent.name if kind == "skill" and path.name == "SKILL.md" else ""
            if skill_name and skill_name in skill_names:
                continue
            seen.add(display)
            if skill_name:
                skill_names.add(skill_name)
            text = path.read_text(encoding="utf-8", errors="replace")
            stat = path.stat()
            timestamp = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            yield Entry(
                key=f"{kind}:{skill_name or display}", kind=kind, title=_markdown_title(text, path.stem),
                content=text, summary=_summary(text), source=display, path=display,
                status="active", updated_at=timestamp,
            )


def _progress_entries() -> Iterable[Entry]:
    directory = _root() / "progress"
    if not directory.exists():
        return
    for path in sorted(directory.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        markdown = path.with_suffix(".md")
        content = markdown.read_text(encoding="utf-8", errors="replace") if markdown.exists() else json.dumps(item, ensure_ascii=False, indent=2)
        yield Entry(
            key=f"progress:{item.get('id', path.stem)}", kind="progress",
            title=str(item.get("title", path.stem)), content=content,
            summary=str(item.get("outcome", ""))[:240], path=_relative(path),
            status=str(item.get("status", "")), created_at=str(item.get("created_at", "")),
            updated_at=str(item.get("updated_at", "")), metadata=json.dumps(item, ensure_ascii=False),
        )


def collect_entries() -> list[Entry]:
    return (
        list(_memory_entries()) + list(_context_entries()) + list(_observation_entries())
        + list(_pattern_entries()) + list(_markdown_entries()) + list(_progress_entries())
    )


def _search_tokens(text: str) -> str:
    normalized = text.lower()
    tokens = re.findall(r"[a-z0-9_.-]+", normalized)
    for run in re.findall(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+", normalized):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return " ".join(dict.fromkeys(token for token in tokens if token))


def _query_tokens(text: str) -> list[str]:
    normalized = text.lower()
    tokens = re.findall(r"[a-z0-9_.-]+", normalized)
    for run in re.findall(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+", normalized):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return list(dict.fromkeys(tokens))


def rebuild() -> int:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="index-", suffix=".db.tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    for _ in range(3):
        stat_signature = _source_stat_signature()
        content_signature = _source_content_signature()
        entries = collect_entries()
        if stat_signature == _source_stat_signature() and content_signature == _source_content_signature():
            break
    else:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Project sources kept changing during index rebuild; retry when writes settle")
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript("""
            PRAGMA journal_mode=DELETE;
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY, entry_key TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
                title TEXT NOT NULL, content TEXT NOT NULL, summary TEXT NOT NULL,
                tags TEXT NOT NULL, source TEXT NOT NULL, path TEXT NOT NULL,
                confidence INTEGER NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                stale INTEGER NOT NULL, metadata TEXT NOT NULL
            );
            CREATE INDEX idx_entries_kind_updated ON entries(kind, updated_at DESC);
            CREATE INDEX idx_entries_confidence ON entries(confidence DESC);
            CREATE INDEX idx_entries_status ON entries(status);
            CREATE INDEX idx_entries_stale ON entries(stale);
            CREATE INDEX idx_entries_filter ON entries(kind, stale, status, confidence DESC);
            CREATE VIRTUAL TABLE entries_fts USING fts5(title, content, tags, tokens, tokenize='unicode61');
            CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        for entry in entries:
            cursor = connection.execute(
                """INSERT INTO entries(entry_key,kind,title,content,summary,tags,source,path,confidence,status,created_at,updated_at,stale,metadata)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (entry.key, entry.kind, entry.title, entry.content, entry.summary, entry.tags,
                 entry.source, entry.path, entry.confidence, entry.status, entry.created_at,
                 entry.updated_at, entry.stale, entry.metadata),
            )
            connection.execute(
                "INSERT INTO entries_fts(rowid,title,content,tags,tokens) VALUES(?,?,?,?,?)",
                (cursor.lastrowid, entry.title, entry.content, entry.tags,
                 _search_tokens(f"{entry.title} {entry.content} {entry.tags}")),
            )
        connection.execute("INSERT INTO index_meta VALUES('schema_version','1')")
        connection.execute("INSERT INTO index_meta VALUES('built_at',?)", (datetime.now(timezone.utc).isoformat(),))
        connection.execute("INSERT INTO index_meta VALUES('source_stat_signature',?)", (stat_signature,))
        connection.execute("INSERT INTO index_meta VALUES('source_content_signature',?)", (content_signature,))
        connection.execute("INSERT INTO index_meta VALUES('deep_checked_at',?)", (str(datetime.now(timezone.utc).timestamp()),))
        connection.commit()
    except Exception:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    else:
        connection.close()
    _rebuild_vectors(entries, content_signature)
    os.replace(temporary, path)
    return len(entries)


def _rebuild_vectors(entries: list[Entry], signature: str) -> None:
    from .config import load_config

    config = load_config(_root()).get("search", {})
    if not config.get("semantic_enabled", False):
        _vector_path().unlink(missing_ok=True)
        _vector_failure_path().unlink(missing_ok=True)
        return
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(str(config.get("semantic_model")))
        texts = [f"{entry.title}\n{entry.summary}\n{entry.content}" for entry in entries]
        vectors = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix="vectors-", suffix=".npz.tmp", dir=_vector_path().parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        with open(temporary, "wb") as handle:
            np.savez(
                handle, vectors=np.asarray(vectors, dtype=np.float32),
                keys=np.asarray([entry.key for entry in entries]), signature=np.asarray(signature),
            )
        os.replace(temporary, _vector_path())
        _vector_failure_path().unlink(missing_ok=True)
    except Exception as exc:
        if "temporary" in locals():
            temporary.unlink(missing_ok=True)
        _vector_path().unlink(missing_ok=True)
        _vector_failure_path().write_text(
            json.dumps({
                "signature": signature,
                "model": str(config.get("semantic_model")),
                "error": str(exc),
            }, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _database_signature(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT value FROM index_meta WHERE key='source_content_signature'").fetchone()
    return str(row[0]) if row else ""


def _fts_query(query: str) -> str:
    tokens = _query_tokens(query)
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def query(
    text: str, *, kinds: list[str] | None = None, top: int = 10,
    confidence_min: int = 0, memory_confidence_min: int = 0,
    status: str = "", include_stale: bool = False,
) -> list[dict[str, object]]:
    from .config import load_config

    config = load_config(_root()).get("search", {})
    if not _db_path().exists() or (config.get("auto_rebuild", True) and not _index_is_fresh()):
        rebuild()
    match = _fts_query(text)
    if not match:
        return []
    where = ["entries_fts MATCH ?", "e.confidence >= ?"]
    parameters: list[object] = [match, confidence_min]
    if not include_stale:
        where.append("e.stale = 0")
    if kinds:
        where.append("e.kind IN (" + ",".join("?" for _ in kinds) + ")")
        parameters.extend(kinds)
    if status:
        where.append("e.status = ?")
        parameters.append(status)
    if memory_confidence_min:
        where.append("(e.kind != 'memory' OR e.confidence >= ?)")
        parameters.append(memory_confidence_min)
    lexical_target = max(50, top * 5) if config.get("semantic_enabled", False) else top
    sql = f"""
        SELECT e.*, bm25(entries_fts, 6.0, 1.0, 2.0, 0.5) AS bm25_score
        FROM entries_fts JOIN entries e ON e.id = entries_fts.rowid
        WHERE {' AND '.join(where)}
        ORDER BY bm25_score ASC, e.confidence DESC, e.updated_at DESC
    """
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    try:
        query_tokens = set(_query_tokens(text))
        minimum_coverage = min(1.0, max(0.0, float(config.get("lexical_min_coverage", 0.6))))
        lexical = []
        for raw in connection.execute(sql, parameters):
            row = dict(raw)
            document_tokens = set(_search_tokens(f"{row['title']} {row['content']} {row['tags']}").split())
            coverage = len(query_tokens & document_tokens) / len(query_tokens)
            if coverage >= minimum_coverage:
                row["lexical_coverage"] = coverage
                lexical.append(row)
                if len(lexical) >= lexical_target:
                    break
        semantic = _semantic_matches(
            text, top=max(50, top * 5), config=config,
            database_signature=_database_signature(connection),
        )
        if not semantic:
            return lexical[:top]
        by_key = {str(row["entry_key"]): row for row in lexical}
        missing = [key for key, _ in semantic if key not in by_key]
        if missing:
            placeholders = ",".join("?" for _ in missing)
            extra = connection.execute(f"SELECT *, 0.0 AS bm25_score FROM entries WHERE entry_key IN ({placeholders})", missing)
            by_key.update({str(row["entry_key"]): dict(row) for row in extra})
        lexical_rank = {str(row["entry_key"]): rank for rank, row in enumerate(lexical, 1)}
        semantic_score = dict(semantic)
        semantic_weight = min(1.0, max(0.0, float(config.get("semantic_weight", 0.35))))
        candidates = []
        for key, row in by_key.items():
            if kinds and str(row["kind"]) not in kinds:
                continue
            if int(row["confidence"]) < confidence_min:
                continue
            if str(row["kind"]) == "memory" and int(row["confidence"]) < memory_confidence_min:
                continue
            if not include_stale and int(row["stale"]):
                continue
            if status and str(row["status"]) != status:
                continue
            lexical_component = 1 / (1 + lexical_rank[key]) if key in lexical_rank else 0.0
            semantic_component = max(0.0, float(semantic_score.get(key, 0.0)))
            confidence_component = float(row.get("confidence", 0)) / 200
            row["semantic_score"] = semantic_component
            row["combined_score"] = (1 - semantic_weight) * lexical_component + semantic_weight * semantic_component + confidence_component
            candidates.append(row)
        candidates.sort(key=lambda row: (-float(row["combined_score"]), -int(row["confidence"])))
        return candidates[:top]
    finally:
        connection.close()


def _index_is_fresh() -> bool:
    from .config import load_config

    try:
        connection = sqlite3.connect(_db_path())
        metadata = dict(connection.execute("SELECT key, value FROM index_meta"))
        current_stat = _source_stat_signature()
        interval = max(0, int(load_config(_root()).get("search", {}).get("deep_freshness_check_seconds", 300)))
        last_deep = float(metadata.get("deep_checked_at", "0"))
        deep_due = datetime.now(timezone.utc).timestamp() - last_deep >= interval
        if metadata.get("source_stat_signature") == current_stat and not deep_due:
            return True
        current_content = _source_content_signature()
        if metadata.get("source_content_signature") != current_content:
            return False
        connection.execute(
            "INSERT OR REPLACE INTO index_meta(key,value) VALUES('source_stat_signature',?)", (current_stat,)
        )
        connection.execute(
            "INSERT OR REPLACE INTO index_meta(key,value) VALUES('deep_checked_at',?)",
            (str(datetime.now(timezone.utc).timestamp()),),
        )
        connection.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        if "connection" in locals():
            connection.close()


def _semantic_matches(
    text: str, *, top: int, config: dict[str, object], database_signature: str,
) -> list[tuple[str, float]]:
    if not config.get("semantic_enabled", False):
        return []
    if not _vector_generation_matches(database_signature):
        if not _vector_failure_matches(database_signature, str(config.get("semantic_model"))):
            _recover_vectors_from_database(database_signature)
    if not _vector_path().exists():
        return []
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        with np.load(_vector_path()) as archive:
            keys = archive["keys"].tolist()
            signature = str(archive["signature"].item())
            vectors = archive["vectors"].copy()
        if signature != database_signature or not isinstance(keys, list):
            return []
        if vectors.ndim != 2 or vectors.shape[0] != len(keys):
            return []
        model = SentenceTransformer(str(config.get("semantic_model")))
        query_vector = model.encode([text], normalize_embeddings=True)[0]
        similarities = vectors @ query_vector
        indices = np.argsort(similarities)[::-1][:top]
        threshold = float(config.get("semantic_threshold", 0.25))
        return [(str(keys[index]), float(similarities[index])) for index in indices if float(similarities[index]) >= threshold]
    except Exception:
        return []


def _vector_generation_matches(database_signature: str) -> bool:
    if not _vector_path().exists():
        return False
    try:
        import numpy as np
        with np.load(_vector_path()) as archive:
            return str(archive["signature"].item()) == database_signature
    except Exception:
        return False


def _vector_failure_matches(database_signature: str, model: str) -> bool:
    if not _vector_failure_path().exists():
        return False
    try:
        failure = json.loads(_vector_failure_path().read_text(encoding="utf-8"))
        return failure.get("signature") == database_signature and failure.get("model") == model
    except (OSError, json.JSONDecodeError):
        return False


def _recover_vectors_from_database(database_signature: str) -> None:
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    try:
        entries = [
            Entry(
                key=str(row["entry_key"]), kind=str(row["kind"]), title=str(row["title"]),
                content=str(row["content"]), summary=str(row["summary"]), tags=str(row["tags"]),
            )
            for row in connection.execute("SELECT entry_key,kind,title,content,summary,tags FROM entries ORDER BY id")
        ]
    finally:
        connection.close()
    _rebuild_vectors(entries, database_signature)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unified local project search")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rebuild", help="Rebuild memory/index.db from project source files")
    find = sub.add_parser("query", help="Search indexed project intelligence")
    find.add_argument("query")
    find.add_argument("--type", dest="kinds", action="append", default=[])
    find.add_argument("--top", type=_positive_int, default=10)
    find.add_argument("--confidence-min", type=_nonnegative_int, default=0)
    find.add_argument("--memory-confidence-min", type=_nonnegative_int, default=0)
    find.add_argument("--status", default="")
    find.add_argument("--include-stale", action="store_true")
    find.add_argument("--json", action="store_true")
    find.add_argument("--full", action="store_true", help="Print full indexed content")
    find.add_argument("--max-chars", type=_positive_int, default=4000)
    args = parser.parse_args(argv)
    if args.command == "rebuild":
        count = rebuild()
        print(f"✓ Indexed {count} project entries → memory/index.db")
        return 0
    results = query(
        args.query, kinds=args.kinds, top=args.top, confidence_min=args.confidence_min,
        memory_confidence_min=args.memory_confidence_min,
        status=args.status, include_stale=args.include_stale,
    )
    if args.json:
        print(json.dumps(results, ensure_ascii=False))
        return 0
    if not results:
        print(f"No indexed entries match '{args.query}'")
        return 0
    print(f"Found {len(results)} indexed entr{'y' if len(results) == 1 else 'ies'}:\n")
    for result in results:
        confidence = f" confidence={result['confidence']}" if result["confidence"] else ""
        print(f"  [{result['kind']}] {result['title']}{confidence}")
        if result["summary"]:
            print(f"           {result['summary'][:240]}")
        print(f"           {result['path']}")
        if args.full:
            print("\n" + str(result["content"])[: args.max_chars] + "\n")
    return 0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
