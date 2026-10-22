"""The pi-agent-core ladder player.

``choose_move`` is async because the copied poke-env Player already awaits an
awaitable return value.  One turn creates the fresh pi-python agent, gives it
the turn tools, asks for an action and maps the JSON answer back to a
``BattleOrder``.  Any model or parsing failure falls back to a legal move, so a
bad answer never ends the battle.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from poke_env.data import GenData, to_id_str
from poke_env.environment.battle import Battle
from poke_env.player.battle_order import BattleOrder
from poke_env.player.local_simulation import LocalSim
from poke_env.player.player import Player
from pokechamp.data_cache import (
    get_cached_ability_effect,
    get_cached_item_effect,
    get_cached_move_effect,
    get_cached_pokemon_ability_dict,
    get_cached_pokemon_item_dict,
    get_cached_pokemon_move_dict,
)
from pokechamp.prompts import state_translate2

from agent_prompts import build_io_user_prompt, build_repair_prompt, build_system_prompt
from backend import PiAgentBackend
from battle_tools import build_battle_tools
from config import SUPPORTED_PROMPT_ALGOS, AgentConfig
from knowledge import KnowledgeBridge, build_knowledge_tool
from trace import TraceLogger


def _extract_json_object(text: str) -> dict | None:
    """Return the last JSON object in the model answer (code fences tolerated)."""
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        return None
    action_keys = {"move", "switch", "terastallize", "dynamax", "action", "target"}
    for candidate in reversed(candidates):
        if action_keys.intersection(candidate):
            return candidate
    return candidates[-1]


class PiAgentPlayer(Player):
    """A poke-env player driven by a pi-python-core agent with battle tools."""

    def __init__(
        self,
        config: AgentConfig,
        battle_format: str,
        team: Any,
        account_configuration: Any,
        server_configuration: Any,
        *,
        temperature: float = 1.0,
        prompt_algo: str = "io",
        log_dir: str = "./battle_log/pi_agent",
        save_replays: str | bool | None = None,
    ) -> None:
        if prompt_algo not in SUPPORTED_PROMPT_ALGOS:
            supported = ", ".join(SUPPORTED_PROMPT_ALGOS)
            raise NotImplementedError(
                f"pi_agent implements only prompt_algo={supported!r} for now; "
                f"{prompt_algo!r} is reserved for a later port of the harness algorithms"
            )
        super().__init__(
            battle_format=battle_format,
            team=team,
            save_replays=save_replays,
            account_configuration=account_configuration,
            server_configuration=server_configuration,
            max_concurrent_battles=1,
        )
        self.config = config
        self.prompt_algo = prompt_algo
        self.log_dir = log_dir
        self.gen = GenData.from_format(battle_format)
        self.prompt_translate = state_translate2

        self.move_effect = get_cached_move_effect()
        self.pokemon_move_dict = get_cached_pokemon_move_dict()
        self.ability_effect = get_cached_ability_effect()
        self.pokemon_ability_dict = get_cached_pokemon_ability_dict()
        self.item_effect = get_cached_item_effect()
        self.pokemon_item_dict = get_cached_pokemon_item_dict()

        self.agent_name = self.ps_client.account_configuration.username
        self._trace = TraceLogger(config.trace_log)
        self._backend = PiAgentBackend(config, self._trace)
        self._knowledge = (
            KnowledgeBridge(
                enabled=config.knowledge_enabled,
                knowledge_dir=config.knowledge_dir,
                package=config.knowledge_package,
                node=config.knowledge_node,
                timeout=config.knowledge_timeout,
            )
            if config.knowledge_enabled
            else None
        )
        self._knowledge_tool = (
            build_knowledge_tool(self._knowledge) if self._knowledge is not None else None
        )
        self._chat_reasoning = config.chat_reasoning

    # ------------------------------------------------------------------ helpers
    def _make_sim(self, battle: Battle) -> LocalSim:
        return LocalSim(
            battle,
            self.move_effect,
            self.pokemon_move_dict,
            self.ability_effect,
            self.pokemon_ability_dict,
            self.item_effect,
            self.pokemon_item_dict,
            self.gen,
            self._dynamax_disable,
            format=self.format,
            prompt_translate=self.prompt_translate,
        )

    def _forced_action(self, battle: Battle) -> BattleOrder | None:
        """Return a trivially forced action without spending an API call."""
        if battle.active_pokemon is None:
            return None
        if battle.active_pokemon.fainted and len(battle.available_switches) == 1:
            return self.create_order(battle.available_switches[0])
        if len(battle.available_moves) == 1 and not battle.available_switches:
            return self.create_order(battle.available_moves[0])
        if not battle.available_moves and len(battle.available_switches) == 1:
            return self.create_order(battle.available_switches[0])
        return None

    def _match_move(self, battle: Battle, name: str):
        target = to_id_str(name or "")
        if not target:
            return None
        for move in battle.available_moves:
            if to_id_str(move.id) == target:
                return move
        return None

    def _match_switch(self, battle: Battle, name: str):
        target = to_id_str(name or "")
        if not target:
            return None
        for pokemon in battle.available_switches:
            if to_id_str(pokemon.species) == target:
                return pokemon
        return None

    def _parse_action(self, text: str, battle: Battle) -> BattleOrder | None:
        payload = _extract_json_object(text)
        if payload is None:
            return None

        action_type = str(payload.get("action") or "").strip().lower()
        move_name = payload.get("move")
        switch_name = payload.get("switch")
        target_name = payload.get("target")

        terastallize = False
        dynamax = False
        tera_value = payload.get("terastallize")
        if isinstance(tera_value, str) and tera_value.strip():
            move_name = tera_value
            terastallize = True
        elif tera_value is True:
            terastallize = True
        dyna_value = payload.get("dynamax")
        if isinstance(dyna_value, str) and dyna_value.strip():
            move_name = dyna_value
            dynamax = True
        elif dyna_value is True:
            dynamax = True

        if not move_name and action_type == "move":
            move_name = target_name
        if not switch_name and action_type == "switch":
            switch_name = target_name

        if move_name:
            move = self._match_move(battle, str(move_name))
            if move is not None:
                return self.create_order(
                    move,
                    terastallize=bool(terastallize and getattr(battle, "can_tera", False)),
                    dynamax=bool(dynamax and getattr(battle, "can_dynamax", False)),
                )
            self._trace.note(f"rejected unknown move {move_name!r}")

        if switch_name:
            pokemon = self._match_switch(battle, str(switch_name))
            if pokemon is not None:
                return self.create_order(pokemon)
            self._trace.note(f"rejected unknown switch {switch_name!r}")

        return None

    def _fallback(self, battle: Battle) -> BattleOrder:
        try:
            if battle.available_moves:
                best = max(battle.available_moves, key=lambda move: move.base_power)
                return self.create_order(best)
            if battle.available_switches:
                best = max(battle.available_switches, key=lambda mon: mon.current_hp_fraction)
                return self.create_order(best)
        except Exception as exc:
            print(f"pi_agent fallback failed: {type(exc).__name__}: {exc}")
        try:
            return self.choose_random_move(battle)
        except Exception as exc:
            print(f"pi_agent random fallback failed: {type(exc).__name__}: {exc}")
            return self.choose_default_move()

    async def _echo(self, battle: Battle, thinking: str, answer: str) -> None:
        message = (thinking or answer or "").strip()
        if not message:
            return
        print(f"LLM [{self.agent_name}]: {message}")
        if not self._chat_reasoning:
            return
        try:
            chunks = [message[i : i + 950] for i in range(0, len(message), 950)]
            for index, chunk in enumerate(chunks, 1):
                prefix = (
                    f"Turn #{battle.turn} thinking: "
                    if len(chunks) == 1
                    else f"Turn #{battle.turn} thinking ({index}/{len(chunks)}): "
                )
                await self.ps_client.send_message(prefix + chunk, room=battle.battle_tag)
                if index < len(chunks):
                    await asyncio.sleep(0.25)
        except Exception as exc:
            print(f"could not send reasoning to battle chat: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ play
    async def choose_move(self, battle: Battle) -> BattleOrder:
        forced = self._forced_action(battle)
        if forced is not None:
            return forced

        try:
            sim = self._make_sim(battle)
            harness_system, state_prompt, state_action_prompt = self.prompt_translate(sim, battle)
            system_prompt = build_system_prompt(harness_system)
            user_prompt = build_io_user_prompt(battle, state_prompt, state_action_prompt)

            def make_sim() -> LocalSim:
                return self._make_sim(battle)

            tools = build_battle_tools(battle, make_sim, self.gen)
            if self._knowledge_tool is not None:
                tools.append(self._knowledge_tool)

            reply = await self._backend.ask(
                system_prompt,
                user_prompt,
                tools,
                agent_name=self.agent_name,
                battle=battle,
            )
            await self._echo(battle, reply.thinking, reply.text)
            action = self._parse_action(reply.text, battle)
            if action is not None:
                return action

            self._trace.note("first answer had no legal action; retrying once with a repair prompt")
            repair_prompt = user_prompt + "\n\n" + build_repair_prompt(battle, reply.text)
            repair = await self._backend.ask(
                system_prompt,
                repair_prompt,
                tools,
                agent_name=self.agent_name,
                battle=battle,
                kind="repair",
            )
            await self._echo(battle, repair.thinking, repair.text)
            action = self._parse_action(repair.text, battle)
            if action is not None:
                return action
            self._trace.note("repair answer had no legal action; using max-damage fallback")
        except Exception as exc:
            self._trace.error(f"{type(exc).__name__}: {exc}")
            print(f"pi_agent choose_move failed ({type(exc).__name__}: {exc}); using fallback")

        return self._fallback(battle)

    async def close(self) -> None:
        await self._backend.aclose()
        if self._knowledge is not None:
            self._knowledge.close()
