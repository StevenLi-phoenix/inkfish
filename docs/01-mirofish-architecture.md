# MiroFish 架构调研：从第一性原理拆解

> 调研对象：[666ghj/MiroFish](https://github.com/666ghj/MiroFish) — "简洁通用的群体智能引擎，预测万物"
> 调研目的：把它的核心机制提炼出来，看哪些可以迁移到小说写作（INKFISH）
> 范围：v0.1.0 主干代码（backend ~16k 行 Python，frontend Vue 3）

---

## TL;DR（一段话版本）

MiroFish 把"上传文档 + 用自然语言写需求"翻译成一个由 LLM 设计、由知识图谱承载、由多智能体在双社交媒体平台演化、由 ReACT Agent 输出的预测报告。它的真正价值不在"社交媒体模拟"这个表层应用，而在**七步骤的可复用流水线**：本体设计 → 图谱构建 → 角色铸造 → 配置生成 → 进程化运行 → 实时反向写回 → 检索式综合输出。表层换掉就是另一个产品。

---

## 1. 系统全景

### 1.1 大流程

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Stage 1     │  │  Stage 2     │  │  Stage 3     │
│  本体设计    │  │  图谱构建    │  │  角色铸造    │
│  Ontology    │→ │  GraphRAG    │→ │  OASIS       │
│  Generator   │  │  (Zep)       │  │  Profiles    │
└──────────────┘  └──────────────┘  └──────────────┘
                                           │
                                           ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Stage 6     │  │  Stage 5     │  │  Stage 4     │
│  报告 +      │  │  双平台并行  │  │  模拟参数    │
│  深度互动    │← │  模拟运行    │← │  智能生成    │
│  Report Agent│  │  Twitter+    │  │  Sim Config  │
│              │  │  Reddit      │  │  Generator   │
└──────────────┘  └──────────────┘  └──────────────┘
       ↑                  │
       │                  ▼ (可选)
       │           ┌──────────────┐
       └──────────│  Graph Memory│  ← 模拟过程中实时把
                   │  Updater     │     Agent 行为写回 Zep
                   └──────────────┘
```

### 1.2 进程拓扑

```
Flask 主进程 (port 5001)
├─ HTTP API (3 个 Blueprint: graph / simulation / report)
├─ Background Threads (TaskManager 单例追踪)
└─ Subprocess Pool: 每个 simulation_id 一个 OASIS 子进程
   ├─ 通过 simulation_dir/commands/ 接命令
   └─ 通过 simulation_dir/responses/ 回结果
        ↑
        Filesystem-based IPC (轮询，无 socket，无 mq)
```

进程隔离是个**深思熟虑的简化**：每个模拟 = 一个 OS 进程 = 一个文件夹。状态全在文件系统里。崩溃了重启 Flask 也不丢东西。代价：IPC 慢（轮询）、不能跨机器。在"研究型工具 + 个人工作站"的场景下这个 trade-off 完全成立。

---

## 2. 七个核心机制（按执行顺序）

### 2.1 本体设计（Ontology Generation）

**位置**：`backend/app/services/ontology_generator.py`

LLM 读用户文档 + 模拟需求，输出 JSON：
- 10 个实体类型（**强制**：8 个具体 + 2 个兜底 `Person` / `Organization`）
- 6–10 个关系类型（`WORKS_FOR` / `REPRESENTS` / `REGULATES` / `REPORTS_ON` / `SUPPORTS` / `OPPOSES` …）
- 每个类型 1–3 个属性（PascalCase / snake_case / UPPER_SNAKE_CASE 严格强制）

**关键设计决策**：

1. **本体不是给定的，是 LLM 设计的。** 不预设 schema，让 LLM 根据具体材料决定"这次要建模哪些角色类型"。这是整个系统的可泛化性来源。
2. **强约束实体必须是"能在社媒上发声的主体"。** 系统提示词明确禁止抽象概念、话题、立场作为实体。这是把"通用图谱"窄化为"可模拟图谱"的关键。
3. **兜底类型保证全集覆盖。** 任何文本里出现的人都能落入 `Person`，任何组织都能落入 `Organization`。LLM 不需要为冷门类型纠结。

**第一性原理意义**：本体决定了世界由什么组成。它的两个功能是 (a) 给图谱做类型约束，(b) 给后续 Agent 铸造分流（个人 vs 群体走不同 prompt）。

### 2.2 图谱构建（GraphRAG via Zep）

**位置**：`backend/app/services/graph_builder.py`

调用 [Zep Cloud](https://www.getzep.com/) 的 Graphiti API：
- `create_graph(name)` → 拿到 `graph_id`
- `set_ontology(graph_id, ontology)` → 应用类型约束
- `add_text_batches(chunks, batch_size=3)` → 异步喂入分块文本
- `_wait_for_episodes(uuids, callback)` → 轮询等 Zep 抽完
- `get_graph_data(graph_id)` → 拿节点+边

**关键设计决策**：

1. **不自己建图，外包给 Zep。** 图抽取、向量化、时序事实管理（"这个事实当前有效"vs"这个事实已过期"）都是 Zep/Graphiti 的强项。
2. **分块策略简单**（默认 chunk_size=500, overlap=50），靠 Zep 的语义聚类去重。
3. **图构建是异步的**（Flask 起后台线程，前端拿 task_id 轮询进度）。

**第一性原理意义**：用一个**时序知识图谱**当世界记忆。它有两个一等公民：节点（实体）和带时间属性的边（事实）。后续所有"检索"和"上下文构建"都在这上面。

### 2.3 角色铸造（OASIS Profile Generation）

**位置**：`backend/app/services/oasis_profile_generator.py`

每个图谱节点 → 一个 Agent profile：
- 先 `_search_zep_for_entity` 用实体名在图里检索一遍，把节点摘要 + 相关边拼成上下文
- 区分**个人** vs **群体/机构**，走不同的 prompt
- LLM 输出 JSON：bio (200 字) + persona (2000 字纯文本) + age + gender + MBTI + country + profession + interested_topics
- 并行生成（默认 5 并发）
- 输出两份格式：`twitter_profiles.csv` + `reddit_profiles.json`

**关键设计决策**：

1. **节点 → Agent 是 1:1。** 图里有多少实体就有多少 Agent，不做聚合。
2. **persona 是 2000 字自由文本而非结构化字段。** 这个选择保留了角色的"模糊性"，给 LLM 演 Agent 时留足腾挪空间。
3. **个人 vs 机构二分法**。机构 Agent 强制 age=30, gender=other, mbti 偏 ISTJ（"严谨保守"）—— 给"机构发言"一个稳定的人格基线。
4. **"个人记忆"和"机构记忆"作为 persona 的必填段。** 强制写入"这个人/这个机构在原始事件里已经做了什么"——给模拟一个起跑姿势。

**第一性原理意义**：把"图里的一个名字"具象化为"会说话的角色"。这一步是死东西变活东西的临界点。

### 2.4 模拟参数智能生成（Sim Config Generation）

**位置**：`backend/app/services/simulation_config_generator.py`（**991 行**——最大的服务文件之一）

LLM 分四步生成完整模拟参数：

1. **TimeSimulationConfig**：总时长（默认 72h）、每轮代表的分钟数（60min）、24 小时活跃曲线（早间/工作/晚高峰/凌晨各有 multiplier，硬编码"中国人作息"）
2. **EventConfig**：初始帖子（哪几个 Agent 发布、内容是什么）、定时事件（在第 X 小时触发什么）、热点话题关键词、舆论引导方向
3. **AgentActivityConfig × N**（分批生成，每批 15 个）：每个 Agent 的 activity_level / posts_per_hour / active_hours / sentiment_bias / stance / influence_weight
4. **PlatformConfig**：推荐算法权重（recency / popularity / relevance）、病毒传播阈值、回声室强度

**关键设计决策**：

1. **"无需手动设置参数"是产品立场。** LLM 接管所有调参——降低用户门槛，但也意味着每次跑都不可重现。
2. **分步生成 + 重试机制**。一次性生成 N 个 Agent 的配置容易超长 / 截断，所以分批 + JSON 修复（`_fix_truncated_json`）。
3. **时间模型耦合了文化假设**（中国人作息）。要做国际化或要做小说，这层得改。

**第一性原理意义**：模拟需要时间律 + 个体行为律 + 环境律。这三套律法都从 LLM 推断出来，而不是用户填表。

### 2.5 双平台并行运行（Subprocess + IPC）

**位置**：`backend/app/services/simulation_runner.py` + `backend/scripts/run_parallel_simulation.py` + `backend/app/services/simulation_ipc.py`

**做法**：

```python
subprocess.Popen([
    python, "backend/scripts/run_parallel_simulation.py",
    "--config", simulation_config.json,
    "--max-rounds", N
], cwd=simulation_dir, start_new_session=True, ...)
```

子进程里跑 [OASIS](https://github.com/camel-ai/oasis)（CAMEL-AI 的社交模拟引擎），每轮：
- 选当前活跃的 Agent（基于时间 multiplier × activity_level）
- 给 Agent 喂"当前时间线 + 你能看到的帖子"
- Agent LLM 决策：从 `OASIS_TWITTER_ACTIONS` / `OASIS_REDDIT_ACTIONS` 里选一个动作（CREATE_POST / LIKE_POST / REPOST / FOLLOW / CREATE_COMMENT / DO_NOTHING …）
- 写到 `twitter/actions.jsonl` 和 `reddit/actions.jsonl`

**Twitter + Reddit 同时跑**——同一批 Agent，同一份 persona，在两个推荐算法不同的平台上独立演化。给"同一批人在不同环境会发生什么"两个独立观测。

**主循环结束后子进程不退出**：进入 IPC 等待模式，监听 `commands/*.json`，可以接 `interview_agent` / `interview_batch` / `close_env` 命令。

**关键设计决策**：

1. **进程隔离 = 状态隔离 = 故障隔离。** Flask 永远不会因为某个模拟挂掉而崩。
2. **Filesystem IPC** 而不是 socket：跨平台、可调试（命令是人类可读 JSON）、简单。代价是延迟（轮询 0.5s 左右）。
3. **"模拟结束 ≠ 世界关闭"。** 这个设计是产品的灵魂——结束后还能采访 Agent，让用户和模拟世界保持对话。
4. **subprocess 命令行接口很干净**：`python script --config foo.json` 可以独立运行，不依赖 Flask。这是好的工程纪律。

**第一性原理意义**：进程是世界的容器。世界活着 = 进程活着 = IPC 通道开着。

### 2.6 图谱记忆反向更新（可选）

**位置**：`backend/app/services/zep_graph_memory_updater.py`

启用 `enable_graph_memory_update=True` 后：
- 模拟主循环每产生一个 Agent action（"张三发了一条帖子说……"）
- 由独立 worker thread 批量打包成自然语言 episode
- 异步写回 Zep 图谱

**第一性原理意义**：模拟过程**改变**了世界状态。如果世界状态只在内存里，模拟一结束就没了。把它写回图谱 = 让"模拟历史"成为图谱事实，下次跑或者后续报告 Agent 检索时能看见。

这是闭环：**输入 → 世界 → 模拟 → 改变世界 → 下一次输入**。

### 2.7 ReACT 报告生成（Report Agent）

**位置**：`backend/app/services/report_agent.py`（**2572 行**——最大的文件）

两阶段：

**A. 大纲规划**
- LLM 拿到 simulation_requirement + 图谱统计（节点数/边数/类型分布）+ top-10 相关事实
- 输出 2–5 个章节的目录
- 系统提示词的核心立场是"上帝视角 + 未来预测报告"

**B. 章节生成（每章节走 ReACT 循环）**
- 工具集 4 个：
  - **InsightForge**：LLM 把问题拆成子问题 → 每个子问题做语义搜索 → 收集事实 + 实体 + 关系链 → 整合成深度洞察。这是最重的工具。
  - **PanoramaSearch**：拿全貌（包括过期事实），看事件演化轨迹
  - **QuickSearch**：单点查询
  - **InterviewAgents**：**调用还活着的子进程**，对相关 Agent 做真实采访（不是 LLM 模拟回答）
- 章节最多 5 次工具调用，最多 2 轮反思
- 写完一章保存 markdown，全部完成后拼装

**关键设计决策**：

1. **"上帝视角" framing。** 报告 Agent 不是"分析师对外部数据做综述"，而是"造世主对自己造的世界做总结"。这个 framing 影响了所有章节的语气。
2. **InterviewAgents 让报告有"原始素材"。** 报告里能引用真实 Agent 在模拟中说的话，可信度比纯 LLM 总结高很多。
3. **ReACT + 工具的设计极度模块化**：4 个工具完全独立，可以增删。

**第一性原理意义**：报告是对世界的**结构化阅读**。结构由 LLM 规划，阅读由 LLM 在工具栈上递归调用完成。

---

## 3. 前端：5 步线性流水线 + 持续在场的世界视图

5 个 Step 组件 + 6 个 view：

| 路由 | 组件 | 职责 |
|---|---|---|
| `/` | Home | 营销页 + 入口 |
| `/process/:projectId` | MainView (Step1+2) | 上传 → 本体 → 图谱 → 创建 simulation |
| `/simulation/:simulationId` | SimulationView (Step2 续) | 准备模拟（生成 profiles + config，进度条） |
| `/simulation/:simulationId/start` | SimulationRunView (Step3) | 跑模拟，看双平台 actions 流 |
| `/report/:reportId` | ReportView (Step4) | 看报告生成（左：报告，右：Agent log） |
| `/interaction/:reportId` | InteractionView (Step5) | 和 Report Agent 聊 / 单独采访任意 Agent / 批量 survey |

**视觉哲学**：左侧常驻图谱，右侧是当前步骤的工作区。"世界一直在你眼前，你在对它做事"。

**Workbench 模式细节**：每个 step card 都标了对应的 API endpoint（`POST /api/graph/ontology/generate`），把后端流水线"显式"地展示给用户——这是很罕见的、面向开发者审美的产品决策。

---

## 4. 第一性原理拆解：MiroFish 在做什么？

剥掉"社交媒体舆论模拟"这层皮，MiroFish 的**不可约简核心**是：

> **把 (语料, 意图) 翻译成一个可被 LLM 反复阅读的、活着的世界，并对它做结构化阅读。**

把这句话拆成五条原子断言：

### A. 语料 + 意图 → 世界
用户输入两件事：（1）资料（文档），（2）问题（"我想看什么发生"）。系统把这两件事翻译成一个**有类型的、有角色的、有动力学的**世界。注意翻译过程里 LLM 介入了三次：本体设计、角色铸造、参数生成。

### A 的反面：MiroFish 不是
- 不是"对静态文档做问答"（那是 RAG）
- 不是"让 LLM 角色扮演"（那是 character chat）
- 不是"跑一个固定规则的多 Agent 仿真"（那是 ABM / agent-based modeling）

它是这三者的**串联**。

### B. 世界由两个底座承载
- **图谱**（Zep）= 静态事实 + 关系 + 时间属性
- **进程**（OASIS subprocess）= 动态行为 + 时间演化

图谱是"世界的记忆"，进程是"世界的活法"。两者通过 graph memory updater 双向耦合。

### C. 世界活着是产品的灵魂
模拟主循环结束后，子进程**不退出**。它进入"采访模式"，等用户问问题。这把 MiroFish 从"批处理工具"变成"可对话的世界"。这是交互上的关键转折。

### D. 阅读世界靠 ReACT + 工具栈
报告不是"模拟跑完后的日志摘要"，是 LLM 拿一组工具去**主动调查**世界。InsightForge 的"自动子问题分解"和 InterviewAgents 的"对活进程发问"，是工具栈里两个最有创造性的设计。

### E. 全自动化是产品立场
任何时候用户能不填的参数，都让 LLM 填。代价：不可重现、贵。收益：门槛低到普通人能用。

---

## 5. 表层选择 vs 核心机制（哪些能换，哪些不能）

| 维度 | MiroFish 当前选择 | 是否核心 | 备注 |
|---|---|---|---|
| 应用领域 | 社交媒体舆论 | **表层** | 替换即变身 |
| 本体类型限定 | 必须能在社媒发声的主体 | **表层** | 改 prompt 即可 |
| 动作词表 | OASIS 的 post/like/comment/follow… | **表层** | 换 substrate 即可 |
| 平台双轨 | Twitter + Reddit | **表层** | 任意双轨都行（POV-A / POV-B 等） |
| 时间模型 | 24h 中国人作息 | **表层** | 换文化、换尺度都可 |
| LLM 设计本体 | 是 | **核心** | 这是泛化性来源 |
| 图谱作为世界记忆 | Zep/Graphiti | **核心** | 后端可换（Neo4j+ 自建管道），但范式不能换 |
| 节点 → Agent 1:1 铸造 | 是 | **核心** | 这是"可发声"的来源 |
| 进程隔离 + filesystem IPC | 是 | 半核心 | 范式核心，具体方案可优化 |
| 模拟结束后保持子进程 alive | 是 | **核心** | 产品灵魂 |
| ReACT + 工具栈做综合 | 是 | **核心** | 工具集可扩展 |
| 全自动化 | 是 | **产品立场** | 可以选择性放弃 |
| Flask + Vue 3 | 是 | **表层** | 任意 web 栈 |

---

## 6. 值得偷的设计模式（清单）

1. **LLM-driven ontology with hard structural constraints**（10 个、8+2 兜底、属性命名规则）—— 让 LLM 自由发挥但给硬约束，避免输出失控。
2. **多步骤生成 + JSON 修复 + 重试**（`simulation_config_generator` 里几乎所有 `_call_llm_with_retry` + `_fix_truncated_json`）—— 长输出的工程化处理范式。
3. **Subprocess 即"世界容器"**—— 单 OS 进程承载完整模拟状态，崩了不影响主服务。
4. **Filesystem-based IPC**—— 简单、可调试、跨平台。命令文件是人类可读的 JSON。
5. **后台任务 + Task Manager 单例 + progress_callback** —— 经典异步任务模式，stage_weights 把多阶段进度合成单个 0–100% 数字给前端。
6. **"上帝视角"系统提示词** —— 把 LLM 框定在一个明确的认知姿态里，比"你是分析师"有效得多。
7. **InsightForge 的子问题分解** —— 用户问 "X" → LLM 拆成 X1/X2/X3 → 各自检索 → 合并。比单次 RAG 召回率高很多。
8. **Live agent interview** —— 检索工具里包含一个"调用活进程"的工具，让综合 Agent 能问"原住民"。
9. **API endpoint 显式标注在 UI 上** —— `POST /api/graph/ontology/generate` 直接写在 step card 里。开发者友好的反向 dogfooding。

---

## 7. 已识别的局限与风险

1. **不可重现性**。每次跑出的世界不一样。研究场景是缺陷，创作场景反而可能是优点。
2. **成本高**。README 说"高消耗，先试 <40 轮"。本体生成 + N 个 profile + N 个 agent config + 双平台每轮每 active agent 一次推理 + 报告生成 ≈ 几十到几百 K tokens，跑大点就上千 K。
3. **Zep 依赖**。整个图谱层是 SaaS。免费额度跑得起 demo，跑生产要付费。如果 Zep API 涨价或下线，整个架构需要重做。
4. **OASIS 耦合**。脚本里直接 import OASIS。换 substrate 不是 trivial 工作。
5. **中文/作息硬编码**。时间模型、prompt 语言切换、persona 国家默认值都假设中文场景。
6. **回声室/极化的"内置"**。`echo_chamber_strength` 是参数化的——预设了模拟会出现这个现象。如果这个先验错了，模拟结果会被推往那个方向。
7. **报告 Agent 的"上帝视角"姿态**会让它过度自信地下结论。"未来预测"这个 framing 在严肃决策场景有误导风险。

---

## 8. 调研结论

MiroFish 的核心是**"LLM 设计、图谱承载、进程演化、ReACT 阅读"** 这套四步骨架。这套骨架在表面上做了"社交媒体舆论模拟"，但骨架本身和应用领域是解耦的。

**对 INKFISH 的启示**：保留四步骨架，替换四个"表层"——本体的语义层、Agent 的动作词表、运行 substrate、最终输出形态。具体设计见 `02-inkfish-design.md`。

---

## Sources
- [MiroFish GitHub](https://github.com/666ghj/MiroFish)
- 本文基于本地 clone 的 main 分支代码（约 16k 行 Python + Vue 3 前端）逐文件阅读得出，未引用外部材料
- 关键文件：
  - `backend/app/services/ontology_generator.py`
  - `backend/app/services/oasis_profile_generator.py`
  - `backend/app/services/simulation_config_generator.py`
  - `backend/app/services/simulation_runner.py`
  - `backend/app/services/simulation_ipc.py`
  - `backend/app/services/zep_graph_memory_updater.py`
  - `backend/app/services/zep_tools.py`
  - `backend/app/services/report_agent.py`
  - `backend/scripts/run_parallel_simulation.py`
