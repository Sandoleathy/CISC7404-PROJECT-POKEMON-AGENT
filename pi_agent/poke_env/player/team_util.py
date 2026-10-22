"""Team loading and player construction for the harness.

The team helpers (``TeamSet``, ``get_metamon_teams``) are taken from upstream
pokechamp; ``validate_team`` and friends are local additions.

A Showdown export separates Pokemon with a **blank line**. Without those blank
lines poke_env reads the whole file as a single Pokemon - that is how a one-Pokemon
team once reached the ladder - so every team loaded here is parsed and counted.
"""

import glob
import os
import random

from poke_env.player.player import Player
from poke_env.player.baselines import AbyssalPlayer, MaxBasePowerPlayer, OneStepPlayer
from poke_env.player.random_player import RandomPlayer
from poke_env.ps_client.account_configuration import AccountConfiguration
from poke_env.ps_client.server_configuration import ShowdownServerConfiguration
from poke_env.teambuilder import Teambuilder

# Bundled Showdown exports, one directory per format. Resolve from this file so
# the copied engine does not depend on the process working directory.
TEAM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "static", "teams")
DEFAULT_TEAM_SIZE = 6


class TeamSet(Teambuilder):
    """Sample from a directory of Showdown team files.

    A simple wrapper around poke-env's Teambuilder that randomly samples a team from a
    directory of team files.

    Args:
        team_file_dir: The directory containing the team files (searched recursively).
            Team files are just text files in the standard Showdown export format. See
            https://pokepast.es/syntax.html for details.
        battle_format: The battle format of the team files (e.g. "gen1ou", "gen2ubers",
            etc.). Note that we assume files have a matching extension (e.g.
            "any_name.gen1ou_team").
    """

    def __init__(self, team_file_dir: str, battle_format: str):
        super().__init__()
        self.team_file_dir = team_file_dir
        self.battle_format = battle_format
        self.team_files = self._find_team_files()

    def _find_team_files(self):
        team_files = []
        for root, _, files in os.walk(self.team_file_dir):
            for file in files:
                # metamon packs are named "*.{format}_team", the bundled ones "*.txt"
                if file.endswith(f".{self.battle_format}_team") or file.endswith(".txt"):
                    team_files.append(os.path.join(root, file))
        return team_files

    def yield_team(self):
        file = random.choice(self.team_files)
        team = parse_team(load_team_file(file))
        print(f"Sampled team from {file}")
        for mon in team:
            if mon.species is not None:
                mon.nickname = mon.species
        return self.join_team(team)


def get_metamon_teams(battle_format: str, set_name: str) -> TeamSet:
    """Download a set of teams from huggingface (if necessary) and return a TeamSet.

    Args:
        battle_format: The battle format of the team files (e.g. "gen1ou", "gen2ubers",
            etc.).
        set_name: The name of the set of teams to download. One of competitive,
            paper_replays, paper_variety, modern_replays, pokeagent_modern_replays.
    """
    if set_name not in {
        "competitive",
        "paper_replays",
        "paper_variety",
        "modern_replays",
        "pokeagent_modern_replays",
    }:
        raise ValueError(
            f"Invalid set name: {set_name}. Must be one of: competitive, paper_replays, paper_variety, modern_replays"
        )
    # Optional dependency: only needed for the downloaded metamon packs, so it is
    # imported here instead of at module level (the harness itself does not need it).
    try:
        from poke_env.data.download import download_teams
    except ImportError as e:
        raise ImportError(
            "get_metamon_teams needs the optional 'huggingface_hub' and 'termcolor' "
            "packages (pip install huggingface_hub termcolor)"
        ) from e

    path = download_teams(battle_format, set_name=set_name)
    if not os.path.exists(path):
        raise ValueError(
            f"Cannot locate valid team directory for format {battle_format} at path {path}"
        )
    team_set = TeamSet(path, battle_format)
    if not team_set.team_files:
        raise ValueError(
            f"No team files found for format {battle_format} in {path}. "
            f"Expected files with extension '.{battle_format}_team'"
        )
    return team_set


def parse_team(team_data: str):
    """Parse a Showdown export into TeambuilderPokemon objects."""
    return Teambuilder.parse_showdown_team(team_data)


def validate_team(team_data: str, source: str = "<inline team>",
                  expected_size: int = DEFAULT_TEAM_SIZE) -> str:
    """Return the team text after checking that it holds ``expected_size`` Pokemon.

    poke_env splits a Showdown export on blank lines, so a file that forgets the
    blank line between two Pokemon parses as a single Pokemon. Failing loudly here is
    much cheaper than discovering it in a replay.
    """
    mons = parse_team(team_data)
    # A plain Showdown export has no "(Species)" marker, so the name lands in nickname
    species = [mon.species or mon.nickname or "?" for mon in mons]
    print(f"{source}: {len(mons)} Pokemon ({', '.join(species)})")
    if len(mons) != expected_size:
        raise ValueError(
            f"{source} parsed into {len(mons)} Pokemon instead of {expected_size} "
            f"({', '.join(species)}); Showdown exports must separate Pokemon with a "
            f"blank line"
        )
    return team_data


def load_team_file(path: str, expected_size: int = DEFAULT_TEAM_SIZE) -> str:
    """Read a Showdown export from disk and validate it."""
    with open(path, encoding="utf-8") as team_file:
        return validate_team(team_file.read(), source=path, expected_size=expected_size)


def load_random_team(id=None, team_format: str = "gen9ou",
                     expected_size: int = DEFAULT_TEAM_SIZE) -> str:
    """Load one of the bundled Showdown teams of a format.

    Args:
        id: 1-based number of the team file (gen9ou1, gen9ou2, ...); a random bundled
            team is used when None.
        team_format: Directory and file prefix under poke_env/data/static/teams.
        expected_size: How many Pokemon the team must contain.
    """
    team_files = sorted(glob.glob(os.path.join(TEAM_DIR, team_format, f"{team_format}*.txt")))
    if not team_files:
        raise ValueError(f"No bundled teams for format {team_format} in {TEAM_DIR}")
    if id is None:
        path = random.choice(team_files)
    elif 1 <= id <= len(team_files):
        path = team_files[id - 1]
    else:
        raise ValueError(f"Team id {id} is out of range 1..{len(team_files)} for {team_format}")
    return load_team_file(path, expected_size=expected_size)


def get_llm_player(args,
                   backend: str,
                   prompt_algo: str,
                   name: str,
                   KEY: str='',
                   battle_format='gen9ou',
                   llm_backend=None,
                   device=0,
                   PNUMBER1: str='',
                   USERNAME: str='',
                   PASSWORD: str='',
                   online: bool=False) -> Player:
    from pokechamp.llm_player import LLMPlayer
    from pokechamp.prompts import state_translate2

    server_config = None
    if online:
        server_config = ShowdownServerConfiguration
    if USERNAME == '':
        USERNAME = name

    if name == 'abyssal':
        return AbyssalPlayer(battle_format=battle_format,
                            account_configuration=AccountConfiguration(f'{USERNAME}{PNUMBER1}', PASSWORD),
                            server_configuration=server_config
                            )
    elif name == 'max_power':
        return MaxBasePowerPlayer(battle_format=battle_format,
                            account_configuration=AccountConfiguration(f'{USERNAME}{PNUMBER1}', PASSWORD),
                            server_configuration=server_config
                            )
    elif name == 'random':
        return RandomPlayer(battle_format=battle_format,
                            account_configuration=AccountConfiguration(f'{USERNAME}{PNUMBER1}', PASSWORD),
                            server_configuration=server_config
                            )
    elif name == 'one_step':
        return OneStepPlayer(battle_format=battle_format,
                            account_configuration=AccountConfiguration(f'{USERNAME}{PNUMBER1}', PASSWORD),
                            server_configuration=server_config
                            )
    elif name in ('pokechamp', 'deepseek'):
        # The LLM agent: pokechamp prompt algorithms driven by the DeepSeek backend
        return LLMPlayer(battle_format=battle_format,
                        api_key=KEY,
                        backend=backend,
                        temperature=args.temperature,
                        prompt_algo=prompt_algo,
                        log_dir=args.log_dir,
                        account_configuration=AccountConfiguration(f'{USERNAME}{PNUMBER1}', PASSWORD),
                        server_configuration=server_config,
                        save_replays=args.log_dir,
                        prompt_translate=state_translate2,
                        device=device,
                        llm_backend=llm_backend)
    else:
        raise ValueError(f'Bot not found: {name}')
