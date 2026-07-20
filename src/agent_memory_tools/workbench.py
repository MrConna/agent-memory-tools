"""Local-only web workbench for project knowledge, skills, and progress."""

from __future__ import annotations

import argparse
import json
import os
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .progress import list_records


STATIC_DIR = Path(__file__).with_name("static")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


def _root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def _markdown_entries(directory: Path) -> list[dict[str, str]]:
    result = []
    for path in sorted(directory.rglob("*.md")) if directory.exists() else []:
        text = path.read_text(encoding="utf-8", errors="replace")
        title = next((line.lstrip("# ") for line in text.splitlines() if line.startswith("#")), path.stem)
        preview = " ".join(
            line.strip() for line in text.splitlines()
            if line.strip() and not line.startswith(("#", "---"))
        )[:240]
        result.append({
            "title": title,
            "path": str(path.relative_to(_root())),
            "summary": preview,
            "content": text,
        })
    return result


def _progress_entries() -> list[dict[str, object]]:
    root = _root()
    entries = list_records()
    for entry in entries:
        markdown = root / "progress" / f"{entry['id']}.md"
        entry["content"] = markdown.read_text(encoding="utf-8") if markdown.exists() else json.dumps(entry, ensure_ascii=False, indent=2)
        entry["summary"] = str(entry.get("outcome") or entry.get("plan") or "")[:240]
    return entries


def state() -> dict[str, object]:
    root = _root()
    skills = _markdown_entries(root / "skills")
    for host in (".codex", ".claude", ".pi", ".agy", ".gemini"):
        skills.extend(_markdown_entries(root / host / "skills"))
    unique = {entry["path"]: entry for entry in skills}
    return {
        "root": str(root),
        "knowledge": _markdown_entries(root / "wiki"),
        "skills": list(unique.values()),
        "progress": _progress_entries(),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/state":
            self._send(json.dumps(state(), ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return
        relative = "index.html" if route == "/" else route.removeprefix("/assets/") if route.startswith("/assets/") else ""
        path = (STATIC_DIR / relative).resolve()
        if not relative or STATIC_DIR.resolve() not in path.parents or not path.is_file():
            self.send_error(404)
            return
        self._send(path.read_bytes(), CONTENT_TYPES.get(path.suffix, "application/octet-stream"))

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/entry":
            self.send_error(404)
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 100_000)
            payload = json.loads(self.rfile.read(length))
            kind = str(payload["kind"])
            name = str(payload["name"]).strip()
            content = str(payload["body"]).strip()
            if not name or not content:
                raise ValueError("name and body are required")
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80] or "entry"
            if kind == "knowledge":
                path = _root() / "wiki" / "concepts" / f"{slug}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"# {name}\n\n{content}\n", encoding="utf-8")
            elif kind == "skill":
                path = _root() / "skills" / slug / "SKILL.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f"---\nname: {slug}\ndescription: Project skill created from the local workbench.\n---\n\n# {name}\n\n{content}\n",
                    encoding="utf-8",
                )
            elif kind == "progress":
                from .progress import create
                create(name, outcome=content, plan=content)
            else:
                raise ValueError("unsupported entry kind")
            self._send(b'{"ok":true}', "application/json", status=201)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self.send_error(400, str(exc))

    def _send(self, body: bytes, content_type: str, *, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local Agent Memory Workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Workbench only supports loopback hosts to protect project knowledge")
    if not (STATIC_DIR / "index.html").exists():
        raise SystemExit("Workbench assets are missing; run `npm --prefix web run build`")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{server.server_port}"
    print(f"Agent Memory Workbench: {url}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
