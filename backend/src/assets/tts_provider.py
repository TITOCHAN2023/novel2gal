"""
TTS 统一接口 — 多平台语音合成

支持的 Provider:
  - edge_tts: 微软 Edge TTS（免费，无需 API key）
  - openai: OpenAI TTS API (tts-1 / tts-1-hd)
  - volcano: 火山引擎/豆包 TTS
  - cosyvoice: 阿里 CosyVoice

用法:
    provider = create_tts_provider()  # 从 .env 自动选择
    await provider.synthesize("你好世界", voice="zh-CN-XiaoxiaoNeural", output_path=Path("out.mp3"))
"""
from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    """TTS 合成结果"""
    path: Path
    duration_ms: int = 0  # 音频时长（毫秒），0=未知


class TTSProvider(ABC):
    """TTS 提供者抽象接口"""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
        speed: float = 1.0,
    ) -> TTSResult | None:
        """合成语音

        Args:
            text: 要合成的文本
            voice: 语音 ID（各平台格式不同）
            output_path: 输出音频文件路径
            speed: 语速倍率（1.0=正常）

        Returns:
            TTSResult 或 None（失败时）
        """
        ...

    @abstractmethod
    def list_voices(self) -> list[dict]:
        """列出可用语音

        Returns:
            [{"id": "...", "name": "...", "language": "...", "gender": "..."}]
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名称"""
        ...


# ============================================================
# Edge TTS（免费，无需 API key）
# ============================================================

class EdgeTTSProvider(TTSProvider):
    """微软 Edge TTS — 免费，语音质量好，适合开发测试"""

    @property
    def name(self) -> str:
        return "edge_tts"

    async def synthesize(self, text: str, voice: str, output_path: Path, speed: float = 1.0) -> TTSResult | None:
        try:
            import edge_tts
        except ImportError:
            logger.error("edge-tts 未安装，请运行: pip install edge-tts")
            return None

        try:
            rate = f"{int((speed - 1) * 100):+d}%"
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            await communicate.save(str(output_path))
            logger.debug(f"Edge TTS: {output_path.name} ({len(text)} 字)")
            return TTSResult(path=output_path)
        except Exception as e:
            logger.warning(f"Edge TTS 失败: {e}")
            return None

    def list_voices(self) -> list[dict]:
        # Edge TTS 的常用中文语音
        return [
            {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "language": "zh-CN", "gender": "female"},
            {"id": "zh-CN-YunxiNeural", "name": "云希", "language": "zh-CN", "gender": "male"},
            {"id": "zh-CN-YunjianNeural", "name": "云健", "language": "zh-CN", "gender": "male"},
            {"id": "zh-CN-XiaoyiNeural", "name": "晓艺", "language": "zh-CN", "gender": "female"},
            {"id": "zh-CN-YunyangNeural", "name": "云扬", "language": "zh-CN", "gender": "male"},
            {"id": "zh-CN-XiaochenNeural", "name": "晓辰", "language": "zh-CN", "gender": "female"},
            {"id": "zh-CN-XiaohanNeural", "name": "晓涵", "language": "zh-CN", "gender": "female"},
            {"id": "zh-CN-XiaomengNeural", "name": "晓萌", "language": "zh-CN", "gender": "female"},
            {"id": "zh-CN-XiaomoNeural", "name": "晓墨", "language": "zh-CN", "gender": "female"},
            {"id": "zh-CN-XiaoshuangNeural", "name": "晓双", "language": "zh-CN", "gender": "female"},
            {"id": "zh-CN-XiaoxuanNeural", "name": "晓璇", "language": "zh-CN", "gender": "female"},
            {"id": "zh-CN-XiaoyanNeural", "name": "晓颜", "language": "zh-CN", "gender": "female"},
            {"id": "zh-CN-XiaozhenNeural", "name": "晓甄", "language": "zh-CN", "gender": "female"},
            {"id": "zh-CN-YunfengNeural", "name": "云枫", "language": "zh-CN", "gender": "male"},
            {"id": "zh-CN-YunhaoNeural", "name": "云皓", "language": "zh-CN", "gender": "male"},
            {"id": "zh-CN-YunxiaNeural", "name": "云夏", "language": "zh-CN", "gender": "male"},
            {"id": "zh-CN-YunzeNeural", "name": "云泽", "language": "zh-CN", "gender": "male"},
            # 日语
            {"id": "ja-JP-NanamiNeural", "name": "七海", "language": "ja-JP", "gender": "female"},
            {"id": "ja-JP-KeitaNeural", "name": "圭太", "language": "ja-JP", "gender": "male"},
        ]


# ============================================================
# OpenAI TTS
# ============================================================

class OpenAITTSProvider(TTSProvider):
    """OpenAI TTS API — 高质量，需要 API key"""

    def __init__(self, api_key: str = "", base_url: str = ""):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    @property
    def name(self) -> str:
        return "openai"

    async def synthesize(self, text: str, voice: str, output_path: Path, speed: float = 1.0) -> TTSResult | None:
        import httpx
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self.base_url}/audio/speech",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": "tts-1",
                        "input": text,
                        "voice": voice or "alloy",
                        "speed": speed,
                        "response_format": "mp3",
                    },
                )
                resp.raise_for_status()
                output_path.write_bytes(resp.content)
                logger.debug(f"OpenAI TTS: {output_path.name} ({len(text)} 字)")
                return TTSResult(path=output_path)
        except Exception as e:
            logger.warning(f"OpenAI TTS 失败: {e}")
            return None

    def list_voices(self) -> list[dict]:
        return [
            {"id": "alloy", "name": "Alloy", "language": "multi", "gender": "neutral"},
            {"id": "echo", "name": "Echo", "language": "multi", "gender": "male"},
            {"id": "fable", "name": "Fable", "language": "multi", "gender": "neutral"},
            {"id": "onyx", "name": "Onyx", "language": "multi", "gender": "male"},
            {"id": "nova", "name": "Nova", "language": "multi", "gender": "female"},
            {"id": "shimmer", "name": "Shimmer", "language": "multi", "gender": "female"},
        ]


# ============================================================
# 火山引擎 TTS（豆包）
# ============================================================

class VolcanoTTSProvider(TTSProvider):
    """火山引擎 TTS（豆包语音合成）"""

    def __init__(self, app_id: str = "", access_token: str = ""):
        self.app_id = app_id or os.environ.get("VOLCANO_TTS_APP_ID", "")
        self.access_token = access_token or os.environ.get("VOLCANO_TTS_TOKEN", "")

    @property
    def name(self) -> str:
        return "volcano"

    async def synthesize(self, text: str, voice: str, output_path: Path, speed: float = 1.0) -> TTSResult | None:
        import httpx
        import base64
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://openspeech.bytedance.com/api/v1/tts",
                    headers={
                        "Authorization": f"Bearer;{self.access_token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "app": {"appid": self.app_id, "cluster": "volcano_tts"},
                        "user": {"uid": "novel2gal"},
                        "audio": {
                            "voice_type": voice,
                            "encoding": "mp3",
                            "speed_ratio": speed,
                        },
                        "request": {
                            "reqid": f"n2g_{id(text)}",
                            "text": text,
                            "operation": "query",
                        },
                    },
                )
                data = resp.json()
                if data.get("code") == 3000:
                    audio_b64 = data.get("data", "")
                    output_path.write_bytes(base64.b64decode(audio_b64))
                    logger.debug(f"Volcano TTS: {output_path.name} ({len(text)} 字)")
                    return TTSResult(path=output_path)
                else:
                    logger.warning(f"Volcano TTS 错误: {data.get('message', '')}")
                    return None
        except Exception as e:
            logger.warning(f"Volcano TTS 失败: {e}")
            return None

    def list_voices(self) -> list[dict]:
        return [
            {"id": "zh_female_shuangkuaisisi_moon_bigtts", "name": "爽快思思", "language": "zh-CN", "gender": "female"},
            {"id": "zh_male_jingqiangkanye_moon_bigtts", "name": "京腔侃爷", "language": "zh-CN", "gender": "male"},
            {"id": "zh_female_wanwanxiaohe_moon_bigtts", "name": "弯弯小河", "language": "zh-CN", "gender": "female"},
            {"id": "zh_male_chunhou_moon_bigtts", "name": "淳厚", "language": "zh-CN", "gender": "male"},
        ]


# ============================================================
# CosyVoice（阿里）
# ============================================================

class CosyVoiceProvider(TTSProvider):
    """阿里 CosyVoice — 高质量开源 TTS"""

    def __init__(self, base_url: str = ""):
        self.base_url = base_url or os.environ.get("COSYVOICE_BASE_URL", "http://localhost:50000")

    @property
    def name(self) -> str:
        return "cosyvoice"

    async def synthesize(self, text: str, voice: str, output_path: Path, speed: float = 1.0) -> TTSResult | None:
        import httpx
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.base_url}/api/tts",
                    json={
                        "text": text,
                        "speaker": voice or "中文女",
                        "speed": speed,
                    },
                )
                resp.raise_for_status()
                output_path.write_bytes(resp.content)
                logger.debug(f"CosyVoice: {output_path.name} ({len(text)} 字)")
                return TTSResult(path=output_path)
        except Exception as e:
            logger.warning(f"CosyVoice 失败: {e}")
            return None

    def list_voices(self) -> list[dict]:
        return [
            {"id": "中文女", "name": "中文女", "language": "zh-CN", "gender": "female"},
            {"id": "中文男", "name": "中文男", "language": "zh-CN", "gender": "male"},
            {"id": "日语男", "name": "日本語男", "language": "ja-JP", "gender": "male"},
        ]


# ============================================================
# 工厂函数
# ============================================================

# 角色→语音映射的默认配置
DEFAULT_VOICE_MAP = {
    # 按性别分配默认语音（Edge TTS）
    "male": "zh-CN-YunxiNeural",
    "female": "zh-CN-XiaoxiaoNeural",
    "default": "zh-CN-XiaoxiaoNeural",
}


def create_tts_provider(provider_name: str = "") -> TTSProvider | None:
    """根据配置创建 TTS Provider

    优先级: 环境变量 TTS_PROVIDER > 参数 > 自动检测
    """
    name = provider_name or os.environ.get("TTS_PROVIDER", "")

    if name == "openai" or (not name and os.environ.get("OPENAI_API_KEY")):
        return OpenAITTSProvider()
    elif name == "volcano" or (not name and os.environ.get("VOLCANO_TTS_TOKEN")):
        return VolcanoTTSProvider()
    elif name == "cosyvoice" or (not name and os.environ.get("COSYVOICE_BASE_URL")):
        return CosyVoiceProvider()
    elif name == "edge_tts" or not name:
        # Edge TTS 作为默认（免费，无需配置）
        return EdgeTTSProvider()

    logger.warning(f"未知 TTS provider: {name}")
    return None
