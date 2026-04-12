"""
BGM 情绪标签系统 — 根据场景氛围自动选择背景音乐

情绪标签 → 音乐映射：
  - tense: 紧张/战斗
  - calm: 平静/日常
  - happy: 欢快/温馨
  - sad: 悲伤/离别
  - romantic: 浪漫/甜蜜
  - mystery: 神秘/悬疑
  - epic: 史诗/壮阔
  - peaceful: 宁静/自然

当前：使用预定义的无版权音乐 URL（来自 freepd.com / incompetech / pixabay 等）
后续：可接入 AI 音乐生成 API 替换
"""
from __future__ import annotations

import logging
import os
import random
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================
# 情绪 → BGM 映射
# ============================================================

# 无版权音乐资源（来自公共领域或 CC0 授权）
# 这些是 URL 占位符，实际部署时替换为本地文件或可靠 CDN
# 结构：每个情绪对应多首可选曲目，随机选择避免重复
BGM_LIBRARY: dict[str, list[dict]] = {
    "tense": [
        {"name": "Tension Rising", "file": "tense_01.mp3"},
        {"name": "Dark Pursuit", "file": "tense_02.mp3"},
    ],
    "calm": [
        {"name": "Peaceful Morning", "file": "calm_01.mp3"},
        {"name": "Gentle Breeze", "file": "calm_02.mp3"},
    ],
    "happy": [
        {"name": "Sunny Day", "file": "happy_01.mp3"},
        {"name": "Cheerful Walk", "file": "happy_02.mp3"},
    ],
    "sad": [
        {"name": "Farewell", "file": "sad_01.mp3"},
        {"name": "Rainy Window", "file": "sad_02.mp3"},
    ],
    "romantic": [
        {"name": "Starlight Dance", "file": "romantic_01.mp3"},
    ],
    "mystery": [
        {"name": "Whispers", "file": "mystery_01.mp3"},
        {"name": "Shadows", "file": "mystery_02.mp3"},
    ],
    "epic": [
        {"name": "Rise of Heroes", "file": "epic_01.mp3"},
    ],
    "peaceful": [
        {"name": "Forest Stream", "file": "peaceful_01.mp3"},
        {"name": "Night Sky", "file": "peaceful_02.mp3"},
    ],
}

# 情绪关键词映射（从场景描述/张力推断情绪）
MOOD_KEYWORDS: dict[str, list[str]] = {
    "tense": ["战斗", "追逐", "紧张", "危险", "conflict", "battle", "fight", "danger", "threat"],
    "calm": ["日常", "平静", "休息", "聊天", "daily", "calm", "rest", "chat", "normal"],
    "happy": ["欢乐", "庆祝", "开心", "笑", "happy", "celebrate", "joy", "fun"],
    "sad": ["悲伤", "离别", "失去", "哭", "sad", "farewell", "loss", "cry", "death"],
    "romantic": ["浪漫", "约会", "心动", "告白", "romance", "love", "date", "confession"],
    "mystery": ["神秘", "调查", "秘密", "谜", "mystery", "investigate", "secret", "puzzle"],
    "epic": ["决战", "觉醒", "命运", "史诗", "epic", "destiny", "awaken", "final"],
    "peaceful": ["自然", "花园", "夜晚", "星空", "nature", "garden", "night", "stars"],
}

# 张力 → 情绪的默认映射
TENSION_MOOD: dict[str, str] = {
    "high": "tense",
    "medium": "calm",
    "low": "peaceful",
}


def infer_bgm_mood(scene_plan: dict) -> str:
    """从场景规划推断 BGM 情绪

    Args:
        scene_plan: SuperAgent 的场景规划结果（含 scene_goal, tension, opening_narration 等）

    Returns:
        情绪标签字符串
    """
    # 1. 如果 scene_plan 直接指定了 bgm_mood
    if scene_plan.get("bgm_mood"):
        mood = scene_plan["bgm_mood"]
        if mood in BGM_LIBRARY:
            return mood

    # 2. 从文本推断
    text = " ".join([
        str(scene_plan.get("scene_goal", "")),
        str(scene_plan.get("opening_narration", "")),
    ]).lower()

    scores: dict[str, int] = {}
    for mood, keywords in MOOD_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[mood] = score

    if scores:
        return max(scores, key=scores.get)  # type: ignore

    # 3. 根据张力 fallback
    tension = str(scene_plan.get("tension", "medium")).lower()
    return TENSION_MOOD.get(tension, "calm")


def get_bgm_url(mood: str, story_id: str = "") -> str:
    """获取指定情绪的 BGM URL

    优先使用故事目录下的自定义 BGM，fallback 到全局默认
    """
    tracks = BGM_LIBRARY.get(mood, BGM_LIBRARY.get("calm", []))
    if not tracks:
        return ""

    track = random.choice(tracks)
    # 返回相对路径（前端通过 Vite proxy 或同源访问）
    return f"/assets/bgm/{track['file']}"


def get_bgm_for_scene(scene_plan: dict, story_id: str = "") -> str:
    """一站式：从场景规划获取 BGM URL"""
    mood = infer_bgm_mood(scene_plan)
    url = get_bgm_url(mood, story_id)
    logger.debug(f"BGM: mood={mood}, url={url}")
    return url
