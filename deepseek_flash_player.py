import os, json
from openai import OpenAI
from poke_env.player import Player
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("DEEPSEEK_API_KEY")
# print(api_key)

client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com",
)

SYSTEM = """你是宝可梦对战 AI。根据战局选择一个动作。
提示中的信息：
- [属性] 是宝可梦的属性组合
- 打对方×N：你的招式对对方的伤害倍率。>1 克制，<1 被抵抗，0 无效
- 受威胁×N：对方属性打该待换成员的倍率。越大越危险
- 速度决定谁先出手
策略：优先使用克制倍率高的招式；当前宝可梦受威胁大时考虑换入受威胁小的成员。
只输出 JSON：{"action": <整数下标>}
招式下标从 0 开始，换人下标接在招式后面。"""

class DeepSeekPlayer(Player):

    def choose_move(self, battle):
        n_moves = len(battle.available_moves)
        n_switches = len(battle.available_switches)

        if n_moves == 0 and n_switches == 0:
            return self.choose_random_move(battle)   # 兜底

        idx = self.call_llm(self.battle_to_prompt(battle, n_moves), n_moves, n_switches)

        if idx < n_moves:
            return Player.create_order(battle.available_moves[idx])
        return Player.create_order(battle.available_switches[idx - n_moves])

    def battle_to_prompt(self, battle, n_moves):
        me, opp = battle.active_pokemon, battle.opponent_active_pokemon

        def type_str(mon):
            return "/".join(str(t).replace("PokemonType.", "") for t in mon.types if t)

        L = [f"回合 {battle.turn}"]

        # 属性 + HP
        L.append(f"我方: {me.species} [{type_str(me)}] HP {me.current_hp_fraction:.0%}")
        L.append(f"对方: {opp.species} [{type_str(opp)}] HP {opp.current_hp_fraction:.0%}")

        # 速度对比（不用精确值，只要谁快）
        if me.base_stats["spe"] > opp.base_stats["spe"]:
            L.append("速度: 我方更快（优先出手）")
        elif me.base_stats["spe"] < opp.base_stats["spe"]:
            L.append("速度: 对方更快")
        else:
            L.append("速度: 相同")

        # 异常状态 / 能力变化（可选，先用 dir() 核对字段名）
        if me.status:
            L.append(f"我方状态: {me.status}")
        if opp.status:
            L.append(f"对方状态: {opp.status}")

        L.append("")
        L.append("可选招式（倍率>1 克制对方，<1 被抵抗，0 无效）：")
        for i, m in enumerate(battle.available_moves):
            eff = opp.damage_multiplier(m.type)
            L.append(f"[{i}] {m.id} | {m.type}系 | 威力{m.base_power} | 打对方×{eff}")

        if battle.available_switches:
            L.append("")
            L.append("可换成员（受威胁=对方属性打它的最大倍率，越小越安全）：")
            for j, p in enumerate(battle.available_switches):
                threat = max([p.damage_multiplier(t) for t in opp.types if t] or [1.0])
                L.append(f"[{n_moves + j}] {p.species} [{type_str(p)}] "
                        f"HP {p.current_hp_fraction:.0%} 受威胁×{threat}")

        return "\n".join(L)

    def call_llm(self, prompt, n_moves, n_switches):
        resp = client.chat.completions.create(
            model="deepseek-flash",
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            extra_body = { "thinking" : {"type": "disabled"} },       # 关闭思考
        )
        raw = resp.choices[0].message.content
        try:
            idx = int(json.loads(raw)["action"])
            assert 0 <= idx < n_moves + n_switches
            self._log(f"OK  turn-battle pick={idx}")
            return idx
        except Exception as e:
            self._log(f"FAIL parse_error={e} raw={raw!r} n_moves={n_moves} n_sw={n_switches}")
            return 0        # 解析失败就出第一个招式

    # 记录AI日志
    def _log(self, msg):
        with open("llm_trace.log", "a", encoding="utf-8") as f:
            f.write(msg + "\n")

import asyncio
from poke_env.player import SimpleHeuristicsPlayer, MaxBasePowerPlayer

async def main():
    player_1 = DeepSeekPlayer(max_concurrent_battles=1)
    player_2 = SimpleHeuristicsPlayer(max_concurrent_battles=1)

    await player_1.battle_against(player_2, n_battles=10)

    print(f"Finished battles: {player_1.n_finished_battles}")
    print(f"Player 1 wins: {player_1.n_won_battles}")

if __name__ == "__main__":
    asyncio.run(main())