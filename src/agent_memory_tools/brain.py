#!/usr/bin/env python3
"""
Brain CLI — 向量检索 + 跨项目记忆

用法:
    brain init                      # 初始化 Brain（下载模型，创建索引）
    brain index                     # 索引当前项目 + 所有已注册项目的 learnings
    brain search "语义查询"          # 向量语义搜索
    brain register /path/to/project # 注册一个项目到 Brain
    brain unregister /path/to/project
    brain projects                  # 列出已注册项目
    brain sync                      # 同步所有项目 learnings 到 Brain
    brain status                    # Brain 状态

数据存储:
    ~/.brain/
    ├── config.json                 # Brain 配置（注册项目列表、模型名）
    ├── embeddings.npy              # 所有 learnings 的 embedding 向量
    ├── index.jsonl                 # 向量索引（id → project/pattern/file offset 映射）
    └── model/                      # 缓存的 sentence-transformers 模型

设计参考: gstack GBrain
"""

import argparse
import json
import os
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BRAIN_HOME = Path(os.environ.get("BRAIN_HOME", Path.home() / ".brain"))
CONFIG_FILE = BRAIN_HOME / "config.json"
INDEX_FILE = BRAIN_HOME / "index.jsonl"
EMBEDDINGS_FILE = BRAIN_HOME / "embeddings.npy"

DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # 多语言，384维，~470MB


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"model": DEFAULT_MODEL, "projects": [], "last_indexed": ""}


def _save_config(config: dict) -> None:
    BRAIN_HOME.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _load_index() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    records = []
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def _save_index(records: list[dict]) -> None:
    BRAIN_HOME.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _load_project_learnings(project_path: str) -> list[dict]:
    """从项目 memory/learnings.jsonl 读取 learnings"""
    p = Path(project_path) / "memory" / "learnings.jsonl"
    if not p.exists():
        return []
    records = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    """初始化 Brain：下载模型，创建目录"""
    config = _load_config()
    model_name = args.model or config.get("model", DEFAULT_MODEL)

    print(f"Initializing Brain at {BRAIN_HOME}")
    print(f"Model: {model_name}")
    print()

    # 下载模型（首次会下载，后续从缓存加载）
    print("Loading embedding model (first time downloads ~470MB)...")
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        dim = model.get_sentence_embedding_dimension()
        print(f"✓ Model loaded: {model_name} (dim={dim})")
    except ImportError:
        print("✗ sentence-transformers not installed. Run: pip install sentence-transformers")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Failed to load model: {e}")
        sys.exit(1)

    # 保存配置
    config["model"] = model_name
    config["initialized_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_config(config)

    # 创建空索引
    if not INDEX_FILE.exists():
        INDEX_FILE.touch()
    if not EMBEDDINGS_FILE.exists():
        import numpy as np
        np.save(str(EMBEDDINGS_FILE, ), np.array([], dtype=np.float32))

    print()
    print("✓ Brain initialized!")
    print()
    print("Next steps:")
    print("  brain register /path/to/project   # 注册项目")
    print("  brain sync                         # 索引所有项目 learnings")
    print("  brain search '语义查询'             # 向量搜索")


def cmd_register(args: argparse.Namespace) -> None:
    """注册一个项目到 Brain"""
    project_path = str(Path(args.project).resolve())
    config = _load_config()

    # 检查项目是否有 memory/learnings.jsonl
    learnings_path = Path(project_path) / "memory" / "learnings.jsonl"
    if not learnings_path.exists():
        print(f"WARN: {learnings_path} not found. Run memory-init.sh first.")
        print("Registering anyway — run `brain sync` after adding learnings.")

    if project_path in config.get("projects", []):
        print(f"Already registered: {project_path}")
        return

    config.setdefault("projects", []).append(project_path)
    _save_config(config)
    print(f"✓ Registered: {project_path}")
    print(f"  Total projects: {len(config['projects'])}")


def cmd_unregister(args: argparse.Namespace) -> None:
    """移除一个项目"""
    project_path = str(Path(args.project).resolve())
    config = _load_config()
    if project_path in config.get("projects", []):
        config["projects"].remove(project_path)
        _save_config(config)
        print(f"✓ Unregistered: {project_path}")
    else:
        print(f"Not registered: {project_path}")


def cmd_projects(args: argparse.Namespace) -> None:
    """列出已注册项目"""
    config = _load_config()
    projects = config.get("projects", [])
    if not projects:
        print("No projects registered. Run: brain register /path/to/project")
        return

    print(f"{len(projects)} registered project(s):\n")
    for p in projects:
        name = Path(p).name
        learnings_path = Path(p) / "memory" / "learnings.jsonl"
        count = 0
        if learnings_path.exists():
            with open(learnings_path, "r") as f:
                count = sum(1 for l in f if l.strip())
        stale = 0
        if learnings_path.exists():
            with open(learnings_path, "r") as f:
                for l in f:
                    l = l.strip()
                    if not l:
                        continue
                    try:
                        if json.loads(l).get("stale"):
                            stale += 1
                    except:
                        pass
        print(f"  {name:30s} {count} learnings ({stale} stale)  {p}")


def cmd_sync(args: argparse.Namespace) -> None:
    """同步所有项目 learnings 到 Brain 向量索引"""
    config = _load_config()
    projects = config.get("projects", [])
    model_name = config.get("model", DEFAULT_MODEL)

    if not projects:
        print("No projects registered. Run: brain register /path/to/project")
        return

    # 收集所有 learnings
    all_entries = []
    for project_path in projects:
        learnings = _load_project_learnings(project_path)
        project_name = Path(project_path).name
        for lrn in learnings:
            if (
                lrn.get("stale")
                or lrn.get("lifecycle_status") != "graduated"
                or lrn.get("scope") != "cross_project"
            ):
                continue  # 跳过 stale
            all_entries.append({
                "project": project_name,
                "project_path": project_path,
                "id": lrn.get("id", ""),
                "pattern": lrn.get("pattern", ""),
                "confidence": lrn.get("confidence", 0),
                "source": lrn.get("source", ""),
                "tags": lrn.get("tags", []),
                "files": lrn.get("files", []),
                "context": lrn.get("context", ""),
            })

    if not all_entries:
        _save_index([])
        EMBEDDINGS_FILE.unlink(missing_ok=True)
        config["last_indexed"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        config["indexed_count"] = 0
        _save_config(config)
        print("No learnings to index.")
        return

    print(f"Indexing {len(all_entries)} learnings from {len(projects)} project(s)...")

    # 生成 embeddings
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except ImportError:
        print("✗ sentence-transformers not installed. Run: pip install sentence-transformers")
        sys.exit(1)

    model = SentenceTransformer(model_name)

    # 构建文本：pattern + context + tags（让搜索更丰富）
    texts = []
    for e in all_entries:
        text = e["pattern"]
        if e.get("context"):
            text += " " + e["context"]
        if e.get("tags"):
            text += " " + " ".join(e["tags"])
        texts.append(text)

    print(f"Generating embeddings ({len(texts)} entries, model={model_name})...")
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)

    # 保存
    np.save(str(EMBEDDINGS_FILE), embeddings.astype(np.float32))
    _save_index(all_entries)

    config["last_indexed"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    config["indexed_count"] = len(all_entries)
    _save_config(config)

    print(f"✓ Indexed {len(all_entries)} learnings")
    print(f"  Embeddings: {EMBEDDINGS_FILE} ({embeddings.shape})")
    print(f"  Index: {INDEX_FILE}")


def cmd_search(args: argparse.Namespace) -> None:
    """向量语义搜索"""
    config = _load_config()
    model_name = config.get("model", DEFAULT_MODEL)

    # 加载索引
    index = _load_index()
    if not index:
        print("No index. Run: brain sync")
        return

    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except ImportError:
        print("✗ sentence-transformers not installed.")
        sys.exit(1)

    # 加载 embeddings
    if not EMBEDDINGS_FILE.exists():
        print("No embeddings file. Run: brain sync")
        return

    embeddings = np.load(str(EMBEDDINGS_FILE))
    if embeddings.size == 0 or len(embeddings.shape) != 2 or embeddings.shape[0] != len(index):
        print("Embeddings/index mismatch. Run: brain sync")
        return

    # 编码查询
    model = SentenceTransformer(model_name)
    query_emb = model.encode([args.query], normalize_embeddings=True)[0]

    # 计算余弦相似度（embeddings 已 normalize）
    similarities = embeddings @ query_emb

    # 排序
    top_k = min(args.top, len(index))
    top_indices = np.argsort(similarities)[::-1][:top_k]

    print(f"Search: \"{args.query}\"")
    print(f"Results (top {top_k}):\n")

    for rank, idx in enumerate(top_indices, 1):
        sim = float(similarities[idx])
        entry = index[idx]
        if sim < args.threshold:
            continue
        project = entry.get("project", "?")
        conf = entry.get("confidence", 0)
        tags = ", ".join(entry.get("tags", [])[:3])
        print(f"  {rank}. [{sim:.3f}] [{conf}/10] [{project}] {entry['pattern'][:80]}")
        if entry.get("context"):
            print(f"           {entry['context'][:100]}")
        if tags:
            print(f"           tags: {tags}")
        if args.verbose and entry.get("files"):
            files = entry["files"][:2]
            print(f"           files: {', '.join(str(f) for f in files)}")
        print()


def cmd_status(args: argparse.Namespace) -> None:
    """Brain 状态"""
    config = _load_config()
    model_name = config.get("model", DEFAULT_MODEL)

    print(f"Brain Home: {BRAIN_HOME}")
    print(f"Model: {model_name}")
    print(f"Last indexed: {config.get('last_indexed', 'never')}")
    print(f"Indexed entries: {config.get('indexed_count', 0)}")
    print(f"Registered projects: {len(config.get('projects', []))}")

    # 检查模型是否可用
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name)
        print(f"Model status: ✓ loaded")
    except Exception as e:
        print(f"Model status: ✗ {e}")

    # 检查索引
    index = _load_index()
    print(f"Index entries: {len(index)}")

    if EMBEDDINGS_FILE.exists():
        import numpy as np
        emb = np.load(str(EMBEDDINGS_FILE))
        print(f"Embeddings: {emb.shape}")
    else:
        print("Embeddings: not found")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Brain CLI — 向量检索 + 跨项目记忆",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="初始化 Brain")
    p_init.add_argument("--model", default="", help=f"Embedding 模型名 (default: {DEFAULT_MODEL})")

    # register
    p_register = sub.add_parser("register", help="注册项目")
    p_register.add_argument("project", help="项目路径")

    # unregister
    p_unregister = sub.add_parser("unregister", help="移除项目")
    p_unregister.add_argument("project", help="项目路径")

    # projects
    sub.add_parser("projects", help="列出已注册项目")

    # sync
    sub.add_parser("sync", help="同步所有项目 learnings 到 Brain")

    # search
    p_search = sub.add_parser("search", help="语义搜索")
    p_search.add_argument("query", help="搜索查询")
    p_search.add_argument("--top", type=int, default=10, help="返回条数")
    p_search.add_argument("--threshold", type=float, default=0.2, help="最低相似度阈值")
    p_search.add_argument("--verbose", "-v", action="store_true", help="显示文件路径")

    # status
    sub.add_parser("status", help="Brain 状态")

    args = parser.parse_args()
    commands = {
        "init": cmd_init,
        "register": cmd_register,
        "unregister": cmd_unregister,
        "projects": cmd_projects,
        "sync": cmd_sync,
        "search": cmd_search,
        "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
