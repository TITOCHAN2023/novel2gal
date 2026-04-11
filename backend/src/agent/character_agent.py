"""
角色 Agent — 每个在场角色的独立 AI

参考 SillyTavern 角色卡体系：
  prompt 组装顺序：角色卡(自然语言) → 记忆 → 当前状态 → 关系 → 场景上下文 → 对话历史

对应文档：
  - multi-agent-generation.md
  - character-dialogue.md
  - project_agent_design.md
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

try:
    from ..config.llm_client import LLMClient
except ImportError:
    from config.llm_client import LLMClient

logger = logging.getLogger(__name__)

CHARACTER_SYSTEM = """你正在扮演一个角色。请完全以该角色的身份说话和行动。

## 你的角色卡
{character_card}

## 你的记忆（你亲身经历过的事）
{memories}

## 你当前的状态
{current_state}

## 你与在场角色的关系
{relationships}

## 输出格式（严格 JSON 数组）
输出一个 JSON 数组，每个元素是角色说的一小句话。人说话是一句一句的，不是一大段。每句话可以有不同的表情。

```json
[
  {{"text": "说起来你知道吗？", "emotion": "happy", "emotion_intensity": 5, "outfit": "dark_robe"}},
  {{"text": "*沉思片刻* 那个地方好像不太对劲。", "emotion": "worried", "emotion_intensity": 4, "outfit": "dark_robe"}},
  {{"text": "不过管它呢！*笑了起来*", "emotion": "happy", "emotion_intensity": 7, "outfit": "dark_robe"}}
]
```

严格规则：
- 输出 1-3 句话的数组，每句不超过 30 字
- 每句可以有不同的 emotion（表情会跟着变）
- 不要 markdown、不要分析、不要编号——只输出角色说的话
- 动作描写用 *斜体* 放在句子里
- emotion: neutral/happy/sad/angry/surprised/worried/excited/shy
- outfit: 简短英文"""


@dataclass
class CharacterAgent:
    """角色 Agent — 以特定角色身份参与场景交互"""
    char_id: str
    name: str
    card: str                           # 自然语言角色卡
    memories: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)  # 当前状态（着装、情绪等）
    relationships: dict[str, str] = field(default_factory=dict)  # {角色名: 关系描述}
    example_dialogues: list[str] = field(default_factory=list)

    def build_system_prompt(self, scene_context: str = "") -> str:
        """构建注入给 LLM 的 system prompt"""
        mem_text = "\n".join(f"- {m}" for m in self.memories[-20:]) if self.memories else "（暂无记忆）"
        state_text = "\n".join(f"- {k}: {v}" for k, v in self.state.items()) if self.state else "（无特殊状态）"
        rel_text = "\n".join(f"- {name}: {desc}" for name, desc in self.relationships.items()) if self.relationships else "（无特殊关系）"

        return CHARACTER_SYSTEM.format(
            character_card=self.card,
            memories=mem_text,
            current_state=state_text,
            relationships=rel_text,
        )

    async def respond(self, llm: LLMClient, scene_context: str, dialogue_history: str) -> list[dict]:
        """
        在场景中产出回应（1-3 句话，每句有独立的 emotion）

        Returns:
            [{"text": "...", "emotion": "happy", "emotion_intensity": 5, "outfit": "..."}]
        """
        system = self.build_system_prompt(scene_context)
        user_prompt = f"## 当前场景\n{scene_context}\n\n## 最近的对话\n{dialogue_history}\n\n请以 {self.name} 的身份说话，输出 JSON 数组。只输出JSON。"

        try:
            result = await llm.chat_json(
                system=system,
                user=user_prompt,
                temperature=0.8,
                max_tokens=512,  # JSON 数组格式有开销，不能卡太紧
            )
            # result 可能是 list 或 dict
            if isinstance(result, dict):
                items = [result]
            elif isinstance(result, list):
                items = result
            else:
                items = [{"text": str(result)}]

            lines = []
            for item in items[:3]:  # 最多 3 句
                text = str(item.get("text", "")).strip().replace("\n", " ")
                if len(text) > 50:
                    for sep in ["。", "！", "？"]:
                        idx = text.find(sep, 10)
                        if idx > 0 and idx < 50:
                            text = text[:idx + 1]
                            break
                    if len(text) > 50:
                        text = text[:50]
                if text and len(text) >= 2:
                    lines.append({
                        "text": text,
                        "emotion": item.get("emotion", "neutral"),
                        "emotion_intensity": min(10, max(1, int(item.get("emotion_intensity", 5)))),
                        "outfit": item.get("outfit", "default"),
                    })
            return lines if lines else [{"text": "……", "emotion": "neutral", "emotion_intensity": 5, "outfit": "default"}]

        except Exception:
            # fallback
            response = await llm.chat(system=system, user=user_prompt, temperature=0.8, max_tokens=128)
            import re
            text = re.sub(r'\*\*.*?\*\*', '', response.strip())
            text = text.replace("\n", " ").strip()
            for sep in ["。", "！", "？"]:
                idx = text.find(sep)
                if 3 < idx < 50:
                    text = text[:idx + 1]
                    break
            if len(text) > 50:
                text = text[:50]
            return [{"text": text or "……", "emotion": "neutral", "emotion_intensity": 5, "outfit": "default"}]

    def add_memory(self, event: str) -> None:
        """添加记忆"""
        self.memories.append(event)
