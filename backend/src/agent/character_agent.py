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
    from ..orchestrator.schemas import CHARACTER_RESPOND_SCHEMA
except ImportError:
    from config.llm_client import LLMClient
    from orchestrator.schemas import CHARACTER_RESPOND_SCHEMA

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

## 输出格式（严格 JSON）
输出 JSON 对象，包含 lines 数组。人说话是一句一句的，每句话可以有不同表情。

```json
{{"lines": [
  {{"text": "说起来你知道吗？", "emotion": "happy", "emotion_intensity": 5, "outfit": "dark_robe"}},
  {{"text": "*沉思片刻* 那个地方好像不太对劲。", "emotion": "worried", "emotion_intensity": 4, "outfit": "dark_robe"}}
]}}
```

严格规则：
- lines 数组 1-3 句话，每句不超过 30 字
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
                max_tokens=512,
                schema=CHARACTER_RESPOND_SCHEMA,
            )
            # schema 模式输出 {"lines": [...]}, fallback 兼容裸数组和单 dict
            if isinstance(result, dict) and "lines" in result:
                items = result["lines"]
            elif isinstance(result, dict):
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

    async def compress_memories(self, llm: LLMClient, threshold: int = 20, keep_recent: int = 10) -> None:
        """压缩旧记忆——超过阈值时将旧的压缩为摘要

        保留最近 keep_recent 条原始记忆，把更早的压缩成 1 条摘要。
        """
        if len(self.memories) <= threshold:
            return

        old_memories = self.memories[:-keep_recent]
        recent_memories = self.memories[-keep_recent:]

        try:
            summary = await llm.chat(
                system=f"你是 {self.name} 的记忆管理者。请将以下记忆压缩为一段简短的摘要（3-5句），保留最重要的事件和情感变化。",
                user="\n".join(f"- {m}" for m in old_memories),
                temperature=0.3,
                max_tokens=256,
            )
            self.memories = [f"[记忆摘要] {summary.strip()}"] + recent_memories
            logger.info(f"记忆压缩: {self.name} ({len(old_memories)} 条 → 1 条摘要 + {len(recent_memories)} 条近期)")
        except Exception as e:
            logger.warning(f"记忆压缩失败 [{self.name}]: {e}")
