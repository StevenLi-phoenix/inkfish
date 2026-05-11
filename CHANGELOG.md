# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- INKFISH P0 PoC: 5 自治角色在咖啡馆并发跑 10 tick，每 tick 输出合法 action JSON，支持 reset/fork。详细路线见 docs/04-build.md。
  Files: src/inkfish/**, tests/**, docs/plans/P0-plan.md
- M0 Config 模块（Settings + SimConfig），从 .env + inkfish.toml 加载。
  Files: src/inkfish/config.py, inkfish.toml
- M1 Storage 层：SQLAlchemy 2.0 ORM (CharacterRow / ActionRow / LocationRow / SnapshotRow / LLMLogRow) with composite PK，WAL pragma，SnapshotManager (save / reset / load_world / list) + Repository CRUD facade。
  Files: src/inkfish/storage/models.py, src/inkfish/storage/db.py, src/inkfish/storage/snapshot.py, src/inkfish/storage/repository.py
- M3 Character schema：Pydantic CharacterAction + ActionType enum + target consistency validator + `_fix_truncated_json` (移植自 mirofish) + `fallback_do_nothing`。
  Files: src/inkfish/character/schema.py, src/inkfish/character/validator.py
- M3 Character context 拼装：build_persona_block / build_memory_block / build_perception_block / build_user_prompt + 系统 prompt 文件。
  Files: src/inkfish/character/context.py, prompts/character_system.txt
- M4 LLM Gateway：DeepSeekClient (OpenAI 兼容 base_url + tool calling) + `call_with_retry` (3-attempt + 温度衰减 + length-aware expand + tenacity 透明 retry 429/timeout)。
  Files: src/inkfish/llm/deepseek.py, src/inkfish/llm/retry.py
- Tick scheduler：run_tick + run_simulation，warmup-then-concurrent dispatch (asyncio.gather)，动态 tool_schema 注入 target enum。
  Files: src/inkfish/tick/scheduler.py
- World seed loader + 5 个差异化 MBTI 角色（ENFP 林夏 / INTP 赵默 / ESTP 陈烈 / ISFJ 王婉 / ENTJ 李锐）+ 咖啡馆地点。
  Files: src/inkfish/world/seed_loader.py, src/inkfish/world/state.py, data/seed/world.json
- M7 API：FastAPI scaffolding，9 个 REST endpoints（health/simulation/tick/snapshot/character），CORS 开放，Depends() 依赖注入。
  Files: src/inkfish/api/main.py, src/inkfish/api/routers/*.py, src/inkfish/api/schemas.py, src/inkfish/api/deps.py
- typer CLI：seed / run / reset / list-snapshots / serve / version 6 命令。
  Files: src/inkfish/cli.py, src/inkfish/__main__.py
- 完整测试套件：174 unit tests（mock + respx）+ 1 live killer test（reset(5) + 重跑 5 ticks，验证 100% content 差异 + Pydantic 全合法）。
  Files: tests/unit/*.py, tests/live/test_killer_reset.py, tests/conftest.py
- 项目骨架：pyproject.toml (uv) + Python 3.12 + ruff/black/mypy/isort 配置 + uv.lock。
  Files: pyproject.toml, .python-version, uv.lock
- 文档：每日 review (docs/reviews/P0-D1.md 至 P0-D11.md + P0-D12.md) + 完整 P0 plan + 动线复盘 (P0-D11-storyline.md) + hotfix 文档 (P0-D8-hotfix.md, P0-hotfix-v2.md) + README。
  Files: docs/plans/P0-plan.md, docs/reviews/P0-D*.md, docs/reviews/P0-hotfix-v2.md, docs/reviews/P0-D11-storyline.md, README.md
- 完整状态分析脚本 (`scripts/analyze_d10.py`)：7-section 报告（aggregate stats / finish_reason / cache / personality / schema validity / qualitative samples / verdict）。
  Files: scripts/analyze_d10.py

### Changed
- LLM 调用从同步顺序改为 **async + 并发 with warmup**（首角色 sequential 建立 prefix cache，余下 asyncio.gather）。Wall-clock 5min → 1min for 2 ticks，cache 命中 0% → 95.6%。
  Files: src/inkfish/llm/deepseek.py, src/inkfish/llm/retry.py, src/inkfish/tick/scheduler.py, src/inkfish/cli.py, src/inkfish/api/routers/simulation.py
- LLM 调用从 `response_format: json_object` 改为 **tool calling with strict enum**。每角色生成专属 schema（target enum = 在场其他角色 ID + 已知地点 ID + ""）。彻底消除 LLM 自造 target 变体（之前出现 `char_linxia` / `林夏` / `lin_xia` 等 7+ 种）。
  Files: src/inkfish/llm/deepseek.py, src/inkfish/llm/retry.py, src/inkfish/tick/scheduler.py
- 默认 LLM 模型从 `deepseek-v4-pro` (reasoner) 改为 **`deepseek-v4-flash`**（非 reasoner，速度 4× 快），max_tokens 16384 → 2000。v4-pro 保留给未来 director / writer 通过 routing rule 调用。
  Files: inkfish.toml, src/inkfish/config.py
- Perception block 字段重排：volatile 字段（时间 / tick_id / mood）从 block 开头移到末尾，stable 字段（地点 / 在场其他人）放前面。byte diff 从 char 1544 推到 char 2150+，cache 命中从 14% → 95%。
  Files: src/inkfish/character/context.py
- Perception block 增加 `[id=char_xxx]` 标记，system prompt 强调 target 必须原样复制。
  Files: src/inkfish/character/context.py, prompts/character_system.txt
- `LLMLogRow` 增加 `attempt` 字段记录重试次数。
  Files: src/inkfish/storage/models.py
- Retry 日志升级：每次成功 call 输出 `LLM ok char=X tick=Y attempt=N/M action=Z wall=Ams tokens=P/R cached=C cost=$C`。
  Files: src/inkfish/llm/retry.py
- run_simulation 结束打印整体 summary：tokens / cache_hit% / 平均+最大 latency / 总成本 / retries / fallbacks。
  Files: src/inkfish/tick/scheduler.py
- `Settings.db_url` 加 `INKFISH_DB_URL` env alias 用于测试隔离。
  Files: src/inkfish/config.py

### Fixed
- **SPEAK target self-fabrication**（用户报告：`speak 有 bug`）：LLM 把 `char_lin` 写成 `char_linxia` / `林夏` 等变体。修复链：（1）perception block 暴露 `[id=...]` 让 LLM 看到 ID；（2）改用 tool calling + JSON schema enum 在 server 端强制；（3）retry 层 `allowed_targets` 后置 Pydantic 校验作为 v4-flash 兜底（v4-flash 不严格 enforce enum）。
  Files: src/inkfish/character/context.py, src/inkfish/llm/deepseek.py, src/inkfish/llm/retry.py, src/inkfish/tick/scheduler.py, prompts/character_system.txt
- **`finish_reason=length` content empty** (D8 实测 35% 调用截断)：v4-pro reasoner 把 max_tokens=800 全消耗在 reasoning 上。修复：max_tokens 上调到 16384（pro）/ 2000（flash），retry 层加 length-aware expand × 1.5 cap 32k。
  Files: inkfish.toml, src/inkfish/config.py, src/inkfish/llm/retry.py
- **SPEAK 群体广播失败**：v4-flash 想说话但没具体 target 时返回 `target=""`，Pydantic 要求 SPEAK 必须有 target → 3 retries 全失败 → fallback DO_NOTHING。修复：parse 时检测 SPEAK/REACT + target=None/"" → 自动降级为 ACT（保留 content，去 triggers_interaction）。
  Files: src/inkfish/character/validator.py, tests/unit/test_action_validator.py
- **Concurrent first-tick cache miss**：5 个并发 LLM 首次调用全部 race，DeepSeek 端 cache 未及时落盘。修复：每 tick 第 1 个角色 sequential（warmup），等返回后再 `asyncio.gather` 剩 4 个。Cache 0% → 95%。
  Files: src/inkfish/tick/scheduler.py
- **`advance_time` double-increment tick_id**：scheduler 已直接赋值 `world.tick_id = tick_id`，再调 `advance_time(hours=1)` 又 +1。改 scheduler 直接用 `timedelta` 加 sim_time，不调 advance_time。
  Files: src/inkfish/tick/scheduler.py
- **DetachedInstanceError**（D3 发现）：read 方法返回 ORM 对象 + session expire_on_commit=True 导致访问字段抛错。修复：sessionmaker 设 `expire_on_commit=False`。
  Files: src/inkfish/storage/db.py
- 测试 `_fake_call_with_retry` 签名同步：所有 fake 加 `tool_schema` + `allowed_targets` + `async def`，hotfix v2 兼容。
  Files: tests/unit/test_tick_scheduler.py, tests/unit/test_api_endpoints.py, tests/unit/test_retry.py, tests/unit/test_deepseek_client.py
