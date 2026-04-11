"""
小说解析器 — 逐章递进式解析

设计原则（Harness > Model）：
  - 每步任务小而明确（micro-pass），弱模型也能做对
  - 角色卡逐章递进构建，保留每版（供三时区切割）
  - JSON 输出 + 健壮提取（多策略容错）
  - 不依赖任何特定模型特性

解析流程：
  对每章（或分块后的每块）：
    micro-pass 1: 提取角色列表（谁出现了）
    micro-pass 2: 提取地点列表
    micro-pass 3: 提取事件和剧情摘要
    micro-pass 4: 提取角色对话样本
    micro-pass 5: 更新角色卡（基于上一版角色卡 + 本章新信息）
  全书完成后：
    合并 pass: 跨章关系归纳 + 世界观规则 + 转折点标注
"""
from __future__ import annotations

import json
import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

try:
    from ..config.llm_client import LLMClient
    from .chunker import chunk_novel, Chunk
except ImportError:
    from config.llm_client import LLMClient
    from parser.chunker import chunk_novel, Chunk

console = Console()


# ============================================================
# Prompts — 每个极度聚焦，输出简单
# ============================================================

EXTRACT_CHARACTERS = """你是小说分析助手。从文本中提取所有出现的角色，以JSON格式输出。

输出示例：
```json
{
  "characters": [
    {
      "id": "zhang_san",
      "name": "张三",
      "aliases": ["小张", "张老师"],
      "description": "一个穿着白衬衫的年轻男子，性格沉稳，在本段中安慰了李四"
    },
    {
      "id": "li_si",
      "name": "李四",
      "aliases": [],
      "description": "张三的学生，活泼好动，本段中因考试失利而沮丧"
    }
  ]
}
```

规则：
- id用小写英文+下划线，同一角色在不同段落保持同一id
- description要包含本段中对该角色的描写（外貌、性格、行为）
- 只提取文本中实际出现或直接参与行动的角色
- 如果某角色只是被其他人提及但未出场，description标注"仅被提及"
- 完整输出所有角色，不要用省略号"""

EXTRACT_LOCATIONS = """你是小说分析助手。从文本中提取所有出现的地点/场景，以JSON格式输出。

输出示例：
```json
{
  "locations": [
    {
      "id": "old_library",
      "name": "旧图书馆",
      "description": "位于学院东侧的三层建筑，光线昏暗，书架间弥漫着旧纸张的气味"
    }
  ]
}
```

规则：
- id用小写英文+下划线
- description包含环境的外观、氛围、特点
- 只提取文本中明确出现或描写的地点
- 完整输出，不要省略"""

EXTRACT_EVENTS = """你是小说分析助手。从文本中提取关键事件并写摘要，以JSON格式输出。

输出示例：
```json
{
  "events": [
    {
      "summary": "张三在图书馆与李四发生争执",
      "participants": ["zhang_san", "li_si"],
      "location": "old_library",
      "significance": "medium"
    }
  ],
  "chapter_summary": "张三来到图书馆寻找资料，意外遇到李四。两人因观点不同发生争执，最终被管理员劝开。"
}
```

规则：
- participants使用角色的英文id
- location使用地点的英文id
- significance: low(日常)/medium(推动剧情)/high(重大转折)
- chapter_summary用3-5句话概括本段主要发展
- 完整输出，不要省略"""

EXTRACT_DIALOGUES = """你是小说分析助手。从文本中提取各角色最有代表性的对话，以JSON格式输出。

输出示例：
```json
{
  "dialogues": {
    "zhang_san": [
      "「你以为这样就能解决问题吗？」",
      "「……算了，随你便吧。」"
    ],
    "li_si": [
      "「老师，我真的尽力了！」"
    ]
  }
}
```

规则：
- key是角色的英文id
- 保留原文对话，含引号或括号
- 每个角色最多5句最能体现说话风格的对话
- 完整输出，不要省略"""

UPDATE_CHARACTER_CARD = """你是角色卡专家。根据新的章节信息，更新角色卡。

当前角色卡（上一版）：
{current_card}

本章中该角色的新信息：
- 描写：{new_description}
- 新对话样本：{new_dialogues}
- 参与事件：{new_events}

请输出更新后的角色卡，JSON格式：
{{
  "natural_language": "完整的自然语言角色卡（markdown格式，包含：外貌、性格、说话风格、背景故事、行为模式）。如果本章有新信息就更新，没有就保留原来的。",
  "config": {{
    "id": "角色id",
    "name": "角色名",
    "aliases": [],
    "age": "",
    "identity": "身份/职业",
    "traits": ["核心性格特征，3-5个词"],
    "speech_style": "一句话概括说话风格",
    "abilities": ["能力列表"],
    "appearance_summary": "外貌概要（可用于生图prompt，英文为佳）"
  }},
  "example_dialogues": ["最能体现角色风格的3-5句对话"]
}}

重要：保留上一版的所有信息，在此基础上增补本章新内容。不要丢失已有信息。"""

SYNTHESIZE_RELATIONSHIPS = """你是小说分析专家。根据全书各章的信息，归纳角色关系网、世界观规则和转折点。

各章提取结果：
{chapter_summaries}

全部角色：
{all_characters}

只输出JSON，格式：
{{
  "relationships": [
    {{
      "from": "角色id",
      "to": "角色id",
      "type": "关系类型（认识/朋友/主从/敌对/师徒/同僚/...）",
      "description": "关系描述"
    }}
  ],
  "world_rules": [
    {{
      "id": "规则id",
      "category": "分类（势力/能力体系/种族/科技/社会规则/...）",
      "description": "规则内容"
    }}
  ],
  "turning_points": [
    {{
      "chunk_index": 0,
      "summary": "转折点描述",
      "impact": "对后续的影响"
    }}
  ]
}}"""


@dataclass
class ChunkResult:
    """一个文本块的解析结果"""
    chunk_index: int
    characters: list[dict] = field(default_factory=list)
    locations: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    chapter_summary: str = ""
    dialogues: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ParseState:
    """解析过程中的累积状态"""
    # 角色卡版本历史：{角色id: [v0, v1, v2, ...]}
    character_card_versions: dict[str, list[dict]] = field(default_factory=dict)
    # 所有块的解析结果
    chunk_results: list[ChunkResult] = field(default_factory=list)
    # 已知角色 id 列表（用于跨块一致性）
    known_character_ids: dict[str, str] = field(default_factory=dict)  # {name: id}


class NovelParser:
    """逐章递进式小说解析器"""

    def __init__(
        self,
        llm: LLMClient,
        max_chunk_chars: int = 6000,
    ):
        self.llm = llm
        self.max_chunk_chars = max_chunk_chars

    async def _micro_pass(self, system: str, user_content: str) -> dict:
        """执行一个 micro-pass（单次 LLM 调用 + JSON 提取）"""
        return await self.llm.chat_json(system=system, user=user_content, temperature=0.3)

    # ---- 逐块 Micro-passes ----

    async def extract_characters(self, text: str, known_ids: dict[str, str]) -> list[dict]:
        hint = ""
        if known_ids:
            hint = f"\n\n已知角色ID映射（请复用这些ID）：\n{json.dumps(known_ids, ensure_ascii=False)}"
        result = await self._micro_pass(EXTRACT_CHARACTERS, text + hint)
        return result.get("characters", [])

    async def extract_locations(self, text: str) -> list[dict]:
        result = await self._micro_pass(EXTRACT_LOCATIONS, text)
        return result.get("locations", [])

    async def extract_events(self, text: str, characters: list[dict], locations: list[dict]) -> dict:
        context = f"本段出现的角色：{json.dumps([c['id'] for c in characters], ensure_ascii=False)}\n"
        context += f"本段出现的地点：{json.dumps([l['id'] for l in locations], ensure_ascii=False)}\n\n"
        result = await self._micro_pass(EXTRACT_EVENTS, context + text)
        return result

    async def extract_dialogues(self, text: str, characters: list[dict]) -> dict[str, list[str]]:
        context = f"本段出现的角色ID：{json.dumps([c['id'] for c in characters], ensure_ascii=False)}\n\n"
        result = await self._micro_pass(EXTRACT_DIALOGUES, context + text)
        return result.get("dialogues", {})

    async def update_character_card(
        self, char_id: str, current_card: dict | None,
        new_description: str, new_dialogues: list[str], new_events: list[str],
    ) -> dict:
        current_card_str = json.dumps(current_card, ensure_ascii=False, indent=2) if current_card else "（这是该角色首次出现，没有之前的角色卡）"
        prompt = UPDATE_CHARACTER_CARD.format(
            current_card=current_card_str,
            new_description=new_description,
            new_dialogues=json.dumps(new_dialogues, ensure_ascii=False),
            new_events=json.dumps(new_events, ensure_ascii=False),
        )
        return await self._micro_pass(prompt, f"请更新角色 {char_id} 的角色卡。")

    # ---- 逐块处理主流程 ----

    async def process_chunk(self, chunk: Chunk, state: ParseState) -> ChunkResult:
        """处理一个文本块（5个micro-pass顺序执行）"""
        text = chunk.text
        result = ChunkResult(chunk_index=chunk.index)

        # 1. 提取角色
        console.print(f"  [dim]├─ 角色提取...[/]")
        result.characters = await self.extract_characters(text, state.known_character_ids)
        for c in result.characters:
            state.known_character_ids[c["name"]] = c["id"]
            for alias in c.get("aliases", []):
                state.known_character_ids[alias] = c["id"]

        # 2. 提取地点
        console.print(f"  [dim]├─ 地点提取...[/]")
        result.locations = await self.extract_locations(text)

        # 3. 提取事件
        console.print(f"  [dim]├─ 事件提取...[/]")
        events_data = await self.extract_events(text, result.characters, result.locations)
        result.events = events_data.get("events", [])
        result.chapter_summary = events_data.get("chapter_summary", "")

        # 4. 提取对话
        console.print(f"  [dim]├─ 对话提取...[/]")
        result.dialogues = await self.extract_dialogues(text, result.characters)

        # 5. 更新每个角色的角色卡（逐章递进）
        for char in result.characters:
            cid = char["id"]
            # 跳过"仅被提及"的角色
            if "仅被提及" in char.get("description", ""):
                continue

            console.print(f"  [dim]├─ 更新角色卡: {char['name']}...[/]")
            current_card = None
            if cid in state.character_card_versions and state.character_card_versions[cid]:
                current_card = state.character_card_versions[cid][-1]

            char_events = [
                e["summary"] for e in result.events
                if cid in e.get("participants", [])
            ]
            char_dialogues = result.dialogues.get(cid, [])

            updated_card = await self.update_character_card(
                cid, current_card,
                char.get("description", ""),
                char_dialogues,
                char_events,
            )
            state.character_card_versions.setdefault(cid, []).append(updated_card)

        console.print(f"  [dim]└─ 完成[/]")
        state.chunk_results.append(result)
        return result

    # ---- 全书合成 ----

    async def synthesize(self, state: ParseState) -> dict:
        """全书完成后：跨章关系归纳"""
        summaries = []
        all_char_names = {}
        for r in state.chunk_results:
            summaries.append(f"块{r.chunk_index}: {r.chapter_summary}")
            for c in r.characters:
                all_char_names[c["id"]] = c["name"]

        prompt = SYNTHESIZE_RELATIONSHIPS.format(
            chapter_summaries="\n".join(summaries),
            all_characters=json.dumps(all_char_names, ensure_ascii=False, indent=2),
        )
        console.print("[cyan]跨章合成：关系网 + 世界观规则 + 转折点...[/]")
        return await self._micro_pass(prompt, "请进行全书跨章分析。")

    # ---- 主入口 ----

    async def parse(self, chunks: list[Chunk]) -> tuple[ParseState, dict]:
        """
        完整解析流程。

        Returns:
            (state, synthesis) — state 包含逐块结果和角色卡版本历史，
                                 synthesis 包含关系网/世界观/转折点
        """
        console.rule("[bold]Novel2Gal 小说解析")
        console.print(f"共 {len(chunks)} 个文本块")

        state = ParseState()

        for chunk in chunks:
            console.print(f"\n[bold cyan]处理块 {chunk.index}: {chunk.chapter_title}[/] ({chunk.char_count} 字)")
            await self.process_chunk(chunk, state)

        # 全书合成
        synthesis = await self.synthesize(state)

        # 统计
        total_chars = len(state.character_card_versions)
        total_events = sum(len(r.events) for r in state.chunk_results)
        total_locations = len({
            loc["id"]
            for r in state.chunk_results
            for loc in r.locations
        })

        console.print(f"\n[bold green]解析完成[/]")
        console.print(f"  角色：{total_chars}（含角色卡版本历史）")
        console.print(f"  地点：{total_locations}")
        console.print(f"  事件：{total_events}")
        console.print(f"  关系：{len(synthesis.get('relationships', []))}")
        console.print(f"  世界观规则：{len(synthesis.get('world_rules', []))}")
        console.print(f"  转折点：{len(synthesis.get('turning_points', []))}")

        return state, synthesis
