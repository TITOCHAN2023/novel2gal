"""
玩家角色设置 — 步骤6

对应文档：
  - player-profiling.md: 玩家主角用和NPC相同的角色卡机制
  - project_player_role.md: 选择原著角色 / 创建新角色 / 默认创建新角色

流程：
  1. 列出可选的原著角色
  2. 玩家选择一个，或输入新角色名
  3. 如果选择原著角色 → 复制该角色卡作为玩家角色卡
  4. 如果创建新角色 → 用 LLM 基于世界观生成新角色卡
  5. 将玩家角色卡写入图数据库（标记 is_player=true）
"""
from __future__ import annotations

import json
import logging

try:
    from ..db.store import NovelStore
    from ..config.llm_client import LLMClient
except ImportError:
    from db.store import NovelStore
    from config.llm_client import LLMClient

logger = logging.getLogger(__name__)

CREATE_CHARACTER_PROMPT = """你是角色创作专家。根据以下世界观信息，为玩家创建一个新角色。

世界观规则：
{world_rules}

已有角色（避免重复）：
{existing_characters}

玩家输入的角色名：{player_name}

请生成角色卡，JSON格式：
```json
{{
  "natural_language": "完整的自然语言角色卡（markdown格式，含外貌、性格、背景故事、说话风格）",
  "config": {{
    "id": "英文id",
    "name": "角色名",
    "aliases": [],
    "age": "",
    "identity": "身份",
    "traits": ["性格特征"],
    "speech_style": "说话风格",
    "abilities": [],
    "appearance_summary": "外貌描述"
  }},
  "example_dialogues": ["示例对话1", "示例对话2"]
}}
```

要求：
- 角色要能自然融入这个世界观
- 性格鲜明，有辨识度
- 背景故事合理但留有空白（让玩家通过游玩填充）"""


async def setup_player_character(
    store: NovelStore,
    llm: LLMClient | None = None,
    player_input: str = "",
) -> dict:
    """
    设置玩家角色。

    Args:
        store: 图数据库
        llm: LLM 客户端（创建新角色时需要）
        player_input: 玩家输入的角色名（空=默认创建新角色）

    Returns:
        玩家角色的数据 dict
    """
    logger.info("=== 步骤6: 玩家角色设置 ===")

    characters = await store.get_all_characters()
    char_names = {c["name"]: c for c in characters}
    char_ids = {c.get("config", {}).get("id", ""): c for c in characters}

    logger.info(f"可选原著角色: {list(char_names.keys())}")

    # 判断玩家选择
    chosen_char = None
    if player_input:
        # 按名字匹配
        if player_input in char_names:
            chosen_char = char_names[player_input]
        # 按 id 匹配
        elif player_input in char_ids:
            chosen_char = char_ids[player_input]

    if chosen_char:
        # 选择了原著角色 → 复制角色卡，标记为玩家
        logger.info(f"玩家选择原著角色: {chosen_char['name']}")
        char_id = chosen_char.get("config", {}).get("id", "player")

        await store.db.query(
            "UPDATE type::thing('character', $id) SET is_player = true",
            {"id": char_id},
        )

        logger.info(f"已标记 {chosen_char['name']} 为玩家角色")
        return chosen_char

    else:
        # 创建新角色——直接用默认模板（快速，不需要 LLM）
        # LLM 生成角色卡太慢（31B 模型 5 分钟+），用模板更可靠
        player_name = player_input or "旅人"
        logger.info(f"创建新角色: {player_name}")

        if False and llm:  # 暂时跳过 LLM 生成，用默认模板
            # 用 LLM 生成角色卡
            rules = await store.get_all_world_rules()
            rules_text = "\n".join(f"- [{r.get('category','')}] {r.get('description','')}" for r in rules)
            existing_text = ", ".join(char_names.keys())

            prompt = CREATE_CHARACTER_PROMPT.format(
                world_rules=rules_text,
                existing_characters=existing_text,
                player_name=player_name,
            )

            card_data = await llm.chat_json(system=prompt, user=f"请为 {player_name} 创建角色卡。")
        else:
            # Mock: 无 LLM 时使用默认角色卡
            card_data = {
                "natural_language": f"# {player_name}\n\n一个刚来到这个世界的旅人，背景不明，性格待定。",
                "config": {
                    "id": "player",
                    "name": player_name,
                    "aliases": [],
                    "identity": "旅人",
                    "traits": ["好奇", "适应力强"],
                    "speech_style": "平和，偶尔惊讶",
                    "appearance_summary": "ordinary looking traveler",
                },
                "example_dialogues": [],
            }

        config = card_data.get("config", {})
        char_id = config.get("id", "player")

        await store.upsert_character(
            char_id=char_id,
            name=config.get("name", player_name),
            card=card_data.get("natural_language", ""),
            config=config,
            dialogues=card_data.get("example_dialogues", []),
            memories=[],
            version=0,
        )

        # 标记为玩家角色
        await store.db.query(
            "UPDATE type::thing('character', $id) SET is_player = true",
            {"id": char_id},
        )

        logger.info(f"新角色创建完成: {config.get('name', player_name)}")
        return card_data
