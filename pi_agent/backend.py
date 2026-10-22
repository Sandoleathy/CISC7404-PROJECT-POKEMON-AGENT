"""pi-python-core backend for one battle decision.

Each decision gets a fresh ``pi_python.Agent`` with the current turn's tools.
The agent may call tools for several model turns and then returns the final
assistant text.  The wrapper extracts text, thinking, tool activity and usage,
writes the decision trace, and closes the agent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pi_python import (
    Agent,
    AssistantMessage,
    RunLimits,
    TextContent,
    ThinkingContent,
    ToolCall,
)
from pi_python.providers import DeepSeekProvider

from config import AgentConfig
from trace import TraceLogger


class BackendError(RuntimeError):
    """A model run ended without usable final text."""


@dataclass
class LLMReply:
    text: str
    thinking: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    errors: list[str] = field(default_factory=list)
    tool_calls: int = 0
    latency: float = 0.0


def _text_of(message: AssistantMessage) -> str:
    return "\n".join(
        block.text for block in message.content if isinstance(block, TextContent) and block.text
    ).strip()


def _tool_result_text(message: Any) -> str:
    content = getattr(message, "content", None) or []
    parts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


class PiAgentBackend:
    """Wraps ``pi_python.Agent`` and the DeepSeek provider for battle turns."""

    def __init__(self, config: AgentConfig, trace: TraceLogger) -> None:
        self.config = config
        self.trace = trace
        self._provider = DeepSeekProvider(api_key=config.api_key, base_url=config.base_url)
        self._limits = RunLimits(
            max_model_requests=8,
            max_tool_calls=8,
            run_timeout=240.0,
            cleanup_timeout=5.0,
        )

    async def ask(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[Any],
        *,
        agent_name: str,
        battle: Any = None,
        kind: str = "action",
    ) -> LLMReply:
        call_id = self.trace.next_call()
        started = time.time()
        self.trace.request(
            call_id,
            kind=kind,
            agent=agent_name,
            battle=battle,
            model=self.config.model,
            thinking=self.config.thinking_level,
            max_tokens=self.config.max_tokens,
            prompt_chars=len(system_prompt or "") + len(user_prompt or ""),
            tool_count=len(tools),
        )

        agent = Agent(
            provider=self._provider,
            model=self.config.model,
            system_prompt=system_prompt,
            tools=tools,
            thinking_level=self.config.thinking_level,
            options={
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            },
            limits=self._limits,
        )
        try:
            result = await agent.prompt(user_prompt)
        except Exception as exc:
            self.trace.error(f"{type(exc).__name__}: {exc}")
            raise
        finally:
            try:
                await agent.aclose()
            except Exception as exc:
                self.trace.note(f"agent cleanup failed: {type(exc).__name__}: {exc}")

        latency = time.time() - started
        assistant_messages: list[AssistantMessage] = []
        thinking_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        tool_results: dict[str, str] = {}

        for message in result.messages:
            if isinstance(message, AssistantMessage):
                assistant_messages.append(message)
                thinking_parts.extend(
                    block.thinking
                    for block in message.content
                    if isinstance(block, ThinkingContent) and block.thinking
                )
                tool_calls.extend(
                    block for block in message.content if isinstance(block, ToolCall)
                )
            elif getattr(message, "role", None) == "tool_result":
                call_id_value = getattr(message, "call_id", "")
                tool_results[call_id_value] = _tool_result_text(message)

        for call in tool_calls:
            self.trace.tool(call.name, call.arguments, tool_results.get(call.id, "(no result)"))

        # Only the last assistant message is the answer. Earlier text is usually
        # a tool-call preface and must not be mistaken for the action.
        final_assistant = assistant_messages[-1] if assistant_messages else None
        text = _text_of(final_assistant) if final_assistant is not None else ""
        thinking = "\n\n".join(part.strip() for part in thinking_parts if part and part.strip())
        usage = dict(result.usage or {})
        finish = (
            final_assistant.stop_reason
            if final_assistant is not None
            else (result.stop_reason or result.status)
        )

        self.trace.answer(text)
        self.trace.thinking(thinking)
        self.trace.usage(usage, finish=finish or "unknown", latency=latency)
        for error in result.errors:
            self.trace.error(error)

        if not text:
            detail = "; ".join(result.errors) or f"status={result.status}"
            self.trace.error(f"no final assistant text ({detail})")
            raise BackendError(f"model finished without a final answer ({detail})")

        return LLMReply(
            text=text,
            thinking=thinking,
            usage=usage,
            status=result.status,
            errors=list(result.errors),
            tool_calls=len(tool_calls),
            latency=latency,
        )

    async def aclose(self) -> None:
        try:
            await self._provider.aclose()
        except Exception as exc:
            self.trace.note(f"provider cleanup failed: {type(exc).__name__}: {exc}")
