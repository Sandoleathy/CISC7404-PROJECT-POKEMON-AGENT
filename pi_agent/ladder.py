"""Run the pi-agent-core player on a local Pokemon Showdown ladder.

The public PokeAgent Challenge server is permanently closed.  This entrypoint
now talks to the local Showdown server (default ``localhost:8000``) and its
preloaded metamon baseline pool.  Start the server and its opponent pool first;
this script only connects and searches the local ladder.

Examples (from the repository root):

    .venv\\Scripts\\python.exe -u pi_agent\\ladder.py --N 1
    .venv\\Scripts\\python.exe -u pi_agent\\ladder.py --server_url localhost:8000 --battle_format gen9ou --N 1

The local server must accept guest logins (``noguestsecurity = true`` in the
Showdown config) when ``--password`` is empty.  A registered local account can
be used by passing ``--username`` and ``--password`` instead.

The script is self-contained: ``pi_agent/poke_env`` is the copied vendored
engine, so it does not need ``temp/harness`` on the path.  The DeepSeek key
comes from the repository ``.env`` (or the process environment).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PI_AGENT_DIR = Path(__file__).resolve().parent
if str(PI_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(PI_AGENT_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PI_AGENT_DIR.parent / ".env")

from config import DEFAULT_TEAM_FILE, PROMPT_ALGOS, SUPPORTED_PROMPT_ALGOS, AgentConfig  # noqa: E402
from pi_agent_player import PiAgentPlayer  # noqa: E402
from poke_env import AccountConfiguration, ServerConfiguration  # noqa: E402
from poke_env.player.team_util import load_random_team, load_team_file  # noqa: E402

# The copied poke_env build expects a bare host and adds
# ``wss://<host>/showdown/websocket`` itself.
DEFAULT_SERVER_URL = os.getenv("PI_AGENT_SERVER_URL", "localhost:8000")
DEFAULT_AUTH_URL = os.getenv("PI_AGENT_AUTH_URL", "https://play.pokemonshowdown.com/action.php?")
DEFAULT_BATTLE_FORMAT = "gen9ou"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="pi-agent-core player on a local Pokemon Showdown ladder")
    parser.add_argument(
        "--username",
        default=os.getenv("PI_AGENT_USERNAME", "PiAgent"),
        help="Local Showdown account name; names are usually limited to 18 characters",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("PI_AGENT_PASSWORD", ""),
        help="Local account password; leave empty for a guest login (requires noguestsecurity=true)",
    )
    parser.add_argument(
        "--server_url",
        default=DEFAULT_SERVER_URL,
        help="Local Showdown host, bare host and port (default localhost:8000)",
    )
    parser.add_argument(
        "--auth_url",
        default=DEFAULT_AUTH_URL,
        help="Authentication endpoint used only when --password is non-empty",
    )
    parser.add_argument(
        "--backend",
        default=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        help="DeepSeek model id",
    )
    parser.add_argument(
        "--prompt_algo",
        default="io",
        choices=PROMPT_ALGOS,
        help="Prompt algorithm; only io is implemented in pi_agent, the others are reserved",
    )
    parser.add_argument(
        "--battle_format",
        default=DEFAULT_BATTLE_FORMAT,
        help="Local format (default gen9ou; gen9oulongtimer is not defined on the local server)",
    )
    parser.add_argument(
        "--team_file",
        default=str(DEFAULT_TEAM_FILE),
        help="Showdown-format team file; defaults to team_gen9ou.txt in pi_agent/",
    )
    parser.add_argument(
        "--random_team",
        action="store_true",
        help="Sample a bundled gen9ou team instead of --team_file",
    )
    parser.add_argument("--log_dir", default="./battle_log/pi_agent")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--N", type=int, default=1, help="Number of local ladder games")
    parser.add_argument(
        "--knowledge_dir",
        default=None,
        help="Override PI_KNOWLEDGE_DIR for the pi-knowledge bridge",
    )
    parser.add_argument(
        "--no_knowledge",
        action="store_true",
        help="Do not register the search_knowledge tool",
    )
    return parser


def build_team(args: argparse.Namespace):
    if "random" in args.battle_format:
        # Random formats get their team from the local server.
        return None
    if args.random_team:
        team_format = "gen9ou" if args.battle_format.startswith("gen9ou") else args.battle_format
        return load_random_team(team_format=team_format)
    if not os.path.exists(args.team_file):
        raise SystemExit(f"team file {args.team_file} not found; pass --team_file or --random_team")
    return load_team_file(args.team_file)


def build_agent(args: argparse.Namespace, config: AgentConfig) -> PiAgentPlayer:
    return PiAgentPlayer(
        config,
        battle_format=args.battle_format,
        team=build_team(args),
        account_configuration=AccountConfiguration(args.username, args.password or None),
        server_configuration=ServerConfiguration(args.server_url, args.auth_url),
        temperature=args.temperature,
        prompt_algo=args.prompt_algo,
        log_dir=args.log_dir,
        save_replays=args.log_dir,
    )


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.prompt_algo not in SUPPORTED_PROMPT_ALGOS:
        parser.error(
            f"--prompt_algo {args.prompt_algo!r} is reserved; pi_agent currently implements "
            f"only {', '.join(SUPPORTED_PROMPT_ALGOS)}"
        )
    if args.knowledge_dir:
        os.environ["PI_KNOWLEDGE_DIR"] = args.knowledge_dir
    if args.no_knowledge:
        os.environ["PI_AGENT_KNOWLEDGE"] = "0"

    config = AgentConfig.from_env(temperature=args.temperature, model=args.backend)
    if not config.api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set; put it in the repository .env file")
    if len(args.username) > 18:
        raise SystemExit(
            f"username {args.username!r} is {len(args.username)} characters; "
            "Showdown names are usually limited to 18"
        )

    os.makedirs(args.log_dir, exist_ok=True)
    agent = build_agent(args, config)
    print(
        f"pi-agent local ladder: {args.username} on {args.server_url} "
        f"({args.battle_format}), prompt_algo={args.prompt_algo}, model={config.model}, "
        f"thinking={config.thinking_level}"
    )
    try:
        await agent.ladder(args.N)
    finally:
        await agent.close()

    print(f"Finished battles: {agent.n_finished_battles}, won: {agent.n_won_battles}")
    if agent.n_finished_battles:
        print(f"Win rate: {agent.win_rate * 100:.1f}%")
    for tag, battle in agent.battles.items():
        if battle.finished:
            # The local server may not report ratings.
            if battle.rating is None and battle.opponent_rating is None:
                ratings = "no rating reported"
            else:
                ratings = f"rating {battle.rating} vs {battle.opponent_rating}"
            print(f"{tag}  {'WIN' if battle.won else 'LOSS'}  {ratings}")


if __name__ == "__main__":
    asyncio.run(main())
