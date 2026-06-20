"""DeepSeek 大模型客户端。

使用 DeepSeek 的 OpenAI 兼容 `chat/completions` 接口，基于已有依赖 httpx 实现，
不额外引入 SDK。所有异常都会被封装为本模块的类型，便于上层优雅降级。
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger

from config import settings


class LLMConfigError(RuntimeError):
    """缺少必要配置（例如未设置 API Key）。"""


class LLMRequestError(RuntimeError):
    """调用大模型失败（网络、鉴权或返回格式异常）。"""


Message = dict[str, str]


class DeepSeekClient:
    """DeepSeek chat/completions 封装。"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        retry_times: int | None = None,
    ) -> None:
        self.api_key = settings.DEEPSEEK_API_KEY if api_key is None else api_key
        self.base_url = (base_url or settings.DEEPSEEK_BASE_URL).rstrip("/")
        self.model = model or settings.DEEPSEEK_MODEL
        self.timeout = float(timeout or settings.DEEPSEEK_TIMEOUT_SECONDS)
        self.retry_times = settings.DEEPSEEK_RETRY_TIMES if retry_times is None else retry_times

    @property
    def available(self) -> bool:
        """是否具备调用条件（已配置 API Key）。"""
        return bool(self.api_key)

    def chat(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """发起一次对话补全，返回模型文本。"""
        if not self.available:
            raise LLMConfigError("未配置 DEEPSEEK_API_KEY，无法调用大模型")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": settings.DEEPSEEK_TEMPERATURE if temperature is None else temperature,
            "max_tokens": max_tokens or settings.DEEPSEEK_MAX_TOKENS,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        last_error: Exception | None = None
        for attempt in range(1, self.retry_times + 2):
            try:
                response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                return self._extract_content(response.json())
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(f"DeepSeek 调用失败，第 {attempt}/{self.retry_times + 1} 次: {exc}")
                if attempt <= self.retry_times:
                    time.sleep(min(2 ** attempt, 8))
        raise LLMRequestError(f"DeepSeek 多次调用失败: {last_error}")

    def _extract_content(self, data: dict[str, Any]) -> str:
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMRequestError(f"DeepSeek 返回格式异常: {data}") from exc
        if not isinstance(content, str) or not content.strip():
            # 混合推理模型若 max_tokens 不足，推理会吃满预算导致 content 为空。
            if choice.get("finish_reason") == "length" and choice.get("message", {}).get("reasoning_content"):
                raise LLMRequestError("DeepSeek 内容被推理占满，请调大 DEEPSEEK_MAX_TOKENS")
            raise LLMRequestError("DeepSeek 返回空内容")
        return content
