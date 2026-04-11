"""快速生成 Overlord 故事的场景树"""
import asyncio, sys, json, os, logging
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# 强制 unbuffered
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', force=True)
logger = logging.getLogger("gen_scenes")

from config.llm_client import LLMClient
from db.store import NovelStore
from orchestrator.player_setup import setup_player_character
from orchestrator.tree_generator import TreeGenerator
from orchestrator.three_zone import build_three_zone_context
from stories.manager import StoryManager, StoryStats

DATA_DIR = Path(__file__).parent.parent / "data"
mgr = StoryManager(DATA_DIR)
STORY_ID = sys.argv[1] if len(sys.argv) > 1 else "overlord_v0"
DEPTH = int(sys.argv[2]) if len(sys.argv) > 2 else 2


async def main():
    logger.info(f"=== 场景生成: {STORY_ID}, depth={DEPTH} ===")

    cache_path = mgr.story_parse_cache(STORY_ID)
    three_zone = build_three_zone_context(cache_path) if cache_path.exists() else None

    store = await NovelStore.create(
        db_path=mgr.story_db(STORY_ID),
        namespace="novel2gal", database=STORY_ID,
        asset_root=mgr.story_assets(STORY_ID),
    )

    chars = await store.get_all_characters()
    logger.info(f"角色: {len(chars)}")

    llm_url = os.environ.get("LLM_BASE_URL", "http://192.168.21.13:1234")
    llm_model = os.environ.get("LLM_MODEL", "google/gemma-4-e4b")

    async with LLMClient(base_url=llm_url, model=llm_model, timeout=300) as llm:
        player = next((c for c in chars if c.get("is_player")), None)
        if not player:
            logger.info("创建玩家角色...")
            await setup_player_character(store, llm, "")

        logger.info("开始树生成...")
        generator = TreeGenerator(
            llm=llm, store=store, three_zone=three_zone,
            initial_depth=DEPTH, max_branches_per_node=2,
        )
        scenes = await generator.generate_tree()

    scenes_path = mgr.story_scenes(STORY_ID)
    scenes_path.write_text(json.dumps(scenes, ensure_ascii=False, indent=2))

    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    mgr.mark_ready(STORY_ID, StoryStats(
        chapters=2, chunks=cache.get("chunk_count", 6),
        characters=len(cache.get("character_card_versions", {})),
        scenes=len(scenes),
    ))
    logger.info(f"完成！{len(scenes)} 个场景 → {scenes_path}")


if __name__ == "__main__":
    asyncio.run(main())
