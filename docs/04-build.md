# INKFISH 实施路线图

## 1. 锁定前提

以下设计决策不可协商，已在需求阶段确认：

1. INKFISH 是自主角色模拟引擎，不是协作写作工具
2. 作者是天道（监视/审阅/调整），不是写作者
3. 零输入可运行——无 premise 时自动生成世界和小说
4. 角色完全自治，自己驱动自己的行为
5. tick = 1 小时，所有角色并发行动
6. 中央 LLM 调度器统一管理请求、限流、routing
7. 权重系统决定角色 LLM 调用频率和存活
8. 互动 budget：角色主动触发，多轮循环，内心永远隔离
9. 多层空间（物理 + 数字 + 异界），地点动态生成
10. 导演 AI + 写作者 AI 是独立 agent，各有 tool call
11. 多导演并行，碰撞不仲裁
12. 存储：SQLite + 每 tick 完整快照 + git-like fork/reset
13. 后端 Python + FastAPI + REST；前端 React + SSE
14. LLM 多 provider routing（DeepSeek 默认，重要角色用 Claude/Qwen）
15. 社会热点可注入模拟世界

---

## 2. 阶段切片

### P0: 核心 Tick 循环 PoC

**目标**：5 个角色在同一个世界里自主行动 10 个 tick，验证基础模拟循环可行。

**工作清单**：
- [ ] FastAPI 项目骨架 + 目录结构
- [ ] `Character` dataclass + `CharacterAction` schema
- [ ] 单 provider LLM 调用（DeepSeek）
- [ ] tick scheduler：顺序执行 5 个角色的 LLM 调用
- [ ] action 输出 JSON 解析 + 校验
- [ ] SQLite 表创建（characters / actions / snapshots）
- [ ] 每 tick 完整快照写入
- [ ] `reset(tick_id)` 实现
- [ ] 简单世界初始化（手动 5 角色 + 1 地点）

**Done**：5 角色跑 10 tick，每 tick 产出 5 个合法 action JSON，快照可 reset 回任意 tick。

**Killer test**：从 tick_5 reset 重跑 5 个 tick，角色行为不同（因为 LLM 非确定性）但每个 action 都合法且与角色性格一致。

**时间**：2 周。

---

### P1: 互动 + 感知 + 空间

**目标**：角色能感知同地点的人、主动发起互动、互动后关系更新。

**工作清单**：
- [ ] `Location` dataclass + 空间模型（单层）
- [ ] 感知规则：同地点可见（认识 → 名字+关系；不认识 → 外貌）
- [ ] context 拼装三层结构：人设 → 记忆 → 感知
- [ ] `triggers_interaction` 检测 + 互动 budget 循环
- [ ] 内心隔离（`inner_thought` 不跨角色）
- [ ] 关系提取 LLM 调用 + 关系表写入
- [ ] 地点动态生成（角色 MOVE_TO 不存在的地点 → 生成）
- [ ] `can_perform()` 鉴权基础版（MOVE_TO 可达性）
- [ ] 3 个地点 + 10 个角色跑通

**Done**：两个角色在咖啡馆相遇，自动发起对话（互动 budget 3 轮），互动后关系表出现新记录。

**Killer test**：角色 A 和 B 互动 5 次后，A 的 context [2] 记忆中能查到"我认识 B，B 是 {职业}"。验证记忆持久化 + 感知正确。

**时间**：3 周。

---

### P2: 中央调度器 + 多 Provider

**目标**：50+ 角色高效运行，LLM 成本可控。

**工作清单**：
- [ ] LLM Gateway 模块：优先级队列 + 并发控制
- [ ] 多 provider 支持：DeepSeek + Anthropic + Qwen
- [ ] Routing 规则引擎（config 驱动，可自定义）
- [ ] 权重计算：`f(出场次数, 导演关注度, 最近活跃度)`
- [ ] DPO 随机重排（高斯噪声）
- [ ] 跳过逻辑（min_weight / max_updates_per_tick）
- [ ] 跳过后恢复 context 注入
- [ ] Prompt 缓存策略（稳定前缀）
- [ ] `llm_logs` 表 + 成本追踪
- [ ] 429 rate limit 处理 + exponential backoff
- [ ] 50 角色 + 5 地点压测

**Done**：50 角色跑 100 tick，调度器正确分配 provider，成本日志完整，无 429 报错。

**Killer test**：权重最低的 10 个角色在 100 tick 中被跳过 >50%，且恢复时 context 正确注入"你已跳过 N tick"。高权重角色 100% 执行。

**时间**：3 周。

---

### P3: 导演系统

**目标**：AI 导演主动制造有趣剧情，能引导故事走向。

**工作清单**：
- [ ] Director agent：system prompt（含 pacing 意识）
- [ ] 全部 tool call 实现（12 个）
- [ ] 导演每 tick 最先运行逻辑
- [ ] `create_events` → 事件出现在地点 → 影响在场角色
- [ ] `inject_motivation` → 下一 tick 角色 context 注入
- [ ] `spawn_director` → 多导演实例管理
- [ ] 多导演共享 Storage + Gateway
- [ ] 社会热点注入基础版（手动输入）
- [ ] 导演不可跳过/不可杀死的硬约束

**Done**：导演观察到两个角色连续 5 tick 无互动后，主动安排一个"偶遇事件"，事件在模拟中发生。

**Killer test**：跑两次 50 tick——一次无导演（纯角色自治），一次有导演。有导演版本产生 >2x 的互动次数和 >1 个戏剧冲突（两个角色产生对立行为）。

**时间**：4 周。

---

### P4: 写作者 + 网文输出

**目标**：从事件日志自动生成可读网文。

**工作清单**：
- [ ] Writer agent：system prompt + tool call
- [ ] 触发机制：导演 `signal_writer` / 作者手动 / step 结束
- [ ] 事件日志 → 网文转写 pipeline
- [ ] 前文连贯性（拉 `previous_output` 末尾）
- [ ] 网文输出存储（`writer_outputs` 表）
- [ ] 多导演线时 Writer 自主选择逻辑
- [ ] 输出长度控制（分割建议配置）

**Done**：导演跑 50 tick 后触发 Writer，输出 3000+ 字网文段落，第三人称限知视角，可读。

**Killer test**：盲给 2-3 个朋友读输出的网文段落，能看懂故事且想知道后续发展。

**时间**：3 周。

---

### P5: 世界初始化 + Checkpoint 系统

**目标**：零输入启动 + 完整时间线管理。

**工作清单**：
- [ ] 三步初始化流程：世界规则 → 地点 → 角色（并行）
- [ ] 零输入模式（premise=None 时随机生成）
- [ ] 有 premise 模式（按约束补全）
- [ ] 几百角色并行生成
- [ ] 角色引用时动态生成（"我要去找我哥" → 生成哥）
- [ ] `fork(tick_id)` 完整实现
- [ ] 分支管理（list / switch / delete）
- [ ] `replay(from, to)` 实现
- [ ] 崩溃恢复测试

**Done**：无任何 premise 点"开始"，系统生成世界 + 100 角色 + 跑 50 tick + 输出一段网文。支持 fork 和 reset。

**Killer test**：从 tick_50 fork 两条线，各跑 20 tick，两条线故事发展不同且各自内部一致。

**时间**：4 周。

---

### P6: 前端

**目标**：浏览器里监视和控制模拟。

**工作清单**：
- [ ] React 项目初始化
- [ ] SSE 客户端（接收所有事件类型）
- [ ] 角色关系图（力导向图，节点=角色，边=关系）
- [ ] 剧情图（时序事件图）
- [ ] 控制面板：配置编辑 / 启动 / 暂停 / fork / reset
- [ ] 对话面板：作者 ↔ 导演（文本输入 + 结构化按钮）
- [ ] 点击角色节点 → 上下文对话框
- [ ] 阅读页：Writer 输出实时显示
- [ ] 成本仪表盘
- [ ] 面板布局（参考 MiroFish：设置/图/premise 分离）

**Done**：在浏览器里看到实时节点图变化，能和导演对话并看到导演的反应影响模拟。

**Killer test**：不开终端，全程浏览器操作：配置世界 → 启动 → 监视 100 tick → 和导演对话干预 → 查看网文输出 → fork → 对比两条线。

**时间**：5 周。

---

### P7: 多层空间 + 多导演 + 大规模

**目标**：完整功能 + 几百角色压力测试。

**工作清单**：
- [ ] 多空间层：digital + otherworld
- [ ] 跨层裂缝机制
- [ ] 数字空间互动（微信群聊天 / 社媒发帖）
- [ ] 多导演并行稳定性
- [ ] 300 角色压测
- [ ] 社会热点 API 对接（微博热搜）
- [ ] 性能优化（批量 LLM 调用、缓存命中率）
- [ ] Docker 打包 + docker-compose
- [ ] PostgreSQL 支持验证

**Done**：300 角色 + 2 导演 + 2 空间层（物理 + 数字）跑 200 tick，输出 2 段网文，成本和速度在预算内。

**Killer test**：成本 < ¥50/200tick（300 角色）；单 tick 端到端 < 30s；无 OOM 或死锁。

**时间**：5 周。

---

### P8+: 实战写一本小说

不再加功能，用 INKFISH 跑出一本 10 万字网文。根据痛点日志迭代。

---

## 3. 风险清单

| ID | 严重度 | 风险 | 缓解 |
|---|---|---|---|
| R1 | 最高 | LLM 生成的角色行为不够"自主"，看起来像 NPC 脚本 | P0 直接验证。用 mes_example 级别的 persona 注入；不行就换更强模型或更长人设 |
| R2 | 高 | 几百角色的 LLM 成本爆炸 | 权重系统 + 跳过逻辑 + DeepSeek Flash 兜底；P2 做成本压测 |
| R3 | 高 | 导演制造的剧情不够有趣 / 太生硬 | P3 killer test 直接验证；pacing prompt 持续迭代；多导演碰撞增加涌现性 |
| R4 | 高 | 网文输出质量差（AI 腔、没有节奏感） | P4 killer test 盲评验证；Writer prompt 迭代；必要时 Writer 用 Opus 级别模型 |
| R5 | 中 | 每 tick 完整快照存储量大（几百角色 × 千 tick） | SQLite 单文件可以到 GB 级不成问题；PostgreSQL 无上限；必要时按间隔快照而非每 tick |
| R6 | 中 | 互动 budget 循环太长拖慢 tick | max_limit 默认 10；互动异步不阻塞主循环；监控互动时长做自适应 |
| R7 | 中 | 多导演并发修改同一角色状态冲突 | 最后写入者赢（last-write-wins）；导演各自盯不同角色线降低冲突概率 |
| R8 | 低 | SQLite 并发写性能 | WAL mode；写操作全部序列化通过 Storage 模块；PostgreSQL 作为后备 |

---

## 4. 开放问题

| ID | 问题 | 何时回答 |
|---|---|---|
| Q1 | 角色 persona 多长能让行为真的"像人"？500字？2000字？ | P0 实验 |
| Q2 | 导演 system prompt 的 pacing 规则具体怎么写最有效？ | P3 迭代 |
| Q3 | Writer 输出网文时，多长的 context（事件日志）能产出最好的叙事？ | P4 实验 |
| Q4 | 几百角色时 prompt 缓存命中率实测多少？成本节省多大？ | P2 压测 |
| Q5 | 社会热点注入后 NPC 反应是否自然？还是需要专门的传播模型？ | P7 |
| Q6 | 数字空间（微信群）的互动模型和物理空间用同一套 budget 还是需要变体？ | P7 |
