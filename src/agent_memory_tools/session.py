#!/usr/bin/env python3
"""
Agent Session Command — bind an agent session to a stable CLI entrypoint.

Supports Codex, pi, and Claude Code. Creates a named command (e.g. `prism-vqa`)
that resumes the bound session from any terminal.

In tmux environments, the tool prefers tmux session management: it attaches to
an existing tmux session or creates a new detached tmux session running the
agent resume command.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REGISTRY = Path.home() / ".agent-memory-tools" / "session-commands.json"
DEFAULT_BIN_DIR = Path.home() / ".local" / "bin"
COMMAND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

RUNTIME_DEFAULTS: dict[str, dict[str, Any]] = {
    "codex": {
        "bin": "codex",
        "resume_template": "{bin} resume -C {cwd}{profile_arg} {session_id}",
        "profile_flag": "--profile",
        "session_id_env": "CODEX_THREAD_ID",
    },
    "pi": {
        "bin": "pi",
        "resume_template": "{bin} --session-id {session_id}{extra_args}",
        "profile_flag": None,
        "session_id_env": "PI_SESSION_ID",
    },
    "claude": {
        "bin": "claude",
        "resume_template": "{bin} --continue --cwd {cwd}{name_arg}{extra_args}",
        "profile_flag": None,
        "session_id_env": None,
    },
}


def die(message: str) -> None:
    print(f"session-command: {message}", file=sys.stderr)
    raise SystemExit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "commands": {}}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        die(f"registry must be a JSON object: {path}")
    commands = data.setdefault("commands", {})
    if not isinstance(commands, dict):
        die(f"registry commands must be a JSON object: {path}")
    data.setdefault("version", 1)
    return data


def write_registry(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def validate_command_name(name: str) -> None:
    if not COMMAND_RE.fullmatch(name):
        die("command name must use only letters, numbers, dot, underscore, or dash, and cannot start empty")


def resolve_session_id(runtime: str, value: str | None) -> str:
    env_key = RUNTIME_DEFAULTS[runtime].get("session_id_env")
    session_id = value or (os.environ.get(env_key, "") if env_key else "")
    if not session_id:
        die(f"missing session id for {runtime}; pass --session-id or set {env_key or 'the relevant env var'}")
    return session_id


def normalize_cwd(value: str | None) -> str:
    cwd = Path(value or os.getcwd()).expanduser()
    if not cwd.exists():
        die(f"cwd does not exist: {cwd}")
    return str(cwd.resolve())


def detect_default_backend() -> str:
    """Prefer tmux when already running inside tmux."""
    return "tmux" if os.environ.get("TMUX") else "native"


def build_native_resume_command(binding: dict[str, Any], extra_args: list[str]) -> list[str]:
    runtime = binding["runtime"]
    defaults = RUNTIME_DEFAULTS[runtime]
    template = binding.get("resume_template") or defaults["resume_template"]
    bin_name = binding.get("bin") or defaults["bin"]

    profile_arg = ""
    profile = binding.get("profile")
    if profile and defaults.get("profile_flag"):
        profile_arg = f" {defaults['profile_flag']} {shlex.quote(profile)}"

    name_arg = ""
    name = binding.get("name")
    if name and runtime == "claude":
        name_arg = f" --name {shlex.quote(name)}"

    extra = ""
    if extra_args:
        extra = " " + " ".join(shlex.quote(a) for a in extra_args)
    elif binding.get("extra_args"):
        extra = " " + " ".join(shlex.quote(a) for a in binding["extra_args"])

    raw = template.format(
        bin=bin_name,
        cwd=shlex.quote(binding["cwd"]),
        session_id=shlex.quote(binding["session_id"]),
        profile_arg=profile_arg,
        name_arg=name_arg,
        extra_args=extra,
    )
    return shlex.split(raw)


def build_tmux_launch_command(binding: dict[str, Any]) -> str:
    """Build the command string that a new tmux session will execute."""
    native = build_native_resume_command(binding, [])
    # Prefix with cd to ensure cwd is correct inside tmux.
    return f"cd {shlex.quote(binding['cwd'])} && {' '.join(shlex.quote(p) for p in native)}"


def quote_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def tmux_session_exists(name: str) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def tmux_create_and_attach(name: str, launch_command: str, cwd: str, dry_run: bool = False) -> int:
    if dry_run:
        print(f"tmux new-session -d -s {shlex.quote(name)} -c {shlex.quote(cwd)} {shlex.quote(launch_command)}")
        print(f"tmux attach -t {shlex.quote(name)}")
        return 0

    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-c", cwd, launch_command],
        check=True,
    )
    subprocess.run(["tmux", "attach", "-t", name])
    return 0


def tmux_attach(name: str, dry_run: bool = False) -> int:
    if dry_run:
        print(f"tmux attach -t {shlex.quote(name)}")
        return 0
    subprocess.run(["tmux", "attach", "-t", name])
    return 0


def create_shim(path: Path, script_path: Path, command_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            f"exec python3 {shlex.quote(str(script_path.resolve()))} run {shlex.quote(command_name)} \"$@\"",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def scan_sessions(runtime: str, cwd: Path | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Scan recent sessions for a runtime. Currently supported: pi, codex."""
    results: list[dict[str, Any]] = []
    if runtime == "pi":
        base = Path.home() / ".pi" / "agent" / "sessions"
        if cwd:
            key = "--" + str(cwd).lstrip(os.sep).replace(os.sep, "-") + "--"
            dirs = [base / key] if (base / key).exists() else []
        else:
            dirs = [d for d in base.iterdir() if d.is_dir()] if base.exists() else []
        for d in dirs:
            for f in sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
                session_id = f.stem.split("_")[-1]
                results.append({
                    "session_id": session_id,
                    "cwd": str(cwd or ""),
                    "runtime": "pi",
                    "updated": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(),
                })
    elif runtime == "codex":
        base = Path.home() / ".codex" / "sessions"
        files = []
        if base.exists():
            for year_dir in base.iterdir():
                if year_dir.is_dir():
                    for month_dir in year_dir.iterdir():
                        if month_dir.is_dir():
                            files.extend(month_dir.rglob("*.jsonl"))
        for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            lines = f.read_text(encoding="utf-8").splitlines()
            data: dict[str, Any] = {}
            if lines:
                try:
                    data = json.loads(lines[0])
                except json.JSONDecodeError:
                    pass
            thread_id = data.get("id") or f.stem[-36:]
            results.append({
                "session_id": thread_id,
                "cwd": data.get("cwd", ""),
                "runtime": "codex",
                "updated": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(),
            })
    return results


def cmd_bind(args: argparse.Namespace) -> int:
    validate_command_name(args.name)
    runtime = args.runtime
    if runtime not in RUNTIME_DEFAULTS:
        die(f"unknown runtime: {runtime}; supported: {', '.join(RUNTIME_DEFAULTS)}")

    session_id = resolve_session_id(runtime, args.session_id)
    cwd = normalize_cwd(args.cwd)
    backend = args.backend or detect_default_backend()

    registry = load_registry(Path(args.registry))
    binding: dict[str, Any] = {
        "runtime": runtime,
        "session_id": session_id,
        "cwd": cwd,
        "profile": args.profile,
        "name": args.name_arg,
        "bin": args.bin,
        "extra_args": args.extra_args or [],
        "resume_template": args.resume_template,
        "backend": backend,
        "tmux_session_name": args.tmux_session_name or args.name,
        "created_at": now_iso(),
    }
    if backend == "tmux":
        binding["launch_command"] = build_tmux_launch_command(binding)
    registry["commands"][args.name] = binding
    write_registry(Path(args.registry), registry)

    bin_dir = Path(args.bin_dir)
    script_path = Path(__file__).resolve()
    shim_path = bin_dir / args.name
    create_shim(shim_path, script_path, args.name)

    print(f"Bound '{args.name}' -> {runtime} session {session_id} (backend={backend})")
    print(f"Registry: {args.registry}")
    print(f"Shim: {shim_path}")
    if str(bin_dir) not in os.environ.get("PATH", ""):
        print(f"NOTE: {bin_dir} is not on PATH; add it to your shell profile.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    registry = load_registry(Path(args.registry))
    binding = registry["commands"].get(args.name)
    if not binding:
        die(f"unknown command: {args.name}; run 'list' to see bindings")

    backend = binding.get("backend", "native")

    if backend == "tmux":
        tmux_name = binding.get("tmux_session_name") or args.name
        if tmux_session_exists(tmux_name):
            return tmux_attach(tmux_name, dry_run=args.dry_run)
        launch_command = binding.get("launch_command") or build_tmux_launch_command(binding)
        return tmux_create_and_attach(
            tmux_name,
            launch_command,
            binding["cwd"],
            dry_run=args.dry_run,
        )

    command = build_native_resume_command(binding, args.resume_args or [])
    if args.dry_run:
        print(quote_command(command))
        return 0

    os.chdir(binding["cwd"])
    subprocess.run(command)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    registry = load_registry(Path(args.registry))
    binding = registry["commands"].get(args.name)
    if not binding:
        die(f"unknown command: {args.name}")
    print(json.dumps(binding, ensure_ascii=False, indent=2))
    if binding.get("backend") == "tmux":
        print("tmux attach command:", f"tmux attach -t {shlex.quote(binding.get('tmux_session_name', args.name))}")
    else:
        print("resume command:", quote_command(build_native_resume_command(binding, [])))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    registry = load_registry(Path(args.registry))
    commands = registry.get("commands", {})
    if not commands:
        print("No session commands bound.")
        return 0
    print(f"{'NAME':<20} {'BACKEND':<8} {'RUNTIME':<8} {'SESSION_ID':<40} {'CWD'}")
    for name, binding in sorted(commands.items()):
        print(
            f"{name:<20} {binding.get('backend', 'native'):<8} {binding['runtime']:<8} "
            f"{binding['session_id']:<40} {binding['cwd']}"
        )
    return 0


def cmd_unbind(args: argparse.Namespace) -> int:
    registry = load_registry(Path(args.registry))
    if args.name not in registry["commands"]:
        die(f"unknown command: {args.name}")
    del registry["commands"][args.name]
    write_registry(Path(args.registry), registry)

    shim_path = Path(args.bin_dir) / args.name
    if shim_path.exists():
        shim_path.unlink()
    print(f"Unbound '{args.name}'")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    runtime = args.runtime
    if runtime not in RUNTIME_DEFAULTS:
        die(f"unknown runtime: {runtime}")
    sessions = scan_sessions(runtime, cwd=Path(args.cwd) if args.cwd else None, limit=args.limit)
    if not sessions:
        print(f"No recent {runtime} sessions found.")
        return 0
    print(f"Recent {runtime} sessions:")
    for i, s in enumerate(sessions, 1):
        print(f"  {i}. {s['session_id']}  cwd={s.get('cwd', '')}  updated={s['updated']}")
    return 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Registry file path")
    parser.add_argument("--bin-dir", default=str(DEFAULT_BIN_DIR), help="Directory for generated shims")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bind agent sessions to stable CLI commands.")
    sub = parser.add_subparsers(dest="command", required=True)

    bind_p = sub.add_parser("bind", help="Bind a session to a command name")
    _add_common_args(bind_p)
    bind_p.add_argument("name", help="Command name")
    bind_p.add_argument("--runtime", choices=list(RUNTIME_DEFAULTS), required=True)
    bind_p.add_argument("--session-id", help="Session / thread / conversation id")
    bind_p.add_argument("--cwd", help="Working directory for resume")
    bind_p.add_argument("--profile", help="Profile (Codex only)")
    bind_p.add_argument("--name-arg", dest="name_arg", help="Display name (Claude only)")
    bind_p.add_argument("--bin", help="Override binary name")
    bind_p.add_argument("--extra-args", nargs="*", help="Extra args passed to resume command")
    bind_p.add_argument("--resume-template", help="Override resume command template")
    bind_p.add_argument(
        "--backend",
        choices=["native", "tmux"],
        default=detect_default_backend(),
        help="Resume backend: native agent CLI or tmux session management (default: tmux if inside tmux)",
    )
    bind_p.add_argument("--tmux-session-name", help="tmux session name (default: command name)")
    bind_p.set_defaults(func=cmd_bind)

    run_p = sub.add_parser("run", help="Run a bound command")
    _add_common_args(run_p)
    run_p.add_argument("name", help="Command name")
    run_p.add_argument("--dry-run", action="store_true", help="Print command without running")
    run_p.add_argument("resume_args", nargs="*", help="Extra args passed to resume (use -- to pass flags)")
    run_p.set_defaults(func=cmd_run)

    show_p = sub.add_parser("show", help="Show binding details")
    _add_common_args(show_p)
    show_p.add_argument("name", help="Command name")
    show_p.set_defaults(func=cmd_show)

    list_p = sub.add_parser("list", help="List bindings")
    _add_common_args(list_p)
    list_p.set_defaults(func=cmd_list)

    unbind_p = sub.add_parser("unbind", help="Remove a binding")
    _add_common_args(unbind_p)
    unbind_p.add_argument("name", help="Command name")
    unbind_p.set_defaults(func=cmd_unbind)

    scan_p = sub.add_parser("scan", help="Scan recent sessions")
    _add_common_args(scan_p)
    scan_p.add_argument("--runtime", choices=list(RUNTIME_DEFAULTS), required=True)
    scan_p.add_argument("--cwd", help="Filter by cwd (pi only)")
    scan_p.add_argument("--limit", type=int, default=10)
    scan_p.set_defaults(func=cmd_scan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
