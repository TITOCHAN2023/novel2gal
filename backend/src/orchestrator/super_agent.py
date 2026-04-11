"""
SuperAgent（编排器 + 叙述者 + 美术导演）— 步骤7核心

职责（对应 multi-agent-generation.md + project_agent_design.md）：
  1. 场景设置：决定地点、在场角色、场景目标/张力
  2. 叙述者：生成旁白、场景描写、第三人称叙述
  3. 交互驱动：按轮次驱动 Character Agent 发言
  4. 节奏控制：判断何时到达自然选择点
  5. 选项提取：生成 2-3 个有意义的选择
  6. 记忆更新：场景结束后更新每个角色的记忆
  7. 角色卡迭代：场景后更新角色卡（活角色卡机制）
  8. 美术导演：为每个场景生成统一风格的生图指令（角色立绘+场景背景）

输出：引擎可消费的 Scene 对象（JSON）+ 生图指令
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

try:
    from ..config.llm_client import LLMClient
    from ..agent.character_agent import CharacterAgent
except ImportError:
    from config.llm_client import LLMClient
    from agent.character_agent import CharacterAgent

logger = logging.getLogger(__name__)

SCENE_PLAN_PROMPT = """你是一个视觉小说的导演（SuperAgent）。你负责规划下一个场景。

## 世界观规则
{world_rules}

## 当前可用角色
{available_characters}

## 当前可用地点
{available_locations}

## 玩家主角信息
{player_info}

## 之前的剧情摘要
{story_so_far}

## 任务
规划下一个场景，输出JSON：
```json
{{
  "location": "地点id",
  "characters_present": ["角色id1", "角色id2"],
  "scene_goal": "这个场景要达成的叙事目标（如：制造冲突、增进关系、揭露秘密）",
  "opening_narration": "场景开头的旁白/环境描写（2-3句，设定氛围）",
  "tension": "low/medium/high"
}}
```

注意：
- 根据玩家主角的经历和偏好，安排他可能感兴趣的场景
- characters_present 必须包含玩家角色
- 场景要有清晰的叙事目标，不要流水账"""

NARRATION_PROMPT = """你是视觉小说的叙述者。根据角色互动的进展，生成适当的旁白/环境描写。

当前场景：{scene_context}
最近的对话：
{recent_dialogue}

请输出1-2句旁白（第三人称，描写环境变化、角色表情/动作、氛围转变等）。
不要输出角色对话，只输出叙述性文字。"""

CHOICE_EXTRACTION_PROMPT = """你是视觉小说的导演。根据当前场景的发展，判断是否到了一个自然的选择点。

场景目标：{scene_goal}
已产生的对话轮数：{turn_count}
最近的对话：
{recent_dialogue}

如果已到选择点，输出JSON：
```json
{{
  "ready": true,
  "choices": [
    {{
      "text": "选项1显示文本",
      "internal_desc": "这个选择会导向什么方向"
    }},
    {{
      "text": "选项2显示文本",
      "internal_desc": "这个选择会导向什么方向"
    }}
  ],
  "closing_narration": "场景结束的旁白（1-2句）"
}}
```

如果还没到选择点，输出：
```json
{{
  "ready": false,
  "reason": "为什么还不到选择点"
}}
```

选择点的判断标准（要严格）：
- 对话必须已经过了至少20轮，不足20轮一律返回 ready=false
- 必须出现明确的分歧/决策时刻（不是随便找个理由就结束）
- 场景目标基本达成或出现了真正的戏剧性转折
- 一个好的场景应该有完整的起承转合，不要草草收场"""

MEMORY_UPDATE_PROMPT = """你是记忆管理者。根据场景中发生的事，为每个在场角色生成记忆摘要。

场景中的完整对话：
{full_dialogue}

在场角色：{characters}

为每个角色生成一条简短的记忆（从该角色的视角，只包含该角色知道/经历的事）：
```json
{{
  "memories": {{
    "角色id": "这个角色视角的记忆摘要（1-2句话）"
  }}
}}
```"""


@dataclass
class SceneLine:
    """场景中的一行"""
    type: str           # "dialogue" | "narration" | "thought"
    character: str = "" # dialogue/thought 时填写
    text: str = ""
    emotion: str = ""   # 角色当前情绪（happy/sad/angry/...）
    emotion_intensity: int = 5  # 情绪强度 1-10
    outfit: str = ""    # 角色当前着装（对应资产索引）


@dataclass
class SceneResult:
    """一个场景的完整输出"""
    scene_id: str
    location: str
    characters_present: list[str]
    lines: list[SceneLine] = field(default_factory=list)
    choices: list[dict] = field(default_factory=list)
    closing_narration: str = ""
    art_prompts: dict = field(default_factory=dict)  # 美术导演生成的生图指令

    def to_engine_json(self) -> dict:
        """转换为前端引擎可消费的 Scene 格式"""
        # 从对话中提取在场角色：按出场顺序收集，用 characters_present 的 ID 匹配
        seen_names: set[str] = set()
        char_entries: list[dict] = []

        # 构建 characters_present ID → 对话中角色名 的映射
        # characters_present 存的是 ID（如 "ainz_ooal_gown"），line.character 存的是显示名（如 "安兹"）
        # 优先：遍历对话行，按出场顺序收集唯一角色名，再用 characters_present 索引位置作 ID
        for line in self.lines:
            if line.character and line.character not in seen_names:
                seen_names.add(line.character)
                # 尝试从 characters_present 找对应 ID（按索引匹配）
                idx = len(char_entries)
                cid = self.characters_present[idx] if idx < len(self.characters_present) else line.character
                char_entries.append({"id": cid, "name": line.character})

        positions = ["left", "center", "right"]
        characters = [
            {
                "id": entry.get("id", f"char_{i}"),
                "name": entry.get("name", ""),
                "sprite": "",  # 待资产系统填充
                "position": positions[i % len(positions)],
                "isActive": False,
                "flipped": False,
            }
            for i, entry in enumerate(char_entries[:3])  # 最多 3 个
        ]

        return {
            "id": self.scene_id,
            "background": "",  # 待资产系统填充
            "bgm": "",
            "transition": "fade",
            "characters": characters if characters else None,
            "lines": [
                {
                    "type": line.type,
                    "character": line.character or None,
                    "text": line.text,
                    **({"emotion": line.emotion, "emotion_intensity": line.emotion_intensity, "outfit": line.outfit} if line.emotion else {}),
                }
                for line in self.lines
            ],
            "choices": [
                {
                    "text": c["text"],
                    "targetScene": f"{self.scene_id}_choice_{i}",
                }
                for i, c in enumerate(self.choices)
            ] if self.choices else None,
        }


ART_DIRECTION_PROMPT = """你是一个视觉小说的美术导演。根据场景规划和角色信息，为每个需要生成的图片资产写出详细的生图指令。

## 全局美术风格
{art_style}

## 当前场景
地点：{location}
氛围：{atmosphere}
时间：{time_of_day}
天气/季节：{weather_season}

## 在场角色
{characters_desc}

请为以下内容生成详细的生图 prompt（英文），JSON格式：
```json
{{
  "scene_background": {{
    "prompt": "详细的场景背景生图指令（包含风格、构图、光影、氛围、视角、季节天气时间）",
    "negative_prompt": "不要出现的元素"
  }},
  "character_sprites": [
    {{
      "character_id": "角色id",
      "character_name": "角色名",
      "prompt": "详细的角色立绘生图指令（包含风格统一、姿势、表情、服装细节、光影一致）",
      "negative_prompt": "不要出现的元素"
    }}
  ]
}}
```

要求：
- 所有图片必须风格统一（{art_style}）
- 背景图：宽幅横构图(16:9)，无人物，环境细节丰富
- 角色立绘：白色/纯色背景，全身或半身，面朝镜头或3/4侧面
- 光影要和场景时间/天气一致
- 服装要符合角色当前状态和世界观设定"""


class SuperAgent:
    """SuperAgent — 编排器 + 叙述者 + 美术导演"""

    def __init__(self, llm: LLMClient, art_style: str = ""):
        self.llm = llm
        # 全局美术风格（初始化时从小说风格推断，或用默认值）
        self.art_style = art_style or "Japanese anime/light novel illustration style, detailed, high quality, consistent character designs"

    async def plan_scene(
        self,
        world_rules: list[dict],
        available_characters: list[dict],
        available_locations: list[dict],
        player_info: dict,
        story_so_far: str,
    ) -> dict:
        """规划下一个场景"""
        logger.info("SuperAgent: 规划场景...")

        rules_text = "\n".join(f"- {r.get('description', '')}" for r in world_rules)
        chars_text = "\n".join(
            f"- {c.get('config', {}).get('id', '?')}: {c.get('name', '?')} — {c.get('config', {}).get('traits', [])}"
            for c in available_characters
        )
        locs_text = "\n".join(
            f"- {l.get('name', '?')}: {l.get('description', '')[:60]}"
            for l in available_locations
        )
        player_text = json.dumps({
            "name": player_info.get("name", ""),
            "traits": player_info.get("config", {}).get("traits", []),
        }, ensure_ascii=False)

        prompt = SCENE_PLAN_PROMPT.format(
            world_rules=rules_text,
            available_characters=chars_text,
            available_locations=locs_text,
            player_info=player_text,
            story_so_far=story_so_far or "（游戏刚开始，还没有剧情）",
        )

        plan = await self.llm.chat_json(system=prompt, user="请规划下一个场景。", temperature=0.7)

        # 校验必要字段
        if not isinstance(plan, dict) or not plan:
            logger.error(f"场景规划返回无效: {str(plan)[:200]}")
            plan = {}
        if "location" not in plan:
            plan["location"] = available_locations[0].get("name", "未知地点") if available_locations else "未知地点"
            logger.warning(f"场景规划缺少 location，使用默认: {plan['location']}")
        if "characters_present" not in plan or not plan["characters_present"]:
            # 默认选前2个角色
            plan["characters_present"] = [
                c.get("config", {}).get("id", "") for c in available_characters[:2]
            ]
            logger.warning(f"场景规划缺少 characters_present，使用默认: {plan['characters_present']}")
        if "scene_goal" not in plan:
            plan["scene_goal"] = "角色互动"

        logger.info(f"场景规划: 地点={plan.get('location')}, 角色={plan.get('characters_present')}, 目标={plan.get('scene_goal','')[:40]}")
        return plan

    async def generate_art_prompts(
        self,
        scene_plan: dict,
        characters_in_scene: list[dict],
    ) -> dict:
        """
        美术导演：为场景生成统一风格的生图指令

        Returns:
            {
                "scene_background": {"prompt": "...", "negative_prompt": "..."},
                "character_sprites": [{"character_id": "...", "prompt": "...", "negative_prompt": "..."}]
            }
        """
        chars_desc = "\n".join(
            f"- {c.get('name', '?')}: {c.get('config', {}).get('appearance_summary', '')} (当前状态: {c.get('config', {}).get('identity', '')})"
            for c in characters_in_scene
        )

        location = scene_plan.get("location", "unknown")
        opening = scene_plan.get("opening_narration", "")

        prompt = ART_DIRECTION_PROMPT.format(
            art_style=self.art_style,
            location=location,
            atmosphere=opening[:100] if opening else "未知",
            time_of_day=scene_plan.get("time_of_day", "day"),
            weather_season=scene_plan.get("weather_season", "未指定"),
            characters_desc=chars_desc,
        )

        try:
            result = await self.llm.chat_json(system=prompt, user="请生成本场景的生图指令。", max_tokens=2048, temperature=0.7)
            logger.info(f"美术导演: 生成了 {len(result.get('character_sprites', []))} 个角色 + 1 个背景的生图指令")
            return result
        except Exception as e:
            logger.warning(f"美术导演生图指令生成失败: {e}")
            return {"scene_background": {}, "character_sprites": []}

    async def generate_narration(self, scene_context: str, recent_dialogue: str) -> str:
        """生成旁白"""
        prompt = NARRATION_PROMPT.format(
            scene_context=scene_context,
            recent_dialogue=recent_dialogue,
        )
        raw = await self.llm.chat(system=prompt, user="请生成旁白。", max_tokens=128, temperature=0.9)
        # 旁白也不要换行——前端对话框一次显示一条
        return raw.strip().replace("\n\n", " ").replace("\n", " ")

    async def check_choice_point(
        self, scene_goal: str, turn_count: int, recent_dialogue: str
    ) -> dict:
        """判断是否到了选择点"""
        prompt = CHOICE_EXTRACTION_PROMPT.format(
            scene_goal=scene_goal,
            turn_count=turn_count,
            recent_dialogue=recent_dialogue,
        )
        result = await self.llm.chat_json(system=prompt, user="判断是否到了选择点。", temperature=0.3)
        if not isinstance(result, dict):
            logger.warning(f"选择点判断返回无效类型: {type(result)}")
            return {"ready": False}
        return result

    async def update_memories(
        self, full_dialogue: str, characters: list[str]
    ) -> dict[str, str]:
        """场景结束后更新角色记忆"""
        prompt = MEMORY_UPDATE_PROMPT.format(
            full_dialogue=full_dialogue,
            characters=", ".join(characters),
        )
        result = await self.llm.chat_json(system=prompt, user="请生成记忆摘要。", temperature=0.3)
        if not isinstance(result, dict):
            logger.warning(f"记忆更新返回无效类型: {type(result)}")
            return {}
        return result.get("memories", {})

    async def generate_scene(
        self,
        scene_id: str,
        scene_plan: dict,
        character_agents: dict[str, CharacterAgent],
        max_turns: int = 25,
        min_turns_before_choice: int = 12,
    ) -> SceneResult:
        """
        完整的场景生成流程：

        1. 开场旁白
        2. 角色交替发言（Character Agent 多轮交互）
        3. 每隔几轮插入旁白
        4. 检测选择点
        5. 提取选项
        6. 更新记忆
        """
        logger.info(f"SuperAgent: 生成场景 {scene_id}")

        result = SceneResult(
            scene_id=scene_id,
            location=scene_plan.get("location", ""),
            characters_present=scene_plan.get("characters_present", []),
        )

        # 开场旁白（按换行分割成多条）
        opening = scene_plan.get("opening_narration", "")
        if opening:
            for para in opening.split("\n"):
                para = para.strip()
                if para:
                    result.lines.append(SceneLine(type="narration", text=para))

        scene_context = f"地点: {scene_plan.get('location', '')}。{opening}"
        scene_goal = scene_plan.get("scene_goal", "")
        dialogue_history: list[str] = []

        # 确定发言顺序（轮流）
        present_ids = scene_plan.get("characters_present", [])
        agents_in_scene = [character_agents[cid] for cid in present_ids if cid in character_agents]

        if not agents_in_scene:
            logger.warning("场景中没有可用的角色 Agent")
            return result

        turn = 0
        while turn < max_turns:
            # 选择当前发言角色（轮流）
            agent = agents_in_scene[turn % len(agents_in_scene)]

            # 角色发言（结构化输出：1-3 句话，每句有独立 emotion）
            history_text = "\n".join(dialogue_history[-10:]) if dialogue_history else "（场景刚开始）"
            responses = await agent.respond(self.llm, scene_context, history_text)

            # responses 是 list[dict]，每个元素是一句话
            for resp in responses:
                text = resp.get("text", "")
                emotion = resp.get("emotion", "")
                intensity = resp.get("emotion_intensity", 5)
                outfit = resp.get("outfit", "")

                result.lines.append(SceneLine(
                    type="dialogue",
                    character=agent.name,
                    text=text,
                    emotion=emotion,
                    emotion_intensity=intensity,
                    outfit=outfit,
                ))
                dialogue_history.append(f"{agent.name}: {text}")

            turn += 1
            last_text = responses[-1].get("text", "") if responses else ""
            logger.debug(f"  轮 {turn}: {agent.name} ({len(responses)}句): {last_text[:40]}...")

            # 每 3 轮插入旁白
            if turn % 3 == 0 and turn < max_turns - 1:
                narration = await self.generate_narration(
                    scene_context, "\n".join(dialogue_history[-6:])
                )
                if narration.strip():
                    # 旁白按换行分割成多条（每条是一个独立的文本框）
                    for para in narration.strip().split("\n"):
                        para = para.strip()
                        if para:
                            result.lines.append(SceneLine(type="narration", text=para))

            # 检测选择点（至少过了 min_turns，之后每 5 轮检查一次）
            if turn >= min_turns_before_choice and turn % 5 == 0:
                choice_check = await self.check_choice_point(
                    scene_goal, turn, "\n".join(dialogue_history[-6:])
                )
                if choice_check.get("ready"):
                    result.choices = choice_check.get("choices", [])
                    closing = choice_check.get("closing_narration", "")
                    if closing:
                        result.lines.append(SceneLine(type="narration", text=closing))
                    logger.info(f"  选择点到达 (轮 {turn}): {len(result.choices)} 个选项")
                    break

        # 如果达到 max_turns 还没有选择点，强制生成选项（含超时保护）
        if not result.choices:
            logger.info(f"  达到最大轮数 {max_turns}，强制生成选项")
            try:
                import asyncio as _aio
                choice_check = await _aio.wait_for(
                    self.check_choice_point(scene_goal, turn, "\n".join(dialogue_history[-4:])),
                    timeout=120,
                )
                result.choices = choice_check.get("choices", [])
            except Exception as e:
                logger.warning(f"  选择点检查超时/失败: {e}，使用默认选项")
                result.choices = []
            if not result.choices:
                result.choices = [
                    {"text": "继续探索", "internal_desc": "继续当前方向"},
                    {"text": "改变话题", "internal_desc": "转向新的互动"},
                ]

        # 更新记忆
        memories = await self.update_memories(
            "\n".join(dialogue_history),
            [a.name for a in agents_in_scene],
        )
        for agent in agents_in_scene:
            if agent.name in memories:
                agent.add_memory(memories[agent.name])
                logger.info(f"  记忆更新: {agent.name} ← {memories[agent.name][:40]}...")

        # 活角色卡迭代：根据场景事件更新角色卡（对应 project_living_card.md）
        for agent in agents_in_scene:
            if agent.name in memories and memories[agent.name]:
                await self._update_character_card(agent, memories[agent.name])

        # 美术导演：为场景生成生图指令
        try:
            # 收集在场角色信息
            chars_info = []
            for agent in agents_in_scene:
                chars_info.append({
                    "name": agent.name,
                    "config": {"appearance_summary": "", "identity": ""},
                })
            result.art_prompts = await self.generate_art_prompts(scene_plan, chars_info)
        except Exception as e:
            logger.warning(f"  美术导演失败: {e}")

        logger.info(f"场景 {scene_id} 完成: {len(result.lines)} 行, {len(result.choices)} 选项")
        return result

    async def _update_character_card(self, agent: CharacterAgent, new_memory: str) -> None:
        """场景后更新角色卡（活角色卡机制）"""
        prompt = f"""你是角色卡维护专家。根据新发生的事件，更新角色卡。

当前角色卡：
{agent.card[:1500]}

新发生的事件（从该角色视角）：
{new_memory}

请输出更新后的角色卡要点（只输出需要修改/新增的部分，不要重写整张卡）：
- 如果性格有变化，说明变化
- 如果有新的关系变化，说明变化
- 如果有重要的新信息，补充

只输出变更部分，简洁明了，不超过3句话。如果没有显著变化，输出"无显著变化"。"""
        try:
            update = await self.llm.chat(system=prompt, user="请分析角色卡是否需要更新。", max_tokens=256, temperature=0.3)
            if "无显著变化" not in update:
                agent.card += f"\n\n### 最新变化\n{update.strip()}"
                logger.info(f"  角色卡迭代: {agent.name} ← {update.strip()[:50]}...")
        except Exception as e:
            logger.warning(f"  角色卡迭代失败 [{agent.name}]: {e}")
