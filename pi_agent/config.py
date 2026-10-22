"""Configuration for the pi-agent-core Pokemon ladder agent.

The module is intentionally dependency-free (standard library plus python-dotenv),
so it can be imported before the copied ``poke_env`` engine is put on ``sys.path``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PI_AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = PI_AGENT_DIR.parent
DEFAULT_TEAM_FILE = PI_AGENT_DIR / "team_gen9ou.txt"
DEFAULT_TRACE_LOG = PI_AGENT_DIR / "llm_trace.log"

# Keep the names used by the existing harness so the two agents can be
# configured from the same .env file.
PROMPT_ALGOS = ("io", "sc", "tot", "minimax")
SUPPORTED_PROMPT_ALGOS = ("io",)

load_dotenv(REPO_ROOT / ".env")


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off", "")


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _resolve_trace_log() -> Path | None:
    setting = os.getenv("PI_AGENT_TRACE_LOG")
    if setting is None:
        return DEFAULT_TRACE_LOG
    if setting.strip().lower() in ("", "0", "false", "no", "off"):
        return None
    return Path(setting).expanduser()


def _resolve_node() -> str | None:
    setting = os.getenv("PI_KNOWLEDGE_NODE_PATH")
    return setting.strip() if setting and setting.strip() else None


def _resolve_knowledge_dir() -> Path | None:
    setting = os.getenv("PI_KNOWLEDGE_DIR")
    if setting and setting.strip():
        return Path(setting).expanduser().resolve()
    return None


def _resolve_knowledge_package() -> Path | None:
    setting = os.getenv("PI_KNOWLEDGE_PACKAGE")
    if setting and setting.strip():
        return Path(setting).expanduser().resolve()
    return None


@dataclass(frozen=True)
class AgentConfig:
    """Runtime settings for one pi-agent ladder player."""

    api_key: str
    model: str
    base_url: str
    temperature: float
    thinking_level: str
    max_tokens: int
    trace_log: Path | None
    chat_reasoning: bool
    knowledge_enabled: bool
    knowledge_dir: Path | None
    knowledge_package: Path | None
    knowledge_node: str | None
    knowledge_timeout: float

    @classmethod
    def from_env(cls, *, temperature: float = 1.0, model: str | None = None) -> "AgentConfig":
        thinking_on = _env_flag("DEEPSEEK_THINKING", True)
        effort = os.getenv("DEEPSEEK_REASONING_EFFORT", "high").strip().lower()
        if effort not in ("low", "medium", "high"):
            effort = "high"
        thinking_level = effort if thinking_on else "off"

        return cls(
            api_key=(os.getenv("DEEPSEEK_API_KEY") or "").strip(),
            model=(model or os.getenv("DEEPSEEK_MODEL", "deepseek-flash")).strip(),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
            temperature=temperature,
            thinking_level=thinking_level,
            max_tokens=_env_int("PI_AGENT_MAX_TOKENS", 8192, 1024, 32768),
            trace_log=_resolve_trace_log(),
            chat_reasoning=_env_flag("PI_AGENT_CHAT_REASONING", False),
            knowledge_enabled=_env_flag("PI_AGENT_KNOWLEDGE", True),
            knowledge_dir=_resolve_knowledge_dir(),
            knowledge_package=_resolve_knowledge_package(),
            knowledge_node=_resolve_node(),
            knowledge_timeout=_env_float("PI_AGENT_KNOWLEDGE_TIMEOUT", 60.0, 5.0, 300.0),
        )
