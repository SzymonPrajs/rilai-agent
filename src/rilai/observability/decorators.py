"""Tracing decorators for agent and model calls.

These decorators automatically log calls to the unified store.
"""

import functools
import time
from typing import Any, Callable, TypeVar

from .store import get_store

F = TypeVar("F", bound=Callable[..., Any])


def trace_agent(func: F) -> F:
    """Decorator to trace agent assess() calls.

    Automatically logs agent output, timing, and salience to the store.
    Expects the decorated function to return an AgentAssessment.

    Usage:
        class MyAgent:
            @trace_agent
            async def assess(self, event, context):
                ...
    """

    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        start_time = time.time()

        try:
            result = await func(self, *args, **kwargs)

            processing_time_ms = int((time.time() - start_time) * 1000)

            # Log to store
            store = get_store()
            store.log_agent_call(
                agent_id=getattr(self, "agent_id", "unknown"),
                output=result.output if hasattr(result, "output") else str(result),
                thinking=result.trace.thinking if hasattr(result, "trace") and result.trace else None,
                urgency=result.salience.urgency if hasattr(result, "salience") and result.salience else 0,
                confidence=result.salience.confidence if hasattr(result, "salience") and result.salience else 0,
                processing_time_ms=processing_time_ms,
            )

            return result

        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)

            # Log error
            store = get_store()
            store.log_agent_call(
                agent_id=getattr(self, "agent_id", "unknown"),
                output=f"Error: {e}",
                urgency=0,
                confidence=0,
                processing_time_ms=processing_time_ms,
            )
            raise

    return wrapper  # type: ignore


def trace_model(func: F) -> F:
    """Decorator to trace model API calls.

    Automatically logs model calls, responses, and timing to the store.
    Expects the decorated function to take messages and model as parameters.

    Usage:
        @trace_model
        async def complete(messages, model, ...):
            ...
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()

        # Extract model and messages from args/kwargs
        messages = kwargs.get("messages", args[0] if args else [])
        model = kwargs.get("model", args[1] if len(args) > 1 else "unknown")

        try:
            result = await func(*args, **kwargs)

            latency_ms = int((time.time() - start_time) * 1000)

            # Log to store
            store = get_store()
            store.log_model_call(
                model=model,
                messages=[{"role": m.role, "content": m.content[:500]} for m in messages] if hasattr(messages[0], "role") else messages,
                response=result.content[:1000] if hasattr(result, "content") else str(result)[:1000],
                latency_ms=latency_ms,
                prompt_tokens=result.usage.prompt_tokens if hasattr(result, "usage") and result.usage else 0,
                completion_tokens=result.usage.completion_tokens if hasattr(result, "usage") and result.usage else 0,
                reasoning_tokens=result.usage.reasoning_tokens if hasattr(result, "usage") and result.usage and hasattr(result.usage, "reasoning_tokens") else None,
            )

            return result

        except Exception:
            latency_ms = int((time.time() - start_time) * 1000)

            # Log error (minimal info)
            store = get_store()
            store.log_model_call(
                model=model,
                messages=[],
                response="Error",
                latency_ms=latency_ms,
            )
            raise

    return wrapper  # type: ignore


def trace_council(func: F) -> F:
    """Decorator to trace council deliberation calls.

    Automatically logs council decisions to the store.

    Usage:
        @trace_council
        async def deliberate(self, ...):
            ...
    """

    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        start_time = time.time()

        try:
            result = await func(self, *args, **kwargs)

            processing_time_ms = int((time.time() - start_time) * 1000)

            # Log to store
            store = get_store()

            # Handle both CouncilResponse and CouncilDecision
            if hasattr(result, "synthesis"):
                # CouncilResponse
                synthesis = result.synthesis
                store.log_council_call(
                    speak=synthesis.speak,
                    urgency=synthesis.urgency,
                    speech_act=synthesis.speech_act.to_dict() if synthesis.speech_act else None,
                    final_message=synthesis.message,
                    thinking=synthesis.thinking,
                    processing_time_ms=processing_time_ms,
                )
            elif hasattr(result, "speak"):
                # CouncilDecision directly
                store.log_council_call(
                    speak=result.speak,
                    urgency=result.urgency,
                    speech_act=result.speech_act.to_dict() if result.speech_act else None,
                    final_message=result.message,
                    thinking=result.thinking if hasattr(result, "thinking") else None,
                    processing_time_ms=processing_time_ms,
                )

            return result

        except Exception:
            raise

    return wrapper  # type: ignore


class TracingContext:
    """Context manager for tracing a complete processing turn.

    Usage:
        with TracingContext(store, "Hello world") as ctx:
            # Process message
            ...
            ctx.set_result(council_speak=True, urgency="medium")
    """

    def __init__(self, store, user_input: str):
        self.store = store
        self.user_input = user_input
        self._turn_context = None
        self._council_speak = False
        self._council_urgency = None
        self._response = None

    def __enter__(self):
        self._turn_context = self.store.start_turn(self.user_input)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.store.end_turn(
            council_speak=self._council_speak,
            council_urgency=self._council_urgency,
            response=self._response,
        )
        return False

    def set_result(
        self,
        council_speak: bool,
        council_urgency: str | None = None,
        response: str | None = None,
    ) -> None:
        """Set the turn result."""
        self._council_speak = council_speak
        self._council_urgency = council_urgency
        self._response = response

    @property
    def turn_id(self) -> int | None:
        """Get current turn ID."""
        return self._turn_context.turn_id if self._turn_context else None
