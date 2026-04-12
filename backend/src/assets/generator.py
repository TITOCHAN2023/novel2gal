"""
资产基础层生成 — 步骤5

为核心角色生成基础立绘参考图，为主要场景生成基准图。

对应 asset-generation.md：
  角色基础层：全身六视图 + 脸部五视图（一致性锚点）
  场景基础层：每场景一张基准图

实现策略：
  1. 先创建目录结构和 prompt 文件（立即完成）
  2. 异步调用 AnyGen 生成图片（如果 API 可用）
  3. 图片不存在不阻塞游戏（前端用空背景降级）
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from ..db.store import NovelStore
except ImportError:
    from db.store import NovelStore


async def generate_base_assets(store: NovelStore, novel_title: str = "Overlord", epub_images_dir: Path | None = None) -> None:
    """为所有角色和地点生成基础资产"""
    logger.info("=== 步骤5: 资产基础层生成 ===")

    characters = await store.get_all_characters()
    locations = await store.get_all_locations()

    # 1. 创建目录结构（立即完成，不阻塞）
    for char in characters:
        folder = Path(char.get("asset_folder", ""))
        if not folder.exists():
            continue
        (folder / "base").mkdir(exist_ok=True)
        (folder / "outfit_default" / "ref").mkdir(parents=True, exist_ok=True)
        (folder / "outfit_default" / "emotion").mkdir(parents=True, exist_ok=True)
        (folder / "voice").mkdir(exist_ok=True)

        # 写 prompt 文件（供后续生图或手动生图使用）
        config = char.get("config", {})
        appearance = config.get("appearance_summary", char.get("name", ""))
        prompt_file = folder / "base" / "generation_prompt.txt"
        prompt_file.write_text(
            f"角色: {char['name']}\n外貌: {appearance}\n小说: {novel_title}\n",
            encoding="utf-8",
        )

    for loc in locations:
        folder = Path(loc.get("asset_folder", ""))
        if not folder.exists():
            continue
        (folder / "base").mkdir(exist_ok=True)
        prompt_file = folder / "base" / "generation_prompt.txt"
        prompt_file.write_text(
            f"地点: {loc['name']}\n描述: {loc.get('description', '')}\n小说: {novel_title}\n",
            encoding="utf-8",
        )

    logger.info(f"目录结构创建完成: {len(characters)} 角色, {len(locations)} 地点")
    # 生图由 server.py 的 _safe_task(gen_images(...)) 非阻塞处理，不在这里调用
