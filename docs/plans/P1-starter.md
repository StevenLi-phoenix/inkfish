# P1 启动 Handoff（互动 + 感知 + 空间）

> 这份文档是 P0 → P1 的接力棒。compact 后新 session 读完此文 + `docs/03-design.md` + `CHANGELOG.md` + `docs/reviews/P0-hotfix-v2.md` 即可冷启动 P1 plan agent。

## P0 出货态势

- **状态**: P0 ✅ 完成 + hotfix v2 ✅ + killer test rerun ✅（详见 CHANGELOG / docs/reviews/P0-*.md）
- **代码**: 174/174 unit tests，ruff/mypy clean，live mini-run 56s（MBP）/ 38s（mini），cache 95.6%，0 retries，0 fallbacks
- **运行**: `inkfish seed && inkfish run --ticks N` 跑通；`uv run pytest` 全绿
- **未 push**：本地 commit only（无 git remote）；/loop 每 15min 自动 commit

## 关键设计决策（不可回退，P1 直接继承）

来自 `docs/reviews/P0-hotfix-v2.md` 和 memory `inkfish_llm_engineering.md`：

1. **LLM 调用永远 async**，`call_with_retry` 是 `async def`，scheduler 用 `asyncio.gather` 并发 + warmup-first-char 暖 cache。
2. **Tool calling + JSON Schema enum 强制** 替代 JSON mode（角色 target 字段最显著）；v4-flash 不严格 enforce → Pydantic 后置 + `_normalize_target` fuzzy match 兜底。
3. **模型 tier 路由**：
   - 角色 (M3) → `deepseek-v4-flash`（非 reasoner，4× 快）
   - 导演 (M5) / 写作者 (M6) → `deepseek-v4-pro`（reasoner，强但慢）
   - 关系提取 / mandatory 后台 → 小模型 (deepseek-chat or 备用)
4. **`max_tokens=2000` 给 v4-flash 已够**；`16384` 给 v4-pro（reasoning_tokens 在 completion_tokens 内）；retry 层有 length-aware expand × 1.5。
5. **Perception block 字段顺序**：stable (地点/在场角色) 前，volatile (sim_time/tick/mood) 后。改动会破 cache。
6. **`reset()` 不删 `llm_logs`**（成本审计跨实验对比）。
7. **SPEAK target=None 自动降级为 ACT**（保留 content），P1 互动 budget 可能要重新评估是否保留。

## P0 → P1 之间的真实痛点（killer test 数据观察）

`docs/reviews/P0-D11-storyline.md` 和 `P0-D11-rerun-v4flash.md` 揭示：

| 痛点 | P1 应解决 |
|---|---|
| **被 SPEAK 的人完全没听到** — char_lin 喊 char_zhao 5 次，赵默 10 个动作全在敲 SQL，零回应 | 感知规则升级：context [3] 加"上一回合别人对你说的话"；`triggers_interaction=True` 触发互动 budget 多轮对话 |
| **target 字符串自造变体** — v4-flash 偶发返回 `[id=char_xx]` wrapper | `_normalize_target` fuzzy match 已落地；`can_perform()` 鉴权进一步严格化 |
| **MOVE_TO 静默忽略未知地点** — 王婉 `MOVE_TO home`（home 不存在）被丢弃 | 地点动态生成：未知 target → LLM 小模型生成 location + connect_to + 加入 world.locations |
| **女儿名字漂移** — 王婉 4 次 THINK 给女儿 3 个不同名（小雅/小月/婉清）| 记忆图：互动后 LLM 提取 `knowledge_updates` 写入 SQLite 关系图，后续 perception 检索 |
| **char_zhao 长 THINK content 偶发被截**（v4-pro 时代 3 次 fallback；v4-flash 已无此问题） | `content` schema maxLength 500 已加；P1 验证是否够 |

## P1 范围（按 `docs/04-build.md` §P1）

> **Done**: 两个角色在咖啡馆相遇，自动发起对话（互动 budget 3 轮），互动后关系表出现新记录。
> **Killer test**: 角色 A 和 B 互动 5 次后，A 的 context [2] 记忆中能查到"我认识 B，B 是 {职业}"。
> **时间**: 3 周。

工作清单：

- [ ] `Location` dataclass 已存在（D3 完成），扩展支持多个地点（不止 Coffee Shop）
- [ ] **感知规则升级**：
  - 同地点可见——已有
  - 认识的：名字 + 关系 + **上一 tick 对方外显 action 摘要**
  - 不认识的：外貌 + 上一 tick 外显 action
  - 不同地点：不可见（除非 P7 数字空间）
- [ ] **context 拼装升级**：
  - block [2] 记忆从 stub 改成真实 — 关系网（图查询）+ 已知事实（按时间倒序 + token budget 截断）
  - block [3] 感知加 "上一回合对方动作"
- [ ] **互动 Budget 循环**：
  ```python
  async def run_interaction_budget(interaction, max_rounds):
      transcript = []
      for round in range(max_rounds):
          # A 先动，看到 B 上一轮外显
          ctx_a = build_interaction_context(a, b, transcript, viewer=a)
          action_a = await call_with_retry(...)
          transcript.append(action_a)
          # B 回应，看到 A 本轮外显
          ctx_b = build_interaction_context(b, a, transcript, viewer=b)
          action_b = await call_with_retry(...)
          transcript.append(action_b)
          # 双方 DO_NOTHING → 结束
          if action_a.type == DO_NOTHING and action_b.type == DO_NOTHING:
              break
      return transcript
  ```
  - **内心隔离**：`build_interaction_context(viewer=X)` 过滤掉对方 `inner_thought`
  - 互动循环 async 不阻塞主 tick
  - `max_rounds` 默认从 `inkfish.toml [characters].interaction_max_limit = 10`
- [ ] **关系提取**（互动结束触发，路由 mandatory 队列，小模型）：
  ```json
  {
    "relationship_changes": [{"from","to","type","delta","reason"}],
    "knowledge_updates": [{"character","learned","confidence"}],
    "mood_updates": [{"character","mood"}]
  }
  ```
  写入 `RelationshipRow` + 新表 `knowledge_facts`（已有 model 或需新增？检查 storage/models.py）
- [ ] **地点动态生成**：角色 `MOVE_TO` 未知 target → 调小模型生成 Location，加入 world.locations + DB
- [ ] **`can_perform()` 严格鉴权**：MOVE_TO 可达性 + SPEAK target 在场 + REACT target 存在；P0 是 warning，P1 改成 reject + retry
- [ ] **3 个地点 + 10 个角色** seed（扩展 data/seed/world.json）
- [ ] killer test：互动 5 次后 A 的记忆有 B 的职业

## 关键文件（P1 要改的）

- `src/inkfish/character/context.py` — perception 块加上一 tick 动作 + 真实 memory block
- `src/inkfish/character/interaction.py` — **新增** `run_interaction_budget()`
- `src/inkfish/tick/scheduler.py` — `triggers_interaction=True` 检测 → 调用 interaction budget；MOVE_TO 触发地点生成；接 `can_perform()` 鉴权
- `src/inkfish/storage/models.py` — 加 `RelationshipRow`（已存在）/ `KnowledgeRow`（新增）
- `src/inkfish/world/state.py` — 加 `present_at()` / `is_reachable()` 方法
- `src/inkfish/character/agent.py` — **新增** `can_perform()` 鉴权（设计 §4.4）
- `src/inkfish/character/relationship.py` — **新增** 关系提取 LLM 调用（小模型，mandatory 队列）
- `data/seed/world.json` — 3 个地点 + 10 个角色

## 启动 P1 的命令

```bash
# 1. 确认 P0 仍 green
cd ~/Codes/inkfish
uv run pytest -q tests/unit/
uv run ruff check src/ tests/
uv run mypy src/inkfish

# 2. 启动 plan agent 设计 P1（建议用 opus）
#   - 读这份 P1-starter.md
#   - 读 docs/03-design.md §4-§5 (角色 / 感知 / 互动)
#   - 读 docs/04-build.md §P1
#   - 读 memory inkfish_llm_engineering.md (LLM 工程偏好)
#   - 设计 P1 分 day 实施

# 3. plan agent 出 P1-plan.md 后保存到 docs/plans/P1-plan.md
# 4. 进入实施 — 每 day 一个 sonnet subagent，写 review 到 docs/reviews/P1-D*.md
```

## 风险（来自 04-build.md §3 + hotfix v2 实测）

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 互动 budget 多轮 LLM 调用 latency 累加（max 10 轮 × ~10s = ~100s 一次互动） | 互动异步不阻塞主 tick；max_rounds 默认 5（不 10）；监控互动时长自适应 |
| R2 | 地点动态生成 LLM 又慢又可能产生不合规 Location | 小模型 + 严格 schema (Pydantic Location)；失败兜底用 default Location |
| R3 | 关系提取漂移（一致性问题）| Confidence 字段 + 后续互动覆盖；P5 引入 ckpt 时能回滚 |
| R4 | 内心独白泄漏给对方 | `build_interaction_context(viewer=X)` 严格 filter；unit test 用 fixture 验证两方 prompt 都不含对方 inner_thought |

## 开放问题（P1 实验阶段回答）

| Q | 何时回答 |
|---|---|
| Q1 | 互动 budget max_rounds 实测最佳值（5 vs 10）？ | P1 D~10 |
| Q2 | 关系提取小模型选哪个（deepseek-chat / qwen-turbo / glm-flash）？| P1 D~12 |
| Q3 | 同地点 N 个角色全发起互动时 LLM 调用爆炸怎么 throttle？| P1 D~14 |
| Q4 | char_zhao 类 INTP 角色在互动中"敷衍"会不会让对话死循环？ | P1 killer test |

## 一句话

P0 给了"5 个独白演员同台"，P1 要让他们**真的开始对话** + **记得彼此** + **走出咖啡馆**。
