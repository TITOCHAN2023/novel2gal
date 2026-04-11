"""
Novel2Gal 初始化流水线 — 按 architecture.md 完整执行

流程：
  1. 导入小说文件（epub）
  2. 解析层：分块 → 逐块 LLM 解析 → 跨块合成
  3. 持久化：写入 SurrealDB + 创建资产文件夹
  4. 三时区切割（按起点章节）
  5. [TODO] 资产基础层生成
  6. [TODO] 玩家角色选择/创建
  7. [TODO] 初始树预生成

解析结果会缓存到磁盘（JSON），重复运行不会重新调 LLM。
"""
import os
import sys
import json
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.logging_config import setup_logging
from config.llm_client import LLMClient
from parser.epub_reader import read_epub
from parser.chunker import chunk_novel
from parser.novel_parser import NovelParser
from db.store import NovelStore

logger = logging.getLogger("pipeline")

# ---- 配置（从 .env 读取）----
DATA_DIR = Path(__file__).parent.parent / "data"
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
DB_PATH = DATA_DIR / "novel.db"
ASSET_ROOT = DATA_DIR / "assets"
PARSE_CACHE = DATA_DIR / "parse_cache.json"
MAX_CHUNK_CHARS = 3000


async def step1_import(epub_path: str) -> list:
    """步骤1: 导入小说 → 分块"""
    logger.info(f"=== 步骤1: 导入小说 ===")
    logger.info(f"文件: {epub_path}")

    chapters = read_epub(epub_path)
    logger.info(f"章节数: {len(chapters)}")

    all_chunks = []
    for ch in chapters:
        ch_chunks = chunk_novel(ch.text, max_chars=MAX_CHUNK_CHARS, overlap_chars=200)
        for c in ch_chunks:
            c.chapter = ch.index + 1
            c.chapter_title = f"{ch.title} (块{c.index})" if len(ch_chunks) > 1 else ch.title
        all_chunks.extend(ch_chunks)
    for i, c in enumerate(all_chunks):
        c.index = i

    logger.info(f"分块数: {len(all_chunks)}")
    for c in all_chunks:
        logger.debug(f"  [{c.index}] {c.chapter_title} — {c.char_count} 字")
    return all_chunks


async def step2_parse(chunks: list, max_chunks: int | None = None):
    """步骤2: LLM 解析（有缓存则跳过）"""
    logger.info(f"=== 步骤2: LLM 解析 ===")

    # 检查缓存
    if PARSE_CACHE.exists():
        logger.info(f"发现解析缓存: {PARSE_CACHE}")
        cache = json.loads(PARSE_CACHE.read_text(encoding="utf-8"))
        cached_chunks = cache.get("chunk_count", 0)
        target_chunks = max_chunks or len(chunks)
        if cached_chunks >= target_chunks:
            # 重建 state 对象
            from parser.novel_parser import ParseState, ChunkResult  # noqa: used in both branches
            state = ParseState()
            state.character_card_versions = cache["character_card_versions"]
            state.known_character_ids = cache.get("known_character_ids", {})
            for cr_data in cache["chunk_results"]:
                cr = ChunkResult(
                    chunk_index=cr_data["chunk_index"],
                    characters=cr_data.get("characters", []),
                    locations=cr_data.get("locations", []),
                    events=cr_data.get("events", []),
                    chapter_summary=cr_data.get("chapter_summary", ""),
                    dialogues=cr_data.get("dialogues", {}),
                )
                state.chunk_results.append(cr)

            synthesis = cache.get("synthesis")
            if synthesis:
                logger.info(f"缓存完整（{cached_chunks} 块+synthesis），跳过 LLM 调用")
                return state, synthesis
            else:
                # 有 chunks 但缺 synthesis → 只补跑合成
                logger.info(f"缓存有 {cached_chunks} 块但缺 synthesis，补跑跨章合成...")
                async with LLMClient(base_url=LLM_BASE_URL, model=LLM_MODEL, timeout=300) as llm:
                    parser = NovelParser(llm=llm)
                    synthesis = await parser.synthesize(state)
                cache["synthesis"] = synthesis
                PARSE_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info("synthesis 已补全并缓存")
                return state, synthesis
        else:
            logger.info(f"缓存不足（{cached_chunks} < {target_chunks}），重新解析")

    if max_chunks:
        chunks = chunks[:max_chunks]

    async with LLMClient(base_url=LLM_BASE_URL, model=LLM_MODEL, timeout=300) as llm:
        parser = NovelParser(llm=llm)
        state, synthesis = await parser.parse(chunks)

    # 写入缓存
    cache_data = {
        "chunk_count": len(chunks),
        "character_card_versions": state.character_card_versions,
        "chunk_results": [
            {
                "chunk_index": cr.chunk_index,
                "chapter_summary": cr.chapter_summary,
                "characters": cr.characters,
                "locations": cr.locations,
                "events": cr.events,
                "dialogues": cr.dialogues,
            }
            for cr in state.chunk_results
        ],
        "synthesis": synthesis,
    }
    PARSE_CACHE.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"解析缓存已保存: {PARSE_CACHE}")

    return state, synthesis


async def step3_persist(state, synthesis):
    """步骤3: 写入图数据库 + 创建资产文件夹"""
    logger.info(f"=== 步骤3: 持久化到图数据库 ===")

    store = await NovelStore.create(
        db_path=DB_PATH,
        namespace="novel2gal",
        database="overlord",
        asset_root=ASSET_ROOT,
    )

    await store.persist_parse_results(
        card_versions=state.character_card_versions,
        chunk_results=state.chunk_results,
        synthesis=synthesis,
    )

    return store


async def step4_verify(store: NovelStore):
    """步骤4: 验证持久化结果"""
    logger.info(f"=== 步骤4: 验证 ===")

    stats = await store.get_stats()
    logger.info(f"数据库统计: {json.dumps(stats, ensure_ascii=False)}")

    chars = await store.get_all_characters()
    logger.info(f"角色 ({len(chars)}):")
    for c in chars:
        logger.info(f"  {c['name']} — v{c.get('card_version', 0)} — folder: {c.get('asset_folder', '')}")

    locs = await store.get_all_locations()
    logger.info(f"地点 ({len(locs)}):")
    for loc in locs:
        logger.info(f"  {loc['name']}")

    rules = await store.get_all_world_rules()
    logger.info(f"世界观规则 ({len(rules)}):")
    for r in rules:
        logger.info(f"  [{r.get('category', '')}] {r.get('description', '')[:60]}")

    # 验证资产文件夹
    asset_path = ASSET_ROOT
    if asset_path.exists():
        dirs = sorted(p for p in asset_path.iterdir() if p.is_dir())
        logger.info(f"资产文件夹 ({len(dirs)}):")
        for d in dirs:
            files = list(d.iterdir())
            logger.info(f"  {d.name}/ → {[f.name for f in files]}")


async def main():
    setup_logging(DATA_DIR / "logs")

    default_epub = os.environ.get("NOVEL_EPUB_PATH", "")
    epub_path = sys.argv[1] if len(sys.argv) > 1 else default_epub
    if not epub_path:
        logger.error("请指定 epub 路径: python init_pipeline.py <epub> 或在 .env 中设置 NOVEL_EPUB_PATH")
        return
    max_chunks = int(sys.argv[2]) if len(sys.argv) > 2 else None

    logger.info("=" * 60)
    logger.info("Novel2Gal 初始化流水线启动")
    logger.info("=" * 60)

    # 步骤 1: 导入
    chunks = await step1_import(epub_path)

    # 步骤 2: 解析（有缓存自动跳过）
    state, synthesis = await step2_parse(chunks, max_chunks)

    # 步骤 3: 持久化
    store = await step3_persist(state, synthesis)

    # 步骤 4: 验证
    await step4_verify(store)

    # 步骤 5: 资产基础层生成（当前为 mock 占位）
    from assets.generator import generate_base_assets
    await generate_base_assets(store)

    # 步骤 6: 玩家角色选择/创建
    from orchestrator.player_setup import setup_player_character
    # 可通过第3个参数指定角色名，空=创建默认新角色
    player_name = sys.argv[3] if len(sys.argv) > 3 else ""
    async with LLMClient(base_url=LLM_BASE_URL, model=LLM_MODEL, timeout=300) as llm:
        player = await setup_player_character(store, llm, player_name)

        # 步骤 7: 初始树预生成（增量持久化，可中断续接）
        from orchestrator.tree_generator import TreeGenerator
        from orchestrator.three_zone import build_three_zone_context
        tree_depth = int(sys.argv[4]) if len(sys.argv) > 4 else 5
        scenes_path = DATA_DIR / "engine_scenes.json"
        three_zone = build_three_zone_context(PARSE_CACHE) if PARSE_CACHE.exists() else None
        generator = TreeGenerator(
            llm=llm, store=store,
            three_zone=three_zone,
            initial_depth=tree_depth,
            max_branches_per_node=2,
            scenes_path=scenes_path,
        )
        new_scenes = await generator.generate_tree()

        all_scenes = json.loads(scenes_path.read_text(encoding="utf-8")) if scenes_path.exists() else {}
        logger.info(f"引擎场景: {scenes_path} (总计 {len(all_scenes)} 个, 本次新增 {len(new_scenes)} 个)")

    logger.info("=" * 60)
    logger.info("流水线完成！")
    logger.info(f"  数据库: {DB_PATH}")
    logger.info(f"  资产: {ASSET_ROOT}")
    logger.info(f"  引擎场景: {DATA_DIR / 'engine_scenes.json'}")
    logger.info(f"  日志: {DATA_DIR / 'logs' / 'pipeline.log'}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
