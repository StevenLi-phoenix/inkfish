# INKFISH 设计调研：把 MiroFish 的骨架搬到小说写作

> 项目代号：INKFISH（墨鱼，呼应 MiroFish）
> 状态：**纯调研 + 规划**，未决定是否实现
> 形态约束：最终是 webui
> 前置阅读：`01-mirofish-architecture.md`
>
> ⚠️ **重要更新**：本文写时假设 INKFISH 是面向多用户的产品。后来用户明确：**INKFISH 是个人写作工具**，并要求纳入酒馆 AI（SillyTavern）的经验。这两个新约束修正了本文的多个设计决策——详见 [`03-tavern-ai-and-personal-pivot.md`](./03-tavern-ai-and-personal-pivot.md)，特别是其中的 §6 "对 02 文档的补丁清单"。本文保留作为 SaaS 视角的对照。

---

## 0. 出发点

MiroFish 把"上传文档 + 写需求"翻译成一个活着的、可被结构化阅读的世界。这套骨架做小说写作天然合适：小说本来就是"一个有人物、有动力学、有阅读姿态的世界"。

但是直接把"社交媒体舆论"换成"小说人物互动"会塌——小说和社媒舆论的核心区别决定了多个层面要重新设计。本文的目的是**逐层判断**哪些可以照搬、哪些必须改、哪些是开放问题。

---

## 1. 小说 vs 社媒舆论：核心差异

| 维度 | MiroFish（社媒舆论） | INKFISH（小说写作） |
|---|---|---|
| 用户的真正诉求 | 看一个**预测** | 拿到**作品本身**（章节文本） |
| 时间律 | 物理时间，匀速，24h 周期 | 故事时间，非匀速，按场景/章节切分 |
| 角色状态 | 立场基本不变（反映舆论分布） | **角色弧光是核心**——不变就没小说 |
| 动作词表 | post/like/comment/repost/follow | speak/act/observe/think/conceal/decide/recall |
| 互动 substrate | Twitter / Reddit | 场景（scene）—— 一次同时同地的人物聚合 |
| 涌现追求 | 群体观点分布 | 戏剧性、张力、节奏 |
| 用户角色 | 观察者 | **共同作者**——要在每一层都能介入 |
| 输出价值 | 决策支持 / 娱乐 | 可读性、独特声音、连贯性 |
| 失败模式 | 极化失真 | 平淡、自相矛盾、AI 腔 |

**最关键的差异是用户角色**：MiroFish 用户上传完就等结果。INKFISH 用户要全程参与——"换一个 POV 重写这场"、"如果她拒绝呢？"、"她现在在想什么？"。这意味着所有阶段都得是**可介入的、可分叉的、可回滚的**。

---

## 2. 七步骨架的逐项映射

我把 MiroFish 的 7 个核心机制（见 `01` §2）逐个翻译到 INKFISH，标注**保留 / 改造 / 重做**。

### 2.1 本体设计 → "故事本体设计"【改造】

**MiroFish 输出**：10 类实体（8 具体 + 2 兜底）+ 关系类型，所有实体必须能在社媒发声。

**INKFISH 输出**：
- **角色类型** 4–6 个（如 protagonist / antagonist / mentor / foil / supporting）+ 1 个兜底 `Character`
- **场所类型** 2–4 个 + 1 个兜底 `Place`
- **物件类型** 0–3 个（only if 物件在故事里有戏份，如 MacGuffin、信物、武器）
- **抽象/主题类型** 0–2 个（如 `Theme`、`Secret`——这些**不能发声**，但要在图里被引用）
- **关系类型** 8–15 个：
  - 情感类：LOVES / HATES / TRUSTS / BETRAYED_BY / OWES
  - 结构类：PARENT_OF / SIBLING_OF / MENTOR_OF
  - 叙事类：PROTAGONIST_OF / ANTAGONIST_TO / FOIL_FOR
  - 空间/时态类：LOCATED_IN / PRESENT_AT / KNOWS_ABOUT

**关键差异**：
1. MiroFish 只允许"能发声的实体"。INKFISH 必须允许 `Theme` / `Secret` / `Setting` 这些**不发声但很重要**的实体，否则建模能力残缺。
2. INKFISH 需要**叙事角色**类型（protagonist 等），这是 MiroFish 没有的——因为社媒模拟里没有"主角"概念。
3. MiroFish 的 ontology 系统提示词带有非常强的产品立场（"必须能在社媒发声"）。INKFISH 需要类似强度的立场——比如"实体必须能引发 reader 的情感投入或代表故事的某个机械部件"。

**开放问题**：
- 类型数量上限给多少？小说里可能就 5 个主要角色，硬塞 8 类反而稀释。
- 是否要让用户选"故事流派"（悬疑/言情/科幻），不同流派给不同 ontology 模板？

### 2.2 图谱构建 → "故事图谱"【保留 + 强化】

继承 Zep/Graphiti 的时序图能力，但**强化**两点：

1. **Episode = 场景**。MiroFish 的 episode 就是文档分块。INKFISH 的 episode 应该是"一个场景的内容"——这样图谱的时序结构和小说的场景结构对齐。这意味着分块策略不能是 chunk_size=500，要按场景切。
2. **关系的时间属性更重要**。"Maria 信任 Pedro" 在第 3 章为真，第 7 章为假——Graphiti 已经原生支持事实过期，要充分利用。这给"角色弧光"提供了天然的数据结构。

**开放问题**：
- Zep 是否真的擅长处理小说级别的语义复杂度？社媒帖子是结构化的短文本，小说是充满隐喻的长文本。要做一个 PoC：拿 5 万字的开篇喂进 Zep，看抽出来的图谱长什么样。
- 自建（Neo4j + 自己写抽取 pipeline）vs 用 Zep 的取舍要根据 PoC 结果决定。短期 Zep，长期可能要换。

### 2.3 角色铸造 → "人物深度档案"【改造】

**MiroFish persona** = bio (200 字) + persona (2000 字) + age/gender/MBTI/profession/topics

**INKFISH character profile** 应该至少包含：
- **身份层**：bio / age / 外貌 / 职业 / 出身
- **心理层**：核心欲望 / 恐惧 / 自我认知 vs 真实 / MBTI 或 enneagram / 创伤
- **声音层**：说话节奏 / 词汇偏好 / 句式特征 / 不会说什么 / 口头禅
- **关系层**：和图里其他角色的具体关系（不只是"LOVES"，要有"她爱他但她不知道为什么"这种细节）
- **弧光层**：起点状态 / 转折触发条件 / 终点状态 / 当前所处阶段
- **秘密层**：角色知道但还不能说出来的东西（first-class，因为戏剧张力来源）

**关键改造**：
- **声音层**和**秘密层**是 MiroFish 没有的。声音决定"她说话像她"，秘密决定"她有戏可演"。
- 配角（兜底 `Character`）可以走简化模板，主要角色必须深度档案。
- profile 应该可以**手工编辑**——MiroFish 是全自动，INKFISH 必须留人工 override 入口。

**开放问题**：
- 多少字算够？2000 字给 LLM 演太长，500 字不够。可能 800–1200 字 + 50 字"声音速记"是个甜点。
- "弧光层"是 LLM 决定还是用户决定？如果 LLM 决定，每次跑结果不同；如果用户决定，门槛高。两个都要支持。

### 2.4 模拟参数生成 → "故事节拍配置"【**重做**】

这是最需要重新设计的一层。MiroFish 的 sim config（24 小时活跃曲线、posts_per_hour）对小说毫无意义。

INKFISH 需要的**节拍配置**：

1. **时间模型**：不是"每轮 60 分钟"，而是"故事跨度（一晚/一周/二十年）+ 节拍密度（每章 N 个场景）+ 时间跳跃规则"。
2. **场景计划**：而不是"初始 posts"。结构上类似——LLM 根据 simulation requirement 生成一个初始场景列表（"开场：Maria 在咖啡馆收到信"），加可选的关键节点场景（"中段：Pedro 的真相揭露"）。
3. **角色出场曲线**：每个角色在哪些章节出现、和谁同台。
4. **戏剧张力曲线**：开局/上升/高潮/下落/结局的张力目标值（0–1），让生成时有结构遵循而非平铺。
5. **POV 策略**：第一人称还是第三人称、是否多 POV、视角切换的章节边界。
6. **风格参数**：节奏（slow / brisk / cinematic）、语气（dry / lyrical / hardboiled）、可见的影响作家清单（"试着像 Le Guin 那样描述权力"）。

**关键差异**：
- MiroFish 的 config 是"系统怎么跑"。INKFISH 的 config 是"故事长什么样"——更接近"导演指南"。
- 这一层很难纯靠 LLM 自动化。用户对节奏、张力、POV 有强烈偏好。**这一层应该提供 LLM 草案 + 用户编辑的混合界面**。

### 2.5 进程化运行 → "场景模拟器"【保留范式 + 重做 substrate】

**保留**：
- 一个 simulation_id 对应一个 OS 子进程
- 子进程跑完不退出（进入交互模式）
- 文件系统 IPC（commands/ + responses/）
- 进度通过 `scenes/*.jsonl` 写文件，前端轮询

**必须重做的是 substrate**。OASIS 是社媒模拟引擎，它的循环是"每个 active agent 选一个社媒动作"。INKFISH 需要"场景循环"：

```
for scene in scene_plan:
  participants = [characters present at this scene]
  scene_setup = LLM(time, place, weather, what just happened)
  for beat in scene:
    # 一个 beat = 一次主角发起 + 反应链
    speaker = pick_next_speaker(scene_state, participants)
    action = speaker.decide(scene_state, world_facts, participants)
    # action ∈ {speak, act, observe, recall, plan, lie, conceal, reveal, decide, leave}
    update_scene_state(action)
    update_world_facts_if_relevant(action)
  scene_summary = LLM(scene_log)
  write_to_zep_as_episode(scene_summary)
```

**两条可选 track 跑并行**（替代 Twitter / Reddit）：
- **Option A: POV 双轨** —— 同一场景生成两份不同 POV 的叙述，给作者挑
- **Option B: 草稿/大纲双轨** —— 一边生成"场景实录"（行为日志风格），一边生成"小说化的散文叙述"
- **Option C: 风格双轨** —— 同一场景两种语气版本

我倾向 **Option B**，因为它解决了 MiroFish 没解决的问题：把"模拟产物"转换为"可读作品"。

**保留 MiroFish 的 IPC 等待模式**：场景跑完后，子进程留着，用户可以：
- "采访" 任意角色（"你为什么那时候选择沉默？"）
- 让某个角色"重做"刚才的决策
- 注入新事件 / 新角色，从某场景重跑

### 2.6 图谱记忆反向更新 → "世界状态演进"【**强化**】

MiroFish 这个功能是可选的（`enable_graph_memory_update=False` by default）。INKFISH 必须**默认开启**，因为没了它故事会自相矛盾——第 5 章 Maria 知道了 Pedro 的秘密，第 8 章不知道——这就是 LLM 写小说最大的崩溃模式。

具体强化：
1. **每个场景结束自动写回**，不是 batch。
2. **写回内容要分层**：
   - 客观事实（"信被烧了"——所有人都知道）
   - 角色内部状态（"Maria 决定不告诉 Pedro"——只有 Maria 自己知道）
   - 关系状态变化（TRUSTS 边过期，DISTRUSTS 边创建）
3. **角色的"知道集"** 要严格隔离——这是写群戏的关键。MiroFish 不需要这个（社媒舆论里大家都看公开 timeline），INKFISH 必须有。

**开放问题**：
- "知道集"怎么在 Zep 里建模？最简单是给每条边加 `known_by: [character_uuids]` 字段。但 Zep 的 schema 灵活度需要确认。
- 写回的延迟容忍度。如果每场景都同步写，慢；批量异步写，可能下一场景看不到上一场景的结果。

### 2.7 ReACT 报告生成 → "手稿生成 + 评论 Agent"【拆成两个】

MiroFish 的 ReportAgent 干两件事：规划目录 + 写章节。INKFISH 应该把它**拆成两个 Agent**：

#### 2.7.1 Manuscript Agent（写手稿）
- 工具栈：
  - `WorldQuery`：查图谱事实（替代 InsightForge）
  - `CharacterInterview`：问活进程里的角色（保留 InterviewAgents）
  - `SceneRetrieve`：拿原始场景日志
  - `CharacterVoice`：拿某个角色的"声音速记"（保证对白不串味）
  - `StyleSample`：拿用户提供的风格样本
- 模式：按章节大纲，逐章节写。每章节走 ReACT：先查相关场景 → 找当时的世界状态 → 读相关角色的声音 → 写散文。
- 输出：markdown 章节文件 + 章节元信息（涉及哪些场景、引用了哪些事实、哪个 POV）

#### 2.7.2 Critique Agent（评论 / 一致性检查）
- 工具栈：
  - 同上 + `ContradictionCheck`（找 Maria 在第 3 章金发、第 7 章棕发这种）
  - `PacingCheck`（章节字数 / 张力曲线偏差）
  - `VoiceDriftCheck`（人物对白是否出戏）
- 模式：每章节写完，自动跑一遍 critique，把发现写成"修改建议"——交给用户决定是否接受。
- 这是 MiroFish 完全没有的功能，但对小说写作价值巨大。

**关键设计决策**：
- **Manuscript Agent 不应该一次性写整本书**。应该一章一暂停，给用户编辑/重写的机会。MiroFish 是 "submit and forget"，INKFISH 是 "draft and dialog"。
- "上帝视角" framing 不适用——manuscript agent 需要"从内部"的姿态（POV 角色的眼睛）。critique agent 才是上帝视角。

---

## 3. INKFISH 整体架构草案

### 3.1 流水线

```
┌─────────────────────┐
│ Stage 0: 创意收集    │ (新增)
│ 用户上传：           │
│ - 灵感笔记 / 大纲    │
│ - 影响作家 / 风格样本│
│ - 人设草稿（可选）   │
│ - 一句话premise      │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Stage 1: 故事本体    │
│ 角色类型 + 关系类型  │
│ + 场所/物件/主题类型 │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Stage 2: 故事图谱    │
│ Zep + 按场景的 episode│
│ + known_by 隔离      │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Stage 3: 人物深度档案│
│ 6 层 profile 生成    │
│ 用户可编辑           │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Stage 4: 节拍配置    │
│ LLM 草案 + 用户编辑  │
│ - 时间模型           │
│ - 场景计划           │
│ - 张力曲线           │
│ - POV 策略           │
│ - 风格参数           │
└──────────┬──────────┘
           ▼
┌─────────────────────┐    ┌──────────────────────┐
│ Stage 5: 场景模拟    │ ←→ │ 实时世界状态更新      │
│ 双 track 并行：       │    │ (默认开启)            │
│ - 场景日志 track     │    │ - 客观事实层          │
│ - 散文叙述 track     │    │ - 角色内部状态层      │
│ 每场景跑完暂停        │    │ - 关系状态变化        │
└──────────┬──────────┘    └──────────────────────┘
           ▼
┌─────────────────────┐
│ Stage 6: 手稿生成    │
│ Manuscript Agent     │
│ + Critique Agent     │
│ 一章一审，可重写      │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Stage 7: 共创对话    │
│ 子进程仍在 → 任意时刻│
│ 采访角色 / 重写场景  │
└─────────────────────┘
```

### 3.2 目录结构提案

```
inkfish/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── ontology.py
│   │   │   ├── graph.py
│   │   │   ├── characters.py
│   │   │   ├── pacing.py
│   │   │   ├── scenes.py
│   │   │   ├── manuscript.py
│   │   │   └── critique.py
│   │   ├── services/
│   │   │   ├── story_ontology_generator.py
│   │   │   ├── story_graph_builder.py
│   │   │   ├── character_profile_generator.py
│   │   │   ├── pacing_config_generator.py
│   │   │   ├── scene_runner.py            # 替代 simulation_runner
│   │   │   ├── scene_ipc.py               # 同 MiroFish 的 IPC
│   │   │   ├── world_state_updater.py     # 替代 zep_graph_memory_updater
│   │   │   ├── manuscript_agent.py        # 替代 report_agent
│   │   │   └── critique_agent.py          # 新增
│   │   └── models/
│   │       ├── project.py
│   │       ├── character.py
│   │       ├── scene.py
│   │       └── chapter.py
│   └── scripts/
│       ├── run_scene_simulation.py
│       └── run_manuscript_assembly.py
└── frontend/                              # Vue 3，保留 MiroFish 的左侧常驻 + 右侧步骤布局
```

### 3.3 前端的 7 视图

| 路由 | 用途 | 左侧持久面板 |
|---|---|---|
| `/` | Home / 项目列表 | — |
| `/project/:id/seed` | Stage 0+1：上传灵感 + 看本体 | 本体可视化 |
| `/project/:id/world` | Stage 2+3：图谱 + 角色卡 | 故事图谱 |
| `/project/:id/pacing` | Stage 4：节拍配置 | 张力曲线图 |
| `/project/:id/scenes` | Stage 5：场景模拟 | 场景图谱 + 角色状态 |
| `/project/:id/manuscript/:chapter` | Stage 6：章节阅读 + 编辑 | 章节大纲 |
| `/project/:id/dialog` | Stage 7：和角色对话 | 角色档案 |

### 3.4 核心数据流

```
project_id (proj_xxxx)
  ├── seed/                  # Stage 0 上传
  ├── ontology.json
  ├── graph_id (在 Zep)
  ├── characters/
  │   └── char_xxx.json      # 6 层档案 + 用户编辑历史
  ├── pacing.json            # 节拍配置
  ├── scenes/
  │   ├── scene_001.jsonl    # 场景行为日志
  │   ├── scene_001.prose.md # 散文叙述 track
  │   └── ...
  ├── chapters/
  │   ├── ch_01.md           # manuscript agent 输出
  │   ├── ch_01.critique.md  # critique agent 输出
  │   └── ...
  └── dialog/
      └── interview_log.jsonl
```

---

## 4. 决策清单（要做的、可能要做的、暂时不做的）

### 必做（第一性原理上不能省）

1. LLM 设计本体（保留 MiroFish 范式）
2. 时序知识图谱当世界记忆（用 Zep 起步）
3. 节点 → 角色 1:1 铸造，但 profile 是 6 层结构
4. 进程隔离 + filesystem IPC（保留 MiroFish 范式）
5. **场景**作为 substrate（替代社媒动作）
6. 默认开启世界状态实时更新 + 知道集隔离
7. ReACT + 工具栈做手稿生成
8. 模拟跑完保持子进程 alive 供共创对话
9. 节拍配置必须有人工编辑入口
10. critique agent 一章一审

### 可能做（要看 PoC 数据）

1. 双 track 场景生成（场景日志 + 散文叙述）—— 取决于"散文 track 是否真的更可读"
2. 多影响作家 / 风格样本注入 —— 涉及版权和模型记忆问题
3. 自建图谱后端替代 Zep —— 取决于 Zep 在长文本场景的表现
4. 张力曲线作为软约束注入 simulation —— 取决于"无引导能否产生戏剧性"
5. 角色弧光自动追踪 —— 实现起来可能很复杂

### 暂时不做

1. 多用户协作（一人一项目就够，第一版别碰这个）
2. 出版工作流（导出 epub/docx/pdf 等，做完核心再说）
3. 视觉化（人物头像、场景插图）—— 容易成为"看起来很好但没用"的功能
4. 评论社区 / 分享功能
5. 移动端

---

## 5. 已识别的风险（按严重度排序）

### R1【高】LLM 写散文质量天花板
最大未知数。Manuscript Agent 能不能产出"读起来像人类作家写的"散文，是产品成立的前提。**风险缓解**：先做最小 PoC——人工准备 1 个角色、1 个场景，让 LLM 把场景日志转成 500 字散文。如果这一步过不了关，整个 INKFISH 不成立。

### R2【高】世界状态一致性
群戏 + 多 POV + 长时间跨度，自相矛盾几乎必然。Zep 的事实过期机制能解决一部分，"知道集"隔离能解决一部分，剩下的要靠 critique agent。**风险缓解**：critique agent 必须做得比 manuscript agent 还好。

### R3【中】用户介入成本
INKFISH 假设用户是"共同作者"，但 7 阶段流水线 + 每章节审核很重。普通用户可能放弃。**风险缓解**：每个阶段都给"全自动通过"按钮，让懒用户能跑通；高阶用户能逐层介入。

### R4【中】成本
小说级别（5–10 万字）的 LLM 调用 token 数可能是 MiroFish 一次跑的 5–10 倍。**风险缓解**：（1）不同阶段用不同模型（本体/critique 用 strong model，场景模拟用 cheap model）；（2）支持续跑——别让用户每次都从头跑。

### R5【中】流派偏置
LLM 训练数据里某些流派（YA、奇幻）远多于其他（实验文学、纯文学）。生成质量会强偏。**风险缓解**：诚实承认；提供风格样本注入做矫正。

### R6【低】版权 / 数据
用户上传未发表手稿——本地存储 + 不发回 LLM 训练 = 起步够用。

### R7【低】Zep 依赖
同 MiroFish。短期可接受，长期可换。

---

## 6. 最小可行验证（MVP 之前的 PoC）

如果**只允许做一件事**来验证 INKFISH 是否值得做，我会做这个：

> **散文转换 PoC**：手工准备 1 个 800 字的角色档案 + 1 个 200 字的场景日志（只有动作，没有描述），让 LLM 输出 500–800 字的小说散文。评估：声音是否符合档案？是否避免 AI 腔？是否需要超过 3 轮编辑才能用？

如果这一步成立，再投入做完整流水线。如果不成立，整个项目不需要继续。

第二个 PoC（如果第一个过了）：

> **三场景一致性 PoC**：手工准备 3 个场景日志，时间间隔在故事里跨度 1 周。让 manuscript agent 顺序生成 3 个章节。检查：（1）人物声音是否一致；（2）前一章节建立的事实有没有被后一章节违反；（3）情感弧线是否合理。

---

## 7. 开放问题（需要在做决定之前回答）

1. **目标用户是谁？** 半专业作家做辅助 vs 普通人做娱乐性创作 —— 两个产品长得完全不一样。
2. **要不要支持续写已有作品？** 用户上传第 1–10 章，让系统补 11+ —— 比从零开始难得多但价值大。
3. **manuscript track 和 prose track 的关系**？是 manuscript agent 读 prose track 后改写、还是直接读场景日志？两个方案的取舍是"prose track 是否值得它的成本"。
4. **节拍配置是否做"模板"？** "三幕剧"/"英雄之旅"/"Snowflake 方法" —— 给用户预设结构选，比让 LLM 自由生成可能更好。
5. **角色之间能否自由对话**（在场景之外）？比如让 Maria 和 Pedro 在 stage 7 直接对话——这种"OOC 互动"对作者有用，但对故事内一致性有冲击。
6. **如何处理 NSFW / 暴力 / 黑暗主题？** 严肃文学绕不开，但 LLM 安全策略会拒绝。
7. **是否需要"学习用户写作风格"的功能？** 上传用户已有作品作为风格样本——技术上可行，但变成"克隆作家"会有伦理问题。
8. **国际化顺序**：先做中文还是先做英文？影响 LLM 选择。
9. **Zep vs 自建**的判断点：在哪个数据规模 / 调用频次 / 月度成本下应该切换？
10. **是否允许多个并发 simulation 在同一项目下？** 比如"试两种结局"——技术上文件系统隔离能支持，但产品逻辑要想清楚。

---

## 8. 下一步建议

如果决定继续：

1. **R1 的散文转换 PoC** —— 不需要任何代码，纯 prompt + 手工评估，1 天搞定
2. 如果 PoC 成立，做**最小后端骨架**：复刻 MiroFish 的 (project + task + IPC + subprocess) 基础设施，但把 OASIS 替换成一个 stub 场景循环
3. 在 stub 场景循环上验证 (世界状态实时更新 + 知道集隔离) 是否真的能避免矛盾
4. 第一个能展示的版本：单角色单场景的"对话生成"——不要野心太大

如果决定不继续：

1. 至少把 §6 的散文转换 PoC 做了，留作判断未来 LLM 能力的 baseline
2. 把这两个文档归档到 `~/Codes/inkfish/docs/`，未来想起来时不用从零开始

---

## 9. 自检：本文论证的薄弱处与反例

写完 §1–§8 后回头审视，主动列出本文论证不够立的地方，方便后续做决策时不被自己说服。

### 9.1 反例：为什么不直接用 Sonnet/GPT 长上下文一章一章写？

最强的反对论证：**Claude Sonnet 4.6 / GPT-5 这一代模型已经能处理 200K token 上下文，理论上你可以把整个世界设定+前面所有章节塞进去，让它写下一章，根本不需要图谱、不需要多 Agent、不需要 MiroFish 那套基础设施**。

我承认这个反对意见有力。能反驳的点：
1. **几十万字小说仍然超长**。一本 8 万字的中篇小说约 16 万 token，加上世界设定+人物档案+大纲+作者风格样本，一次塞进去就接近上限，没空间给思考和工具调用。
2. **长上下文 ≠ 强一致性**。已有研究表明 LLM 在长上下文中部信息丢失严重。"图谱+检索"是给关键事实建立独立可索引的存储，比期待模型自己记住更可靠。
3. **共创交互无法靠纯生成实现**。"采访 Maria"需要 Maria 有持久身份，不能每次都是上下文里的临时片段。这是 INKFISH 的差异化。
4. **但**：如果用户只想"写一个 5000 字短篇"，INKFISH 完全过度设计。要诚实——产品价值边界在中篇及以上。

### 9.2 反例：现有 AI 写作工具已经覆盖这块了吗？

[Sudowrite](https://www.sudowrite.com/) / [NovelCrafter](https://www.novelcrafter.com/) / NovelAI 等已经在这块卷了几年。INKFISH 的差异化不能只是"我也做这个"。

读了它们的产品页，差异点应该是：
- **它们大多是"作者主导，AI 补片段"的工作流**——按 ⌘+J 让 AI 续 200 字
- INKFISH 提议的是"图谱主导，AI 演化整个世界"——这是不同的产品论
- 我没系统调研它们的实现细节，只看了营销页。**这是真实的盲区**——做之前应该读它们的 docs / blog / 反向工程。

### 9.3 论证薄弱处：双 track 必要性没证明

§2.5 我建议生成场景日志 + 散文叙述两条 track 并行（Option B），但理由（"实时给用户看可读文本"）站不住——单 track + 后处理也能给可读文本，只是非实时。

诚实结论：**双 track 的真正动机是 MiroFish 有双平台所以我也想要双轨**——这是个不好的设计动机。建议第一版**单 track**（场景日志），让 manuscript agent 在用户请求时按需生成散文。如果实测发现单 track 体验差，再上双 track。

### 9.4 论证薄弱处：critique agent 的假阳性问题

§2.7.2 我把 critique agent 当成"低风险高价值"组件。但 LLM 做一致性检查的失败模式是**假阳性**——它会把"作者故意的暗示性矛盾"标记为 bug，把"角色就是这种说话风格"标记为"voice drift"。

如果 critique 假阳性率 > 30%，用户会很快关掉这个功能。**应该把 critique 设计成"建议"而非"警报"**，并且支持用户标记 false positive 让模型学习——这一层在 §2.7.2 没写。

### 9.5 论证薄弱处："角色弧光"在图谱里怎么建模？

§2.3 我说 profile 要有"弧光层"，但没说图谱怎么承载弧光。Zep 的事实有时间过期，但"角色从相信→不相信"这种过渡是渐变的，不是 boolean 翻转。

老实说：**我不知道**。两个可能方向：
- 把弧光建模成一系列离散 episode（"第 3 章 Maria 开始怀疑 Pedro"），靠时序事实表达
- 在 character profile 里维护一个独立的"arc state"字段，每场景结束时由 LLM 评估是否进了下一阶段

要在 PoC 阶段试。

### 9.6 漏掉的设计：MiroFish 的 echo_chamber_strength 不能继承

MiroFish 的 PlatformConfig 里有 `echo_chamber_strength: float = 0.5`，假设社媒会形成回声室。**这个参数继承到小说里就是灾难**——所有角色互相同意 = 没有戏剧冲突 = 不是小说。INKFISH 反而要做相反的事：**conflict_pressure** 参数，主动鼓励角色分歧。

§2.4 没列这条，§5 风险也没列。这是漏掉的。

### 9.7 漏掉的决策：用户最小工作单元

"用户介入成本"在 R3 里提了，但没回答关键问题：**用户每次按一下"继续"，系统帮 ta 生成多大一块？** 选项：
- 一段（300 字）—— 慢，but 用户可控
- 一个场景（1500 字）—— 平衡
- 一章（5000 字）—— 快，but 用户失控

不同选择决定了完全不同的产品形态。这是必须早做的决策，本文没正面回答。

### 9.8 整体倾向：本文偏乐观

我对"七步骨架可以照搬"这个判断信心略高于实际证据。MiroFish 跑通的最大 demo 是《红楼梦续写》—— 那本身就是文学场景，理论上和 INKFISH 距离很近。但他们的 demo 是不是好读，我没去看视频。**做 INKFISH 之前应该先认真看那个 demo**。

---

## Sources
- 本文是 `01-mirofish-architecture.md` 的衍生设计文档，无外部引用
- MiroFish 代码：[666ghj/MiroFish](https://github.com/666ghj/MiroFish)
- 相关参考（未引用，留待 PoC 阶段查阅）：
  - [Graphiti](https://github.com/getzep/graphiti) —— Zep 背后的时序图引擎
  - [OASIS](https://github.com/camel-ai/oasis) —— MiroFish 用的多 Agent 社交模拟引擎
  - [BookGPT / Storyteller-AI](https://github.com/) 等已有的"AI 写小说"项目（PoC 阶段做调研）
