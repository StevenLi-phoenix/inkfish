# P0 Hotfix v2 — SPEAK target enum + async + v4-flash + cache-aware

**日期**: 2026-05-11
**触发**: 用户指出 "speak 有 bug"（target 自造 `char_linxia`/`林夏` 等变体）→ 演化为完整重构
**状态**: ✅ 完成

## 用户反馈触发的连环修复

| # | 用户输入 | 修复 |
|---|---|---|
| 1 | "speak 有 bug" | scheduler 加 target unknown warning + perception 加 `[id=...]` |
| 2 | "tool call 是需要给 llm 实际枚举的 ID 的" | 完整改造 tool calling + schema enum + Pydantic 后置校验 |
| 3 | "max length 改到 16k+" | inkfish.toml max_tokens 16384 + length-aware retry expand |
| 4 | "llm 调用需要改成异步的" | DeepSeekClient → AsyncOpenAI；asyncio.gather 并发 |
| 5 | "测试是否破坏缓存" | warmup-first-char + sequence diff 测试；找出 perception 块布局问题 |
| 6 | "log 加 api wall time + 整体 cache + 成本" | retry 加 per-call log；run_simulation 末尾打 summary |
| 7 | "角色用 flash + 主角/导演/写作者用 pro" | 默认切 v4-flash；max_tokens 2000；保留 v4-pro 路由位 |
| 8 | "cache 太低了" | perception 块重排：volatile 字段（time/tick/mood）放最后 |

## 核心改动

### 1. Tool calling (替代 JSON mode)
- `DeepSeekClient.complete_with_tool(system, user, tool_schema)` — 走 OpenAI tool calling API
- `tools=[{function: ...}]`, **不传 tool_choice**（v4-pro reasoner 拒绝 forced，v4-flash auto 即可）
- 解析 `message.tool_calls[0].function.arguments` 作为 LLMResult.content
- 实测：v4-pro 严格 enforce enum；**v4-flash 不严格 enforce**，需 Pydantic 后置兜底

### 2. 动态 tool_schema（per-character）
- `scheduler._build_action_tool_schema(char, world)` 每 char 一份 schema
- `target.enum = sorted(其他在场 char_ids + 已知 location_ids) + [""]`
- 空串 `""` 表示无 target（schema strict 模式不支持 `["string", "null"]`，所以用 sentinel）
- `content.maxLength = 500`、`inner_thought.maxLength = 500`、`mood.maxLength = 100`

### 3. Pydantic 后置 enum 校验
- `call_with_retry(... allowed_targets=enum)` 参数
- 解析后若 `action.target` 不在 enum 中 → 视作 parse failure → retry
- v4-flash 的兜底，v4-pro 已 server 端 enforce

### 4. async + concurrent dispatch
- `DeepSeekClient` 用 `AsyncOpenAI`，`complete_*` 全 async
- `call_with_retry` async + tenacity 自动适配
- `run_tick` async：**warmup 模式**——第 1 角色 sequential（cache 建立）+ 剩 4 角色 `asyncio.gather`
- 实测：cache 命中从 0%（纯并发） → 95% （warmup-then-concurrent）

### 5. SPEAK 广播降级为 ACT
- LLM 想"对所有人说话"时 schema 没有"无目标 SPEAK"概念，于是返回 `target=""`
- Pydantic 验证 SPEAK 必须有 target → 失败 retry → fallback DO_NOTHING
- **修复**：parse_action_json 检测 SPEAK/REACT + target=None/"" → 自动转 ACT（保留 content）
- 这给"群体广播"一个合法表达通道，P1 互动 budget 时再细化

### 6. Perception 块字段重排（cache 关键）
**Before**:
```
当前感知：
  时间：2026年01月01日 上午9点    ← volatile（早早破坏 prefix）
  回合：tick 1                  ← volatile
  地点：晨光咖啡馆 — ...         ← stable
  在场其他人：...               ← stable
  你当前的心情：好奇            ← volatile
```

**After**:
```
当前感知：
  地点：晨光咖啡馆 — ...         ← stable（cache 命中区）
  在场其他人：...               ← stable
  时间：2026年01月01日 上午9点    ← volatile（放最后）
  回合：tick 1                  ← volatile
  你当前的心情：好奇            ← volatile
```

结果：byte diff 从 char 1544 推后到 char 2150+，cache hit 从 14% → 95%。

### 7. log 增强
- 每 LLM 成功 call: `LLM ok char=X tick=Y attempt=N/M action=Z wall=Ams tokens=P/R cached=C cost=$C`
- run_simulation 结束: `═══ run_simulation complete ═══` + tokens / cache_hit % / latency / total cost

### 8. 模型选择
- inkfish.toml `[routing].default_model = "deepseek-v4-flash"` （角色用）
- max_tokens 16384 → 2000（flash 无 reasoning_tokens 消耗）
- 注释说明：M5 导演 / M6 写作者将通过 routing rule 走 v4-pro

## 性能对比（2 ticks live mini-run）

| 配置 | Wall | Cache | Cost | Fallbacks |
|---|---|---|---|---|
| v4-pro sync (D8 原版) | 5min+ | 0% | $0.0023 | 0 |
| v4-pro async + warmup | 3:58 | 95.6% | $0.0016 | 0 |
| v4-flash async（旧 perception） | 54.8s | 13.7% | $0.0072 | 0 |
| v4-flash + reordered（前 SPEAK fix）| 1:09 | 69.9% | $0.0050 | 1 |
| **v4-flash + reordered + SPEAK降级** ⭐ | **56.6s** | **95.6%** | **$0.00306** | **0** |

最终配置：v4-pro async 的 **1/4 wall**、**2× cost**、**同 cache**、**零 fallback**。

## 一致性验证

- 174 unit tests 全过（173 + 1 新增 SPEAK→ACT 降级测试）
- ruff / mypy 全 clean
- SPEAK target 100% 来自 allowed enum 集合（不再出现 `char_linxia` / `林夏` 等变体）
- 0 fallback / 0 retries（v4-flash 一次过率 100%）

## 待办（P1 范围）

- SPEAK 广播在 P1 互动 budget 中可能需要单独建模（vs 1-on-1 SPEAK）
- 当 SPEAK target=valid 时，触发互动 budget；ACT 不触发
- 性格表现：v4-flash 比 v4-pro 短/直白；character 一致性可能需重新评估
- Director / Writer 启用时通过 routing rule 切 v4-pro

## 修改的关键文件

- `src/inkfish/llm/deepseek.py` — AsyncOpenAI + `complete_with_tool`
- `src/inkfish/llm/retry.py` — async + tool_schema + allowed_targets 后置校验 + per-call log
- `src/inkfish/tick/scheduler.py` — asyncio.gather + warmup-then-concurrent + `_build_action_tool_schema` + run_simulation summary
- `src/inkfish/character/context.py` — perception 块字段顺序重排
- `src/inkfish/character/validator.py` — `"" → None` normalize + SPEAK→ACT 降级
- `prompts/character_system.txt` — target 规则强调
- `inkfish.toml` — model = v4-flash, max_tokens = 2000
- `src/inkfish/config.py` — SimConfig 默认值同步
- `src/inkfish/api/routers/simulation.py` — `await run_simulation`
- `src/inkfish/cli.py` — `asyncio.run(run_simulation(...))`

## 一句话

围绕 "speak 有 bug" 一句反馈，串起 8 件相关的真实修复，落地为：**速度 5×、成本可控、缓存 95%、零 fallback** 的 P0 release。
