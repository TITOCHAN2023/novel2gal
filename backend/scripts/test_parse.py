"""
解析 + 持久化 测试脚本

完整流程：epub → 分块 → 逐块解析 → 写入 SurrealDB → 创建资产文件夹 → 验证

用法：
  cd backend
  source .venv/bin/activate
  python scripts/test_parse.py [epub文件路径] [块数限制]
"""
import os
import sys
import json
import asyncio
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.llm_client import LLMClient
from parser.epub_reader import read_epub
from parser.chunker import chunk_novel
from parser.novel_parser import NovelParser
from db.store import NovelStore
from rich.console import Console

console = Console()

DEFAULT_EPUB = os.environ.get("NOVEL_EPUB_PATH", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
ASSET_ROOT = str(Path(__file__).parent.parent / "data" / "assets")
DB_PATH = Path(__file__).parent.parent / "data" / "novel.db"


async def main():
    epub_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EPUB
    max_chunks = int(sys.argv[2]) if len(sys.argv) > 2 else None

    # ============================================================
    # 步骤 1: 读取 epub + 分块
    # ============================================================
    console.rule("[bold]步骤 1: 读取小说")
    chapters = read_epub(epub_path)
    console.print(f"章节: {len(chapters)}")

    all_chunks = []
    for ch in chapters:
        ch_chunks = chunk_novel(ch.text, max_chars=3000, overlap_chars=200)
        for c in ch_chunks:
            c.chapter = ch.index + 1
            c.chapter_title = f"{ch.title} (块{c.index})" if len(ch_chunks) > 1 else ch.title
        all_chunks.extend(ch_chunks)
    for i, c in enumerate(all_chunks):
        c.index = i

    if max_chunks:
        all_chunks = all_chunks[:max_chunks]
    console.print(f"分块: {len(all_chunks)} 块")

    # ============================================================
    # 步骤 2: LLM 解析（逐块递进）
    # ============================================================
    console.rule("[bold]步骤 2: LLM 解析")
    async with LLMClient(base_url=LLM_BASE_URL, model=LLM_MODEL, timeout=300) as llm:
        parser = NovelParser(llm=llm)
        state, synthesis = await parser.parse(all_chunks)

    # ============================================================
    # 步骤 3: 写入 SurrealDB + 创建资产文件夹
    # ============================================================
    console.rule("[bold]步骤 3: 持久化到图数据库")

    store = await NovelStore.create(
        db_path=DB_PATH,
        namespace="novel2gal",
        database="overlord",
        asset_root=ASSET_ROOT,
    )

    await store.persist_parse_results(
        character_card_versions=state.character_card_versions,
        chunk_results=state.chunk_results,
        synthesis=synthesis,
    )
    console.print("[green]写入完成[/]")

    # ============================================================
    # 步骤 4: 验证
    # ============================================================
    console.rule("[bold]步骤 4: 验证图数据库")

    stats = await store.get_stats()
    console.print(f"数据库统计: {json.dumps(stats, ensure_ascii=False)}")

    # 查所有角色
    chars = await store.get_all_characters()
    console.print(f"\n[bold yellow]角色 ({len(chars)}):[/]")
    for c in chars:
        console.print(f"  {c['name']} — traits: {c.get('config', {}).get('traits', [])}")
        console.print(f"    资产文件夹: {c.get('asset_folder', '')}")

    # 查所有地点
    locs = await store.get_all_locations()
    console.print(f"\n[bold yellow]地点 ({len(locs)}):[/]")
    for loc in locs:
        console.print(f"  {loc['name']}: {loc.get('description', '')[:60]}")

    # 查世界观规则
    rules = await store.get_all_world_rules()
    console.print(f"\n[bold yellow]世界观规则 ({len(rules)}):[/]")
    for r in rules:
        console.print(f"  [{r.get('category', '')}] {r.get('description', '')[:80]}")

    # 验证资产文件夹
    console.print(f"\n[bold yellow]资产文件夹:[/]")
    asset_path = Path(ASSET_ROOT)
    if asset_path.exists():
        for p in sorted(asset_path.iterdir()):
            if p.is_dir():
                files = list(p.iterdir())
                console.print(f"  {p.name}/ ({len(files)} 文件)")
                for f in files:
                    console.print(f"    {f.name}")

    # 验证角色卡版本历史
    console.print(f"\n[bold yellow]角色卡版本历史:[/]")
    for char_id in state.character_card_versions:
        versions = state.character_card_versions[char_id]
        console.print(f"  {char_id}: {len(versions)} 个版本")
        for i, v in enumerate(versions):
            traits = v.get("config", {}).get("traits", [])
            console.print(f"    v{i}: {traits}")

    console.print(f"\n[bold green]全部完成！[/]")


if __name__ == "__main__":
    asyncio.run(main())
