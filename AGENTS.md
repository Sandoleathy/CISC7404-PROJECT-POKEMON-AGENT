# AGENTS.md

给在本仓库工作的 AI 编码 Agent 的说明。人类开发者请看 [README.md](README.md)。

## 项目是什么

- CISC7404（AI-Trustworthy）课程项目：宝可梦 PvP Demo，仓库名 `CISC7404-PROJECT-POKEMON-AGENT`。
- 做法：用 `poke_env` 连本地 Pokémon Showdown 服务器，写一个由大模型（DeepSeek）决策的对战 Agent，让它和 poke-env 自带的启发式玩家对战，用胜负场次衡量表现。
- 现状：demo 阶段。脚本直连、没有配置层、没有测试。一次"实验"= 起服务器 → 跑若干场对战 → 看胜负统计和 `llm_trace.log`。
- 这是课程作业，代码会被队友和助教阅读：优先可读性，改动尽量小，不要做与任务无关的重构/重排。

## 常用命令（Windows / PowerShell）

```powershell
# 首次准备（虚拟环境必须叫 venv，且不要上传，见 README）
python -m venv venv
venv\Scripts\Activate.ps1          # 注意是 Scripts，不是 Script（README 里写错了）
pip install -r requirements.txt

# 跑对战（也可以不激活，直接用 venv 的解释器）
venv\Scripts\python.exe first_battle.py            # 非 AI 基线：MaxBasePowerPlayer vs SimpleHeuristicsPlayer，100 场
venv\Scripts\python.exe deepseek_flash_player.py   # LLM Agent：DeepSeekPlayer vs SimpleHeuristicsPlayer，10 场
venv\Scripts\python.exe inspect_battle.py          # 调试：打印 battle/宝可梦/招式对象的字段名，只打印一次
```

环境要求：Node ≥ v22.18.0（跑 Showdown 服务器）、Python ≥ 3.10。

## 运行前提：本地 Pokémon Showdown 服务器

- `poke_env` 默认用 `LocalhostServerConfiguration`，即 `ws://localhost:8000/showdown/websocket`；默认对战格式 `gen9randombattle`。仓库代码没有显式传 `battle_format` / `server_configuration`，所以队伍是由 poke-env 自动生成的随机队。
- 要换格式必须显式传参（例如 `Player(battle_format="gen9ou", team=...)`），非 random 格式需要自己提供队伍。
- 起服务器：

```powershell
git clone https://github.com/smogon/pokemon-showdown.git
cd pokemon-showdown
npm install
copy config\config-example.js config\config.js
node pokemon-showdown start --no-security
```

浏览器打开 `http://localhost:8000` 可看到对战界面。

- **服务器没启动或不在 8000 端口时，脚本会卡在连接/超时**。这不是 Agent 代码的 bug：先确认服务器在跑，再排查代码。改代码前先确认这一点，能省掉很多误判。

## 环境变量与密钥

- 根目录 `.env` 里是 `DEEPSEEK_API_KEY=...`，由 `python-dotenv` 的 `load_dotenv()` 读进 `os.environ`。
- `.env` 已被 git 忽略：**不要 `git add` 它，不要在输出/日志/提示词里回显 key，也不要把 key 硬编码进任何脚本**（统一用 `os.environ.get("DEEPSEEK_API_KEY")`）。
- 缺 key 或 key 无效时，`OpenAI(...)` 构造不会报错，但第一次调用会抛异常并中断对战。遇到莫名其妙的崩溃先检查这一点。

## 代码结构与改法

| 文件 | 作用 |
| --- | --- |
| `deepseek_flash_player.py` | 唯一的 LLM Agent：`DeepSeekPlayer` + 提示词构造 + LLM 调用 + 日志 |
| `first_battle.py` | 非 AI 基线：内置玩家互打，作为对比基准 |
| `inspect_battle.py` | 调试脚本：打印 `battle` 等对象的属性名，用来核对 poke-env 字段 |
| `llm_trace.log` | 运行时追加写的决策日志（**已被 git 跟踪**，见"已知坑"） |
| `requirements.txt` | `pip freeze` 出来的全量精确版本 |

扩展 Agent 时跟着现有写法走：

1. 继承 `poke_env.player.Player`，覆盖 `choose_move(self, battle)`。
2. `battle_to_prompt()` 把 `battle` 编译成中文提示词，`SYSTEM` 常量解释提示词里每个字段的含义和策略——改提示词时**两个地方要一起改**，否则模型会看到没解释过的字段。
3. 动作编码统一为**一个整数下标**：`[0, n_moves)` 是招式，`[n_moves, n_moves + n_switches)` 是换人；最终用 `Player.create_order(...)` 返回动作。
4. 兜底逻辑必须"永不抛异常"：没有可用动作时 `choose_random_move(battle)`，LLM 输出非法时返回 `0`（第一个招式）。`choose_move` 里抛异常会直接结束对战，宁可出烂招也不要崩。
5. 新增 Agent 建议单独放 `xxx_player.py`，不要改 `first_battle.py` 的基线行为（基线数据是拿来做对比的）。

常用观测字段（不确定就用 `inspect_battle.py` 验证，不要凭记忆猜 poke-env API）：

- `battle.turn`、`battle.active_pokemon` / `battle.opponent_active_pokemon`：`species`、`types`、`current_hp_fraction`、`status`、`base_stats`、`damage_multiplier(type)`
- `battle.available_moves`：`id`、`type`、`base_power`
- `battle.available_switches`

LLM 调用细节（`deepseek_flash_player.py`）：openai SDK + `base_url="https://api.deepseek.com"`、`model="deepseek-flash"`、`temperature=0`、`response_format={"type": "json_object"}`、`extra_body={"thinking": {"type": "disabled"}}`。换模型只改 `model` 字符串；DeepSeek 的模型名会变，报 400/404 时先怀疑模型名。

代码风格：注释、提示词、日志、文档一律中文；4 空格缩进；不必要不要引入新依赖（`requirements.txt` 是全量精确版本，增删依赖后要同步更新）。

## 验证方式（没有自动化测试，也没有 lint 配置）

仓库里没有 pytest / 测试目录 / 格式化配置，"验证"就是真跑一遍：

1. 起本地 showdown 服务器；
2. `venv\Scripts\python.exe first_battle.py` 确认环境和连接正常；
3. `venv\Scripts\python.exe deepseek_flash_player.py` 跑 LLM Agent，看结尾的 `Finished battles` / `Player 1 wins`，并检查 `llm_trace.log`。

- 冒烟测试可以临时把 `n_battles` 改小（1 场），但**不要把这种改动留在提交里**：测完改回，或 `git restore <file>`。
- 每回合要调用一次 API，串行跑 10 场需要几分钟；不要因为"慢"就放弃跑真实验证。
- 日志判读：`llm_trace.log` 中 `OK  turn-battle pick=N` 是正常；`FAIL parse_error=... raw=...` 说明模型返回了非法 JSON 或下标越界，消息里带了原始输出，用它来改提示词。日志是追加写的，会越跑越长。

## 已知坑

- `llm_trace.log` **被 git 跟踪**（历史提交带进来的）。跑一次对战它就会变脏。提交前用 `git restore llm_trace.log` 丢弃运行产生的日志（除非确实要提交样本日志），**不要把它和功能改动混在同一个 commit 里**。
- 根目录 `.gitignore` 里写的是 `venv\`（反斜杠），git 并不能靠这一行忽略 `venv/`（实测 `git check-ignore venv` 不匹配；`venv/` 没被跟踪是因为 venv 内部自带 `.gitignore`）。这个非法 glob 还会让 ripgrep/rg 在仓库根目录搜索时直接报 `error parsing glob 'venv\'` 失败——搜索时排除 venv，例如 `rg --glob '!venv'`，或把搜索范围限定到具体目录。
- README 里的 `venv\Script\activate` 少了一个 s，正确路径是 `venv\Scripts\Activate.ps1`。
- 两个 player 都是 `max_concurrent_battles=1`：对战是串行的。不要为了"加速"改成并发，既容易触发服务器/限流问题，日志也会交错到无法分析。

## 提交约定

- 分支 `main`，远程 `origin` = `github.com:Sandoleathy/CISC7404-PROJECT-POKEMON-AGENT`。
- 提交信息用中文短句，沿用现有风格（如"第一版接入Deepseek模型的宝可梦对战Agent…"）。
- 不要提交：`.env`、`venv/`、API key、一次性的调试打印、只用于本地实验的临时改动。

## 维护本文件

改动了运行方式（新脚本、新依赖、新对战格式、日志路径等）时，顺手更新本文件对应小节，让下一个人/Agent 拿到的说明和代码一致。
