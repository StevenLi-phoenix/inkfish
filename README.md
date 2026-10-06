# INKFISH

> 自主角色模拟引擎——AI 全自动写网络小说

> [!WARNING]
> **Unpolished（未打磨）**：这是早期实验项目，目前只完成 P0 概念验证。接口、数据格式和文档都可能不经通知就改动，部分文档可能落后于代码，也还没有 LICENSE。欢迎围观和试玩，但请不要在生产环境里依赖它。

INKFISH 不是协作写作工具。它是一台完全自主的小说机器：每个角色都是独立的 AI Agent，在同一个世界里感知环境、做决策、行动、互动，引擎把这些事件流转写成网络小说章节。作者不参与写作——作者是"天道"，通过节点图和对话框向 AI 导演下指令，监视并调整故事走向。零输入即可运行：没有任何前提时，引擎自动生成世界和角色。

---

## 项目状态

**当前**：P0 完成（核心 tick 循环 PoC）。5 个角色在 Coffee Shop 自主行动 10 个 tick，全部合法 action JSON，快照可 reset 到任意时间点。

**下一步**：P1（互动 + 感知 + 多地点空间）。

完整路线图见 `docs/04-build.md`。

---

## 快速开始

### 依赖

- Python 3.12+
- `uv` 包管理器（`pip install uv` 或 `brew install uv`）
- DeepSeek API key（[platform.deepseek.com](https://platform.deepseek.com) 申请）

### 安装

```bash
git clone <repo>
cd inkfish
echo "DEEPSEEK_API_KEY=sk-xxx" > .env   # 替换为真实 key
uv sync
```

### 跑一次模拟

```bash
# 初始化世界（5 角色 + 1 咖啡馆，写入 tick 0 快照）
uv run inkfish seed

# 跑 10 个 tick（约 25-40 分钟，~$0.008 LLM 成本）
uv run inkfish run --ticks 10

# 列出所有快照
uv run inkfish list-snapshots

# 回滚到 tick 5
uv run inkfish reset 5

# 从 tick 5 继续 5 个 tick（产生全新故事支线）
uv run inkfish run --from-tick 5 --ticks 5
```

### 启动 API server

```bash
uv run inkfish serve --port 8000
# 浏览器打开 http://127.0.0.1:8000/docs 查看 OpenAPI 文档
```

---

## CLI 命令

| 命令 | 作用 |
|---|---|
| `inkfish seed [--seed-path PATH]` | 从 JSON 初始化世界到 tick 0 |
| `inkfish run [--ticks N] [--from-tick T]` | 跑 N 个 tick（默认 10） |
| `inkfish reset TICK_ID` | 回滚到指定 tick（`llm_logs` 保留，不删） |
| `inkfish list-snapshots` | 列出所有快照 |
| `inkfish serve [--host H] [--port P]` | 启动 FastAPI dev server |

---

## REST API 端点（9 个）

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/simulation/start` | 启动模拟（P0 同步阻塞） |
| `POST` | `/simulation/pause` | 暂停模拟（P0 占位） |
| `POST` | `/simulation/reset` | 重置到指定 tick |
| `GET` | `/tick` | 最新 tick 完整状态 + actions |
| `GET` | `/tick/{id}` | 指定 tick 状态 + actions |
| `GET` | `/snapshot` | 列出所有快照 |
| `GET` | `/character` | 当前所有角色 |
| `GET` | `/character/{id}` | 单角色详情 + 最近 N 条 action |
| `GET` | `/health` | 服务健康 + 最新 tick 编号 |

完整 schema 见 `http://127.0.0.1:8000/docs` 或 `src/inkfish/api/`。

---

## 项目结构

```
inkfish/
├── src/inkfish/
│   ├── config.py              # M0 配置（Settings + SimConfig）
│   ├── storage/
│   │   ├── db.py              # SQLite engine + WAL pragma + init_db
│   │   ├── models.py          # M1 SQLAlchemy 2.0 ORM（composite PK 快照）
│   │   ├── snapshot.py        # SnapshotManager（save / reset / list / load）
│   │   └── repository.py      # CRUD 封装
│   ├── character/
│   │   ├── schema.py          # M3 CharacterAction Pydantic + ActionType enum
│   │   ├── context.py         # build_user_prompt()（prompt 拼装）
│   │   └── validator.py       # parse_action_json() + _fix_truncated_json
│   ├── llm/
│   │   ├── deepseek.py        # M4 DeepSeekClient（openai SDK + base_url）
│   │   └── retry.py           # call_with_retry（3 次 + temp decay + JSON repair + log）
│   ├── tick/
│   │   └── scheduler.py       # run_tick / run_simulation（P0 同步顺序）
│   ├── world/
│   │   ├── seed_loader.py     # world.json → WorldState + DB tick 0
│   │   └── state.py           # WorldState 内存视图
│   └── api/
│       ├── main.py            # FastAPI app（5 router 挂载）
│       ├── routers/           # simulation / tick / snapshot / character / health
│       └── schemas.py         # API 请求/响应 Pydantic
├── data/seed/world.json       # 5 角色 + 1 地点种子（ENFP/INTP/ESTP/ISFJ/ENTJ）
├── prompts/character_system.txt  # 角色系统 prompt（改动会使 DeepSeek 缓存失效）
├── tests/
│   ├── unit/                  # 173 单元测试（全 mock，秒级）
│   └── live/                  # killer test（真实 DeepSeek，~45 分钟）
├── docs/                      # 设计 / 计划 / 每日评审
├── inkfish.toml               # 运行时配置
└── pyproject.toml             # uv 管理，Python 3.12
```

---

## 开发

### 测试

```bash
# 单元测试（mock，< 1 秒）
uv run pytest tests/unit/

# live killer test（真实 DeepSeek，~45 分钟，约 $0.016）
uv run pytest tests/live/test_killer_reset.py -v -s

# 带覆盖率
uv run pytest --cov=src/inkfish tests/unit/
```

### 静态检查

```bash
uv run ruff check src/ tests/
uv run mypy src/inkfish
uv run black src/ tests/
```

### 配置

- `inkfish.toml` — 运行时参数（tick 配置 / 模型 / retry / 成本控制等）
- `.env` — `DEEPSEEK_API_KEY`（gitignored）

---

## 文档

| 文件 | 内容 |
|---|---|
| `docs/03-design.md` | **权威系统设计**（M0-M8 九模块、核心机制） |
| `docs/04-build.md` | 实施路线图（P0-P8 阶段切片） |
| `docs/plans/P0-plan.md` | P0 详细实施计划（含模块签名、快照设计、风险） |
| `docs/reviews/P0-D*.md` | P0 每日交付审查（D1-D12） |

---

## P0 完成情况

- ✅ 5 角色跑 10 tick，每 tick 产 5 个合法 action JSON（50/50 全通过 Pydantic 校验）
- ✅ 快照可 reset 回任意 tick（`llm_logs` 跨 reset 保留）
- ✅ Killer test 100% 通过：Set A / Set B 各 25 条 action，A/B content 差异 **100%（25/25）**
- ✅ 173 单元测试 + 1 live killer test 全绿
- ✅ FastAPI 9 个 REST 端点全通（httpx TestClient 验证）
- ✅ 总 LLM 成本 ~$0.008 / 10-tick run；overall cache 命中 ~59%；tick 1-2 命中 ~93%

详见 `docs/reviews/P0-D11.md` 和 `docs/reviews/P0-D10-analysis.md`。

---

## 已知问题（P1 待办）

- **INTP/ISFJ 类角色长 THINK content 偶发截断**（Phase 1 fallback rate ~3%）：v4-pro reasoning token 消耗压缩 content 预算。候选修复：`content` max_length 收紧到 500 或 system prompt 加"content 不超过 80 字"。
- **5 角色同地点**：P0 所有角色都在 Coffee Shop，缺少 `MOVE_TO` 和多点感知，行为多样性受限。P1 引入多地点后改善。
- **Prompt cache tick 3+ 命中率从 93% 降至 54%**：perception block 随 tick 变化，不完全稳定。P1/P5 fork 设计需注意。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python 3.12 + uv |
| 后端 | FastAPI 0.115 + Uvicorn |
| ORM | SQLAlchemy 2.0（typed `Mapped[]`） |
| 存储 | SQLite / 可无痛升级 PostgreSQL |
| LLM | DeepSeek v4-pro（openai SDK + base_url） |
| 测试 | pytest + respx + httpx TestClient |
| CLI | typer |
| 格式化 | black + ruff + mypy |

---

## License

TBD
