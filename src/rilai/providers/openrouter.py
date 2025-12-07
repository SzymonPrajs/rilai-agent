"""OpenRouter API client with native thinking model support.

Supports models with extended reasoning (DeepSeek R1, Claude :thinking, o1/o3).
See: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

import httpx

from rilai.config import get_config


@dataclass
class Message:
    """A chat message."""

    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class TokenUsage:
    """Token usage statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0  # Tokens used for thinking (if applicable)
    total_tokens: int = 0


@dataclass
class ModelResponse:
    """Unified response with reasoning support.

    For thinking models, the reasoning field contains the model's
    step-by-step thinking process.
    """

    content: str
    reasoning: str | None = None  # Thinking steps (if model supports)
    model: str = ""
    finish_reason: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)

    # Tracing fields
    latency_ms: int = 0
    request_messages: list[dict] | None = None
    request_model: str | None = None
    request_temperature: float | None = None
    reasoning_effort: str | None = None


# Known thinking model patterns
THINKING_MODEL_PATTERNS = [
    ":thinking",  # Anthropic claude-*:thinking variants
    "deepseek-r1",  # DeepSeek R1 and distillations
    "o1",  # OpenAI o1
    "o3",  # OpenAI o3
    "gemini-2.5",  # Google Gemini thinking
    "qwq",  # Qwen QwQ
]

# Models that should use Groq as provider (fast inference)
GROQ_PROVIDER_MODELS = [
    "meta-llama/llama-3.1-8b-instruct",
    "meta-llama/llama-3.3-70b-instruct",
    "meta-llama/llama-3.1-70b-instruct",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]


def is_thinking_model(model: str) -> bool:
    """Check if a model supports native reasoning tokens."""
    model_lower = model.lower()
    return any(pattern in model_lower for pattern in THINKING_MODEL_PATTERNS)


def get_preferred_provider(model: str) -> str | None:
    """Get preferred provider for a model, if any."""
    model_lower = model.lower()
    for groq_model in GROQ_PROVIDER_MODELS:
        if groq_model.lower() in model_lower or model_lower in groq_model.lower():
            return "Groq"
    return None


class OpenRouterClient:
    """Client for OpenRouter API with thinking model support."""

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self._api_key = api_key
        self._base_url = base_url or self.BASE_URL
        self._client: httpx.AsyncClient | None = None

    @property
    def api_key(self) -> str:
        """Get API key from config if not set."""
        if self._api_key:
            return self._api_key
        config = get_config()
        return config.OPENROUTER_API_KEY

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/SzymonPrajs/rilai",
                    "X-Title": "Rilai v2",
                },
                timeout=120.0,  # Thinking models can be slow
            )
        return self._client

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None,
        capture_request: bool = False,
    ) -> ModelResponse:
        """Send a completion request with optional reasoning.

        Args:
            messages: List of messages to send
            model: Model to use (defaults to config small model)
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            reasoning_effort: For thinking models, controls depth of reasoning
                - minimal: Quick assessments (~500 tokens)
                - low: Basic reasoning (~2000 tokens)
                - medium: Moderate depth (~5000 tokens)
                - high: Deep analysis (~10000 tokens)
            capture_request: If True, include request details in response for tracing
        """
        start_time = time.time()
        client = await self._get_client()

        config = get_config()
        model = model or config.MODELS["small"]

        message_dicts = [{"role": m.role, "content": m.content} for m in messages]

        payload: dict[str, Any] = {
            "model": model,
            "messages": message_dicts,
            "temperature": temperature,
        }

        # Add provider preference if available (e.g., Groq for llama models)
        preferred_provider = get_preferred_provider(model)
        if preferred_provider:
            payload["provider"] = {"order": [preferred_provider]}

        if max_tokens:
            payload["max_tokens"] = max_tokens

        # Enable reasoning for thinking models
        thinking_model = is_thinking_model(model)
        if thinking_model and reasoning_effort:
            # Map effort to token budget
            effort_tokens = {
                "minimal": 500,
                "low": 2000,
                "medium": 5000,
                "high": 10000,
            }

            payload["include_reasoning"] = True
            payload["reasoning"] = {
                "effort": reasoning_effort,
                "max_tokens": effort_tokens.get(reasoning_effort, 2000),
            }

        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        latency_ms = int((time.time() - start_time) * 1000)

        # Extract response content
        choice = data["choices"][0]
        message_data = choice["message"]
        content = message_data.get("content", "")

        # Extract reasoning (various model formats)
        reasoning = self._extract_reasoning(message_data, model)

        # Parse usage
        usage_data = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            reasoning_tokens=usage_data.get("reasoning_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return ModelResponse(
            content=content,
            reasoning=reasoning,
            model=data.get("model", model),
            finish_reason=choice.get("finish_reason", ""),
            usage=usage,
            latency_ms=latency_ms,
            request_messages=message_dicts if capture_request else None,
            request_model=model if capture_request else None,
            request_temperature=temperature if capture_request else None,
            reasoning_effort=reasoning_effort if capture_request else None,
        )

    def _extract_reasoning(self, message_data: dict, model: str) -> str | None:
        """Extract reasoning from various model response formats.

        Different models expose reasoning differently:
        - OpenRouter standard: message.reasoning field
        - DeepSeek: <think>...</think> tags in content
        - Claude: Separate reasoning field via :thinking variant
        """
        # Check for explicit reasoning field (OpenRouter standard)
        if "reasoning" in message_data:
            return message_data["reasoning"]

        # Check for reasoning_content (alternative format)
        if "reasoning_content" in message_data:
            return message_data["reasoning_content"]

        # DeepSeek R1 uses <think> tags in content
        content = message_data.get("content", "")
        if "deepseek-r1" in model.lower():
            think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
            if think_match:
                return think_match.group(1).strip()

        return None

    async def stream(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream a completion response.

        Note: Streaming does not support reasoning token extraction.
        """
        client = await self._get_client()

        config = get_config()
        model = model or config.MODELS["small"]

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "stream": True,
        }

        # Add provider preference if available (e.g., Groq for llama models)
        preferred_provider = get_preferred_provider(model)
        if preferred_provider:
            payload["provider"] = {"order": [preferred_provider]}

        async with client.stream("POST", "/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    chunk = json.loads(data_str)
                    if content := chunk["choices"][0]["delta"].get("content"):
                        yield content

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Singleton instance
openrouter = OpenRouterClient()
