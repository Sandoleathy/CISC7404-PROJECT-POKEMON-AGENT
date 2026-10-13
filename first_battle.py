import asyncio
from poke_env.player import RandomPlayer, MaxBasePowerPlayer

async def main():
    player_1 = MaxBasePowerPlayer(max_concurrent_battles=1)
    player_2 = RandomPlayer(max_concurrent_battles=1)

    await player_1.battle_against(player_2, n_battles=100)

    print(f"Finished battles: {player_1.n_finished_battles}")
    print(f"Player 1 wins: {player_1.n_won_battles}")

if __name__ == "__main__":
    asyncio.run(main())