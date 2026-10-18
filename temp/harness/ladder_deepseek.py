"""Ladder the DeepSeek pokechamp agent on the PokeAgent Challenge server.

Run it from the harness root, because the data cache uses relative paths:

    python ladder_deepseek.py --username MyAgent --N 1

The API key comes from DEEPSEEK_API_KEY; the repository's .env is loaded
automatically when this folder sits inside it.
"""

import argparse
import asyncio
import os

from dotenv import load_dotenv

from common import prompt_algos
from pokechamp.llm_player import LLMPlayer
from pokechamp.prompts import state_translate2
from poke_env import AccountConfiguration, ServerConfiguration
from poke_env.player.team_util import load_random_team, load_team_file

load_dotenv()

# This poke_env version builds "wss://<server_url>/showdown/websocket" itself,
# so server_url must be a bare host name and must not contain a scheme or path.
PokeAgentChallengeServerConfiguration = ServerConfiguration(
    os.getenv("POKEAGENT_SERVER_URL", "battling.pokeagentchallenge.com"),
    os.getenv("POKEAGENT_AUTH_URL", "https://battling.pokeagentchallenge.com/action.php?"),
)

# Challenge-legal gen9ou team shipped next to this script
DEFAULT_TEAM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "team_gen9ou.txt")

parser = argparse.ArgumentParser(description="DeepSeek agent on the PokeAgent Challenge ladder")

parser.add_argument("--username", default=os.getenv("POKEAGENT_USERNAME", "DeepSeekHarness"),
                    help="Ladder account name; the challenge server rejects names longer than 18 characters")
parser.add_argument("--password", default=os.getenv("POKEAGENT_PASSWORD", ""),
                    help="Ladder password; leave empty to log in without authentication")
parser.add_argument("--backend", default=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
                    help="DeepSeek model id")
parser.add_argument("--prompt_algo", default="io", choices=prompt_algos,
                    help="io is one LLM call per turn; minimax searches the game tree (many calls)")
parser.add_argument("--battle_format", default="gen9oulongtimer",
                    help="Ladder format; the upstream challenge server uses gen9ou")
parser.add_argument("--team_file", default=DEFAULT_TEAM_FILE,
                    help="Showdown-format team file; defaults to team_gen9ou.txt in this folder")
parser.add_argument("--random_team", action="store_true",
                    help="Sample a bundled gen9ou team instead of --team_file")
parser.add_argument("--log_dir", default="./battle_log/ladder")
parser.add_argument("--temperature", type=float, default=1.0)
parser.add_argument("--N", type=int, default=1, help="Number of ladder games")

args = parser.parse_args()


def build_team():
    """Return a validated Showdown team for the ladder.

    ``load_team_file`` / ``load_random_team`` parse the team and refuse anything
    that does not hold six Pokemon, which is how a malformed export (Pokemon not
    separated by a blank line) is caught before a battle instead of in the replay.
    """
    if args.random_team:
        # Bundled gen9ou exports; some of them use moves the challenge ladder bans
        # (Tera Blast), so team_gen9ou.txt stays the safer default.
        team_format = "gen9ou" if args.battle_format.startswith("gen9ou") else args.battle_format
        return load_random_team(team_format=team_format)
    if not os.path.exists(args.team_file):
        raise SystemExit(f"team file {args.team_file} not found; pass --team_file or --random_team")
    return load_team_file(args.team_file)


def build_agent():
    return LLMPlayer(
        battle_format=args.battle_format,
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        backend=args.backend,
        temperature=args.temperature,
        prompt_algo=args.prompt_algo,
        log_dir=args.log_dir,
        team=build_team(),
        # state_translate2 is the prompt the pokechamp agent used in the paper
        prompt_translate=state_translate2,
        account_configuration=AccountConfiguration(args.username, args.password or None),
        server_configuration=PokeAgentChallengeServerConfiguration,
    )


async def main():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY is not set; put it in the repository .env file")
    if len(args.username) > 18:
        # A longer name makes the server drop the login and the agent hangs
        # forever on "waiting for log in", so fail fast instead.
        raise SystemExit(f"username {args.username!r} is {len(args.username)} characters; "
                         "the challenge server allows at most 18")

    os.makedirs(args.log_dir, exist_ok=True)
    agent = build_agent()

    print(f"Ladder: {args.username} on {PokeAgentChallengeServerConfiguration.server_url} "
          f"({args.battle_format}), prompt_algo={args.prompt_algo}, backend={args.backend}")

    await agent.ladder(args.N)

    print(f"Finished battles: {agent.n_finished_battles}, won: {agent.n_won_battles}")
    for tag, battle in agent.battles.items():
        if battle.finished:
            # The challenge ladder does not always report ratings
            if battle.rating is None and battle.opponent_rating is None:
                ratings = "no rating reported"
            else:
                ratings = f"rating {battle.rating} vs {battle.opponent_rating}"
            print(f"{tag}  {'WIN' if battle.won else 'LOSS'}  {ratings}")


if __name__ == "__main__":
    asyncio.run(main())
