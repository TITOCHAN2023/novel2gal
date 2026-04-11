"""
核心数据模型 — 角色卡、场景、世界状态、解析结果
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ============================================================
# 角色卡：双层结构
# ============================================================

class CharacterConfig(BaseModel):
    """结构化配置层 — 由自然语言角色卡自动格式化输出，供 SuperAgent 编排时快速查询"""
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list, description="别名/外号")
    age: str = ""
    identity: str = ""                          # 身份/职业
    traits: list[str] = Field(default_factory=list, description="核心性格特征")
    speech_style: str = ""                      # 说话风格概要
    abilities: list[str] = Field(default_factory=list)
    appearance_summary: str = ""                # 外貌概要（用于生图 prompt）
    default_outfit: str = ""                    # 默认服装描述
    schedule: dict[str, str] = Field(default_factory=dict, description="日程 {时段: 地点}")
    social: dict[str, str] = Field(default_factory=dict, description="对其他角色态度 {角色名: 态度}")


class CharacterCard(BaseModel):
    """完整角色卡 = 自然语言层 + 结构化配置层"""
    # 自然语言层（源头）
    natural_language: str = Field(description="完整的自然语言角色卡，markdown格式")
    # 结构化配置层（从自然语言自动派生）
    config: CharacterConfig
    # 示例对话（few-shot）
    example_dialogues: list[str] = Field(default_factory=list)
    # 初始记忆（已发生区中该角色亲历的事件）
    initial_memories: list[str] = Field(default_factory=list)


# ============================================================
# 地点/场景
# ============================================================

class LocationCard(BaseModel):
    id: str
    name: str
    description: str                            # 自然语言描述
    atmosphere: str = ""                        # 氛围
    appearance_prompt: str = ""                 # 用于生图的外观描述


# ============================================================
# 世界观规则
# ============================================================

class WorldRule(BaseModel):
    id: str
    category: str                               # 势力/能力体系/地理/社会/...
    description: str


# ============================================================
# 事件（用于已发生区的时间线）
# ============================================================

class NovelEvent(BaseModel):
    id: str
    chapter: int
    summary: str
    participants: list[str] = Field(default_factory=list, description="参与角色ID列表")
    location: str = ""
    is_turning_point: bool = False              # 是否为关键转折点


# ============================================================
# 美术风格卡：双层结构（与角色卡平行）
# ============================================================

class ArtStyleConfig(BaseModel):
    """结构化标签层 — 供生图时快速查询"""
    base_style: str = "anime"                    # anime / realistic / watercolor / pixel
    color_palette: list[str] = Field(default_factory=list)  # 主色调 ["dark", "gold", "red"]
    lighting: str = "dramatic"                   # dramatic / soft / flat / neon
    line_weight: str = "medium"                  # thin / medium / thick
    detail_level: str = "high"                   # low / medium / high
    character_proportion: str = "standard"        # chibi / standard / realistic
    background_style: str = "detailed"           # minimal / detailed / painterly
    reference_artists: list[str] = Field(default_factory=list)  # ["so-bin", "abec"]


class ArtStyleCard(BaseModel):
    """完整美术风格卡 = 自然语言描述 + 结构化标签"""
    # 自然语言层（源头，LLM 根据小说风格/epub 插图生成）
    natural_language: str = Field(default="", description="完整的美术风格描述")
    # 结构化标签层（从自然语言自动派生）
    config: ArtStyleConfig = Field(default_factory=ArtStyleConfig)
    # 通用 negative prompt（所有图片共用）
    global_negative: str = "low quality, blurry, deformed, ugly, watermark, text, signature"
    # 角色立绘专用后缀
    character_suffix: str = "white background, full body, standing pose, facing viewer, detailed face"
    # 场景背景专用后缀
    scene_suffix: str = "wide shot, 16:9 aspect ratio, no characters, atmospheric, detailed environment"


# ============================================================
# 三时区解析结果
# ============================================================

class ThreeZoneContext(BaseModel):
    """三时区上下文 — 小说按起点切割后的结果"""

    class CanonPast(BaseModel):
        """已发生区：完整使用，按角色分发记忆"""
        summary: str                            # 全局摘要
        events: list[NovelEvent]                # 事件时间线
        character_memories: dict[str, list[str]]  # {角色ID: [该角色亲历的事件摘要]}

    class PresentState(BaseModel):
        """当前背景：起点处的世界快照"""
        character_states: dict[str, dict]       # {角色ID: {状态字段}}
        relationships: list[dict]               # [{from, to, type, description}]
        active_conflicts: list[str]             # 进行中的冲突/悬念
        world_state: dict[str, str]             # {状态key: value}

    class PotentialFuture(BaseModel):
        """潜在未来区：只取角色人设+环境，不取事件"""
        characters: list[CharacterCard]         # 未出场角色的角色卡（无记忆）
        locations: list[LocationCard]           # 未出现的地点
        world_rules: list[WorldRule]            # 额外的世界观规则
        # 注意：没有 events 字段 — 不提取事件

    canon_past: CanonPast
    present_state: PresentState
    potential_future: PotentialFuture


# ============================================================
# 完整解析结果
# ============================================================

class NovelParseResult(BaseModel):
    """小说解析的完整输出"""
    title: str
    total_chapters: int
    characters: list[CharacterCard]
    locations: list[LocationCard]
    world_rules: list[WorldRule]
    events: list[NovelEvent]
    turning_points: list[NovelEvent]            # 关键转折点子集

    def split_at(self, start_chapter: int) -> ThreeZoneContext:
        """按起点章节切割为三时区上下文"""
        past_events = [e for e in self.events if e.chapter < start_chapter]
        future_events = [e for e in self.events if e.chapter >= start_chapter]

        # 已发生区：完整事件 + 按角色分发记忆
        char_memories: dict[str, list[str]] = {}
        for event in past_events:
            for cid in event.participants:
                char_memories.setdefault(cid, []).append(event.summary)

        # 当前背景：起点处的状态（简化版，完整版需要图数据库快照）
        # 这里先给出结构，具体状态提取在解析时填充

        # 潜在未来：只取角色人设+环境
        past_char_ids = {cid for e in past_events for cid in e.participants}
        future_characters = [
            CharacterCard(
                natural_language=c.natural_language,
                config=c.config,
                example_dialogues=c.example_dialogues,
                initial_memories=[],  # 关键：潜在未来的角色没有记忆
            )
            for c in self.characters
            if c.config.id not in past_char_ids
        ]

        future_locations = [
            loc for loc in self.locations
            if not any(
                e.location == loc.id for e in past_events
            )
        ]

        return ThreeZoneContext(
            canon_past=ThreeZoneContext.CanonPast(
                summary="",  # 由 LLM 后续生成
                events=past_events,
                character_memories=char_memories,
            ),
            present_state=ThreeZoneContext.PresentState(
                character_states={},
                relationships=[],
                active_conflicts=[],
                world_state={},
            ),
            potential_future=ThreeZoneContext.PotentialFuture(
                characters=future_characters,
                locations=future_locations,
                world_rules=self.world_rules,
            ),
        )
