"""
集中配置 — 所有可配置项从 .env 读取，默认值在这里定义
"""
import os

# LLM
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1234")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "600"))

# 解析
CHUNK_MAX_CHARS = int(os.environ.get("CHUNK_MAX_CHARS", "3000"))
CHUNK_OVERLAP_CHARS = int(os.environ.get("CHUNK_OVERLAP_CHARS", "200"))

# 生图
ANYGEN_API_KEY = os.environ.get("ANYGEN_API_KEY", "")
IMAGE_MAX_CONCURRENT = int(os.environ.get("IMAGE_MAX_CONCURRENT", "8"))

# TTS
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "")  # edge_tts / openai / volcano / cosyvoice / 空=自动
TTS_MAX_CONCURRENT = int(os.environ.get("TTS_MAX_CONCURRENT", "4"))
TTS_ENABLED = os.environ.get("TTS_ENABLED", "false").lower() in ("true", "1", "yes")
