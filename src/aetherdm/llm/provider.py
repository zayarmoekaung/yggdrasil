"""LLM provider — uses OpenAI-compatible API for Qwen (cloud) and KoboldCPP (local)."""

from typing import Any, Literal

from openai import OpenAI

from aetherdm.config import settings


class LLMProvider:
    """Unified LLM interface via the OpenAI SDK.

    Supports two modes:
    - "qwen": Uses Dashscope or a custom base URL with a Qwen model
    - "kobold": Uses a local KoboldCPP OpenAI-compatible endpoint
    """

    def __init__(self, mode: Literal["qwen", "kobold"] | None = None):
        self.mode = mode or settings.llm_mode
        self._client = self._build_client()

    def _build_client(self) -> OpenAI:
        """Build an OpenAI client configured for the selected provider."""
        if self.mode == "qwen":
            return OpenAI(
                api_key=settings.qwen_api_key or "dummy",
                base_url=settings.qwen_base_url or None,
                # No timeout — LLM calls can take 30-60s for complex prompts
            )
        elif self.mode == "kobold":
            return OpenAI(
                api_key="koboldcpp",
                base_url=settings.kobold_base_url,
            )
        else:
            raise ValueError(f"Unknown LLM mode: {self.mode}")

    @property
    def model(self) -> str:
        if self.mode == "qwen":
            return settings.qwen_model
        return settings.kobold_model

    def _build_params(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            params["response_format"] = response_format
        params.update(kwargs)
        return params

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a chat completion request and return the assistant's reply."""
        import asyncio

        params = self._build_params(messages, temperature, max_tokens, response_format, **kwargs)
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: self._client.chat.completions.create(**params)
        )
        return response.choices[0].message.content or ""

    def chat_sync(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Synchronous chat completion."""
        params = self._build_params(messages, temperature, max_tokens, response_format, **kwargs)
        response = self._client.chat.completions.create(**params)
        return response.choices[0].message.content or ""
