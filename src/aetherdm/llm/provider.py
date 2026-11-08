"""LLM provider — LiteLLM wrapper supporting Qwen (cloud) and KoboldCPP (local)."""

from typing import Any, Literal

import litellm

from aetherdm.config import settings


class LLMProvider:
    """Unified LLM interface via LiteLLM.

    Supports two modes:
    - "qwen": Uses Dashscope or OpenRouter with a Qwen model
    - "kobold": Uses a local KoboldCPP OpenAI-compatible endpoint
    """

    def __init__(self, mode: Literal["qwen", "kobold"] | None = None):
        self.mode = mode or settings.llm_mode
        self._configure_provider()

    def _configure_provider(self) -> None:
        """Set API keys and base URLs based on the configured mode."""
        if self.mode == "qwen":
            if settings.qwen_api_key:
                litellm.api_key = settings.qwen_api_key
            # Dashscope uses the dashscope model prefix; OpenRouter uses openrouter/
            if settings.qwen_base_url:
                litellm.api_base = settings.qwen_base_url
            self.model = settings.qwen_model
        elif self.mode == "kobold":
            litellm.api_base = settings.kobold_base_url
            self.model = settings.kobold_model
            # KoboldCPP doesn't require an API key, but set a placeholder if needed
            if not litellm.api_key:
                litellm.api_key = "koboldcpp"
        else:
            raise ValueError(f"Unknown LLM mode: {self.mode}")

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a chat completion request and return the assistant's reply."""
        litellm_params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            litellm_params["response_format"] = response_format
        litellm_params.update(kwargs)

        response = await litellm.acompletion(**litellm_params)
        return response.choices[0].message.content or ""

    def chat_sync(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Synchronous version of chat()."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.chat(messages, temperature, max_tokens, response_format, **kwargs)
            )
        # Already in an event loop — use run_until_complete won't work;
        # fall back to synchronous litellm.completion directly
        litellm_params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            litellm_params["response_format"] = response_format
        litellm_params.update(kwargs)
        response = litellm.completion(**litellm_params)
        return response.choices[0].message.content or ""
