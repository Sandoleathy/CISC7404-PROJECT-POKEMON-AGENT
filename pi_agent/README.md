# pi_agent

A second-generation ladder harness for the PokeAgent Challenge, built on the Python
[`pi-python-core`](https://pypi.org/project/pi-python-core/) library (import name
`pi_python`). The battle engine is a self-contained copy of the vendored `poke_env` used by
`temp/harness`, so this folder can be run from any working directory.

The agent currently implements the `io` prompt algorithm: one tool-using agent run per
turn, one JSON action back. `sc`, `tot` and `minimax` are accepted by the CLI but rejected
by `PiAgentPlayer` until they are ported.

## Layout

| Path | Role |
| --- | --- |
| `ladder.py` | CLI entrypoint: PokeAgent Challenge `gen9oulongtimer` ladder |
| `pi_agent_player.py` | `PiAgentPlayer(Player)`; async `choose_move`, JSON parsing, fallbacks |
| `backend.py` | `pi_python.Agent` + `DeepSeekProvider` wrapper, usage/thinking extraction |
| `agent_prompts.py` | System-prompt augmentation, io JSON contract, repair prompt |
| `battle_tools.py` | `get_battle_state`, `get_available_actions`, `calculate_damage` |
| `knowledge.py` | `search_knowledge` tool and the persistent Node bridge owner |
| `knowledge_bridge.mjs` | Node host for the official pi-knowledge extension entry |
| `config.py` | `.env` loading and all runtime settings |
| `trace.py` | `--- call #N ...` decision trace |
| `poke_env/` | Copied vendored engine (LocalSim, retries, gen9ou data) |
| `pokechamp/` | Only `data_cache.py`, `prompts.py`, `sim_constants.py` |
| `team_gen9ou.txt` | Default ladder team |
| `LICENSE.pokechamp` | MIT licence of the copied PokéChamp code |

## Requirements

- Python 3.11+ (the repository `.venv` currently runs 3.14) with `pi-python-core`,
  `numpy`, `orjson`, `websockets`, `requests`, `python-dotenv` (all in the repository
  `.venv`).
- Node.js 22+ and `pi-knowledge` only for the RAG tool. Default package path:
  `~/.pi/agent/npm/node_modules/pi-knowledge/extension.js`.
- `DEEPSEEK_API_KEY`, `POKEAGENT_USERNAME`, `POKEAGENT_PASSWORD` in the repository `.env`.
  The `.env` is loaded automatically.

## Run

From the repository root:

```powershell
.venv\Scripts\python.exe -u pi_agent\ladder.py --N 1
```

Useful flags: `--username`, `--password`, `--backend` (DeepSeek model id), `--N`,
`--battle_format`, `--team_file`, `--random_team`, `--temperature`, `--log_dir`,
`--knowledge_dir`, `--no_knowledge`.

The challenge server rejects account names longer than 18 characters. The server
occasionally answers HTTP 530 when its origin is down; that is external, retry later.

## Tools

The model sees four tools per turn:

- `get_battle_state` - the full `state_translate2` prompt (history, actives, boosts,
  hazards, known moves, team, legal actions).
- `get_available_actions` - compact JSON of legal moves/switches and Tera/Dynamax flags.
- `calculate_damage(move, attacker, defender)` - `LocalSim.calculate_remaining_hp`
  damage %, type multiplier, speed order, KO chance and status-move notes.
- `search_knowledge(query, mode, limit, kb_id)` - pi-knowledge RAG.

The final answer must be one JSON object (for example `{"move":"earthquake"}` or
`{"switch":"ghost"}`). A tolerant extractor accepts code fences and reasoning text around
it. If the answer has no legal action, one repair prompt is sent; after that the player
falls back to max base power (or a random legal order), so a bad model answer never ends
the battle.

## RAG

`pi-knowledge` is a Node/Pi extension, not a Python package. `knowledge.py` starts one
persistent Node process that imports the official `extension.js`, registers its tools on a
minimal fake `pi` object, and answers JSON lines. The Python tool calls
`knowledge_search`; the bridge is lazy, reused and shut down with the player.

The knowledge base is **not** built automatically. `~/.pi/knowledge` is empty in this
checkout, so the tool returns “No knowledge bases.” / “No results found.” and the model
continues. Build a KB separately with pi-knowledge (or point `PI_KNOWLEDGE_DIR` at one)
once the corpus is decided.

## Trace

Default trace: `pi_agent/llm_trace.log` (explicitly git-ignored). Each header is followed by
`TOOL:`, `ANSWER:`, `THINKING:`, `USAGE:` and `ERROR:`/`NOTE:` lines. Set
`PI_AGENT_TRACE_LOG=<path>` to move it or `PI_AGENT_TRACE_LOG=0` to disable it.

See the repository `AGENTS.md` for the full configuration table and verification notes.
