"""Local 1v1 singles battles: the DeepSeek agent against a poke-env baseline.

Run it from the harness root, because the data cache uses relative paths:

    python local_1v1.py --player_prompt_algo minimax --opponent_name one_step --N 5
"""

import asyncio
import os
import argparse

import numpy as np

# Visual effects are optional (they need pyfiglet/rich/fade installed)
try:
    from pokechamp.visual_effects import print_banner
    VISUAL_EFFECTS = True
except ImportError:
    VISUAL_EFFECTS = False

from common import *
from poke_env.player.team_util import get_llm_player, load_random_team

parser = argparse.ArgumentParser()

# Player arguments
parser.add_argument("--player_prompt_algo", default="io", choices=prompt_algos)
parser.add_argument("--player_backend", type=str, default="deepseek-flash", help="DeepSeek model id")
parser.add_argument("--player_name", type=str, default='pokechamp', choices=bot_choices)
parser.add_argument("--player_device", type=int, default=0)

# Opponent arguments
parser.add_argument("--opponent_prompt_algo", default="io", choices=prompt_algos)
parser.add_argument("--opponent_backend", type=str, default="deepseek-flash", help="DeepSeek model id (used when the opponent is an LLM)")
parser.add_argument("--opponent_name", type=str, default='one_step', choices=bot_choices)
parser.add_argument("--opponent_device", type=int, default=0)

# Shared arguments
parser.add_argument("--temperature", type=float, default=0.3)
parser.add_argument("--battle_format", default="gen9ou", choices=["gen9ou", "gen9randombattle"])
parser.add_argument("--log_dir", type=str, default="./battle_log/one_vs_one")
parser.add_argument("--N", type=int, default=25)
parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")

args = parser.parse_args()

# Set random seed if provided
if args.seed is not None:
    import random
    random.seed(args.seed)
    np.random.seed(args.seed)
    print(f"Using random seed: {args.seed}")

def random_bundled_team():
    """Sample a bundled team for the current format (parsed and validated)."""
    # gen9ou and its variants share the bundled gen9ou exports
    team_format = "gen9ou" if args.battle_format.startswith("gen9ou") else args.battle_format
    return load_random_team(team_format=team_format)


async def main():
    if VISUAL_EFFECTS:
        print_banner("LOCAL", "fire")
        print_banner("BATTLE", "water")
    print(f"Player: {args.player_name} ({args.player_backend}, {args.player_prompt_algo})")
    print(f"Opponent: {args.opponent_name} ({args.opponent_backend}, {args.opponent_prompt_algo})")
    print(f"Format: {args.battle_format}")
    print("=" * 50)

    os.makedirs(args.log_dir, exist_ok=True)

    player = get_llm_player(args,
                            args.player_backend,
                            args.player_prompt_algo,
                            args.player_name,
                            device=args.player_device,
                            PNUMBER1=PNUMBER1,  # for name uniqueness locally
                            battle_format=args.battle_format)

    opponent = get_llm_player(args,
                              args.opponent_backend,
                              args.opponent_prompt_algo,
                              args.opponent_name,
                              device=args.opponent_device,
                              PNUMBER1=PNUMBER1 + '2',  # for name uniqueness locally
                              battle_format=args.battle_format)

    if 'random' not in args.battle_format:
        # Non-random formats need a team; random formats get one from the server
        player.update_team(random_bundled_team())
        opponent.update_team(random_bundled_team())

    for i in range(args.N):
        # Alternate who initiates so neither side always moves first
        if np.random.randint(0, 100) > 50:
            await player.battle_against(opponent, n_battles=1)
        else:
            await opponent.battle_against(player, n_battles=1)

        if 'random' not in args.battle_format and i < args.N - 1:
            player.update_team(random_bundled_team())
            opponent.update_team(random_bundled_team())

        print(f"battle {i + 1}/{args.N}: player win rate {player.win_rate * 100:.1f}%")

    print(f'player winrate: {player.win_rate * 100}')


if __name__ == "__main__":
    asyncio.run(main())