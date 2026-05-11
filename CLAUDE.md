# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目状态

**当前阶段：P0 进行中（D1–D5 完成，D6 进行中，125 单元测试全绿）**

`external/mirofish` 是 git submodule（灵感来源 MiroFish 的参考实现，只读）。

**文档阅读顺序**：
- `docs/01-mirofish.md` — 参考架构：MiroFish 七步骨架（INKFISH 灵感来源）
- `docs/02-tavern.md` — 参考架构：SillyTavern 资产格式与教训
- `docs/03-design.md` — **INKFISH 系统设计规格**（权威设计文档）
- `docs/04-build.md` — 实施路线图（阶段切片 P0–P8）
- `docs/plans/P0-plan.md` — P0 详细实施计划（D1–D11）
- `docs/reviews/P0-D1.md`, `P0-D2.md` — D1/D2 交付审查

## 自动维护

每 15 分钟由 `/loop` 定时任务自动执行：
1. 扫描项目当前状态（git status、新文件、测试结果）
2. 更新本文件（CLAUDE.md）以反映最新进度
3. `git add -A`（提交全部变更）并 commit

## 开发环境

```bash
source .venv/bin/activate       # 激活 venv（Python 3.12）
uv run pytest -q                # 跑测试
uv run python -m inkfish version
uv run ruff check src/ tests/
uv run mypy src/inkfish
```

依赖在 `pyproject.toml`，锁定在 `uv.lock`（提交到 repo）。
配置文件：`inkfish.toml`（运行时参数）+ `.env`（秘钥，gitignored）。

## P0 实现进度

| 模块 | 状态 | 文件 |
|---|---|---|
| M0 Config | ✅ D1 完成 | `src/inkfish/config.py` |
| M1 Storage — ORM Models | ✅ D2 完成 | `src/inkfish/storage/models.py` |
| M1 Storage — DB Engine + WAL | ✅ D2 完成 | `src/inkfish/storage/db.py` |
| M1 Storage — SnapshotManager | ✅ D3 完成 | `src/inkfish/storage/snapshot.py` |
| M1 Storage — Repository CRUD | ✅ D3 完成 | `src/inkfish/storage/repository.py` |
| World State（内存视图） | ✅ D3 完成 | `src/inkfish/world/state.py` |
| M3 Character — ActionType enum + CharacterAction Pydantic | ✅ D4 完成 | `src/inkfish/character/schema.py` |
| M3 Character — JSON repair + parse_action_json + fallback | ✅ D4 完成 | `src/inkfish/character/validator.py` |
| M4 LLM Gateway — DeepSeekClient（OpenAI SDK wrapper） | ✅ D5 完成 | `src/inkfish/llm/deepseek.py` |
| M4 LLM Gateway — call_with_retry + tenacity + LLMLogRow | ✅ D5 完成 | `src/inkfish/llm/retry.py` |
| World State — query helpers (get_character/location, advance_time) | ✅ D6 完成 | `src/inkfish/world/state.py` |
| World Seed — seed_loader（load_seed_file + seed_world） | ✅ D6 完成 | `src/inkfish/world/seed_loader.py` |
| World Seed — data/seed/world.json（5 角色 + 1 地点） | ✅ D6 完成 | `data/seed/world.json` |
| Tick Scheduler | ⬜ 待 D7 | `src/inkfish/tick/` |
| M7 API（FastAPI REST） | ⬜ 待 D9 | `src/inkfish/api/` |
| CLI（typer commands） | 🔧 占位 | `src/inkfish/cli.py` |

## 核心设计立场

INKFISH 是一个**自主角色模拟引擎**，输出网络小说。

- **不是协作写作工具**——AI 全自动写小说，作者不参与写作
- **作者是天道**——监视、审阅、调整（通过节点图 + 对话框向导演下指令）
- **零输入可运行**——无任何 premise 时自动生成世界和小说
- **角色完全自治**——每个角色是独立 agent，自己驱动自己的行为

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | Python + FastAPI | LLM SDK 生态；async 原生 |
| API | REST + SSE | 简单直接 |
| 前端 | React | 节点图交互复杂度 |
| ORM | SQLAlchemy | SQLite ↔ PostgreSQL 无痛切换 |
| 存储 | SQLite（开发）→ PostgreSQL（大规模） | 结构化快照 + git-like 操作 |
| LLM | 多 provider routing | DeepSeek（默认）/ Anthropic / Qwen / Ollama |
| 部署 | Docker | macOS + Linux 统一 |

## 架构：九个模块

```
M8 Frontend(React) → M7 API(FastAPI+SSE) → M5 Director / M6 Writer → M3 Character → M4 LLM Gateway → M1 Storage + M2 Space
                                                                                                       ↑
                                                                                                    M0 Config
```

- **M0 Config**：全局配置（导演数、权重阈值、routing 规则、tick 参数）
- **M1 Storage**：SQLite + 完整快照 + git-like ckpt（fork/reset/replay）
- **M2 Space**：多层空间模型（物理 + 数字 + 异界）、地点动态生成、跨层管理
- **M3 Character**：角色 agent 生命周期、感知、决策、action 输出、互动 budget
- **M4 LLM Gateway**：中央调度器、优先级队列、多 provider routing、限流、prompt 缓存
- **M5 Director**：AI 导演——剧情规划、tool call（12 个）、pacing 意识、社会热点注入
- **M6 Writer**：AI 写作者——事件日志 → 网文转写、tool call、分割逻辑
- **M7 API**：FastAPI REST endpoints + SSE 实时推送
- **M8 Frontend**：React（角色关系图、剧情图、控制面板、对话面板、阅读页）

## 核心机制

### 模拟循环
- tick = 1 小时，所有角色并发行动
- 执行顺序：导演先跑 → 角色并发（权重 + DPO 随机重排避免惊群）
- 权重系统：出场次数决定 LLM 调用频率，低权重跳过，极低权重冻结

### 角色系统
- 完全自治 agent，99% 设定 AI 生成
- Context：人设（可缓存）→ 记忆（图查询）→ 感知（当前 tick）
- Action 输出：结构化 JSON（SPEAK/THINK/ACT/MOVE_TO/REACT/DO_NOTHING）
- 内心独白永远隔离，不跨角色可见
- 鉴权：`can_perform()` 前置条件检查

### 互动 Budget
- 同地点角色主动触发互动 → 多轮对话循环（max_limit 可配）
- 双方轮流调用，内心隔离
- 互动结束 → 小模型提取关系 delta → 写入图

### 导演
- 最高权重，每 tick 最先跑，永不被杀
- 只看当前盯着的角色日志，可通过 tool call 查其他
- 多导演并行，碰撞不仲裁
- Pacing 意识内置于 prompt
- 社会热点注入（API + 手动）

### 存储
- 单一 SQLite（可升 PostgreSQL）
- 每 tick 完整快照（非差异）
- 支持 fork / reset / replay

## 实施路线图摘要（详见 `docs/04-build.md`）

| Phase | 里程碑 |
|---|---|
| P0 | 核心 tick 循环 PoC：5 角色自主行动 10 tick |
| P1 | 互动 + 感知 + 空间：角色能互相看见、对话、关系更新 |
| P2 | 中央调度器 + 多 provider：50+ 角色高效运行 |
| P3 | 导演系统：AI 主动制造剧情 |
| P4 | 写作者 + 网文输出：事件 → 可读网文 |
| P5 | 世界初始化 + ckpt：零输入启动 + 时间线管理 |
| P6 | 前端：React 节点图 + 控制面板 |
| P7 | 多层空间 + 大规模：300 角色 + 多导演 |
| P8+ | 实战写一本小说 |

**当前阶段**：P0 进行中（D1–D6 完成，下一步 D7: Tick Scheduler）。

## 开发约定

- **所有 LLM 调用**记 prompt + response + token + latency 到 SQLite（`llm_logs` 表）
- **结构化 JSON 输出**：角色 action 必须是合法 JSON，LLM 输出异常时 retry/repair
- **每 tick 快照**：完整状态落盘，保证崩溃恢复和时间线 fork
- **Prompt 缓存**：角色人设放 context 最前部保证缓存命中

## 参考代码（`external/mirofish`，只读）

MiroFish 值得借鉴的模式：
- `backend/app/services/simulation_runner.py` — 子进程启动 + `start_new_session=True`
- `backend/app/services/simulation_config_generator.py` — `_call_llm_with_retry` + `_fix_truncated_json`
- `backend/app/services/oasis_profile_generator.py` — 并行角色生成（ThreadPoolExecutor）
- `frontend/src/components/` — 前端布局参考（设置/图/输入分离）
