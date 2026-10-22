"""System and user prompts for the io-only pi-agent player.

The battle-state text comes from the ported PokéChamp ``state_translate2``
function, so the model sees the same information as the existing harness.  The
extra guidance explains the agent tools and the strict JSON action contract.
"""

from __future__ import annotations

from poke_env.environment.battle import Battle

TOOL_GUIDANCE = """\
You are playing a Pokemon battle through an agent runtime. You can call these tools before deciding:
- get_battle_state: the full turn history, active Pokemon, boosts, hazards, known moves, team and legal actions.
- get_available_actions: a compact JSON view of the legal moves and switches.
- calculate_damage: one move's damage, type multiplier, speed order and KO chance.
- search_knowledge: search the local Pokemon strategy knowledge base (may be empty).

Tool rules:
- Use a tool only when it materially improves the decision. Do not call a tool just to repeat the prompt.
- Use at most three tool calls per turn; one or two is usually enough.
- Never invent tool output, move names or switch species.
- A move name must be an id from the legal moves; a switch name must be a species from the legal switches.
- Your private reasoning belongs in your thinking. The final message must be exactly one JSON object
  matching the required format, with no markdown fences and no text after it.
"""

COT_INSTRUCTION = (
    "Reason briefly if that helps; your private thinking is not part of the final answer. "
    "Then output exactly one JSON object and nothing else."
)


def build_system_prompt(harness_system_prompt: str) -> str:
    """Append tool guidance to the PokéChamp system prompt."""
    base = (harness_system_prompt or "").rstrip()
    return f"{base}\n\n{TOOL_GUIDANCE}" if base else TOOL_GUIDANCE


def _gimmick_options(battle: Battle) -> str:
    options = ""
    if getattr(battle, "can_dynamax", False):
        options += ' or {"dynamax":"<move_name>"}'
    if getattr(battle, "can_tera", False):
        options += ' or {"terastallize":"<move_name>"}'
    return options


def io_constraint(battle: Battle) -> str:
    """Return the same JSON action contract the harness uses for ``io``."""
    gimmick = _gimmick_options(battle)
    active_fainted = battle.active_pokemon is not None and battle.active_pokemon.fainted
    no_moves = len(battle.available_moves) == 0
    no_switches = len(battle.available_switches) == 0

    if active_fainted or no_moves:
        return (
            "Choose the most suitable pokemon to switch. Your output MUST be a JSON like: "
            '{"switch":"<switch_pokemon_name>"}\n'
        )
    if no_switches:
        return (
            "Choose the best action and your output MUST be a JSON like: "
            f'{{"move":"<move_name>"}}{gimmick}\n'
        )
    return (
        "Choose the best action and your output MUST be a JSON like: "
        f'{{"move":"<move_name>"}}{gimmick} or {{"switch":"<switch_pokemon_name>"}}\n'
    )


def build_io_user_prompt(battle: Battle, state_prompt: str, state_action_prompt: str) -> str:
    return (
        f"{state_prompt}{state_action_prompt}"
        f"{io_constraint(battle)}"
        f"{COT_INSTRUCTION}\n"
    )


def build_repair_prompt(battle: Battle, previous_answer: str) -> str:
    """A short second attempt when the first answer had no legal action."""
    moves = ", ".join(move.id for move in battle.available_moves) or "(none)"
    switches = ", ".join(pokemon.species for pokemon in battle.available_switches) or "(none)"
    return (
        "Your previous answer did not contain a legal action.\n"
        f"Previous answer: {previous_answer[:1200]}\n"
        f"Legal moves: {moves}\n"
        f"Legal switches: {switches}\n"
        f"{io_constraint(battle)}"
        "Return exactly one JSON object now."
    )
