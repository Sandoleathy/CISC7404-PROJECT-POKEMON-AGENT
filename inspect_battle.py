import asyncio
from poke_env.player import Player, RandomPlayer

class Inspector(Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._printed = False

    def choose_move(self, battle):
        if not self._printed:
            self._printed = True

            print("=" * 60)
            print("【Battle 对象】")
            print([a for a in dir(battle) if not a.startswith("_")])

            print("\n【我方场上宝可梦】")
            print([a for a in dir(battle.active_pokemon) if not a.startswith("_")])

            print("\n【可用招式对象】")
            if battle.available_moves:
                print([a for a in dir(battle.available_moves[0]) if not a.startswith("_")])

            print("\n【当前数值示例】")
            me = battle.active_pokemon
            print(f"species = {me.species}")
            print(f"current_hp_fraction = {me.current_hp_fraction}")
            for m in battle.available_moves:
                print(f"  move: id={m.id} base_power={m.base_power}")

        return self.choose_random_move(battle)

async def main():
    a = Inspector()
    b = RandomPlayer()
    await a.battle_against(b, n_battles=1)

if __name__ == "__main__":
    asyncio.run(main())