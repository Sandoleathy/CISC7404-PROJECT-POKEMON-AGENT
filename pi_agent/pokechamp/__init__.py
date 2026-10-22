"""
PokéChamp LLM Player Module (DeepSeek-only harness)

This module contains the LLM-based Pokemon battle player implementation and
the prompt utilities it relies on. The DeepSeek backend is the only supported
LLM integration.
"""

# Main classes are imported when needed to avoid circular imports:
#   from pokechamp.llm_player import LLMPlayer
#   from pokechamp.deepseek_player import DeepSeekPlayer
# Prompts are not imported here to avoid circular imports with poke_env.

__all__ = [
    # Imports are handled directly at the call site to avoid circular imports.
]

__version__ = "1.0.0"