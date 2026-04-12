"""
编排器 JSON Schema 定义

SuperAgent / CharacterAgent 的 structured output schema。
"""

SCENE_PLAN_SCHEMA = {
    "name": "scene_plan",
    "schema": {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "地点id"},
            "characters_present": {
                "type": "array",
                "items": {"type": "string"},
                "description": "在场角色id列表",
            },
            "scene_goal": {"type": "string", "description": "场景叙事目标"},
            "opening_narration": {"type": "string", "description": "开场旁白（2-3句）"},
            "tension": {"type": "string", "enum": ["low", "medium", "high"]},
            "bgm_mood": {
                "type": "string",
                "enum": ["tense", "calm", "happy", "sad", "romantic", "mystery", "epic", "peaceful"],
                "description": "场景背景音乐情绪",
            },
        },
        "required": ["location", "characters_present", "scene_goal", "opening_narration", "tension", "bgm_mood"],
        "additionalProperties": False,
    },
}

CHOICE_POINT_SCHEMA = {
    "name": "choice_point",
    "schema": {
        "type": "object",
        "properties": {
            "ready": {"type": "boolean"},
            "reason": {"type": "string", "description": "为什么到了/没到选择点"},
            "choices": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "选项显示文本"},
                        "internal_desc": {"type": "string", "description": "这个选择会导向什么方向"},
                    },
                    "required": ["text", "internal_desc"],
                    "additionalProperties": False,
                },
            },
            "closing_narration": {"type": "string", "description": "场景结束旁白"},
        },
        "required": ["ready", "reason"],
        "additionalProperties": False,
    },
}

MEMORY_UPDATE_SCHEMA = {
    "name": "memory_update",
    "schema": {
        "type": "object",
        "properties": {
            "memories": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "key=角色id, value=记忆摘要",
            },
        },
        "required": ["memories"],
        "additionalProperties": False,
    },
}

ART_DIRECTION_SCHEMA = {
    "name": "art_direction",
    "schema": {
        "type": "object",
        "properties": {
            "scene_background": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "negative_prompt": {"type": "string"},
                },
                "required": ["prompt", "negative_prompt"],
                "additionalProperties": False,
            },
            "character_sprites": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "character_id": {"type": "string"},
                        "character_name": {"type": "string"},
                        "prompt": {"type": "string"},
                        "negative_prompt": {"type": "string"},
                    },
                    "required": ["character_id", "character_name", "prompt", "negative_prompt"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["scene_background", "character_sprites"],
        "additionalProperties": False,
    },
}

# CharacterAgent 的发言输出
CHARACTER_RESPOND_SCHEMA = {
    "name": "character_respond",
    "schema": {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "对话文本（≤30字）"},
                        "emotion": {"type": "string", "description": "情绪: happy/sad/angry/surprised/worried/excited/shy/neutral"},
                        "emotion_intensity": {"type": "integer", "description": "情绪强度 1-10"},
                        "outfit": {"type": "string", "description": "当前着装"},
                    },
                    "required": ["text", "emotion", "emotion_intensity", "outfit"],
                    "additionalProperties": False,
                },
                "description": "1-3句对话",
            },
        },
        "required": ["lines"],
        "additionalProperties": False,
    },
}
