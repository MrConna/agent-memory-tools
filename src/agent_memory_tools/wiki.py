#!/usr/bin/env python3
"""Wiki memory CLI — project-local Markdown working knowledge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd()))


def _wiki_dir() -> Path:
    path = _home() / "memory" / "wiki"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pages_dir() -> Path:
    path = _wiki_dir() / "pages"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sources_file() -> Path:
    return _wiki_dir() / "sources.jsonl"


def _index_file() -> Path:
    return _wiki_dir() / "index.md"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or "untitled"


def _project_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return _home() / candidate


def _ensure_project_local(path: Path) -> None:
    try:
        path.resolve().relative_to(_home().resolve())
    except ValueError:
        print(f"✗ Source outside project: {path}", file=sys.stderr)
        sys.exit(1)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_home().resolve()))
    except ValueError:
        return str(path.resolve())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_jsonl(path: Path, *, strict: bool = False) -> list[dict]:
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
            except json.JSONDecodeError as exc:
                message = f"{path.name} line {i} invalid JSON: {exc.msg}"
                if strict:
                    print(f"✗ {message}", file=sys.stderr)
                    sys.exit(1)
                print(f"WARN: {message}, skipping", file=sys.stderr)
    return records


def _save_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _load_sources() -> list[dict]:
    return _load_jsonl(_sources_file(), strict=True)


def _save_sources(records: list[dict]) -> None:
    _save_jsonl(_sources_file(), records)


def _page_path(slug: str) -> Path:
    return _pages_dir() / f"{_slug(slug)}.md"


def _read_page(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, object] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip().strip('"') for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value.strip('"')
    return meta, body


def _format_list(values: list[str]) -> str:
    return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in values) + "]"


def _write_page(slug: str, title: str, summary: str, sources: list[str]) -> Path:
    page = _page_path(slug)
    created = _now()
    if page.exists():
        meta, _ = _read_page(page)
        created = str(meta.get("created_at") or created)

    source_lines = "\n".join(f"- `{source}`" for source in sources) or "- None"
    body = f"""---
slug: "{_slug(slug)}"
title: "{title}"
sources: {_format_list(sources)}
created_at: "{created}"
updated_at: "{_now()}"
stale: "false"
---

# {title}

{summary}

## Sources

{source_lines}
"""
    page.write_text(body, encoding="utf-8")
    return page


def _refresh_index() -> None:
    pages = []
    for page in sorted(_pages_dir().glob("*.md")):
        meta, body = _read_page(page)
        title = meta.get("title") or page.stem
        stale = " [STALE]" if str(meta.get("stale", "")).lower() == "true" else ""
        first_line = next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")), "")
        pages.append(f"- [{title}](pages/{page.name}){stale} — {first_line[:120]}")

    content = "# Wiki Memory\n\n"
    if pages:
        content += "\n".join(pages) + "\n"
    else:
        content += "No wiki pages yet.\n"
    _index_file().write_text(content, encoding="utf-8")


def _init_wiki() -> None:
    _pages_dir()
    if not _sources_file().exists():
        _sources_file().write_text("", encoding="utf-8")
    if not _index_file().exists():
        _refresh_index()


def cmd_init(args: argparse.Namespace) -> None:
    _init_wiki()
    print(f"✓ Wiki memory initialized: {_wiki_dir()}")


def _add_sources(paths: list[str], *, allow_external: bool = False) -> None:
    _init_wiki()
    records = _load_sources()
    by_path = {r.get("path"): r for r in records}
    changed = 0

    for raw in paths:
        path = _project_path(raw)
        if not allow_external:
            _ensure_project_local(path)
        if not path.exists() or not path.is_file():
            print(f"✗ Source not found: {raw}", file=sys.stderr)
            sys.exit(1)
        display = _display_path(path)
        digest = _sha256(path)
        stat = path.stat()
        record = by_path.get(display)
        if record:
            if record.get("sha256") != digest:
                changed += 1
            record.update({
                "sha256": digest,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "updated_at": _now(),
                "missing": False,
                "stale": False,
            })
            record.pop("current_sha256", None)
        else:
            record = {
                "path": display,
                "sha256": digest,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "pages": [],
                "created_at": _now(),
                "updated_at": _now(),
                "missing": False,
                "stale": False,
            }
            records.append(record)
            by_path[display] = record
        print(f"✓ Source tracked: {display}")

    _save_sources(records)
    print(f"{len(paths)} source(s) tracked, {changed} changed")


def cmd_add_source(args: argparse.Namespace) -> None:
    _add_sources(args.paths, allow_external=args.allow_external)


def cmd_add_page(args: argparse.Namespace) -> None:
    _init_wiki()
    slug = _slug(args.slug)
    source_paths = [_project_path(source) for source in args.source]
    if not args.allow_external:
        for source_path in source_paths:
            _ensure_project_local(source_path)
    sources = [_display_path(source_path) for source_path in source_paths]
    if args.source and args.track_sources:
        _add_sources(args.source, allow_external=args.allow_external)

    page = _write_page(slug, args.title or slug.replace("-", " ").title(), args.summary, sources)

    records = _load_sources()
    for record in records:
        if record.get("path") in sources:
            pages = list(record.get("pages", []))
            if slug not in pages:
                pages.append(slug)
            record["pages"] = sorted(pages)
            record["updated_at"] = _now()
    _save_sources(records)
    _refresh_index()
    print(f"✓ Wiki page written: {_display_path(page)}")


def cmd_search(args: argparse.Namespace) -> None:
    _init_wiki()
    keywords = [kw.lower() for kw in args.query.split() if kw.strip()]
    if not keywords:
        print("No query provided.")
        return

    scored = []
    for page in sorted(_pages_dir().glob("*.md")):
        meta, body = _read_page(page)
        haystack = f"{meta.get('title', '')} {body}".lower()
        hits = sum(1 for kw in keywords if kw in haystack)
        if hits:
            scored.append((hits, page, meta, body))

    if not scored:
        print(f"No wiki pages match '{args.query}'")
        return

    scored.sort(key=lambda item: (-item[0], item[1].name))
    print(f"Found {len(scored)} wiki page(s), showing top {min(len(scored), args.top)}:\n")
    for hits, page, meta, body in scored[: args.top]:
        title = meta.get("title") or page.stem
        stale = " [STALE]" if str(meta.get("stale", "")).lower() == "true" else ""
        snippet = next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")), "")
        print(f"  {page.stem}{stale} ({hits} hit{'s' if hits != 1 else ''}) — {title}")
        if snippet:
            print(f"           {snippet[:120]}")


def _set_page_stale(slug: str, stale: bool) -> None:
    path = _page_path(slug)
    if not path.exists():
        return
    meta, body = _read_page(path)
    meta["stale"] = "true" if stale else "false"
    meta["updated_at"] = _now()
    lines = ["---"]
    for key in ("slug", "title", "sources", "created_at", "updated_at", "stale"):
        value = meta.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key}: {_format_list([str(v) for v in value])}")
        else:
            lines.append(f'{key}: "{value}"')
    lines.append("---")
    path.write_text("\n".join(lines) + "\n" + body, encoding="utf-8")


def cmd_sync(args: argparse.Namespace) -> None:
    _init_wiki()
    records = _load_sources()
    stale_pages: set[str] = set()
    missing = 0
    changed = 0

    for record in records:
        path = _project_path(str(record.get("path", "")))
        if not path.exists() or not path.is_file():
            record["missing"] = True
            record["updated_at"] = _now()
            missing += 1
            stale_pages.update(str(p) for p in record.get("pages", []))
            continue
        digest = _sha256(path)
        record["missing"] = False
        if digest != record.get("sha256"):
            record["current_sha256"] = digest
            record["stale"] = True
            record["updated_at"] = _now()
            changed += 1
            stale_pages.update(str(p) for p in record.get("pages", []))

    for slug in stale_pages:
        _set_page_stale(slug, True)

    _save_sources(records)
    _refresh_index()
    if stale_pages:
        print(f"Found {len(stale_pages)} stale wiki page(s): {', '.join(sorted(stale_pages))}")
    else:
        print("Wiki is up to date.")
    if changed or missing:
        print(f"Sources changed={changed} missing={missing}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wiki memory CLI — Markdown working knowledge")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize memory/wiki")

    p_add_source = sub.add_parser("add-source", help="Track source files by path and hash")
    p_add_source.add_argument("paths", nargs="+", help="Source files to track")
    p_add_source.add_argument("--allow-external", action="store_true", help="Allow sources outside the project root")

    p_add_page = sub.add_parser("add-page", help="Create or replace a wiki page")
    p_add_page.add_argument("slug", help="Page slug")
    p_add_page.add_argument("--title", default="", help="Display title")
    p_add_page.add_argument("--summary", required=True, help="Markdown summary body")
    p_add_page.add_argument("--source", action="append", default=[], help="Source path for this page")
    p_add_page.add_argument("--allow-external", action="store_true", help="Allow sources outside the project root")
    p_add_page.add_argument("--no-track-sources", dest="track_sources", action="store_false")
    p_add_page.set_defaults(track_sources=True)

    p_search = sub.add_parser("search", help="Keyword search wiki pages")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--top", type=int, default=10, help="Max results")

    sub.add_parser("sync", help="Mark pages stale when tracked sources change")

    args = parser.parse_args()
    commands = {
        "init": cmd_init,
        "add-source": cmd_add_source,
        "add-page": cmd_add_page,
        "search": cmd_search,
        "sync": cmd_sync,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
