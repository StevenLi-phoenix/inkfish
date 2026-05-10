# MiroFish 架构参考

> 调研对象：[666ghj/MiroFish](https://github.com/666ghj/MiroFish) — "简洁通用的群体智能引擎，预测万物"
> 范围：main 分支主干代码（backend ~16k 行 Python，frontend Vue 3）
> 用途：技术参考文档，给六个月后的自己看

---

## TL;DR

MiroFish 把"上传文档 + 用自然语言写需求"翻译成一份预测报告，中间走一条七步流水线：LLM 设计图谱本体 → Zep GraphRAG 把文档建成时序知识图谱 → 每个图节点铸造为一个 OASIS Agent → LLM 生成完整的模拟参数 → 双平台（Twitter + Reddit）OASIS 子进程并行跑模拟 → 模拟过程中实时把 Agent 行为反向写回图谱 → 模拟结束后子进程不退出，进入 IPC 等待模式，由一个 ReACT Report Agent 拿四件工具去调查这个仍然活着的世界并产出报告。整套架构把"应用领域 = 社交媒体舆论"和"机制骨架"分得很干净——骨架是可复用的。

---

## 1. 系统全景

### 1.1 流水线大图

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Step 1      │  │  Step 2      │  │  Step 3      │
│  本体设计    │  │  图谱构建    │  │  角色铸造    │
│  Ontology    │→ │  GraphRAG    │→ │  OASIS       │
│  Generator   │  │  (Zep)       │  │  Profiles    │
└──────────────┘  └──────────────┘  └──────────────┘
                                           │
                                           ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Step 7      │  │  Step 5      │  │  Step 4      │
│  ReACT       │  │  双平台并行  │  │  模拟参数    │
│  Report      │← │  模拟运行    │← │  智能生成    │
│  Agent       │  │  Twitter +   │  │  Sim Config  │
│              │  │  Reddit      │  │  Generator   │
└──────────────┘  └──────────────┘  └──────────────┘
       ▲                  │
       │                  ▼ (可选 Step 6)
       │           ┌──────────────┐
       └──────────│  Graph Memory│  模拟过程中实时
                   │  Updater     │  把行为写回 Zep
                   └──────────────┘
```

### 1.2 进程拓扑

```
Flask 主进程 (port 5001)
├─ HTTP API (3 个 Blueprint: graph / simulation / report)
├─ Background threads (TaskManager 单例追踪)
└─ Subprocess pool: 每个 simulation_id 一个 OASIS 子进程
   ├─ 通过 simulation_dir/ipc_commands/  接命令
   └─ 通过 simulation_dir/ipc_responses/ 回结果
        ↑
        Filesystem-based IPC (轮询，无 socket，无 mq)
```

进程隔离是个深思熟虑的简化：每个模拟 = 一个 OS 进程 = 一个文件夹。状态全在文件系统里，崩了重启 Flask 也不丢。代价是 IPC 走轮询、不能跨机器，在"研究型工具 + 个人工作站"的场景下这个 trade-off 完全成立。

---

## 2. 七步骨架

### 2.1 本体设计（Ontology Generation）

**位置**：`backend/app/services/ontology_generator.py`

LLM 读用户文档 + 模拟需求，输出一份 JSON 本体定义：

- 实体类型必须正好 10 个，结构是 8 个具体类型 + 2 个兜底类型（`Person` / `Organization`）
- 边类型 6–10 个（如 `WORKS_FOR` / `REPRESENTS` / `REGULATES` / `REPORTS_ON` / `SUPPORTS` / `OPPOSES`）
- 每个类型 1–3 个属性，命名严格强制：实体类型 PascalCase、关系类型 UPPER_SNAKE_CASE、属性 snake_case
- 系统保留属性名（`uuid` / `name` / `summary` / `created_at` …）需要避开

**关键设计**：

1. **本体是 LLM 设计的，不是预定义的。** 系统不预设 schema，让 LLM 根据具体材料决定"这次要建模哪些角色"。这是整个流水线的可泛化性来源。
2. **强约束实体必须是"能在社媒上发声的主体"。** 系统提示词明确禁止抽象概念、话题、立场作为实体。这是把"通用图谱"窄化为"可模拟图谱"的关键约束。
3. **兜底类型保证全集覆盖。** 文本中出现的任何"路人甲""某网友"都能落入 `Person`，避免 LLM 为冷门角色纠结类型。

**第一性原理意义**：本体决定了世界由什么组成。它有两个下游用途：(a) 给 Zep 图谱做类型约束，(b) 给后续 Agent 铸造做分流（个人 vs 机构走不同 prompt）。

### 2.2 图谱构建（GraphRAG via Zep）

**位置**：`backend/app/services/graph_builder.py`

调用 [Zep Cloud](https://www.getzep.com/) 的 Graphiti API：

- `create_graph(name)` → 拿到 `graph_id`
- `set_ontology(graph_id, ontology)` → 用 Pydantic 动态生成 EntityModel/EdgeModel 并应用
- 文本 chunk 默认 size=500、overlap=50；`add_text_batches(chunks, batch_size=3)` 异步喂入
- `_wait_for_episodes(uuids, callback)` 每 3 秒轮询每个 episode 的 `processed` 状态，超时 600s
- `get_graph_data(graph_id)` 拿全量节点 + 边

**关键设计**：

1. **图抽取外包给 Zep。** 实体识别、向量化、时序事实管理（"这个事实当前有效"vs"这个事实已过期"）都是 Zep/Graphiti 的强项，自己重写不划算。
2. **整个流程异步**。Flask 起后台线程，前端拿 `task_id` 轮询进度。`stage_weights` 把"创建图(0–10%) → 设置本体(10–15%) → 分块(15–20%) → 上传(20–60%) → 等 Zep 处理(60–90%) → 拉取信息(90–100%)"合成为单个 0–100 数字。
3. **动态创建 Pydantic 类**。本体的 entity/edge 定义在运行时被 `type()` 转成 `EntityModel` / `EdgeModel` 子类，再传给 `client.graph.set_ontology()`。这是被 Zep SDK 强制的用法。

**第一性原理意义**：用一个**时序知识图谱**当世界的"长期记忆"。它的两类一等公民——节点（实体）和带时间属性的边（事实）——是后续所有"检索"和"上下文构建"的底座。

### 2.3 角色铸造（OASIS Profile Generation）

**位置**：`backend/app/services/oasis_profile_generator.py`（1205 行）

每个图谱节点 → 一个 Agent profile：

1. `_search_zep_for_entity` 用实体名在图里再做一次混合搜索（并行 edges + nodes，各带重试），把节点摘要 + 相关边拼成上下文
2. 区分**个人**（`student` / `professor` / `journalist` / `expert` / `official` …）vs **机构/群体**（`university` / `governmentagency` / `mediaoutlet` / `company` …），走不同 prompt
3. LLM 输出 JSON：`bio`（200 字简介） + `persona`（2000 字纯文本人设） + `age` + `gender` + `mbti` + `country` + `profession` + `interested_topics`
4. 并行生成（默认 5 并发，`ThreadPoolExecutor`）
5. 输出两种格式：`twitter_profiles.csv` + `reddit_profiles.json`

**关键设计**：

1. **节点 → Agent 是 1:1**。图里有多少实体就铸造多少 Agent，不做聚合，也不做过滤。
2. **persona 是 2000 字自由文本而非结构化字段**。这个选择保留了角色的"模糊性"，给 LLM 演 Agent 时留足腾挪空间。
3. **个人 vs 机构二分法**。机构 Agent 强制 `age=30`、`gender=other`、`mbti` 偏 `ISTJ`（"严谨保守"），给"机构发言"一个稳定的人格基线。
4. **"个人记忆 / 机构记忆"是 persona 的必填段**。强制写入"这个人/这个机构在原始事件里已经做了什么"——给模拟一个起跑姿势，避免 Agent 一开局就脱离材料。

**第一性原理意义**：把"图里的一个名字"具象化为"会说话的角色"。这一步是死东西变活东西的临界点。

### 2.4 模拟参数智能生成（Sim Config）

**位置**：`backend/app/services/simulation_config_generator.py`（991 行，最大的服务文件之一）

LLM 分四步生成完整模拟参数：

1. **TimeSimulationConfig**：总时长（默认 72h）、每轮代表分钟数（60min）、24 小时活跃曲线（dead/morning/work/peak/night 各有 multiplier；默认硬编码"中国人作息"——deep hours 0–5、peak hours 19–22）
2. **EventConfig**：初始帖子（哪几个 Agent 发布、内容是什么）、定时事件（在第 X 小时触发什么）、热点话题关键词、舆论引导方向；之后用 `_assign_initial_post_agents` 给初始帖子绑定具体发布者
3. **AgentActivityConfig × N**（按 `AGENTS_PER_BATCH=15` 分批生成）：每个 Agent 的 `activity_level` / `posts_per_hour` / `comments_per_hour` / `active_hours` / `sentiment_bias`（-1.0~1.0） / `stance`（supportive/opposing/neutral/observer） / `influence_weight`
4. **PlatformConfig**：推荐算法权重（recency / popularity / relevance）、`viral_threshold`、`echo_chamber_strength`；Twitter 默认偏 recency（0.4/0.3/0.3，threshold=10），Reddit 默认偏 popularity（0.3/0.4/0.3，threshold=15，echo chamber 0.6）

**关键设计**：

1. **"无需手动设置参数"是产品立场。** LLM 接管所有调参，降低用户门槛，代价是每次跑都不可重现。
2. **分步生成 + JSON 修复 + 重试**。一次性生成 N 个 Agent 的配置容易超长 / 截断，所以分批 + `_call_llm_with_retry` + `_fix_truncated_json`。
3. **时间模型耦合了文化假设**（中国人作息），如果切换文化或切换时间尺度（比如小说的多日演化），这层需要改。
4. **平台默认参数硬编码**。两个 PlatformConfig 是常量而非 LLM 生成，留了一个"该不该让 LLM 决定平台算法"的开放问题。

**第一性原理意义**：模拟需要时间律 + 个体行为律 + 环境律。这三套律法都从 LLM 推断，而不是用户填表。

### 2.5 双平台并行运行（Subprocess + Filesystem IPC）

**位置**：`backend/app/services/simulation_runner.py`（1768 行） + `backend/scripts/run_parallel_simulation.py`（1699 行） + `backend/app/services/simulation_ipc.py`

Flask 这边：

```python
process = subprocess.Popen(
    [sys.executable, "backend/scripts/run_parallel_simulation.py",
     "--config", config_path, "--max-rounds", str(max_rounds)],
    cwd=sim_dir,
    stdout=main_log_file, stderr=subprocess.STDOUT,
    env=env_with_utf8,
    start_new_session=True,  # 新进程组，方便 killpg
)
```

子进程里跑 [OASIS](https://github.com/camel-ai/oasis)（CAMEL-AI 的社交模拟引擎）：

- 用 `asyncio.gather` 同时跑 `run_twitter_simulation` 和 `run_reddit_simulation`
- 每轮根据时间 multiplier × `activity_level` 选活跃 Agent
- 给 Agent 喂"当前时间线 + 你能看到的帖子"，Agent LLM 决策
- Twitter 动作集：`CREATE_POST` / `LIKE_POST` / `REPOST` / `FOLLOW` / `QUOTE_POST` / `DO_NOTHING`
- Reddit 动作集：`LIKE_POST` / `DISLIKE_POST` / `CREATE_POST` / `CREATE_COMMENT` / `LIKE_COMMENT` / `DISLIKE_COMMENT` / `SEARCH_POSTS` / `SEARCH_USER` / `TREND` / `REFRESH` / `FOLLOW` / `MUTE` / `DO_NOTHING`
- 写到 `twitter/actions.jsonl` 和 `reddit/actions.jsonl`

主循环结束后子进程**不退出**：进入 IPC 等待模式，监听 `ipc_commands/*.json`，可以接 `interview` / `batch_interview` / `close_env` 命令。Flask 端用 `SimulationIPCClient.send_command` 写命令文件，轮询 `ipc_responses/<command_id>.json`（默认 60s 超时，0.5s 间隔）。

**关键设计**：

1. **进程隔离 = 状态隔离 = 故障隔离**。Flask 永远不会因为某个模拟挂掉而崩。子进程崩了也只影响那一个 simulation。
2. **Filesystem IPC** 而不是 socket：跨平台、可调试（命令文件就是人类可读 JSON）、简单。代价是延迟（轮询 0.5s 量级）。
3. **"模拟结束 ≠ 世界关闭"**。这是产品的灵魂——结束后还能 interview Agent，让用户和模拟世界保持对话。`--no-wait` 开关可以关掉这个行为。
4. **subprocess 命令行接口干净**：`python script --config foo.json` 可以独立运行，不依赖 Flask。这是好的工程纪律——本地调试和生产部署用同一条入口。

**第一性原理意义**：进程是世界的容器。世界活着 = 进程活着 = IPC 通道开着。

### 2.6 图谱记忆反向更新

**位置**：`backend/app/services/zep_graph_memory_updater.py`

启用 `enable_graph_memory_update=True` 后：

- 模拟主循环每产生一个 Agent action（"张三发了一条帖子说……"）
- 由独立 worker thread 把 action 翻译成自然语言（`AgentActivity.to_episode_text()`，每种 action_type 有对应的 `_describe_*` 函数，会带上原帖内容和被互动方的名字）
- 按平台分桶累积，每桶到 `BATCH_SIZE=5` 就触发一次 `client.graph.add_batch(...)` 推回 Zep；`SEND_INTERVAL=0.5s` 限速；`MAX_RETRIES=3` 退避

**第一性原理意义**：模拟过程**改变**了世界状态。如果状态只在内存里，模拟一结束就没了。把它写回图谱 = 让"模拟历史"成为图谱事实，下次跑或者后续 Report Agent 检索时能看见。

这是闭环：**输入 → 世界 → 模拟 → 改变世界 → 下一次输入**。

### 2.7 ReACT 报告生成（Report Agent）

**位置**：`backend/app/services/report_agent.py`（2572 行，最大的文件） + `backend/app/services/zep_tools.py`（1736 行）

两阶段：

**A. 大纲规划（plan_outline）**

LLM 拿到 `simulation_requirement` + 图谱统计（节点数 / 边数 / 类型分布） + 一批相关事实样本，输出 2–5 个章节的目录。系统提示词的核心 framing 是：

> "你是一个「未来预测报告」的撰写专家，拥有对模拟世界的「上帝视角」……你正在观察的不是'实验数据'，而是'未来的预演'。"

这把 LLM 框定在一个明确的认知姿态里，比"你是分析师"有效得多。

**B. 章节生成（每章节一个 ReACT 循环）**

工具集 4 个，全部封装在 `ZepToolsService`：

- **InsightForge**（深度洞察检索）—— 最重的工具。LLM 把章节问题拆成最多 5 个子问题，每个子问题做语义搜索，从命中的 edge 里收集相关实体 UUID，逐个拉详情，构建关系链，整合成深度洞察。
- **PanoramaSearch**（广度搜索）—— 拉全量节点和边（包括 `is_expired` / `is_invalid` 的历史事实），按关键词做相关性排序，看事件演化轨迹。
- **QuickSearch**（快速搜索）—— 单点 `search_graph(scope="edges", limit=10)`。
- **InterviewAgents**（深度采访）—— 调用 `SimulationRunner` 通过 IPC 给**还活着的子进程**发 `batch_interview` 命令，对相关 Agent 做真实采访（不是 LLM 模拟回答，是真去叫醒模拟里的 Agent）。

ReACT 循环参数：`max_iterations=5`、`min_tool_calls=3`、`MAX_TOOL_CALLS_PER_SECTION=5`。如果 LLM 跳过工具直接 Final Answer 会被纠回；如果反复同时输出工具调用 + Final Answer 会触发 `conflict_retries` 计数。每章写完保存 markdown，全部完成后由 `ReportManager.assemble_full_report` 拼装。

**关键设计**：

1. **"上帝视角" framing**。Report Agent 不是"分析师对外部数据做综述"，是"造世主对自己造的世界做总结"。这个 framing 影响了所有章节的语气。
2. **InterviewAgents 让报告有"原始素材"**。报告里能引用真实 Agent 在模拟中说的话，可信度比纯 LLM 总结高。
3. **InsightForge 的子问题分解**。用户问 X → LLM 拆成 X1/X2/X3 → 各自检索 → 合并。比单次 RAG 召回率高很多。
4. **工具集模块化**。4 个工具完全独立，可以增删；每个工具的输入输出都是 `dataclass`。

**第一性原理意义**：报告是对世界的**结构化阅读**。结构由 LLM 规划，阅读由 LLM 在工具栈上递归调用完成。

---

## 3. 第一性原理：MiroFish 在做什么

剥掉"社交媒体舆论模拟"这层皮，MiroFish 的不可约简核心是：

> 把 (语料, 意图) 翻译成一个可被 LLM 反复阅读的、活着的世界，并对它做结构化阅读。

把这句话拆成五条原子断言：

### A. 语料 + 意图 → 世界

用户输入两件事：（1）资料（文档），（2）问题（"我想看什么发生"）。系统把这两件事翻译成一个有类型的、有角色的、有动力学的世界。注意翻译过程中 LLM 介入了三次：本体设计、角色铸造、参数生成。

MiroFish 不是 RAG（不是对静态文档做问答），不是 character chat（不是让 LLM 单纯角色扮演），不是 ABM（不是跑固定规则的多 Agent 仿真）。它是这三者的**串联**。

### B. 世界由两个底座承载

- **图谱**（Zep）= 静态事实 + 关系 + 时间属性
- **进程**（OASIS subprocess）= 动态行为 + 时间演化

图谱是"世界的记忆"，进程是"世界的活法"。两者通过 Graph Memory Updater 双向耦合：图谱的事实进入 Agent 的 persona，Agent 的行为又写回图谱。

### C. 世界活着是产品的灵魂

模拟主循环结束后，子进程不退出。它进入"采访模式"，等用户问问题。这把 MiroFish 从"批处理工具"变成"可对话的世界"。前端的 InteractionView 让用户和 Report Agent 聊、单独采访任意 Agent、批量 survey——所有这些都建立在"世界还活着"这个前提上。

### D. 阅读世界靠 ReACT + 工具栈

报告不是"模拟跑完后的日志摘要"，是 LLM 拿一组工具去主动调查世界。InsightForge 的"自动子问题分解"和 InterviewAgents 的"对活进程发问"，是工具栈里两个最有创造性的设计。

### E. 全自动化是产品立场

任何时候用户能不填的参数，都让 LLM 填。代价：不可重现、贵。收益：门槛低到普通人能用。

---

## 4. 表层选择 vs 核心机制

| 维度 | MiroFish 当前选择 | 是否核心 |
|---|---|---|
| 应用领域 | 社交媒体舆论 | 表层 |
| 本体类型限定 | 必须能在社媒发声的主体 | 表层（改 prompt 即可） |
| 动作词表 | OASIS 的 post/like/comment/follow… | 表层（换 substrate 即可） |
| 平台双轨 | Twitter + Reddit | 表层（任意双轨都行） |
| 时间模型 | 24h "中国人作息" | 表层（换文化 / 换尺度都可） |
| LLM 设计本体（10 + 兜底 2） | 是 | **核心**（泛化性来源） |
| 图谱作为世界记忆 | Zep / Graphiti | **核心**（后端可换，范式不能换） |
| 节点 → Agent 1:1 铸造 | 是 | **核心**（"可发声"的来源） |
| 进程隔离 + filesystem IPC | 是 | 半核心（范式核心，方案可优化） |
| 模拟结束后子进程 alive | 是 | **核心**（产品灵魂） |
| ReACT + 工具栈做综合 | 是 | **核心**（工具集可扩展） |
| 全自动化 | 是 | 产品立场（可放弃） |
| Flask + Vue 3 | 是 | 表层 |

---

## 5. 值得借鉴的设计模式

1. **LLM-driven ontology with hard structural constraints**——10 个、8 + 2 兜底、属性命名规则严格强制。让 LLM 自由发挥但给硬约束，避免输出失控。
2. **多步骤生成 + JSON 修复 + 重试**（`simulation_config_generator` 里的 `_call_llm_with_retry` + `_fix_truncated_json`）—— 长输出的工程化处理范式。
3. **Subprocess 即"世界容器"**——单 OS 进程承载完整模拟状态，崩了不影响主服务，也是天然的状态边界。
4. **Filesystem-based IPC**——简单、可调试、跨平台。命令文件是人类可读 JSON，错误诊断成本极低。
5. **后台任务 + Task Manager 单例 + progress_callback**——经典异步任务模式，`stage_weights` 把多阶段进度合成单个 0–100% 数字给前端。
6. **"上帝视角"系统提示词**——把 LLM 框定在一个明确的认知姿态里，比通用 framing（"你是分析师"）有效得多。
7. **InsightForge 的子问题分解**——用户问 X → LLM 拆成 X1/X2/X3 → 各自检索 → 合并。
8. **Live agent interview**——综合 Agent 的工具集里包含一个"调用活进程"的工具，让综合 Agent 能问"原住民"。
9. **API endpoint 显式标注在 UI 上**——`POST /api/graph/ontology/generate` 直接写在 step card 里。这是开发者审美的反向 dogfooding。
10. **subprocess 入口的独立可运行性**——`run_parallel_simulation.py` 不依赖 Flask，本地能直接跑。本地调试和生产部署共用同一条入口。

---

## 6. 已识别的局限与风险

1. **不可重现性**。每次跑出的世界不一样，研究场景是缺陷，创作场景反而可能是优点。
2. **成本高**。README 自己说"高消耗，先试 <40 轮"。本体生成 + N 个 profile + N 个 agent config + 双平台每轮每 active agent 一次推理 + 报告生成（每章节最多 5 次工具调用，工具内部还会再触发若干 LLM 调用）≈ 几十到几百 K tokens 起步，跑大点上千 K。
3. **Zep 依赖**。整个图谱层是 SaaS。免费额度跑得起 demo，跑生产要付费。如果 Zep API 涨价或下线，整个图谱层需要重做（虽然 GraphRAG 范式可以用 Neo4j + 自建抽取管道复刻）。
4. **OASIS 耦合**。脚本里直接 `from camel.societies.workforce import ...` 之类，换 substrate 不是 trivial 工作。
5. **中文 / 作息硬编码**。时间模型、prompt 语言切换、persona 国家默认值都隐含中文场景假设。`get_language_instruction()` 提供了切换接口，但 24h 活跃曲线本身是常量。
6. **"回声室 / 极化"被参数化**。`echo_chamber_strength` 是 PlatformConfig 字段——预设了模拟会出现这个现象。如果这个先验错了，模拟结果会被推往那个方向。
7. **报告 Agent 的"上帝视角"姿态**会让它过度自信地下结论。"未来预测"这个 framing 在严肃决策场景有误导风险——它鼓励 LLM 用断言式语言写不确定的事。

---

## Sources

- 仓库：[github.com/666ghj/MiroFish](https://github.com/666ghj/MiroFish)
- 本文基于 main 分支代码（约 16k 行 Python + Vue 3 前端）逐文件阅读得出，未引用外部材料
- 关键代码路径：
  - `backend/app/services/ontology_generator.py`
  - `backend/app/services/graph_builder.py`
  - `backend/app/services/oasis_profile_generator.py`
  - `backend/app/services/simulation_config_generator.py`
  - `backend/app/services/simulation_runner.py`
  - `backend/app/services/simulation_ipc.py`
  - `backend/app/services/zep_graph_memory_updater.py`
  - `backend/app/services/zep_tools.py`
  - `backend/app/services/report_agent.py`
  - `backend/app/api/graph.py`
  - `backend/app/api/simulation.py`
  - `backend/app/api/report.py`
  - `backend/scripts/run_parallel_simulation.py`
  - `frontend/src/components/Step{1..5}*.vue`
  - `frontend/src/router/`
- README：`/tmp/MiroFish/README.md`
