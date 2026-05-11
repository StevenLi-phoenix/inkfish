# INKFISH P0 — 实施计划

## Context

INKFISH 处于设计阶段，仓库目前只有 `docs/`、`external/mirofish/`（只读 submodule，参考实现）、`CLAUDE.md`、`.env`（已含 `DEEPSEEK_API_KEY`），无任何生产代码。

`docs/03-design.md` 是权威系统设计（M0–M8 九模块、tick 循环、schema、context 拼装规则），`docs/04-build.md` 是分阶段路线图（P0–P8）。本计划实施 **P0：核心 Tick 循环 PoC**，即 04-build.md 中的第一阶段：

> 5 个角色在同一个世界里自主行动 10 个 tick，验证基础模拟循环可行。

P0 的产出不只是一个 demo——它落地的 schema（`Character`/`CharacterAction`/snapshots/llm_logs）、LLM retry+JSON-repair 模式、快照机制都会被 P1–P7 直接复用。**P0 的决策不能轻易改**，所以本计划重在确认 schema 形状和分层边界。

## Locked Decisions（已与用户确认）

| 决策点 | 选择 | 理由 |
|---|---|---|
| DeepSeek 模型 | `deepseek-v4-pro` | 2026/5/31 前有 75% 折扣；P0 用得起强模型可以排除 R1（persona 不像人）混淆来源 |
| FastAPI 范围 | 完整 REST scaffolding（placeholder endpoints） | 提前为 P6 前端对接；P0 内增加约 1.5 天工作量 |
| Killer test | Default 跑 live LLM | 不加 env gating；CI 直接调真实 DeepSeek（~¥0.5/run），验证强度高 |

## 目录结构

```
/Users/lishuyu/Codes/inkfish/
├── pyproject.toml              # uv 管理，Python 3.12
├── inkfish.toml                # 运行时配置（tick / model / retry）
├── .env                        # 已存在
├── .python-version             # "3.12"
├── uv.lock                     # 提交到 repo
├── src/inkfish/
│   ├── __init__.py
│   ├── __main__.py             # `python -m inkfish` → CLI
│   ├── cli.py                  # typer: run / reset / list-snapshots / seed / serve
│   ├── config.py               # M0: Settings (.env) + SimConfig (toml)
│   ├── storage/
│   │   ├── db.py               # engine + WAL pragma + init_db
│   │   ├── models.py           # M1: SQLAlchemy 2.0 ORM
│   │   ├── snapshot.py         # SnapshotManager
│   │   └── repository.py       # CRUD 封装
│   ├── character/
│   │   ├── schema.py           # M3: Pydantic CharacterAction + Character dataclass
│   │   ├── context.py          # build_user_prompt()
│   │   └── validator.py        # parse_action_json() + _fix_truncated_json
│   ├── llm/
│   │   ├── deepseek.py         # M4: DeepSeekClient (openai SDK + base_url)
│   │   └── retry.py            # call_with_retry — 3-attempt + temp decay + JSON repair + log
│   ├── tick/
│   │   └── scheduler.py        # run_tick / run_simulation（同步顺序）
│   ├── world/
│   │   ├── seed_loader.py
│   │   └── state.py            # WorldState 内存视图
│   └── api/
│       ├── main.py             # FastAPI app
│       ├── routers/
│       │   ├── simulation.py   # POST /simulation/start /pause /reset
│       │   ├── tick.py         # GET /tick/{id} /tick (latest)
│       │   ├── snapshot.py     # GET /snapshots, POST /reset/{tick_id}
│       │   ├── character.py    # GET /characters /characters/{id}
│       │   └── health.py       # GET /health
│       └── schemas.py          # API 请求/响应 Pydantic
├── data/
│   ├── seed/world.json         # 5 角色 + 1 地点的硬编码种子
│   └── inkfish.db              # SQLite（gitignored）
├── prompts/
│   └── character_system.txt    # ~150 token 系统 prompt
└── tests/
    ├── conftest.py             # tmp_db / fake_llm / sample_world fixtures
    ├── unit/                   # 全 mock，CI 默认跑
    └── live/
        └── test_killer_reset.py  # default live，需要 DEEPSEEK_API_KEY
```

**为什么 `src/` layout**：避免工作目录 shadow imports；为 PostgreSQL/Docker 打包预留 wheel 化空间。
**为什么 `prompts/` 在 Python 外**：保证代码改动不影响 DeepSeek 自动前缀缓存的 hash。
**为什么 `data/seed/` 分离**：killer test 需要每次从字节相同的种子启动。
**无 `alembic/`**：P0 schema 由 `Base.metadata.create_all()` 创建；P2 引入 LLM Gateway 字段时再迁移到 alembic。

## Dependencies (`pyproject.toml`)

运行时：
- `fastapi==0.115.*` — REST scaffolding
- `uvicorn[standard]==0.32.*` — ASGI server
- `sqlalchemy==2.0.*` — ORM (typed `Mapped[]`)
- `openai==1.55.*` — DeepSeek OpenAI-compatible client
- `pydantic==2.9.*` — `CharacterAction` 校验
- `pydantic-settings==2.6.*` — `.env` 类型化加载
- `tenacity==9.0.*` — 429 重试 + jittered backoff
- `typer==0.13.*` — CLI（比 argparse 清爽，无运行成本）
- `python-dateutil==2.9.*` — sim_time 处理

开发：
- `pytest==8.3.*`, `pytest-asyncio==0.24.*`（P2 用，提前装）
- `pytest-cov==6.0.*`
- `respx==0.21.*` — mock httpx for unit tests
- `httpx==0.27.*` — TestClient
- `black==24.10.*`, `ruff==0.7.*`, `isort==5.13.*`, `mypy==1.13.*`

**版本策略**：minor 锁定，patch 由 `uv.lock` 解析；`uv.lock` 提交到 repo。

## 关键模块签名

### M0 `src/inkfish/config.py`
```python
class Settings(BaseSettings):
    deepseek_api_key: SecretStr
    db_url: str = "sqlite:///data/inkfish.db"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@dataclass(frozen=True)
class SimConfig:
    tick_interval_hours: int = 1
    model: str = "deepseek-v4-pro"
    max_retries: int = 3
    temperature: float = 0.7
    max_tokens: int = 800
    log_level: str = "INFO"
    # P0 之外的字段保留默认（min_weight / dpo_sigma / 等）

def load_config(toml_path: Path = Path("inkfish.toml")) -> tuple[Settings, SimConfig]: ...
```

### M1 Storage — `src/inkfish/storage/models.py`

Composite PK `(id, tick_id)` 的快照方案，每 tick 写一份完整状态。理由见 §快照设计。

```python
class CharacterRow(Base):
    __tablename__ = "characters"
    id: Mapped[str] = mapped_column(primary_key=True)
    tick_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]; mbti: Mapped[str]; age: Mapped[int]
    background: Mapped[str]; appearance: Mapped[str]; personality: Mapped[str]
    current_location: Mapped[str]; current_mood: Mapped[str]
    routine: Mapped[dict] = mapped_column(JSON)
    weight: Mapped[float]; alive: Mapped[bool]
    death_summary: Mapped[str | None]
    appearance_count: Mapped[int]; last_active_tick: Mapped[int]; skipped_ticks: Mapped[int]

class ActionRow(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(primary_key=True)         # uuid4
    tick_id: Mapped[int]; character_id: Mapped[str]
    action_type: Mapped[str]; content: Mapped[str]
    target: Mapped[str | None]; mood: Mapped[str]
    inner_thought: Mapped[str]; triggers_interaction: Mapped[bool]
    created_at: Mapped[datetime]

class LocationRow(Base):
    __tablename__ = "locations"
    id: Mapped[str] = mapped_column(primary_key=True)
    tick_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]; description: Mapped[str]
    present_characters: Mapped[list] = mapped_column(JSON)
    connected_to: Mapped[list] = mapped_column(JSON)

class SnapshotRow(Base):
    __tablename__ = "snapshots"
    tick_id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime]; parent_tick_id: Mapped[int | None]
    char_count: Mapped[int]; action_count: Mapped[int]

class LLMLogRow(Base):                                         # 全局规约：所有 LLM 调用必落
    __tablename__ = "llm_logs"
    id: Mapped[str] = mapped_column(primary_key=True)
    tick_id: Mapped[int]; character_id: Mapped[str | None]
    provider: Mapped[str]; model: Mapped[str]
    prompt: Mapped[str]; response: Mapped[str]
    prompt_tokens: Mapped[int]; response_tokens: Mapped[int]
    cached_tokens: Mapped[int]                                 # prompt_cache_hit_tokens
    cost_usd: Mapped[float]; latency_ms: Mapped[int]
    finish_reason: Mapped[str]; error: Mapped[str | None]
    created_at: Mapped[datetime]
```

`init_db()` 启用 `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL`。

### `src/inkfish/storage/snapshot.py`
```python
class SnapshotManager:
    def save_snapshot(self, world: WorldState, tick_id: int) -> None: ...
    def reset(self, to_tick_id: int) -> None: ...
    def list_snapshots(self) -> list[SnapshotInfo]: ...
    def load_world(self, tick_id: int) -> WorldState: ...
```

`reset(to_tick_id)` 单事务执行：
```sql
DELETE FROM actions     WHERE tick_id > :t;
DELETE FROM characters  WHERE tick_id > :t;
DELETE FROM locations   WHERE tick_id > :t;
DELETE FROM snapshots   WHERE tick_id > :t;
-- llm_logs 不删（保留成本/调试历史，跨 reset 实验对比用）
```

### M3 Character — `src/inkfish/character/schema.py`
```python
class ActionType(str, Enum):
    SPEAK = "SPEAK"; THINK = "THINK"; ACT = "ACT"
    MOVE_TO = "MOVE_TO"; REACT = "REACT"; DO_NOTHING = "DO_NOTHING"

class CharacterAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    character_id: str
    tick_id: int
    action_type: ActionType
    content: str = Field(max_length=2000)
    target: str | None = None
    mood: str
    inner_thought: str = ""
    triggers_interaction: bool = False

    @model_validator(mode="after")
    def _check_target(self) -> "CharacterAction":
        # SPEAK / MOVE_TO / REACT 必须有 target；THINK / DO_NOTHING 必须无 target
        ...
```

### `src/inkfish/character/validator.py`
```python
def _fix_truncated_json(raw: str) -> str:
    # 移植 mirofish simulation_config_generator.py:483-499
    # 闭合未配对的 {} []，去除控制字符 \x00-\x1f
    ...

def parse_action_json(raw: str, character_id: str, tick_id: int) -> CharacterAction | None:
    # raw → _fix_truncated_json → json.loads → CharacterAction(**)
    # 失败返回 None，调用方决定是 retry 还是 fallback
    ...

def fallback_do_nothing(character_id: str, tick_id: int, mood: str) -> CharacterAction: ...
```

### M4 LLM — `src/inkfish/llm/deepseek.py`
```python
class LLMResult(NamedTuple):
    content: str
    prompt_tokens: int
    response_tokens: int
    cached_tokens: int            # prompt_cache_hit_tokens
    cost_usd: float
    latency_ms: int
    finish_reason: str

class DeepSeekClient:
    def __init__(self, api_key: SecretStr, model: str = "deepseek-v4-pro"):
        self.client = OpenAI(api_key=api_key.get_secret_value(),
                             base_url="https://api.deepseek.com")
        self.model = model

    def complete_json(self, system: str, user: str, *,
                      temperature: float = 0.7,
                      max_tokens: int = 800) -> LLMResult:
        # response_format={"type": "json_object"}；user 中已包含 "json"
        ...
```

### `src/inkfish/llm/retry.py`
```python
def call_with_retry(
    client: DeepSeekClient,
    system: str,
    user: str,
    character_id: str,
    tick_id: int,
    *,
    on_log: Callable[[LLMLogRow], None],
    max_attempts: int = 3,
) -> CharacterAction:
    """
    1. Attempt 1: temp=0.7, 原 user prompt
    2. Attempt 2: temp=0.6, user prefix 加 "上次响应非法 JSON: {err}. 只输出 JSON."
    3. Attempt 3: temp=0.5, 同 #2
    429 → tenacity wait_random_exponential(min=1, max=5), stop_after_attempt(5)
    任一 attempt 解析成功 → 返回 CharacterAction
    全失败 → 返回 fallback_do_nothing()
    每次 attempt 必落 llm_logs（含 error 字段，是否 fallback）
    """
```

### Tick — `src/inkfish/tick/scheduler.py`
```python
def run_tick(tick_id: int, world: WorldState, client: DeepSeekClient,
             repo: Repository, snapshots: SnapshotManager,
             cfg: SimConfig) -> list[CharacterAction]:
    """
    P0：同步顺序循环 5 个角色。
    for c in world.characters:
        system = read_system_prompt()
        user = build_user_prompt(c, world, tick_id, sim_time)
        action = call_with_retry(client, system, user, c.id, tick_id, on_log=repo.log_llm)
        repo.save_action(action)
        # 更新 c.appearance_count / last_active_tick
    snapshots.save_snapshot(world, tick_id)
    return actions
    """

def run_simulation(n_ticks: int, start_tick: int = 0, ...) -> None: ...
```

无 async/并发——P0 故意保持单线程顺序，便于调试和确定性。P2 才上 `asyncio.gather`。

### CLI — `src/inkfish/cli.py`
```python
app = typer.Typer()
@app.command() def seed(): ...                # data/seed/world.json → tick_0
@app.command() def run(ticks: int = 10, from_tick: int | None = None): ...
@app.command() def reset(tick_id: int): ...
@app.command() def list_snapshots(): ...
@app.command() def serve(host: str = "127.0.0.1", port: int = 8000): ...  # uvicorn
```

### API — `src/inkfish/api/main.py`
```python
app = FastAPI(title="INKFISH", version="0.1.0")
app.include_router(health.router, prefix="/health")
app.include_router(simulation.router, prefix="/simulation")
app.include_router(tick.router, prefix="/tick")
app.include_router(snapshot.router, prefix="/snapshot")
app.include_router(character.router, prefix="/character")
```

P0 端点（结构完整，body 可以是 stub but 返回真实数据）：
- `GET /health` → `{status, phase, sim_state, latest_tick}`
- `POST /simulation/start` (body: `{n_ticks: int, premise: str | null}`) → 启动后台任务，返回 task_id
- `POST /simulation/pause` → 设置暂停 flag（P0 单线程，下一 tick 边界生效）
- `POST /simulation/reset` (body: `{tick_id: int}`) → 调用 `SnapshotManager.reset`
- `GET /tick` → 最新 tick 完整状态
- `GET /tick/{id}` → 指定 tick 状态 + actions
- `GET /snapshots` → list
- `GET /characters` → 当前所有角色
- `GET /characters/{id}` → 单角色详情 + 最近 N action

**P0 不做**：SSE（推到 P6 前端阶段）、auth、rate limiting、CORS（dev 模式宽开）。

## 快照设计（关键决策）

**选 composite PK `(id, tick_id)`，每 tick 复制完整 character/location 行**——不是 JSON blob，不是 history 表。

理由：
1. P1 感知规则要查 "tick T 时在 location X 的所有 character" — SQL 直接 `WHERE tick_id=T AND current_location=X`，JSON blob 要反序列化全表
2. P3 导演 tool `query_graph` 要跨 tick 范围查 — 用 SQL window function 一行搞定
3. P5 PostgreSQL 迁移时 composite PK + 索引扩展容易；JSON blob 需要 GIN 索引
4. mirofish 走的也是行级状态，不是 blob

**储存成本**（不构成 P0 问题）：5 char × 10 tick × ~1KB ≈ 50KB。P7 300 char × 1000 tick ≈ 300MB——SQLite 单文件 GB 级毫无压力，且 PostgreSQL 无上限。R5 风险已经在 04-build.md §3 列出，缓解策略已定。

**reset** 用单事务 `DELETE WHERE tick_id > :t`，由 SQLite WAL mode 保证原子。`llm_logs` 不删（成本审计跨 reset 实验对比的需要）。

## 实施步骤（12 个工作日）

按依赖顺序，每步包含验证标准。完成一步才进下一步。

| Day | 步骤 | 完成判定 |
|---|---|---|
| **D1** | `pyproject.toml` + `uv sync` + 目录 + ruff/black/mypy 配置 + `tests/conftest.py` 空骨架 + `pytest -q` 跑通 | 空仓库一键 setup |
| **D1.5** | `config.py` + `inkfish.toml` + `test_config.py` | Settings 从 .env 读 key，SimConfig 从 toml 读，类型正确 |
| **D2** | `storage/models.py` + `storage/db.py` (`init_db` + WAL) + `test_storage_models.py`（round-trip 插入查询，composite PK 行为） | 5 表创建，写入读取正常 |
| **D3** | `storage/snapshot.py` + `storage/repository.py` + `test_snapshot_reset.py`（不调 LLM，用 fake world fixture，验证 reset(N) 删除 > N 行） | reset 行为正确，llm_logs 保留 |
| **D4** | `character/schema.py`（CharacterAction Pydantic）+ `character/validator.py`（含移植的 `_fix_truncated_json`）+ `test_action_validator.py`（参数化：合法/截断/控制字符/缺字段/extra forbid） | validator 对垃圾 LLM 输出鲁棒 |
| **D5** | `llm/deepseek.py` + `llm/retry.py` + `test_deepseek_client.py`（respx mock 429 → 200，验证重试和 log 写入）+ **1 个 live smoke**（无 mock，调真 API 验证 v4-pro 可达） | 单次调用产出合法 `CharacterAction` + log row |
| **D6** | `world/seed_loader.py` + `data/seed/world.json`（5 角色 + 1 地点 "Coffee Shop"——刻意选 MBTI 差异大的 persona：ENFP/INTP/ESTP/ISFJ/ENTJ）+ `world/state.py` | `inkfish seed` 写入 tick_0 |
| **D7** | `character/context.py`（build_user_prompt）+ `prompts/character_system.txt` + `test_context_assembly.py`（golden snapshot 测试，保证 block [1] 字节稳定） | Prompt 给定输入字节相同 |
| **D8** | `tick/scheduler.py`（同步循环）+ `cli.py`（typer 命令）+ `__main__.py` | `inkfish seed && inkfish run --ticks 3` 产 15 actions |
| **D9** | `api/main.py` + 5 个 router + `api/schemas.py` + FastAPI TestClient 测试 | `inkfish serve` 启动，9 个 endpoint 全通 |
| **D10** | 端到端 10-tick 完整跑通 + 观察 `cached_tokens`（第 2 tick 起应 > 0）+ 必要时调 prompt | 50 valid actions + 10 snapshots + cache hit 命中 |
| **D11** | `tests/live/test_killer_reset.py`（default live，无 env gating） | 见下 §验证 |
| **D12** | README（运行/测试/CLI 用法）+ 总结 + commit | 文档完成，全测试绿 |

每天结束时 commit。

## 验证（§Killer Test 详）

`tests/live/test_killer_reset.py`：

1. 调 `inkfish seed`（清空 DB，从 `data/seed/world.json` 重新加载）
2. `run_simulation(n_ticks=10, start_tick=0)`
3. 读 `actions WHERE tick_id IN (6..10)` → set A（25 条）
4. `SnapshotManager.reset(to_tick_id=5)` + 验证 tick > 5 的 character/action/location/snapshot 行都被删
5. `run_simulation(n_ticks=5, start_tick=5)`
6. 读 `actions WHERE tick_id IN (6..10)` → set B（25 条）
7. 断言：
   - `len(B) == 25`
   - 每一个 B action 都通过 `CharacterAction` Pydantic 校验（实际上 retry 层已保证，这步是契约重申）
   - 对每个 character：A 和 B 的 `content` 字段在 ≥ 3/5 tick 上 byte-不同（非确定性证据）
   - **persona 一致性**（软断言，3 次重跑接受 ≥ 60% 通过）：刻意选的 persona 应在 action 分布上体现差异——例如 INTP 角色 `THINK + DO_NOTHING` ≥ 2/5 tick，ESTP 角色 `SPEAK + ACT` ≥ 3/5 tick。失败不抛 error 但 log 警告并触发 04-build.md Q1（"persona 多长能让行为真像人？"）的迭代

成本评估：5 char × 10 tick × 2 run × ~500 token = ~50K token ≈ ¥0.6/次 killer test 跑（v4-pro 折扣价）。

## 风险

| # | 风险 | 缓解 |
|---|---|---|
| **R1** | persona 一致性软断言失败——LLM 输出"通用 NPC" | 种子 persona 精心写差异化（每个 400-600 字 background + 具体行为示例）；失败则 D12 slack 调到 ~800 字 |
| **R2** | DeepSeek JSON 模式偶尔丢字段或加尾随逗号 | `_fix_truncated_json` + 3-attempt retry + DO_NOTHING fallback。监控 `llm_logs.error` 比例，目标 < 5%；超阈值调 retry 策略 |
| **R3** | `cached_tokens` 没命中（block [1] 不稳定） | `test_context_assembly.py` golden snapshot 强制 byte 稳定；D10 手动看头两 tick 的 log 确认 |
| **R4** | killer test live 调用偶发 5xx | tenacity 已处理；如果真 LLM 不稳定，记录失败 tick，重跑当前 tick 而不是整段重试 |
| **R5** | FastAPI scaffolding 1.5 天超时 | D9 出现超时立即砍：只保留 health/snapshot/tick 三个 router，其他放 stub 返回 501 |
| **R6** | uv 环境跨机器漂移 | `.python-version` + 提交 `uv.lock`；CLAUDE.md 已强制 `source .venv/bin/activate` |

## 关键文件清单（修改这里需要谨慎）

- `src/inkfish/storage/models.py` — schema 决策（composite PK）；改这里会传染到 snapshot / repository / scheduler / API schemas，P1+ 改动成本指数级
- `src/inkfish/character/schema.py` — `CharacterAction` 是 LLM ↔ 模拟器之间的唯一契约，整个 P1+ 互动/感知都消费这个类型
- `src/inkfish/llm/retry.py` — JSON repair + retry + log；M4 中央 Gateway 的最小版本，P2 会扩展成全功能 Gateway，retry/repair 模式保留
- `src/inkfish/storage/snapshot.py` — killer test 通不过往往是这里 bug
- `prompts/character_system.txt` — 改一个字就 cache 失效；改动需 commit 注明并观察下次 run 的 `cached_tokens`

## 复用 mirofish 的具体行号

参考实现已勘察清楚（read-only）：

- `external/mirofish/backend/app/services/simulation_config_generator.py:434-481` → 3-attempt retry + temperature decay 模式直接抄到 `inkfish/llm/retry.py`
- `external/mirofish/backend/app/services/simulation_config_generator.py:483-533` → `_fix_truncated_json` 和 `_try_fix_config_json` 直接抄到 `inkfish/character/validator.py`（最小修改：去掉对 mirofish-specific config 字段的硬编码）
- `external/mirofish/backend/app/services/oasis_profile_generator.py:851-1014` → 并行角色生成的 ThreadPoolExecutor 模式 **P5 才用**，不在 P0 范围
- `external/mirofish/backend/app/services/simulation_runner.py:438-448` → subprocess + `start_new_session=True` **P6+ 用**（前端启停模拟），P0 单进程

## 完成判据（P0 Done）

按 04-build.md 原文 + 用户决策细化：

- [ ] `inkfish seed && inkfish run --ticks 10` 一键完成，无 unhandled exception
- [ ] DB 中 `actions` 表 50 条记录，全部通过 `CharacterAction` Pydantic 校验
- [ ] `snapshots` 表 10 条，每条对应一个完整状态
- [ ] `inkfish reset 5 && inkfish run --ticks 5` 后 `actions` 表正好回到 50 条，但 tick 6-10 是新内容
- [ ] `llm_logs` 表完整记录每次调用（含 cached_tokens、cost_usd、latency_ms）
- [ ] `inkfish serve` 启动 FastAPI，9 个 endpoint 全通（用 httpx TestClient 验证）
- [ ] `pytest tests/` 全绿（含 unit + live killer test）
- [ ] README 文档完整，新机器能按文档 setup 并跑通

完成后切到 P1（互动 + 感知 + 空间），不在本计划范围。
