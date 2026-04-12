"""
TTS 语音生成模块 — 为场景对话生成语音文件

按资产统一模式：
  - 初始化生成：流水线 Phase 4 后自动触发
  - 中断恢复：已有语音跳过
  - 增量生成：新场景生成时自动生成语音
  - 速率控制：并发可配

存储路径：
  assets/character_{id}/voice/{scene_id}_{line_index}.mp3
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .tts_provider import TTSProvider, create_tts_provider, DEFAULT_VOICE_MAP

logger = logging.getLogger(__name__)


def get_voice_for_character(char_config: dict, provider: TTSProvider) -> str:
    """根据角色配置选择语音

    优先级: char_config.voice_id > 按性别匹配 > 默认
    """
    # 角色卡里手动配的 voice_id
    voice_id = char_config.get("voice_id", "")
    if voice_id:
        return voice_id

    # 按性别匹配
    # 从 appearance_summary 或 traits 推测性别
    appearance = str(char_config.get("appearance_summary", "")).lower()
    traits = [str(t).lower() for t in char_config.get("traits", [])]
    name = str(char_config.get("name", ""))

    # 简单启发式
    female_hints = ["female", "woman", "girl", "她", "女", "姐", "娘", "妹", "夫人", "小姐"]
    male_hints = ["male", "man", "boy", "他", "男", "兄", "哥", "叔", "先生"]

    text = appearance + " " + " ".join(traits) + " " + name
    if any(h in text for h in female_hints):
        return DEFAULT_VOICE_MAP.get("female", DEFAULT_VOICE_MAP["default"])
    elif any(h in text for h in male_hints):
        return DEFAULT_VOICE_MAP.get("male", DEFAULT_VOICE_MAP["default"])

    return DEFAULT_VOICE_MAP["default"]


async def generate_scene_voice(
    provider: TTSProvider,
    scene_id: str,
    lines: list[dict],
    characters: list[dict],
    asset_root: Path,
    max_concurrent: int = 4,
) -> dict[str, str]:
    """为一个场景的所有对话行生成语音

    Args:
        provider: TTS Provider
        scene_id: 场景 ID
        lines: 场景对话行列表 [{type, character, text, ...}]
        characters: 角色列表（含 config）
        asset_root: 资产根目录
        max_concurrent: 最大并发数

    Returns:
        {"{scene_id}_{line_index}": "/assets/.../voice/xxx.mp3"} 生成的语音文件路径
    """
    # 构建角色名 → voice 映射
    char_voice: dict[str, str] = {}
    char_id_map: dict[str, str] = {}  # name → id
    for char in characters:
        cfg = char.get("config", {})
        cid = cfg.get("id", "")
        name = char.get("name", "")
        if cid and name:
            char_voice[name] = get_voice_for_character(cfg, provider)
            char_id_map[name] = cid

    results: dict[str, str] = {}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def gen_one(index: int, line: dict):
        async with semaphore:
            # 只为对话行生成语音（旁白可选）
            line_type = line.get("type", "")
            text = line.get("text", "").strip()
            character = line.get("character", "")

            if not text or len(text) < 2:
                return

            # 清理动作描写 *xxx*
            import re
            clean_text = re.sub(r'\*[^*]+\*', '', text).strip()
            if not clean_text:
                return

            # 确定语音和输出路径
            if character and character in char_voice:
                voice = char_voice[character]
                cid = char_id_map.get(character, "narrator")
            else:
                voice = DEFAULT_VOICE_MAP["default"]
                cid = "narrator"

            voice_dir = asset_root / f"character_{cid}" / "voice"
            output_path = voice_dir / f"{scene_id}_{index}.mp3"

            # 已有跳过
            if output_path.exists() and output_path.stat().st_size > 100:
                key = f"{scene_id}_{index}"
                story_id = asset_root.parent.name
                results[key] = f"/assets/{story_id}/character_{cid}/voice/{scene_id}_{index}.mp3"
                return

            result = await provider.synthesize(clean_text, voice, output_path)
            if result:
                key = f"{scene_id}_{index}"
                story_id = asset_root.parent.name
                results[key] = f"/assets/{story_id}/character_{cid}/voice/{scene_id}_{index}.mp3"

    # 并发生成
    tasks = [gen_one(i, line) for i, line in enumerate(lines)]
    await asyncio.gather(*tasks, return_exceptions=True)

    if results:
        logger.info(f"TTS 生成完成: {scene_id} ({len(results)}/{len(lines)} 行)")
    return results


async def generate_all_scene_voices(
    scenes: dict[str, dict],
    characters: list[dict],
    asset_root: Path,
    max_concurrent: int = 4,
) -> dict[str, dict[str, str]]:
    """为所有场景生成语音

    Returns:
        {scene_id: {"{scene_id}_{line_index}": "url"}}
    """
    provider = create_tts_provider()
    if not provider:
        logger.info("TTS 未配置，跳过语音生成")
        return {}

    logger.info(f"=== TTS 语音生成 ({provider.name}, {len(scenes)} 场景, 并发={max_concurrent}) ===")

    all_results: dict[str, dict[str, str]] = {}
    for scene_id, scene in scenes.items():
        lines = scene.get("lines", [])
        if not lines:
            continue
        result = await generate_scene_voice(
            provider, scene_id, lines, characters, asset_root, max_concurrent,
        )
        if result:
            all_results[scene_id] = result

    total = sum(len(v) for v in all_results.values())
    logger.info(f"TTS 全部完成: {total} 个语音文件")
    return all_results


def inject_voice_urls(scenes: dict[str, dict], voice_results: dict[str, dict[str, str]]) -> int:
    """将 TTS 语音 URL 注入到场景 JSON 的 lines[].voice 字段

    Args:
        scenes: engine_scenes 字典
        voice_results: generate_all_scene_voices 的返回值

    Returns:
        注入的语音数量
    """
    count = 0
    for scene_id, voice_map in voice_results.items():
        scene = scenes.get(scene_id)
        if not scene:
            continue
        lines = scene.get("lines", [])
        for i, line in enumerate(lines):
            key = f"{scene_id}_{i}"
            if key in voice_map:
                line["voice"] = voice_map[key]
                count += 1
    logger.info(f"语音 URL 注入: {count} 行")
    return count
