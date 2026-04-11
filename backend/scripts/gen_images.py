"""
SuperAgent 美术导演生图脚本

流程：
  1. LLM 根据小说+epub插图生成全局美术风格卡
  2. LLM 为每个角色生成 art-directed 生图 prompt
  3. LLM 为每个地点生成 art-directed 生图 prompt
  4. AnyGen 并行执行生图
"""
import asyncio, sys, os, json, logging
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', force=True)
logger = logging.getLogger("gen_images")

from config.llm_client import LLMClient
from db.store import NovelStore
from assets.image_generator import generate_character_sprite, generate_scene_background, remove_white_bg
from stories.manager import StoryManager

STORY_ID = sys.argv[1] if len(sys.argv) > 1 else "overlord_v0"
DATA_DIR = Path(__file__).parent.parent / "data"
mgr = StoryManager(DATA_DIR)

# ---- 美术风格卡生成 prompt ----
ART_STYLE_PROMPT = """你是一个视觉小说的美术总监。根据以下小说信息，定义一套完整的全局美术风格。

小说标题：{title}
世界观：{world_rules}
主要角色：{characters}

请输出JSON格式的美术风格卡：
```json
{{
  "style_description": "完整的美术风格描述（英文，用于所有生图的全局 prompt 前缀）",
  "color_palette": "主色调描述",
  "lighting": "光影风格",
  "character_style": "角色绘画风格要求（全局适用）",
  "background_style": "背景绘画风格要求（全局适用）",
  "negative_prompt": "全局不要出现的元素（英文）"
}}
```"""

CHARACTER_ART_PROMPT = """你是美术导演。根据全局美术风格和角色信息，生成角色立绘的详细生图指令。

全局风格：{art_style}

角色信息：
- 名字：{name}
- 外貌：{appearance}
- 身份：{identity}
- 性格：{traits}
- 说话风格：{speech_style}

请输出JSON：
```json
{{
  "prompt": "详细的角色立绘生图 prompt（英文）。包含：画风统一、全身站姿、白色背景、角色外貌细节（发色/瞳色/体型/标志性特征）、服装细节、表情和姿态暗示性格、光影和全局风格一致",
  "negative_prompt": "不要出现的元素"
}}
```"""

SCENE_ART_PROMPT = """你是美术导演。根据全局美术风格和场景信息，生成场景背景的详细生图指令。

全局风格：{art_style}

场景信息：
- 名字：{name}
- 描述：{description}

请输出JSON：
```json
{{
  "prompt": "详细的场景背景生图 prompt（英文）。包含：画风统一、宽幅横构图16:9、无人物、环境细节丰富（建筑/自然/物件/氛围）、光影和时间感、全局风格一致",
  "negative_prompt": "不要出现的元素"
}}
```"""


async def main():
    logger.info(f"=== SuperAgent 美术导演生图: {STORY_ID} ===")

    store = await NovelStore.create(
        db_path=mgr.story_db(STORY_ID),
        namespace="novel2gal", database=STORY_ID,
        asset_root=mgr.story_assets(STORY_ID),
    )

    chars = await store.get_all_characters()
    locs = await store.get_all_locations()
    rules = await store.get_all_world_rules()
    logger.info(f"角色: {len(chars)}, 地点: {len(locs)}, 规则: {len(rules)}")

    llm_url = os.environ.get("LLM_BASE_URL", "http://192.168.21.13:1234")
    llm_model = os.environ.get("LLM_MODEL", "google/gemma-4-e4b")

    asset_root = mgr.story_assets(STORY_ID)
    epub_dir = mgr.story_dir(STORY_ID) / "epub_images"

    async with LLMClient(base_url=llm_url, model=llm_model, timeout=300) as llm:

        # ---- Step 1: 生成全局美术风格卡 ----
        logger.info("Step 1: 生成全局美术风格卡...")
        rules_text = "\n".join(f"- {r.get('description', '')}" for r in rules[:5])
        chars_text = ", ".join(c.get("name", "?") for c in chars[:10])

        entry = mgr.get_story(STORY_ID)
        title = entry.title if entry else "Overlord"

        art_style_data = await llm.chat_json(
            system=ART_STYLE_PROMPT.format(title=title, world_rules=rules_text, characters=chars_text),
            user="请定义美术风格卡。",
        )
        art_style = art_style_data.get("style_description", "anime style, detailed, high quality")
        global_negative = art_style_data.get("negative_prompt", "low quality, blurry, deformed")
        logger.info(f"  风格: {art_style[:80]}...")
        logger.info(f"  negative: {global_negative[:60]}...")

        # 保存风格卡
        style_path = asset_root / "art_style.json"
        style_path.write_text(json.dumps(art_style_data, ensure_ascii=False, indent=2))

        # ---- Step 2: 为每个角色生成 art prompt ----
        logger.info(f"\nStep 2: 为 {len(chars)} 个角色生成 art prompt...")
        char_prompts = {}
        for c in chars:
            cfg = c.get("config", {})
            name = c.get("name", "?")
            try:
                result = await llm.chat_json(
                    system=CHARACTER_ART_PROMPT.format(
                        art_style=art_style,
                        name=name,
                        appearance=cfg.get("appearance_summary", ""),
                        identity=cfg.get("identity", ""),
                        traits=", ".join(cfg.get("traits", [])),
                        speech_style=cfg.get("speech_style", ""),
                    ),
                    user=f"请为 {name} 生成立绘指令。",
                )
                char_prompts[cfg.get("id", "")] = result
                logger.info(f"  {name}: {result.get('prompt', '')[:60]}...")
            except Exception as e:
                logger.warning(f"  {name} art prompt 失败: {e}")

        # ---- Step 3: 为每个地点生成 art prompt ----
        logger.info(f"\nStep 3: 为 {len(locs)} 个地点生成 art prompt...")
        loc_prompts = {}
        for loc in locs:
            name = loc.get("name", "?")
            try:
                result = await llm.chat_json(
                    system=SCENE_ART_PROMPT.format(
                        art_style=art_style,
                        name=name,
                        description=loc.get("description", ""),
                    ),
                    user=f"请为 {name} 生成背景指令。",
                )
                loc_id = name.replace(" ", "_").lower()
                loc_prompts[loc_id] = result
                logger.info(f"  {name}: {result.get('prompt', '')[:60]}...")
            except Exception as e:
                logger.warning(f"  {name} art prompt 失败: {e}")

    # ---- Step 4: AnyGen 并行生图 ----
    logger.info(f"\nStep 4: AnyGen 生图 ({len(char_prompts)} 角色 + {len(loc_prompts)} 地点, 并行=4)")

    if not os.environ.get("ANYGEN_API_KEY"):
        logger.error("无 ANYGEN_API_KEY，跳过生图")
        return

    semaphore = asyncio.Semaphore(4)
    results = {}

    async def gen_char(char_id: str, art: dict):
        async with semaphore:
            out = asset_root / f"character_{char_id}" / "base" / "sprite.png"
            if out.exists():
                return
            path = await generate_character_sprite(
                name=char_id, appearance="",
                output_path=out, art_prompt=art.get("prompt", ""),
            )
            if path:
                results[f"char_{char_id}"] = str(path)

    async def gen_loc(loc_id: str, art: dict):
        async with semaphore:
            out = asset_root / f"location_{loc_id}" / "base" / "background.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists():
                return
            path = await generate_scene_background(
                name=loc_id, description="",
                output_path=out, art_prompt=art.get("prompt", ""),
            )
            if path:
                results[f"loc_{loc_id}"] = str(path)

    tasks = []
    for cid, art in char_prompts.items():
        tasks.append(gen_char(cid, art))
    for lid, art in loc_prompts.items():
        tasks.append(gen_loc(lid, art))

    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"\n=== 完成: {len(results)}/{len(char_prompts) + len(loc_prompts)} 张图片 ===")
    for k, v in results.items():
        logger.info(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
