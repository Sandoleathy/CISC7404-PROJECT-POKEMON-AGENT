# pokechamp harness (DeepSeek only)

A trimmed copy of the [PokéChamp](https://github.com/sethkarten/pokechamp) LLM battle
harness (paper: *PokéChamp: an Expert-level Minimax Language Agent*, ICML'25), reduced to
a single LLM provider: **DeepSeek**.

Copied and trimmed from the upstream PokéChamp repository; the original MIT licence is
kept in [LICENSE.pokechamp](LICENSE.pokechamp).

## What was kept

| Path | Role |
| --- | --- |
| `pokechamp/llm_player.py` | `LLMPlayer`: battle state → prompt → LLM action, prompt algorithms |
| `pokechamp/prompts.py` | Battle-state translation and prompt building |
| `pokechamp/data_cache.py` | Loads usage statistics / Pokédex once and caches them |
| `pokechamp/minimax_optimizer.py` | Optimised game-tree search used by the `minimax` algorithm |
| `pokechamp/sim_constants.py` | Type list and damage constants for the local simulator |
| `pokechamp/deepseek_player.py` | **The only LLM backend**: DeepSeek chat completions |
| `pokechamp/visual_effects.py` | Optional terminal banners (needs `rich`/`pyfiglet`/`fade`) |
| `poke_env/` | Battle engine (poke-env fork with `LocalSim`, the in-process battle simulator) |
| `poke_env/player/team_util.py` | Team loading (`TeamSet`, validated Showdown exports) and the player factory |
| `poke_env/data/static/` | Gen 1-9 data plus gen9ou usage statistics and teams |
| `poke_env/data/download.py` | Metamon team-pack downloader used by `get_metamon_teams` (optional dependency) |
| `local_1v1.py` | Runs the agent against poke-env baselines on a local Showdown server |
| `ladder_deepseek.py` | Runs the agent on the PokeAgent Challenge ladder |
| `team_gen9ou.txt` | Default ladder team (the root agent's gen9ou team, validated on load) |
| `llm_trace.log` | Per-call DeepSeek decision trace appended by the backend (tracked by git) |

Prompt algorithms: `io` (one call per turn), `sc` (self-consistency), `tot`
(tree-of-thought), `minimax` (tree search with LLM leaf evaluation).

## What was removed

* Every non-DeepSeek backend (`gpt_player`, `llama_player`, `gemini_player`,
  `ollama_player`, `openrouter_player`) and the backend-detection logic in `LLMPlayer`.
* The Bayesian predictor package and its hooks inside `poke_env` (`guess_stats`,
  `_get_bayesian_stats`, opponent-move prediction). `Pokemon.guess_stats` now always uses
  the format's usage statistics.
* VGC double-battle support, the MCP player, the timeout player, the `pokellmon` bot, the
  multi-agent ladder orchestrator, evaluation/training scripts and the test suite. The
  metamon team downloader (`poke_env/data/download.py`) is kept, but only imported when
  `get_metamon_teams` is actually called.
* Gen-9 VGC data, VGC team files, usage-stat dumps and data-construction scripts, plus
  `poke_env/player/utils.py` (which pulled in `pandas`/`tqdm` for evaluation helpers the
  harness does not use).

## Requirements

Python ≥ 3.10. From the repository root:

```powershell
venv\Scripts\python.exe -m pip install -r temp\harness\requirements.txt
```

## Running

Both scripts read `poke_env/data/static/...` through relative paths, so **run them from
this folder**:

```powershell
cd temp\harness

# Local: DeepSeek agent vs a poke-env baseline (needs a local Showdown server on :8000)
..\..\venv\Scripts\python.exe local_1v1.py --player_prompt_algo io --opponent_name one_step --N 5

# Ladder: the agent plays on the PokeAgent Challenge server
..\..\venv\Scripts\python.exe ladder_deepseek.py --username MyAgent --N 1
```

Useful flags: `--player_prompt_algo {io,sc,tot,minimax}`, `--battle_format`
(`gen9ou`, `gen9randombattle` locally; `gen9oulongtimer` by default on the ladder),
`--backend` (DeepSeek model id), `--N` (number of battles), `--team_file` (Showdown team
export) and `--random_team` (sample a bundled team instead), `--log_dir`.

## Teams

Team handling lives in `poke_env/player/team_util.py`. Every team that the harness loads is
parsed and counted before it is used:

| Helper | Purpose |
| --- | --- |
| `load_team_file(path)` | Read a Showdown export from disk, validate it, return the text |
| `load_random_team(id=None, team_format="gen9ou")` | Sample one of the bundled exports under `poke_env/data/static/teams/<format>/` |
| `TeamSet(dir, battle_format)` | poke-env `Teambuilder` that samples a team file from a directory tree (upstream code) |
| `get_metamon_teams(battle_format, set_name)` | Download a metamon team pack (`competitive`, `modern_replays`, ...) and wrap it in a `TeamSet` (upstream code) |
| `validate_team(text)`, `parse_team(text)` | Parse a team and raise when it does not hold six Pokemon |

* **A Showdown export must separate Pokemon with a blank line.** Without those blank lines
  poke_env reads the whole file as a single Pokemon - that is how a one-Pokemon team once
  reached the ladder - so `validate_team` prints the parsed species and refuses anything
  that is not six Pokemon.
* Ladder default: `team_gen9ou.txt` next to the scripts (the same gen9ou team the root
  project's `deepseek_flash_player.py` uses). Override with `--team_file <path>` or use
  `--random_team` for a bundled team; `local_1v1.py` always samples bundled teams.
* `get_metamon_teams` needs the optional `huggingface_hub` and `termcolor` packages
  (`pip install huggingface_hub termcolor`); everything else works without them.

## Configuration

| Variable | Meaning |
| --- | --- |
| `DEEPSEEK_API_KEY` | **Required.** Read from the environment; the repository's `.env` is loaded by `ladder_deepseek.py` |
| `DEEPSEEK_MODEL` | Default model id (default `deepseek-flash`) |
| `DEEPSEEK_BASE_URL` | API base URL (default `https://api.deepseek.com`) |
| `DEEPSEEK_THINKING` | `0` disables thinking mode (default: enabled) |
| `DEEPSEEK_REASONING_EFFORT` | `low`, `medium` or `high` (default `high`); lower effort means shorter, cheaper thinking |
| `HARNESS_TRACE_LOG` | Path of the decision trace; `0` disables it (default `./llm_trace.log`) |
| `POKEAGENT_USERNAME` / `POKEAGENT_PASSWORD` | Ladder account; an empty password logs in without authentication |
| `POKEAGENT_SERVER_URL` | Ladder host name only, e.g. `battling.pokeagentchallenge.com` |
| `POKEAGENT_AUTH_URL` | Login endpoint used when a password is set |

## Decision trace

Every LLM call is appended to `llm_trace.log` in this folder by
`pokechamp/deepseek_player.py` - the same idea as the root project's
`deepseek_flash_player.py`:

```
--- call #12 2026-10-17 00:41:03 | action | agent=DeepSeekFlash | battle=battle-gen9oulongtimer-20504523 turn=7 | model=deepseek-flash | json=True | thinking=high | max_tokens=8192 | prompt_chars=9120
ANSWER: {"move":"earthquake"}
THINKING: We are Garchomp at 14% ...
USAGE: prompt_tokens=2150 completion_tokens=310 finish=stop latency=6.2s
```

* `ANSWER` is what the prompt algorithms parse, `THINKING` is the reasoning shown in the
  battle chat, `USAGE` is per-call tokens, finish reason and latency, `ERROR` marks a
  failed call (the harness retries it) and `RETRY` marks an empty answer that is repeated
  with double budget. The header also records the effective `thinking=` effort (`off` when
  thinking is disabled), so runs made with different settings stay distinguishable. Each
  field is capped at 8000 characters.
* The path is independent of the working directory. Set `HARNESS_TRACE_LOG=<path>` to move
  the file, or `HARNESS_TRACE_LOG=0` to switch tracing off.
* Like the root `llm_trace.log` it is **tracked by git**, so it turns dirty after every
  run: `git restore temp/harness/llm_trace.log` before committing code changes. Console
  output is separate - redirect it with `-u` if you want to keep it too (see Notes).

Notes:

* The ladder rejects account names longer than 18 characters; `ladder_deepseek.py` stops
  with an error instead of hanging on "waiting for log in".
* Thinking mode raises small `max_tokens` budgets (100-200 in the prompt algorithms) to
  8192, because DeepSeek bills reasoning tokens against the same budget and the model
  regularly spends 5000-7000 of them per turn. An answer that is still empty
  (`finish=length`) is retried once with double budget, which the trace logs as a `RETRY:`
  line. Set `DEEPSEEK_REASONING_EFFORT=medium` or `low` (or `DEEPSEEK_THINKING=0`) to cut
  the reasoning and the cost.
* The agent writes its reasoning into the battle chat and to stdout every turn, which is
  upstream PokéChamp behaviour (`LLMPlayer._send_thinking_message`). The same reasoning is
  also written to `llm_trace.log` (see "Decision trace").
* The challenge ladder sometimes resets the TLS handshake or the login POST; the vendored
  client retries both four times (5 s apart) instead of hanging on "waiting for log in".
* Formats such as `gen9oulongtimer` reuse the gen9ou usage statistics, so the agent keeps
  its statistical opponent modelling on the ladder.
* `minimax` makes many LLM calls per turn: start with `io` when testing.
* The harness passes `max_concurrent_battles=1` (the poke-env default), so battles are
  played one at a time; do not raise it, the logs interleave and rate limits kick in.
* `DEEPSEEK_API_KEY` is never printed or written to the battle logs.
