"""
三时区上下文管理器

按起点章节将解析结果切割为：
  - 已发生 (Canon Past): 完整使用，按角色分发记忆
  - 当前背景 (Present State): 世界状态快照
  - 潜在未来 (Potential Future): 只取角色人设+环境，不取事件

对应文档: three-zone-context.md
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ThreeZoneContext:
    """三时区上下文"""

    # 已发生区
    canon_past_summary: str = ""                          # 全局剧情摘要
    character_memories: dict[str, list[str]] = field(default_factory=dict)  # {角色id: [该角色亲历的事件]}

    # 当前背景
    world_state: dict[str, str] = field(default_factory=dict)
    active_conflicts: list[str] = field(default_factory=list)

    # 潜在未来区（只有人设，不有事件）
    future_characters: dict[str, dict] = field(default_factory=dict)  # {角色id: 角色卡config}
    future_locations: list[dict] = field(default_factory=list)
    world_rules: list[dict] = field(default_factory=list)

    # 所有角色的角色卡（按版本）
    character_cards: dict[str, dict] = field(default_factory=dict)     # {角色id: 对应版本的角色卡}


def build_three_zone_context(
    parse_cache_path: Path,
    start_chunk: int = 0,
) -> ThreeZoneContext:
    """
    从解析缓存构建三时区上下文

    Args:
        parse_cache_path: parse_cache.json 路径
        start_chunk: 玩家选择的起点块索引（0=从头开始=续集模式）
    """
    logger.info(f"构建三时区上下文 (起点块={start_chunk})")

    cache = json.loads(parse_cache_path.read_text(encoding="utf-8"))
    chunk_results = cache.get("chunk_results", [])
    card_versions = cache.get("character_card_versions", {})
    synthesis = cache.get("synthesis", {})
    total_chunks = len(chunk_results)

    ctx = ThreeZoneContext()

    # 世界观规则（全局，不按时区切割）
    ctx.world_rules = synthesis.get("world_rules", [])

    if start_chunk <= 0:
        # 续集模式（从最后开始）：全部都是已发生
        start_chunk = total_chunks

    # ---- 已发生区：起点之前的所有块 ----
    past_chunks = [cr for cr in chunk_results if cr["chunk_index"] < start_chunk]
    past_char_ids: set[str] = set()

    # 全局剧情摘要
    summaries = [cr.get("chapter_summary", "") for cr in past_chunks if cr.get("chapter_summary")]
    ctx.canon_past_summary = "\n".join(summaries)

    # 按角色分发记忆（只给该角色亲历的事件）
    for cr in past_chunks:
        for event in cr.get("events", []):
            participants = event.get("participants", [])
            summary = event.get("summary", "")
            for pid in participants:
                ctx.character_memories.setdefault(pid, []).append(summary)
                past_char_ids.add(pid)

    # 角色卡：用对应版本（起点之前最后一个版本）
    for cid, versions in card_versions.items():
        if cid in past_char_ids:
            # 找到起点之前最后的版本
            # versions 是按块顺序积累的，取不超过 start_chunk 个
            version_idx = min(len(versions) - 1, start_chunk - 1)
            if version_idx >= 0:
                ctx.character_cards[cid] = versions[version_idx]

    # ---- 潜在未来区：起点之后的块 ----
    future_chunks = [cr for cr in chunk_results if cr["chunk_index"] >= start_chunk]

    for cr in future_chunks:
        for char in cr.get("characters", []):
            cid = char.get("id", "")
            if cid and cid not in past_char_ids and cid not in ctx.future_characters:
                # 新角色：只取人设，不取事件（no memories!）
                # 用最新版本的角色卡 config
                if cid in card_versions and card_versions[cid]:
                    latest = card_versions[cid][-1]
                    ctx.future_characters[cid] = {
                        "config": latest.get("config", {}),
                        "natural_language": latest.get("natural_language", ""),
                        "example_dialogues": latest.get("example_dialogues", []),
                        # 关键：没有 memories
                    }

        for loc in cr.get("locations", []):
            lid = loc.get("id", "")
            if lid and not any(l.get("id") == lid for l in ctx.future_locations):
                ctx.future_locations.append(loc)

    logger.info(f"三时区上下文构建完成:")
    logger.info(f"  已发生: {len(past_chunks)} 块, {len(ctx.character_memories)} 角色有记忆")
    logger.info(f"  潜在未来: {len(ctx.future_characters)} 新角色(无记忆), {len(ctx.future_locations)} 新地点")
    logger.info(f"  世界观规则: {len(ctx.world_rules)}")

    return ctx


def get_character_context(ctx: ThreeZoneContext, char_id: str) -> dict:
    """
    为特定角色获取其上下文（供 CharacterAgent 使用）

    Returns:
        {
            "card": 自然语言角色卡,
            "config": 结构化配置,
            "memories": 该角色的记忆列表（已发生区的亲历事件）,
            "example_dialogues": 示例对话,
            "is_future": 是否是潜在未来区的角色（无记忆）
        }
    """
    # 已发生区的角色
    if char_id in ctx.character_cards:
        card = ctx.character_cards[char_id]
        return {
            "card": card.get("natural_language", ""),
            "config": card.get("config", {}),
            "memories": ctx.character_memories.get(char_id, []),
            "example_dialogues": card.get("example_dialogues", []),
            "is_future": False,
        }

    # 潜在未来区的角色（只有人设，没有记忆）
    if char_id in ctx.future_characters:
        fc = ctx.future_characters[char_id]
        return {
            "card": fc.get("natural_language", ""),
            "config": fc.get("config", {}),
            "memories": [],  # 关键：空记忆
            "example_dialogues": fc.get("example_dialogues", []),
            "is_future": True,
        }

    return {"card": "", "config": {}, "memories": [], "example_dialogues": [], "is_future": True}


def build_super_agent_context(ctx: ThreeZoneContext) -> str:
    """
    为 SuperAgent 构建完整世界观上下文（注入 system prompt）
    """
    parts = []

    # 世界观规则
    if ctx.world_rules:
        parts.append("## 世界观规则")
        for r in ctx.world_rules:
            parts.append(f"- [{r.get('category', '')}] {r.get('description', '')}")

    # 已发生的剧情摘要
    if ctx.canon_past_summary:
        parts.append("\n## 已发生的剧情（不可改变的历史）")
        parts.append(ctx.canon_past_summary)

    # 当前世界状态
    if ctx.world_state:
        parts.append("\n## 当前世界状态")
        for k, v in ctx.world_state.items():
            parts.append(f"- {k}: {v}")

    # 可用角色概览
    all_chars = {}
    for cid, card in ctx.character_cards.items():
        cfg = card.get("config", {})
        all_chars[cid] = f"{cfg.get('name', cid)} — {', '.join(cfg.get('traits', []))}"
    for cid, fc in ctx.future_characters.items():
        cfg = fc.get("config", {})
        all_chars[cid] = f"{cfg.get('name', cid)} — {', '.join(cfg.get('traits', []))} (尚未登场)"

    if all_chars:
        parts.append("\n## 可用角色")
        for cid, desc in all_chars.items():
            parts.append(f"- {cid}: {desc}")

    return "\n".join(parts)
