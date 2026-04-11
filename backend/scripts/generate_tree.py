#!/usr/bin/env python3
"""
场景树生成脚本 — 独立运行，可中断续接

用法：
  cd backend
  .venv/bin/python scripts/generate_tree.py [depth] [branches]

默认 depth=5, branches=2
每生成一个场景立即保存到 data/engine_scenes.json
Ctrl+C 中断后重新运行会自动跳过已生成的场景
"""
import os
import sys
import json
import asyncio
import logging
import signal
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.llm_client import LLMClient
from db.store import NovelStore
from orchestrator.tree_generator import TreeGenerator
from orchestrator.three_zone import build_three_zone_context

# 配置
DATA_DIR = Path(__file__).parent.parent / "data"
SCENES_PATH = DATA_DIR / "engine_scenes.json"
CACHE_PATH = DATA_DIR / "parse_cache.json"
LLM_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234")
LLM_MODEL = os.environ.get("LLM_MODEL", "")

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(DATA_DIR / "logs" / "tree_gen.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("tree_gen")


async def main():
    depth = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    branches = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    # 显示已有进度
    if SCENES_PATH.exists():
        existing = json.loads(SCENES_PATH.read_text(encoding="utf-8"))
        logger.info(f"发现已有场景: {len(existing)} 个，将续接生成")
    else:
        logger.info("从头开始生成")

    logger.info(f"参数: depth={depth}, branches={branches}")
    logger.info(f"LLM: {LLM_URL} / {LLM_MODEL or '(auto)'}")
    start = time.time()

    store = await NovelStore.create(
        db_path=DATA_DIR / "novel.db",
        namespace="novel2gal", database="overlord",
        asset_root=DATA_DIR / "assets",
    )
    three_zone = build_three_zone_context(CACHE_PATH) if CACHE_PATH.exists() else None

    async with LLMClient(base_url=LLM_URL, model=LLM_MODEL, timeout=300) as llm:
        generator = TreeGenerator(
            llm=llm, store=store, three_zone=three_zone,
            initial_depth=depth,
            max_branches_per_node=branches,
            scenes_path=SCENES_PATH,
        )
        new_scenes = await generator.generate_tree()

    elapsed = time.time() - start
    all_scenes = json.loads(SCENES_PATH.read_text(encoding="utf-8")) if SCENES_PATH.exists() else {}
    logger.info(f"完成！总计 {len(all_scenes)} 个场景, 本次新增 {len(new_scenes)} 个, 耗时 {elapsed/60:.1f} 分钟")


if __name__ == "__main__":
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        existing = json.loads(SCENES_PATH.read_text(encoding="utf-8")) if SCENES_PATH.exists() else {}
        logger.info(f"\n中断！已保存 {len(existing)} 个场景。重新运行此脚本即可续接。")
