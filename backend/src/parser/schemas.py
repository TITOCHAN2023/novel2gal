"""
小说解析 JSON Schema 定义

用于 LLM structured output，保证输出格式正确。
每个 schema 对应一个 micro-pass。
"""

EXTRACT_CHARACTERS_SCHEMA = {
    "name": "extract_characters",
    "schema": {
        "type": "object",
        "properties": {
            "characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "小写英文+下划线，同一角色保持同一id"},
                        "name": {"type": "string", "description": "角色名"},
                        "aliases": {"type": "array", "items": {"type": "string"}, "description": "别名列表"},
                        "description": {"type": "string", "description": "本段中对该角色的描写"},
                    },
                    "required": ["id", "name", "aliases", "description"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["characters"],
        "additionalProperties": False,
    },
}

EXTRACT_LOCATIONS_SCHEMA = {
    "name": "extract_locations",
    "schema": {
        "type": "object",
        "properties": {
            "locations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "小写英文+下划线"},
                        "name": {"type": "string", "description": "地点名"},
                        "description": {"type": "string", "description": "环境描写"},
                    },
                    "required": ["id", "name", "description"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["locations"],
        "additionalProperties": False,
    },
}

EXTRACT_EVENTS_SCHEMA = {
    "name": "extract_events",
    "schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "participants": {"type": "array", "items": {"type": "string"}},
                        "location": {"type": "string"},
                        "significance": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                    "required": ["summary", "participants", "location", "significance"],
                    "additionalProperties": False,
                },
            },
            "chapter_summary": {"type": "string", "description": "3-5句概括本段主要发展"},
        },
        "required": ["events", "chapter_summary"],
        "additionalProperties": False,
    },
}

EXTRACT_DIALOGUES_SCHEMA = {
    "name": "extract_dialogues",
    "schema": {
        "type": "object",
        "properties": {
            "dialogues": {
                "type": "object",
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "description": "key=角色英文id, value=对话列表",
            },
        },
        "required": ["dialogues"],
        "additionalProperties": False,
    },
}

UPDATE_CHARACTER_CARD_SCHEMA = {
    "name": "update_character_card",
    "schema": {
        "type": "object",
        "properties": {
            "natural_language": {"type": "string", "description": "完整自然语言角色卡（markdown格式）"},
            "config": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "age": {"type": "string"},
                    "identity": {"type": "string"},
                    "traits": {"type": "array", "items": {"type": "string"}},
                    "speech_style": {"type": "string"},
                    "abilities": {"type": "array", "items": {"type": "string"}},
                    "appearance_summary": {"type": "string"},
                    "voice_id": {"type": "string", "description": "TTS 语音 ID（可选，留空自动分配）"},
                },
                "required": ["id", "name", "aliases", "age", "identity", "traits", "speech_style", "abilities", "appearance_summary"],
                "additionalProperties": False,
            },
            "example_dialogues": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["natural_language", "config", "example_dialogues"],
        "additionalProperties": False,
    },
}

SYNTHESIZE_SCHEMA = {
    "name": "synthesize_relationships",
    "schema": {
        "type": "object",
        "properties": {
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "type": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["from", "to", "type", "description"],
                    "additionalProperties": False,
                },
            },
            "world_rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "category": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["id", "category", "description"],
                    "additionalProperties": False,
                },
            },
            "turning_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "chunk_index": {"type": "integer"},
                        "summary": {"type": "string"},
                        "impact": {"type": "string"},
                    },
                    "required": ["chunk_index", "summary", "impact"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["relationships", "world_rules", "turning_points"],
        "additionalProperties": False,
    },
}
