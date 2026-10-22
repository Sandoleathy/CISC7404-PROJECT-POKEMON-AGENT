# AGENTS.md

Instructions for AI coding agents working in this repository. Human contributors: see
[README.md](README.md).

## What this project is

- CISC7404 (AI-Trustworthy) course project: a Pokemon PvP demo, repository
  `CISC7404-PROJECT-POKEMON-AGENT`.
- Approach: drive a Pokemon Showdown battle through `poke_env` with a large language
  model (DeepSeek) and measure it by wins/losses against poke-env's built-in heuristic
  players.
- Three generations of code live here:
  1. the original demo scripts in the repository root (direct connection, no config
     layer, minimal prompt);
  2. `temp/harness/`, a trimmed DeepSeek-only copy of the PokéChamp harness (ICML'25
     paper code, https://github.com/sethkarten/pokechamp) with its own vendored
     `poke_env` engine;
  3. `pi_agent/`, a self-contained harness built on the Python `pi-python-core` library
     (`import pi_python`), with model-callable battle tools and a pi-knowledge RAG tool.
     It currently implements only the `io` prompt algorithm.
- Status: demo/experiment stage, no test suite, no linter, no configuration layer.
  One "experiment" = start a server (or use the online ladder) -> run N battles -> read
  the win/loss summary and the logs.
- This is coursework that teammates and the TA read: prefer readability, keep diffs
  small, and do not refactor or reformat files unrelated to your task.

## Repository layout

| Path | Role |
| --- | --- |
| `deepseek_flash_player.py` | Original LLM agent: `DeepSeekPlayer`, prompt building, one API call per turn, writes `llm_trace.log` |
| `first_battle.py` | Non-AI baseline: `MaxBasePowerPlayer` vs `SimpleHeuristicsPlayer`, 100 battles |
| `inspect_battle.py` | Debug helper: prints the attribute names of `battle`/Pokemon/Move objects once |
| `team.txt` | Team export for the root agent, but it is missing the blank lines between Pokemon, so it parses as a single Pokemon. The root agent hardcodes its team instead; the harness ships a corrected copy as `team_gen9ou.txt` |
| `llm_trace.log` | Decision log appended by the root agent (**tracked by git**, see "Known pitfalls") |
| `requirements.txt` | Full `pip freeze` of the root scripts (exact versions) |
| `temp/harness/` | DeepSeek-only PokéChamp harness: own README, `pokechamp/` (LLM player, prompts, minimax, DeepSeek backend), vendored `poke_env/` + static data, `local_1v1.py`, `ladder_deepseek.py`, `team_gen9ou.txt`, `llm_trace.log` |
| `pi_agent/` | Self-contained pi-python-core harness: copied `poke_env/` + the needed `pokechamp/` helpers (absolute data paths), `pi_agent_player.py`, `battle_tools.py`, `knowledge.py`, `knowledge_bridge.mjs`, `ladder.py`, `team_gen9ou.txt`. See `pi_agent/README.md` for the file map |
| `pi_agent/poke_env/` | Copied snapshot of the vendored engine used by `temp/harness/`; deliberate local changes are preserved and data paths are absolute. Do not restore upstream behaviour |
| `pi_agent/pokechamp/` | Only `data_cache.py`, `prompts.py`, `sim_constants.py`; `llm_player.py`/`minimax_optimizer.py` are intentionally not copied yet |

`temp/harness/` is meant to be committed (about 20 MB, mostly `poke_env/data/static`).
`temp/harness/README.md` documents the harness in detail; this file only lists what an
agent must know before touching it.

## Setup and commands (Windows / PowerShell)

The current checkout was created with `uv` and uses `.venv`; older commands below that say
`venv` mean that same interpreter (`.venv\Scripts\python.exe`).

```powershell
# First-time setup: the virtual environment must be named venv and must not be uploaded
python -m venv venv
venv\Scripts\Activate.ps1          # PowerShell; in cmd it is venv\Scripts\activate
pip install -r requirements.txt

# Root demo scripts (the venv interpreter can be used without activating)
venv\Scripts\python.exe first_battle.py            # non-AI baseline, 100 battles
venv\Scripts\python.exe deepseek_flash_player.py   # LLM agent, one ladder game
venv\Scripts\python.exe inspect_battle.py          # poke-env field names, prints once

# Harness: always run it from temp\harness, its data paths are relative
cd temp\harness
..\..\venv\Scripts\python.exe ladder_deepseek.py --username <name> --N 1
..\..\venv\Scripts\python.exe local_1v1.py --player_prompt_algo io --opponent_name one_step --N 5

# pi_agent: self-contained, run from the repository root (data paths are absolute)
.venv\Scripts\python.exe -u pi_agent\ladder.py --N 1
.venv\Scripts\python.exe pi_agent\ladder.py --prompt_algo io --N 1
```

- Python >= 3.10 (the checked-in `.venv` currently runs 3.14.5 and is isolated, so install
  packages into it explicitly). `uv sync` is the current way to restore it; it installs
  `pi-python-core` from `pyproject.toml`.
- `pi_agent` needs `pi-python-core` (import name `pi_python`), the existing
  `numpy`/`orjson`/`websockets`/`requests`/`python-dotenv`, and Node.js 22+ only for the
  pi-knowledge bridge. It does not use the `pi` CLI and does not need a model configured
  in Pi.
- The harness needs `numpy`, `orjson`, `openai`, `websockets`, `requests` and
  `python-dotenv`, all already present. `rich`/`pyfiglet`/`fade`/`termcolor` are **not**
  installed and are not required: `pokechamp/visual_effects.py` degrades to plain text.
- `local_1v1.py` needs a local Showdown server on port 8000; the ladder script talks to
  the public PokeAgent Challenge server. `pi_agent` currently ships **only** the ladder
  entrypoint; its player class can be used for a local test by passing
  `server_configuration=None`, but no local script is committed.
- Team selection: `--team_file <path>` (default `temp/harness/team_gen9ou.txt` or
  `pi_agent/team_gen9ou.txt`) or `--random_team` for a bundled export; both are parsed and
  must yield six Pokemon.
- `--prompt_algo` in `pi_agent` accepts `io` only. `sc`, `tot` and `minimax` are reserved
  names and fail fast instead of silently behaving like `io`.

## Environment variables and secrets

- The repository root `.env` holds `DEEPSEEK_API_KEY=...`; `python-dotenv`'s
  `load_dotenv()` reads it into `os.environ`.
- `.env` is git-ignored: never `git add` it, never print the key in output, logs, prompts
  or commits, and never hardcode it in a script. Use
  `os.environ.get("DEEPSEEK_API_KEY")`.
- Additional variables read by `temp/harness/ladder_deepseek.py` and the DeepSeek backend:
  `DEEPSEEK_MODEL` (default `deepseek-flash`), `DEEPSEEK_BASE_URL`,
  `DEEPSEEK_THINKING` (`0` disables thinking), `DEEPSEEK_REASONING_EFFORT`
  (`low`/`medium`/`high`, default `high`), `POKEAGENT_USERNAME`,
  `POKEAGENT_PASSWORD`, `POKEAGENT_SERVER_URL`, `POKEAGENT_AUTH_URL`, and
  `HARNESS_TRACE_LOG` (trace-log path, `0` disables the trace log).
- `pi_agent` reads the same `DEEPSEEK_*` and `POKEAGENT_*` variables from the repository
  `.env`. It also reads:
  | Variable | Meaning |
  | --- | --- |
  | `PI_AGENT_TRACE_LOG` | Trace path (default `pi_agent/llm_trace.log`; `0` disables) |
  | `PI_AGENT_MAX_TOKENS` | Per-request output ceiling (default `8192`, clamp 1024-32768) |
  | `PI_AGENT_CHAT_REASONING` | `1` posts the model's thinking into battle chat (default off) |
  | `PI_AGENT_KNOWLEDGE` | `0` disables the `search_knowledge` tool |
  | `PI_AGENT_KNOWLEDGE_TIMEOUT` | Seconds to wait for one pi-knowledge request (default 60) |
  | `PI_KNOWLEDGE_DIR` | Knowledge-base directory passed to the Node bridge (default `~/.pi/knowledge`) |
  | `PI_KNOWLEDGE_PACKAGE` | Path to the pi-knowledge `extension.js` (default under `~/.pi/agent/npm`) |
  | `PI_KNOWLEDGE_NODE_PATH` | Node.exe used for the bridge (default: first `node` on PATH) |
- `pi-python-core` uses DeepSeek's Responses API (`/responses`), not the root scripts'
  `openai` chat-completions client. A missing or invalid `DEEPSEEK_API_KEY` still
  constructs the provider; the first `agent.prompt()` raises.
- Ladder credentials must come from the environment; `passwords.json` is git-ignored.

## Logs: where to look

### Root agent (`deepseek_flash_player.py`)

- Appends to `llm_trace.log` in the repository root.
- `OK  turn-battle pick=N` means a decision was parsed; the next line is the model's
  reasoning (`Reaoning: ...`).
- `FAIL parse_error=... raw=... n_moves=... n_sw=...` means the model returned invalid
  JSON or an out-of-range index; the raw output is included, use it to fix the prompt.
- The file is tracked by git and grows on every run, so it turns dirty after each battle.

### Harness (`temp/harness/`)

- Appends a per-call trace to `temp/harness/llm_trace.log` from
  `pokechamp/deepseek_player.py`, the same mechanism as the root agent's `_log()`: a
  `--- call #N ...` header (agent, battle tag, turn, model, thinking effort, prompt size) followed by
  `ANSWER:` (what the prompt algorithms parse), `THINKING:` (the reasoning), `USAGE:`
  (tokens and latency) or `ERROR:` when the API call raised. Each field is capped at
  8000 characters.
  - `HARNESS_TRACE_LOG=<path>` moves the file, `HARNESS_TRACE_LOG=0` disables tracing.
  - It is tracked by git like the root log, so it too turns dirty after every run.
- Everything else goes to stdout/stderr of the process: poke_env's logger prints every
  websocket frame, the LLM player prints its reasoning as `LLM [<username>]: ...`, and the
  script prints the final `Finished battles: ..., won: ...` summary. The agent also posts
  its reasoning into the battle chat (~950-character chunks).
- `--log_dir` (default `./battle_log/ladder` for the ladder, `./battle_log/one_vs_one`
  for local battles) is only passed to poke_env as `save_replays`.

### pi_agent (`pi_agent/`)

- Appends one block per **agent run** (a turn may contain several model/tool
  round-trips) to `pi_agent/llm_trace.log` by default. The header is
  `--- call #N ... | action | agent=... | battle=... turn=... | model=... | thinking=... |
  max_tokens=... | prompt_chars=... | tools=...`, followed by:
  - `TOOL: name(args) -> result` for each tool the model called,
  - `ANSWER:` the final assistant text that was parsed,
  - `THINKING:` the model's reasoning blocks,
  - `USAGE:` aggregated tokens, stop reason and latency,
  - `ERROR:` / `NOTE:` for failures, retries and fallbacks.
- `PI_AGENT_TRACE_LOG=<path>` moves the file; `PI_AGENT_TRACE_LOG=0` disables it. Unlike
  the root/harness traces, `pi_agent/llm_trace.log` is explicitly git-ignored and is not
  tracked.
- The process prints `LLM [<username>]: ...` (thinking when present) to stdout. Battle-chat
  reasoning is off by default; set `PI_AGENT_CHAT_REASONING=1` to post it in ~950-character
  chunks.
- `--log_dir` (default `./battle_log/pi_agent`) is passed to poke_env as `save_replays`.

To keep the console output as well, redirect it while running from `temp\harness`:

```powershell
cd temp\harness
..\..\venv\Scripts\python.exe -u ladder_deepseek.py --N 1 *> ladder.log
```

`-u` flushes Python output continuously; without it the file stays empty until the process
exits, which looks like a hang but is not one.

Agents: verification logs (`ladder.log`, `smoke_battle.log`, ...) and `battle_log/` are
runtime artifacts. Delete them before you finish, so the working tree stays clean.

## How the agents are built

Root agent: `DeepSeekPlayer.choose_move()` builds a prompt, asks the API and maps one
integer back to an action. When extending it:

1. Subclass `poke_env.player.Player` and override `choose_move(self, battle)`.
2. `battle_to_prompt()` compiles the battle state and the `SYSTEM` constant explains every
   field of that prompt - change both together, or the model sees unexplained fields.
3. Action encoding is a single integer index: `[0, n_moves)` selects a move,
   `[n_moves, n_moves + n_switches)` selects a switch; return the action through
   `Player.create_order(...)`.
4. Fallbacks must never raise: `choose_random_move(battle)` when nothing is available,
   and index `0` when the LLM answer is invalid. An exception in `choose_move` ends the
   battle, so a bad move is always better than a crash.
5. Put new agents in their own `xxx_player.py`; do not change the baseline behaviour of
   `first_battle.py`, its numbers are the comparison point.

### `pi_agent/` (pi-python-core)

`PiAgentPlayer.choose_move()` is an `async def`; the copied Player already awaits an
awaitable return value. Each turn:

1. `LocalSim` + `state_translate2` build the same state/system prompt the harness uses.
2. A fresh `pi_python.Agent` is created with `DeepSeekProvider`, the current turn's tools
   and `RunLimits(max_model_requests=8, max_tool_calls=8, run_timeout=240)`. The prompt
   asks for at most three tool calls per turn; hitting the limit falls back safely.
3. The model may call the tools, then returns one JSON object. A short repair prompt gets
   one second attempt; after that the player falls back to max-base-power (or a random
   legal order). Parsing and fallbacks never raise into the battle loop.
4. Tools are built per turn in `battle_tools.py`:
   - `get_battle_state` - `state_translate2` text (history, actives, boosts, hazards,
     known moves, team, legal actions);
   - `get_available_actions` - compact JSON of legal moves/switches and Tera/Dynamax flags;
   - `calculate_damage` - `LocalSim.calculate_remaining_hp` for damage %, type multiplier,
     speed order and KO chance;
   - `search_knowledge` - pi-knowledge RAG (see below).
5. The reply is parsed with a tolerant JSON extractor, matched against
   `battle.available_moves`/`available_switches`, and returned through
   `Player.create_order(...)` (including `terastallize`/`dynamax`).

`sc`, `tot` and `minimax` are deliberately not implemented yet. The CLI still lists them
but `PiAgentPlayer` raises `NotImplementedError` for them, so a run is never mislabelled.

### pi-knowledge RAG

`pi-knowledge` is a Node/Pi extension, **not** a Python package. `knowledge.py` starts one
persistent Node process (`knowledge_bridge.mjs`), which imports the official
`extension.js`, registers its tools on a minimal fake `pi` object, and answers JSON lines.
The Python tool calls `knowledge_search`; `knowledge_show` is available for diagnostics.
The process is lazy, reused for the whole run, and shut down by the player.

- Default package path: `~/.pi/agent/npm/node_modules/pi-knowledge/extension.js`;
  override with `PI_KNOWLEDGE_PACKAGE`.
- Default storage: pi-knowledge's own `~/.pi/knowledge`; override with
  `PI_KNOWLEDGE_DIR` (also exposed as `ladder.py --knowledge_dir`).
- RAG is **not indexed automatically**. No KB exists in the current checkout, so the tool
  returns “No knowledge bases.” / “No results found.” and the model continues. Building
  the battle knowledge corpus is still an open design decision.
- A missing Node/pi-knowledge install degrades to an “unavailable” tool result; it never
  aborts a battle.

Useful observation fields (verify with `inspect_battle.py` instead of guessing poke-env
internals):

- `battle.turn`, `battle.active_pokemon` / `battle.opponent_active_pokemon`: `species`,
  `types`, `current_hp_fraction`, `status`, `base_stats`, `damage_multiplier(type)`
- `battle.available_moves`: `id`, `type`, `base_power`
- `battle.available_switches`

LLM call details: openai SDK against `https://api.deepseek.com`,
`model="deepseek-flash"`, `temperature=0` (root agent) or `1.0` (harness default),
`response_format={"type": "json_object"}`, thinking enabled through
`reasoning_effort="high"` plus `extra_body={"thinking": {"type": "enabled"}}`. Only the
model string changes between DeepSeek models; DeepSeek renames models over time, so
suspect the model name first on HTTP 400/404.

`pi_agent` does **not** use the openai SDK or `response_format`. It uses
`pi_python.providers.DeepSeekProvider` (DeepSeek's Responses API) through
`pi_python.Agent`; the JSON contract lives in the prompt. Thinking is selected with
`Agent(thinking_level=...)` (`DEEPSEEK_THINKING` / `DEEPSEEK_REASONING_EFFORT` map to
`off`/`low`/`medium`/`high`).

## Working inside `temp/harness/`

- **DeepSeek is the only backend.** `pokechamp/deepseek_player.py` is the single
  implementation; the GPT/LLaMA/Gemini/Ollama/OpenRouter backends and the backend
  detection in `LLMPlayer` were removed on purpose. Do not reintroduce them.
- Prompt algorithms are `io` (one call per turn), `sc`, `tot` and `minimax` (tree search
  with LLM leaf evaluation, many calls per turn).
- `poke_env/` there is a **vendored** engine, not the pip package. It carries deliberate
  local changes; keep them and do not "restore" upstream behaviour:
  - only the modern `websockets` client is used (the legacy one hangs on connect here);
  - websocket connect and the login POST are retried four times, 5 s apart, because the
    challenge server intermittently resets them;
  - the Bayesian predictor was removed, so `Pokemon.guess_stats()` uses the format's usage
    statistics only;
  - formats starting with `gen9ou` (for example `gen9oulongtimer`) reuse the gen9ou usage
    statistics;
  - `team_util.get_llm_player()` builds only the LLM agent and poke-env baselines;
    `poke_env/player/utils.py` (which pulled in pandas/tqdm) was deleted.
- `ServerConfiguration` differs from the pip package: this engine takes a **bare host**
  and builds `wss://<host>/showdown/websocket` itself, while pip's `poke_env==0.16.1`
  (used by the root scripts) expects the full websocket URL.
- Ladder facts worth remembering: account names must be at most 18 characters, the
  `gen9oulongtimer` format bans moves such as Tera Blast (that is why the default team is
  `team_gen9ou.txt` rather than a random bundled team), and the server often reports no
  rating.
- Teams are loaded through `poke_env/player/team_util.py`: `load_team_file` (a single
  file), `load_random_team` (a bundled export), `TeamSet` (samples a directory of team
  files) and `get_metamon_teams` (downloads a metamon pack; it needs the optional
  `huggingface_hub` and `termcolor` packages, so `poke_env/data/download.py` is imported
  lazily). Everything loaded this way is parsed and must contain six Pokemon.
- A Showdown export separates Pokemon with a blank line. poke_env silently reads a file
  without those blank lines as a single Pokemon, which is how a one-Pokemon team once
  reached the ladder; see "Known pitfalls".

## Style

- Write all new comments, prompts, log messages and documentation in **English** (teammate
  requirement). This file is English for the same reason. `pi_agent` code, tool
  descriptions and prompts are English too.
- The root demo scripts (`deepseek_flash_player.py`, `first_battle.py`,
  `inspect_battle.py`) and `README.md` still carry Chinese comments from the first
  version; translate them when you touch those files, but do not mass-rewrite unrelated
  files.
- 4-space indentation. Avoid new dependencies: `requirements.txt` is a full pin set, so
  update it in the same change if you really need one.

## Verification (no automated tests, no lint config)

There is no pytest suite, test directory or formatter configuration, so "verified" means
"actually ran":

1. Root agent: `venv\Scripts\python.exe deepseek_flash_player.py`, then read the
   `Finished battles` / win summary and `llm_trace.log`.
2. Harness: run `local_1v1.py` against a baseline (needs a local server), or
   `ladder_deepseek.py --N 1` against the public server; check the `Finished battles:
   ..., won: ...` line and the per-turn `LLM [<username>]: ...` reasoning.
3. pi_agent: `ladder.py --N 1` against the public server, then read
   `pi_agent/llm_trace.log` for `TOOL:` / `ANSWER:` / `ERROR:`. A local integration test is
   possible by constructing `PiAgentPlayer` with `server_configuration=None`; no local
   script is committed. The challenge server itself can return HTTP 530 while its origin is
   down; that is external and worth retrying later.
4. A battle costs one API call per turn with `io` and many with `minimax`; a serial battle
   takes minutes. Shrinking `n_battles`/`--N` for a smoke test is fine, but do not leave
   such a change in a commit.
5. All agents use `max_concurrent_battles=1`, so battles run one at a time. Do not raise
   it to "go faster": it invites rate limits and interleaved, unreadable logs.

## Known pitfalls

- Both old `llm_trace.log` files (repository root and `temp/harness/`) are tracked by git,
  so a single run makes them dirty. Run
  `git restore llm_trace.log temp/harness/llm_trace.log` before committing unless you
  deliberately want to commit the sample log, and never mix them into a commit that
  contains code changes. `pi_agent/llm_trace.log` is explicitly git-ignored and is not
  tracked.
- An empty redirected log file does not mean a hang: without `python -u` the buffer is only
  flushed at exit. The real hang symptom is the line `waiting for log in`, which means the
  server rejected the login (name longer than 18 characters, missing password) or reset
  the connection.
- On this machine a Windows system proxy (`127.0.0.1:7890`) is enabled in the registry.
  `requests` (used by poke_env to log in) honours it while `websockets`/`httpx` do not, so
  a dead or filtering proxy shows up as login `ConnectionResetError` while the websocket
  connects fine. Set `NO_PROXY=<host>` for the run if that happens.
- `.gitignore` used to contain `venv\`, an invalid glob that git ignored and that made
  ripgrep abort with `error parsing glob 'venv\'`. It is now `venv/`.
- `README.md` contains a `.evn` typo (should be `.env`) and documents
  `venv\Scripts\activate`, which is the cmd form; PowerShell uses
  `venv\Scripts\Activate.ps1`.
- The harness must be started from `temp\harness`: the data cache opens
  `./poke_env/data/static/...` relative to the current working directory.
- A Showdown team export needs a blank line between Pokemon. `team.txt` in the repository
  root has none, so poke_env parses it as a single Pokemon (that is why a ladder replay
  showed a one-Pokemon team). Every team the harness loads is now parsed and counted, and
  `temp/harness/team_gen9ou.txt` is the root agent's team with the blank lines restored.
- `pi_agent/poke_env` is a copy, not an import of `temp/harness/poke_env`. Its data
  lookups were changed to be absolute (`pokechamp/data_cache.py`,
  `poke_env/environment/pokemon.py`, `poke_env/player/team_util.py`,
  `poke_env/player/local_simulation.py`). Do not revert them to `./poke_env/...`; that is
  why `pi_agent` can be started from any directory.
- `pi_agent/pokechamp` intentionally omits `llm_player.py` and `minimax_optimizer.py`.
  `team_util.get_llm_player()` still lazily imports `LLMPlayer` for the `pokechamp` bot
  name, so that path fails; build `PiAgentPlayer` directly instead.
- `pi-knowledge` is a Node extension, not a Python package. Do not add a fake
  `pi_knowledge` Python dependency; `knowledge.py` + `knowledge_bridge.mjs` host the
  official extension entry. If Node is missing, the tool reports “unavailable” and the
  battle continues.
- `~/.pi/knowledge` is empty in this checkout and `pi_agent` never indexes automatically.
  `search_knowledge` returns “No knowledge bases.” / “No results found.” until a KB is
  built. The battle knowledge corpus is still undecided; do not commit a generated KB.
- `pi_agent` supports only `--prompt_algo io`. `sc`/`tot`/`minimax` raise
  `NotImplementedError`; do not make them silently fall back to `io`.
- The PokeAgent Challenge websocket host can answer HTTP 530 while its origin is down
  (the main site may still return 200). This is external; retry later instead of changing
  the server URL.
- For a local integration test against the sibling `pokemon-showdown`, its
  `config/config.js` needs `noguestsecurity = true` so empty-password guest accounts can
  log in. That is a development-server setting outside this repository; restore it after
  the test.

## Commit conventions

- Branch `main`, remote `origin` = `github.com:Sandoleathy/CISC7404-PROJECT-POKEMON-AGENT`.
- Commit messages: one short line, matching the existing history (for example
  "第一版接入Deepseek模型的宝可梦对战Agent…"); English is equally fine.
- Never commit: `.env`, `venv/`, API keys, ladder passwords, one-off debug prints,
  redirected console logs (`*.log` is ignored) or `battle_log/`, and local-only
  experiments. The only logs tracked on purpose are the two old `llm_trace.log` files
  (root agent and harness); `pi_agent/llm_trace.log` is ignored.

## Maintaining this file

When the way this project runs changes (new script, new dependency, new battle format, new
log location, ...), update the matching section here in the same change, so the next human
or agent gets instructions that match the code.
