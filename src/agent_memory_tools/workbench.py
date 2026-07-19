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


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Agent Memory</title><style>
:root{color-scheme:light dark;font:100%/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;--bg:#f5f5f7;--surface:rgba(255,255,255,.72);--text:#1d1d1f;--muted:#6e6e73;--line:rgba(0,0,0,.09);--accent:#0071e3;--shadow:0 16px 44px rgba(0,0,0,.08)}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 72% -10%,#dfeeff 0,transparent 34%),var(--bg);color:var(--text);min-height:100vh}.shell{display:grid;grid-template-columns:15rem 1fr;min-height:100vh}aside{position:sticky;top:0;height:100vh;padding:2rem 1rem;background:rgba(245,245,247,.72);backdrop-filter:blur(28px) saturate(160%);border-right:1px solid var(--line)}.brand{padding:.4rem .75rem 1.8rem}.brand strong{display:block;font-size:1.15rem;letter-spacing:-.02em}.root{font-size:.72rem;color:var(--muted);overflow:hidden;text-overflow:ellipsis}.nav button{width:100%;display:flex;justify-content:space-between;margin:.2rem 0;padding:.65rem .75rem;border:0;border-radius:.65rem;background:transparent;color:var(--text);font:inherit;text-align:left;cursor:pointer;transition:background 120ms ease,transform 120ms ease}.nav button:hover,.nav button.active{background:rgba(0,113,227,.11);color:var(--accent)}.nav button:active,.primary:active{transform:scale(.97)}main{max-width:78rem;width:100%;padding:3.5rem clamp(1.2rem,4vw,4.5rem);display:grid;align-content:start;gap:1.4rem}.hero h1{font-size:clamp(2.2rem,5vw,4rem);line-height:1.04;letter-spacing:-.045em;margin:0}.hero p{color:var(--muted);font-size:1.05rem;margin:.65rem 0 0}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}.card,.panel{background:var(--surface);backdrop-filter:blur(24px) saturate(160%);border:1px solid rgba(255,255,255,.56);box-shadow:var(--shadow);border-radius:1.25rem}.card{padding:1.2rem}.n{font-size:2.1rem;font-weight:650;letter-spacing:-.04em}.label{color:var(--muted);text-transform:capitalize}.panel{padding:1.3rem 1.4rem}.panel h2{margin:0 0 1rem;font-size:1.25rem;letter-spacing:-.025em}.form{display:grid;grid-template-columns:9rem 1fr 2fr auto;gap:.65rem}button,input,select,textarea{font:inherit}input,select,textarea{width:100%;padding:.72rem .8rem;border:1px solid var(--line);border-radius:.7rem;background:rgba(255,255,255,.7);color:var(--text);outline:0}input:focus,select:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(0,113,227,.14)}textarea{min-height:5.2rem;resize:vertical}.primary{align-self:start;padding:.72rem 1rem;border:0;border-radius:.7rem;background:var(--accent);color:white;cursor:pointer;transition:transform 100ms ease,filter 100ms}.primary:hover{filter:brightness(1.08)}.item{padding:1rem 0;border-top:1px solid var(--line)}.item:first-child{border:0}.item b{font-size:1.02rem}.muted{color:var(--muted);font-size:.82rem}pre{margin:.55rem 0 0;white-space:pre-wrap;word-break:break-word;font:inherit;color:var(--muted);max-height:11rem;overflow:auto}@media(prefers-color-scheme:dark){:root{--bg:#09090b;--surface:rgba(28,28,30,.7);--text:#f5f5f7;--muted:#a1a1a6;--line:rgba(255,255,255,.1);--shadow:0 18px 50px rgba(0,0,0,.28)}body{background:radial-gradient(circle at 72% -10%,#102a47 0,transparent 34%),var(--bg)}aside{background:rgba(18,18,20,.72)}input,select,textarea{background:rgba(44,44,46,.76)}.card,.panel{border-color:rgba(255,255,255,.08)}}@media(max-width:760px){.shell{display:block}aside{position:sticky;height:auto;z-index:2;padding:.7rem 1rem;border-right:0;border-bottom:1px solid var(--line)}.brand{padding:.2rem 0 .5rem}.nav{display:flex;gap:.35rem}.nav button{justify-content:center}.nav button span{display:none}main{padding:2rem 1rem}.cards{grid-template-columns:repeat(3,1fr)}.form{grid-template-columns:1fr}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}</style></head><body>
<div class=shell><aside><div class=brand><strong>Agent Memory</strong><div class=root id=root></div></div><nav class=nav id=nav></nav></aside><main><header class=hero><h1>Project intelligence,<br>in one place.</h1><p>Knowledge, skills, and complex-task progress that stay with the project.</p></header><div class=cards id=cards></div><section class=panel><h2>Add to project</h2><form class=form id=form><select id=kind aria-label="Entry type"><option value=knowledge>Knowledge</option><option value=skill>Skill</option><option value=progress>Progress</option></select><input id=name placeholder="Name or task title" required><textarea id=body placeholder="What should the project remember?" required></textarea><button class=primary>Add</button></form></section><section class=panel><h2 id=title></h2><div id=content></div></section></main></div><script>
let state={};const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function show(k){document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.key===k));let rows=state[k]||[];title.textContent=k[0].toUpperCase()+k.slice(1);content.innerHTML=rows.map(x=>`<div class=item><b>${esc(x.title||x.name||x.id)}</b><div class=muted>${esc(x.status||x.path||'')}</div><pre>${esc(x.summary||x.description||x.outcome||'')}</pre></div>`).join('')||'<div class=muted>Nothing here yet.</div>'}
function load(){fetch('/api/state').then(r=>r.json()).then(s=>{state=s;root.textContent=s.root;cards.innerHTML=nav.innerHTML='';for(let k of ['knowledge','skills','progress']){cards.innerHTML+=`<div class=card><div class=n>${s[k].length}</div><div class=label>${k}</div></div>`;nav.innerHTML+=`<button data-key="${k}" onclick="show('${k}')">${k}<span>${s[k].length}</span></button>`}show('progress')})}form.onsubmit=async e=>{e.preventDefault();let button=form.querySelector('button');button.textContent='Adding…';button.disabled=true;let r=await fetch('/api/entry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:kind.value,name:name.value,body:body.value})});button.textContent='Add';button.disabled=false;if(!r.ok)alert(await r.text());else{form.reset();load()}};load();
</script></body></html>"""


def _root() -> Path:
    return Path(os.environ.get("PROJECT_ROOT", os.getcwd())).expanduser().resolve()


def _markdown_entries(directory: Path) -> list[dict[str, str]]:
    result = []
    for path in sorted(directory.rglob("*.md")) if directory.exists() else []:
        text = path.read_text(encoding="utf-8", errors="replace")
        title = next((line.lstrip("# ") for line in text.splitlines() if line.startswith("#")), path.stem)
        result.append({"title": title, "path": str(path.relative_to(_root())), "summary": text[:800]})
    return result


def state() -> dict[str, object]:
    root = _root()
    skills = _markdown_entries(root / "skills")
    for host in (".codex", ".claude", ".pi", ".agy", ".gemini"):
        skills.extend(_markdown_entries(root / host / "skills"))
    unique = {entry["path"]: entry for entry in skills}
    return {"root": str(root), "knowledge": _markdown_entries(root / "wiki"), "skills": list(unique.values()), "progress": list_records()}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/api/state":
            body, content_type = json.dumps(state(), ensure_ascii=False).encode(), "application/json; charset=utf-8"
        elif route == "/":
            body, content_type = HTML.encode(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/entry":
            self.send_error(404); return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 100_000)
            payload = json.loads(self.rfile.read(length))
            kind, name, content = str(payload["kind"]), str(payload["name"]).strip(), str(payload["body"]).strip()
            if not name or not content:
                raise ValueError("name and body are required")
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80] or "entry"
            if kind == "knowledge":
                path = _root() / "wiki" / "concepts" / f"{slug}.md"
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(f"# {name}\n\n{content}\n", encoding="utf-8")
            elif kind == "skill":
                path = _root() / "skills" / slug / "SKILL.md"
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(f"---\nname: {slug}\ndescription: Project skill created from the local workbench.\n---\n\n# {name}\n\n{content}\n", encoding="utf-8")
            elif kind == "progress":
                from .progress import create
                create(name, outcome=content, plan=content)
            else:
                raise ValueError("unsupported entry kind")
            body = b'{"ok":true}'
            self.send_response(201); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self.send_error(400, str(exc))

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
