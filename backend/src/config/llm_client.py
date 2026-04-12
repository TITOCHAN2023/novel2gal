"""
LLM Client — 支持 OpenAI 兼容 API（本地模型/LM Studio/vLLM/Ollama 等）

用法：
  client = LLMClient(base_url=os.environ["LLM_BASE_URL"])
  response = await client.chat("你好", system="你是一个助手")
"""
from __future__ import annotations

import json
import re
import httpx
from dataclasses import dataclass, field


@dataclass
class LLMClient:
    """OpenAI 兼容 API 客户端"""
    base_url: str = "http://localhost:1234"
    model: str = ""  # 留空则自动用服务器上第一个模型
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 600.0

    _http: httpx.AsyncClient = field(init=False, repr=False)
    _model_resolved: str = field(init=False, default="")

    def __post_init__(self):
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            trust_env=False,  # 忽略系统代理，直连本地模型服务
        )

    async def _resolve_model(self) -> str:
        """如果未指定 model，自动获取服务器上的第一个模型"""
        if self._model_resolved:
            return self._model_resolved
        if self.model:
            self._model_resolved = self.model
            return self.model

        resp = await self._http.get("/v1/models")
        resp.raise_for_status()
        models = resp.json().get("data", [])
        if not models:
            raise RuntimeError("LLM 服务器上没有可用模型")
        self._model_resolved = models[0]["id"]
        return self._model_resolved

    async def chat(
        self,
        user: str,
        system: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        retries: int = 3,
        response_format: dict | None = None,
    ) -> str:
        """发送 chat completion 请求（带重试）"""
        model = await self._resolve_model()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "reasoning_effort": "none",
        }
        if response_format:
            payload["response_format"] = response_format

        import asyncio, logging
        logger = logging.getLogger("llm_client")

        for attempt in range(retries):
            try:
                resp = await self._http.post("/v1/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                if attempt < retries - 1:
                    wait = (attempt + 1) * 5
                    logger.warning(f"LLM 调用失败 (尝试 {attempt+1}/{retries}): {e}，{wait}秒后重试")
                    await asyncio.sleep(wait)
                else:
                    raise

    async def chat_json(
        self,
        user: str,
        system: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        schema: dict | None = None,
    ) -> dict:
        """发送请求并解析 JSON 输出。优先用 structured output，fallback 到容错提取。"""
        # 构建 response_format
        response_format: dict | None = None
        if schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.get("name", "output"),
                    "strict": True,
                    "schema": schema.get("schema", schema),
                },
            }
        else:
            # 没有 schema 也要求 json_object 模式
            response_format = {"type": "json_object"}

        raw = await self.chat(
            user, system, temperature, max_tokens,
            response_format=response_format,
        )
        # structured output 模式下输出应该直接是合法 JSON，但仍做容错
        return extract_json(raw)

    async def close(self):
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


def extract_json(text: str) -> dict:
    """从 LLM 输出中健壮地提取 JSON（多种策略）"""
    # 策略1：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略2：提取 ```json ... ``` 代码块（宽松匹配）
    match = re.search(r'```(?:json)?\s*\n?(.*?)(?:\n\s*```|$)', text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 策略3：修复截断的 JSON（模型输出 ... 或被截断）
    # 去掉 ... 并尝试补全括号
    cleaned = re.sub(r',?\s*\.\.\..*', '', text, flags=re.DOTALL)
    # 补全未闭合的括号
    open_braces = cleaned.count('{') - cleaned.count('}')
    open_brackets = cleaned.count('[') - cleaned.count(']')
    cleaned = cleaned.rstrip().rstrip(',')
    cleaned += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 策略4：找第一个 { 到最后一个 }
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    # 策略4：找 [ 到 ]（数组）
    start = text.find('[')
    end = text.rfind(']')
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 输出中提取 JSON:\n{text[:500]}...")
