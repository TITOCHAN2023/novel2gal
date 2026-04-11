"""
全书解析脚本 — 解析 Overlord 全部 31 块 + 持久化 + 三时区切割验证

只做步骤 1-3，不做场景生成。
"""
import os
import sys
import json
import asyncio
import logging
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.logging_config import setup_logging
from config.llm_client import LLMClient
from parser.epub_reader import read_epub
from parser.chunker import chunk_novel
from parser.novel_parser import NovelParser, ParseState, ChunkResult
from db.store import NovelStore

DATA_DIR = Path(__file__).parent.parent / "data"
CACHE_PATH = DATA_DIR / "parse_cache.json"
LLM_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
EPUB_PATH = os.environ.get("NOVEL_EPUB_PATH", "")

logger = logging.getLogger("parse_full")


async def main():
    setup_logging(DATA_DIR / "logs")
    start_time = time.time()

    # 步骤1: 导入+分块
    logger.info("=" * 60)
    logger.info("全书解析开始")
    logger.info("=" * 60)

    chapters = read_epub(EPUB_PATH)
    all_chunks = []
    for ch in chapters:
        ch_chunks = chunk_novel(ch.text, max_chars=3000, overlap_chars=200)
        for c in ch_chunks:
            c.chapter = ch.index + 1
            c.chapter_title = f"{ch.title} (块{c.index})" if len(ch_chunks) > 1 else ch.title
        all_chunks.extend(ch_chunks)
    for i, c in enumerate(all_chunks):
        c.index = i

    logger.info(f"总块数: {len(all_chunks)}")
    logger.info(f"总字数: {sum(c.char_count for c in all_chunks)}")

    # 步骤2: 检查缓存——支持断点续传
    state = ParseState()
    synthesis = None
    start_chunk = 0

    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        cached_count = cache.get("chunk_count", 0)
        if cached_count >= len(all_chunks) and cache.get("synthesis"):
            logger.info(f"缓存完整 ({cached_count} 块)，跳过解析")
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
            synthesis = cache["synthesis"]
        elif cached_count > 0:
            logger.info(f"缓存部分完成 ({cached_count}/{len(all_chunks)} 块)，断点续传")
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
            start_chunk = cached_count

    # 解析剩余块
    if synthesis is None:
        remaining = all_chunks[start_chunk:]
        if remaining:
            logger.info(f"开始解析: 块 {start_chunk} ~ {len(all_chunks)-1}")
            async with LLMClient(base_url=LLM_URL, model=LLM_MODEL, timeout=300) as llm:
                parser = NovelParser(llm=llm)

                for chunk in remaining:
                    logger.info(f"\n--- 块 {chunk.index}/{len(all_chunks)-1}: {chunk.chapter_title} ({chunk.char_count}字) ---")
                    try:
                        await parser.process_chunk(chunk, state)
                    except Exception as e:
                        logger.error(f"块 {chunk.index} 解析失败: {e}", exc_info=True)
                        logger.info("保存当前进度到缓存...")
                        _save_cache(state, len(state.chunk_results), None)
                        logger.info("可重新运行脚本断点续传")
                        return

                    # 每块解析完都保存缓存（断点续传）
                    _save_cache(state, len(state.chunk_results), None)

                # 全部块解析完，做跨章合成
                logger.info("\n=== 跨章合成 ===")
                synthesis = await parser.synthesize(state)

            # 保存完整缓存
            _save_cache(state, len(all_chunks), synthesis)

    # 步骤3: 持久化到图数据库
    logger.info("\n=== 持久化到图数据库 ===")
    # 清理旧数据
    db_path = DATA_DIR / "novel.db"
    if db_path.exists():
        import shutil
        shutil.rmtree(db_path, ignore_errors=True)
    asset_path = DATA_DIR / "assets"
    if asset_path.exists():
        import shutil
        shutil.rmtree(asset_path, ignore_errors=True)

    store = await NovelStore.create(
        db_path=db_path, namespace="novel2gal", database="overlord",
        asset_root=asset_path,
    )
    await store.persist_parse_results(state.character_card_versions, state.chunk_results, synthesis)

    # 验证
    stats = await store.get_stats()
    elapsed = time.time() - start_time

    logger.info("\n" + "=" * 60)
    logger.info(f"全书解析完成！耗时: {elapsed/60:.1f} 分钟")
    logger.info(f"数据库: {json.dumps(stats, ensure_ascii=False)}")
    logger.info(f"角色: {list(state.character_card_versions.keys())}")
    logger.info(f"角色卡版本数: {sum(len(v) for v in state.character_card_versions.values())}")
    logger.info("=" * 60)

    # 三时区切割验证
    logger.info("\n=== 三时区切割验证 ===")
    total_chunks = len(all_chunks)
    mid = total_chunks // 2
    logger.info(f"假设从块 {mid} 开始玩（共 {total_chunks} 块）：")

    past_events = [cr for cr in state.chunk_results if cr.chunk_index < mid]
    future_chunks = [cr for cr in state.chunk_results if cr.chunk_index >= mid]

    # 已发生区角色
    past_char_ids = set()
    for cr in past_events:
        for c in cr.characters:
            past_char_ids.add(c["id"])

    # 潜在未来区角色（在已发生区没出现过的）
    future_char_ids = set()
    for cr in future_chunks:
        for c in cr.characters:
            if c["id"] not in past_char_ids:
                future_char_ids.add(c["id"])

    logger.info(f"  已发生区角色 ({len(past_char_ids)}): {past_char_ids}")
    logger.info(f"  潜在未来区新角色 ({len(future_char_ids)}): {future_char_ids}")
    logger.info(f"  已发生区事件数: {sum(len(cr.events) for cr in past_events)}")


def _save_cache(state: ParseState, chunk_count: int, synthesis: dict | None):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = {
        "chunk_count": chunk_count,
        "character_card_versions": state.character_card_versions,
        "known_character_ids": state.known_character_ids,
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
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
