"""Append-only decision trace for the pi-agent ladder player.

The format deliberately mirrors ``temp/harness/pokechamp/deepseek_player.py``:
one header per agent run, followed by tool activity, the final answer, the
model's thinking and token usage.  Writing never raises into a battle.
"""

from __future__ import annotations

import datetime
import threading
from pathlib import Path
from typing import Any, Iterable


class TraceLogger:
    def __init__(self, path: Path | None, max_chars: int = 8000) -> None:
        self.path = path
        self.max_chars = max_chars
        self._lock = threading.Lock()
        self.call_count = 0

    @staticmethod
    def _clip(value: Any, limit: int = 8000) -> str:
        text = "" if value is None else str(value)
        if len(text) > limit:
            return f"{text[:limit]}...[truncated, {len(text)} chars total]"
        return text

    def next_call(self) -> int:
        with self._lock:
            self.call_count += 1
            return self.call_count

    def _write(self, lines: Iterable[str]) -> None:
        if self.path is None:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as trace:
                for line in lines:
                    trace.write(str(line) + "\n")
        except OSError as exc:  # a trace must never break a battle
            print(f"could not write pi_agent trace log {self.path}: {exc}")

    def request(
        self,
        call_id: int,
        *,
        kind: str,
        agent: str,
        battle: Any,
        model: str,
        thinking: str,
        max_tokens: int,
        prompt_chars: int,
        tool_count: int,
    ) -> None:
        if battle is not None:
            where = f"battle={getattr(battle, 'battle_tag', '-')} turn={getattr(battle, 'turn', '-')}"
        else:
            where = "battle=-"
        header = (
            f"--- call #{call_id} {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
            f" | {kind} | agent={agent or '-'} | {where}"
            f" | model={model} | json=True | thinking={thinking}"
            f" | max_tokens={max_tokens} | prompt_chars={prompt_chars}"
            f" | tools={tool_count}"
        )
        self._write([header])

    def tool(self, name: str, arguments: Any, result: Any) -> None:
        self._write(
            [
                f"TOOL: {name}({self._clip(arguments, 400)}) -> "
                f"{self._clip(result, 1200)}"
            ]
        )

    def answer(self, text: Any) -> None:
        self._write([f"ANSWER: {self._clip(text)}"])

    def thinking(self, text: Any) -> None:
        if text:
            self._write([f"THINKING: {self._clip(text)}"])

    def usage(self, usage: dict[str, Any], *, finish: str, latency: float) -> None:
        parts = []
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "input",
            "output",
            "reasoning",
            "cache_read",
            "cache_write",
            "input_tokens",
            "output_tokens",
        ):
            if usage.get(key) is not None:
                parts.append(f"{key}={usage[key]}")
        prefix = (" ".join(parts) + " ") if parts else ""
        self._write([f"USAGE: {prefix}finish={finish} latency={latency:.1f}s"])

    def error(self, text: Any) -> None:
        self._write([f"ERROR: {self._clip(text)}"])

    def note(self, text: Any) -> None:
        self._write([f"NOTE: {self._clip(text)}"])
