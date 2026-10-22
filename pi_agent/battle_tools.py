"""Model-callable battle tools for the pi-agent ladder player.

The functions wrap the same helpers the PokéChamp harness uses internally
(``state_translate2`` and ``LocalSim.calculate_remaining_hp``), but expose them
to the model as tools.  Every tool returns readable text and never raises into
the battle loop.
"""

from __future__ import annotations

import json
import math
from typing import Callable

from pi_python import tool

from poke_env.data import GenData, to_id_str
from poke_env.environment.battle import Battle
from poke_env.environment.move import Move
from poke_env.environment.move_category import MoveCategory
from poke_env.environment.pokemon import Pokemon
from poke_env.player.local_simulation import LocalSim
from pokechamp.prompts import state_translate2

SimFactory = Callable[[], LocalSim]

ACTIVE_NAMES = {"active", "current", "me", "self", "you", "your", "mypokemon"}
OPPONENT_ACTIVE_NAMES = {"active", "opponent", "opposing", "enemy", "foe", "theirs"}


def _types(mon: Pokemon) -> str:
    names = [t.name.capitalize() for t in (mon.type_1, mon.type_2) if t is not None]
    return " / ".join(names) if names else "unknown"


def _hp_percent(mon: Pokemon) -> int | None:
    try:
        if not mon.max_hp:
            return None
        return round(mon.current_hp / mon.max_hp * 100)
    except (AttributeError, TypeError, ZeroDivisionError):
        return None


def _status(mon: Pokemon) -> str:
    return mon.status.name.lower() if mon.status is not None else "none"


def _mon_summary(mon: Pokemon) -> dict:
    return {
        "species": mon.species,
        "hp_percent": _hp_percent(mon),
        "types": _types(mon),
        "status": _status(mon),
        "ability": mon.ability or "",
        "item": mon.item or "",
        "fainted": bool(mon.fainted),
        "boosts": {key: value for key, value in (mon._boosts or {}).items() if value},
    }


def _match_species(pokemon: Pokemon, wanted: str) -> bool:
    species = to_id_str(pokemon.species or "")
    target = to_id_str(wanted or "")
    return bool(species and target and (species == target or target in species or species in target))


def _resolve_mon(battle: Battle, name: str, *, default_side: str) -> Pokemon | None:
    """Resolve "active"/"opponent" or a species name on either side.

    ``default_side`` is used for an empty name and as the fallback when a
    species name is not found.  The model often asks for the opponent's move
    against our active Pokemon, so both sides are searched explicitly.
    """
    wanted = (name or "").strip()
    lowered = wanted.lower()
    if not wanted or lowered in ACTIVE_NAMES:
        return battle.active_pokemon
    if lowered in OPPONENT_ACTIVE_NAMES:
        return battle.opponent_active_pokemon

    teams = (battle.team, battle.opponent_team)
    if default_side == "opponent":
        teams = (battle.opponent_team, battle.team)
    for team in teams:
        for pokemon in team.values():
            if _match_species(pokemon, wanted):
                return pokemon
    return battle.opponent_active_pokemon if default_side == "opponent" else battle.active_pokemon


def _side_of(battle: Battle, pokemon: Pokemon | None) -> str:
    if pokemon is None:
        return "unknown"
    if pokemon is battle.active_pokemon:
        return "player"
    if pokemon is battle.opponent_active_pokemon:
        return "opponent"
    if any(pokemon is member for member in battle.team.values()):
        return "player"
    if any(pokemon is member for member in battle.opponent_team.values()):
        return "opponent"
    return "unknown"


def _resolve_move(mon: Pokemon, name: str, gen: GenData) -> Move | None:
    wanted = to_id_str(name or "")
    if not wanted:
        return None
    for move in mon.moves.values():
        if to_id_str(move.id) == wanted:
            return move
    try:
        return Move(wanted, gen=gen.gen)
    except Exception:
        return None


def _speed(mon: Pokemon, sim: LocalSim) -> float:
    try:
        stats = mon.calculate_stats(battle_format=sim.format)
        base = stats.get("spe") or 0
        return float(base) * float(sim.boost_multiplier("spe", mon._boosts.get("spe", 0)))
    except Exception:
        return 0.0


def _json(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _calculate_damage(
    sim: LocalSim,
    battle: Battle,
    move_name: str,
    attacker_name: str,
    defender_name: str,
    gen: GenData,
) -> str:
    if battle.active_pokemon is None or battle.opponent_active_pokemon is None:
        return _json({"error": "battle has no active Pokemon on one or both sides yet"})

    attacker = _resolve_mon(battle, attacker_name, default_side="player")
    defender = _resolve_mon(battle, defender_name, default_side="opponent")
    if attacker is None or defender is None:
        return _json({"error": "could not resolve the attacker or defender"})

    attacker_side = _side_of(battle, attacker)
    defender_side = _side_of(battle, defender)
    move = _resolve_move(attacker, move_name, gen)
    if move is None:
        return _json(
            {
                "error": f"unknown move {move_name!r}",
                "attacker": attacker.species,
                "attacker_side": attacker_side,
                "attacker_moves": [m.id for m in attacker.moves.values()],
            }
        )

    payload: dict = {
        "attacker": attacker.species,
        "attacker_side": attacker_side,
        "defender": defender.species,
        "defender_side": defender_side,
        "move": move.id,
        "type": move.type.name.capitalize() if move.type is not None else "unknown",
        "category": move.category.name if move.category is not None else "unknown",
        "base_power": move.base_power,
        "accuracy": None if move.accuracy is None else (100 if move.accuracy is True else move.accuracy),
        "priority": move.priority,
    }

    if move.category == MoveCategory.STATUS:
        payload.update(
            {
                "damage_percent": 0,
                "defender_hp_after_percent": _hp_percent(defender),
                "turns_to_faint": None,
                "notes": "Status move: it does not deal direct damage. Consider its boosts, status, healing or hazard effect.",
            }
        )
        return _json(payload)

    try:
        type_multiplier = float(defender.damage_multiplier(move))
    except Exception:
        type_multiplier = None
    payload["type_multiplier"] = type_multiplier
    payload["stab"] = move.type is not None and move.type in [t for t in attacker.types if t is not None]

    try:
        if attacker_side == "opponent":
            team, opp_team = sim.battle.opponent_team, sim.battle.team
        else:
            team, opp_team = sim.battle.team, sim.battle.opponent_team
        hp1, hp2, move_success, _defender_success, turns = sim.calculate_remaining_hp(
            attacker,
            defender,
            move,
            None,
            return_turns=True,
            team=team,
            opp_team=opp_team,
        )
    except Exception as exc:
        payload["error"] = f"damage calculation failed: {type(exc).__name__}: {exc}"
        return _json(payload)

    damage = max(0.0, 100.0 - float(hp2))
    payload.update(
        {
            "damage_percent": round(damage, 1),
            "defender_hp_after_percent": int(hp2),
            "move_executes": bool(move_success),
            "attacker_hp_after_percent": int(hp1),
            "turns_to_faint_from_current_hp": (
                int(math.ceil(turns)) if isinstance(turns, (int, float)) and math.isfinite(turns) else None
            ),
        }
    )

    attacker_speed = _speed(attacker, sim)
    defender_speed = _speed(defender, sim)
    payload["attacker_moves_first"] = attacker_speed > defender_speed or (
        attacker_speed == defender_speed and move.priority > 0
    )

    if type_multiplier == 0:
        payload["notes"] = "The move has no effect on this defender."
    elif damage >= 100:
        payload["notes"] = "This move can KO the defender from its current HP."
    elif not move_success:
        payload["notes"] = "The defender may move first, so the attacker might not get this move off."
    else:
        payload["notes"] = "Damage uses the current stats, boosts and field; hazards and items may change it."

    return _json(payload)


def _available_actions(battle: Battle) -> str:
    moves = []
    for move in battle.available_moves:
        moves.append(
            {
                "id": move.id,
                "type": move.type.name.capitalize() if move.type is not None else "unknown",
                "category": move.category.name if move.category is not None else "unknown",
                "base_power": move.base_power,
                "accuracy": None if move.accuracy is None else (100 if move.accuracy is True else move.accuracy),
                "priority": move.priority,
                "pp": getattr(move, "current_pp", None),
            }
        )
    switches = [_mon_summary(pokemon) for pokemon in battle.available_switches]
    return _json(
        {
            "turn": battle.turn,
            "active": _mon_summary(battle.active_pokemon) if battle.active_pokemon else None,
            "opponent_active": (
                _mon_summary(battle.opponent_active_pokemon) if battle.opponent_active_pokemon else None
            ),
            "available_moves": moves,
            "available_switches": switches,
            "can_terastallize": bool(battle.can_tera),
            "can_dynamax": bool(battle.can_dynamax),
        }
    )


def build_battle_tools(battle: Battle, make_sim: SimFactory, gen: GenData):
    """Build the per-turn battle tools (state, actions, damage)."""

    @tool(name="get_battle_state")
    def get_battle_state() -> str:
        """Return the full current battle state in the agent's prompt format.

        Includes recent turn history, both active Pokemon, stat boosts, side
        conditions, known opponent moves, your remaining team, legal moves and
        legal switches. Use it when you need details that are missing from the
        short turn prompt.
        """
        if battle.active_pokemon is None or battle.opponent_active_pokemon is None:
            return "Battle state is not available yet (team preview or missing active Pokemon)."
        try:
            sim = make_sim()
            _system, state_prompt, state_action_prompt = state_translate2(sim, battle)
            return state_prompt + state_action_prompt
        except Exception as exc:
            return f"Could not build the battle state: {type(exc).__name__}: {exc}"

    @tool(name="get_available_actions")
    def get_available_actions() -> str:
        """List the legal moves and switches for this turn as JSON.

        Includes current HP, types, status, stat boosts, move power, accuracy,
        priority and the Tera/Dynamax flags. Use it before choosing an action.
        """
        try:
            return _available_actions(battle)
        except Exception as exc:
            return f"Could not list actions: {type(exc).__name__}: {exc}"

    @tool(name="calculate_damage")
    def calculate_damage(move: str, attacker: str = "active", defender: str = "opponent") -> str:
        """Estimate one move's damage, type multiplier, speed order and KO chance.

        Args:
            move: Move id or name, for example "earthquake" or "Earthquake".
            attacker: "active" for your current Pokemon, "opponent" for the opposing
                active Pokemon, or a species name on either team.
            defender: "opponent" for the opposing active Pokemon, "active" for your
                current Pokemon, or a species name on either team.
        """
        try:
            return _calculate_damage(make_sim(), battle, move, attacker, defender, gen)
        except Exception as exc:
            return _json({"error": f"damage tool failed: {type(exc).__name__}: {exc}"})

    return [get_battle_state, get_available_actions, calculate_damage]
