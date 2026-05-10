# INKFISH 系统设计（权威版）

> 写给六个月后的 Steven。你已经不记得之前的所有讨论。这份文档就是 INKFISH 的全部。
>
> 配套文档：[`01-mirofish.md`](./01-mirofish.md)（灵感来源 1：MiroFish 参考）、[`02-tavern.md`](./02-tavern.md)（灵感来源 2：SillyTavern 参考）、[`04-build.md`](./04-build.md)（实施路线图）。

---

## 1. 设计立场

INKFISH 是 Steven 个人写中文长篇小说用的本地工作台。它把作者放在中央，把模型当成可调度的演员、世界记忆、风格守门人。它面向一个读者、一个使用者、一台机器——所有为多人协作、计费、租户隔离、社区分享而做的抽象都不存在。

它要成为：一个可以让作者在同一份角色和同一份世界状态上，自由切换"模拟一个场景看会发生什么 / 把几个角色拉进群戏推一段对话 / 把场景骨架转写成正式散文 / 单独把某个角色拉出来追问"四种动作的工具。任何一种动作的产物都立即变成下一种动作的素材。所有提示词、所有参数、所有注入位置都对作者完全开放。文件直接落到磁盘，UTF-8 markdown / JSON / PNG，能 git 也能手编。

它要避免成为：另一个 SillyTavern 的 fork（角色对话能力强但缺图谱与隔离执行）；另一个 MiroFish 的小说皮（流水线漂亮但只能批跑且依赖 SaaS）；另一个把 LLM 当魔法箱的"AI 写作助手"（提示词写死在代码里，作者只能调参数）。INKFISH 的核心权力始终在作者手里——模型只是高带宽的执行肌肉。

---

## 2. 架构总览

```
┌────────────────────────────────────────────────────────────────────┐
│                       UI 层（HTMX 或 Tauri）                        │
│  Prompt Manager  |  Director Console  |  Scene Browser  |  Editor  │
└────────────────────────────────┬───────────────────────────────────┘
                                 │ GraphQL (唯一前后端接口)
┌────────────────────────────────▼───────────────────────────────────┐
│                  FastAPI 后端 + GraphQL endpoint                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              Mode Router                                     │  │
│  │   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │  │
│  │   │ 场景模拟  │ │ 群戏对话  │ │ 散文转写  │ │ 角色采访  │       │  │
│  │   └─────┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │  │
│  └─────────┼────────────┼────────────┼────────────┼─────────────┘  │
│            ▼            ▼            ▼            ▼                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                Director Coordinator (LLM)                    │  │
│  │  - 决定本拍谁说话 / 谁在场 / 谁能看见什么                       │  │
│  │  - 维护 per-character 知道集 mask                              │  │
│  │  - 注入导演控制台的 Pacing / Tone / Beat / Voice 等 notes     │  │
│  └─────────────┬─────────────────────────────────┬──────────────┘  │
│                │                                 │                 │
│   ┌────────────┴───────────┐         ┌──────────┴────────────┐    │
│   ▼                        ▼         ▼                        ▼    │
│ ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌───────────┐ │
│ │ Maria   │  │ Pedro   │  │ Antonia │  │ Narrator │  │ Critic    │ │
│ │ Session │  │ Session │  │ Session │  │ Session  │  │ Session   │ │
│ │ (子进程) │  │ (子进程) │  │ (子进程) │  │          │  │ (按需)     │ │
│ └────┬────┘  └────┬────┘  └────┬────┘  └────┬─────┘  └─────┬─────┘ │
│      │           │           │             │              │       │
│      └───────────┴───────────┴──────┬──────┴──────────────┘       │
│                                     ▼                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              Scene Log (append-only, JSONL)                  │  │
│  │   每条都标 actor_id / channel(speech|action|inner) / ts       │  │
│  └─────────────────────────────────┬────────────────────────────┘  │
│                                    │                               │
│  ┌─────────────────────────────────▼────────────────────────────┐  │
│  │            Reverse Updater（写回三层世界知识）                 │  │
│  └────────┬─────────────────────┬──────────────────┬────────────┘  │
└───────────┼─────────────────────┼──────────────────┼───────────────┘
            ▼                     ▼                  ▼
    ┌──────────────┐      ┌──────────────┐    ┌──────────────┐
    │  Lorebook    │      │ Story Graph  │    │ Vector Store │
    │ (作者声明)    │      │ (演化事实)    │    │ (已写章节)    │
    │ JSON 文件     │      │ KuzuDB        │    │ sqlite-vec    │
    └──────────────┘      └──────────────┘    └──────────────┘
            │                     │                  │
            └─────────┬───────────┴──────────────────┘
                      ▼
              ┌──────────────────┐
              │  Hybrid Retrieve │  ← 三源合并、去重、按知道集过滤
              └──────────────────┘
                      ▲
                      │ 任何 LLM session 取上下文都走它
                      │
            （上方所有 Session 与 Director 通过此 API 取知识）
```

**数据流的两个方向都标好了**：作者在 UI 上发起一次行动（任何一种模式）→ Mode Router 配出 Director + 角色 sessions 的拓扑 → 每个角色 session 通过 Hybrid Retrieve 拉自己被允许看到的上下文 → 各自独立调 LLM → 输出汇入 Scene Log → Reverse Updater 把新事实写回 Story Graph、把新散文 chunk 写入 Vector Store。Lorebook 默认只读，由作者手动维护。

---

## 3. 四模式的执行模型

四种模式共享同一份角色档案、Lorebook、Story Graph、Scene Log。任意时刻可以从一个模式切到另一个模式，所有产物互为素材。区别只在 Director 的拓扑配置和默认输出形态。

### 3.1 场景模拟（Mode S = Simulation）

**输入**：场景骨架（一段自然语言，"晚饭桌上 Maria 和 Pedro 第一次正面冲突"）+ 在场角色列表 + 可选时间长度（"推 10 拍"）+ 可选导演 notes。

**触发**：作者在场景浏览器里新建场景或从已有场景骨架启动。

**Director 行为**：
- 第一拍前：从 Story Graph 拉相关边（Maria↔Pedro 的关系状态、最近发生过什么），从 Lorebook 拉激活条目，组装"场景开场摘要"
- 每一拍：决定本拍谁应该开口或行动（基于当前 beat 紧张度、上一拍谁说过、角色 activity_bias）。一拍可以多人，但每个人都走自己的 session。
- 拍间：把刚发生的所有外显行为追加到 Scene Log，按本场 visibility 规则更新每个角色的 known set
- 终止：达到拍数上限 / 达到导演 note 里的某个 beat / 作者按停

**输出**：append-only JSONL（`scenes/<id>.transcript.jsonl`），每行 `{actor, channel: speech|action|inner|observe, content, ts}`。同时写一份人类可读的 markdown 版（`scenes/<id>.transcript.md`）便于直接看。

**状态影响**：Scene Log 完整保留；Story Graph 增量更新（Reverse Updater 把"Pedro 知道了 Maria 在说谎"这种事实抽出来写进图）；角色档案的 `arc.observed_actions` 增加引用；Lorebook 不变。

### 3.2 群戏对话（Mode G = Group Chat）

**输入**：在场角色列表 + 当前场景上下文（可以是从 Mode S 续上的，或新起一场）+ 作者的发言（作者扮演旁白、画外音、或某个 NPC）。

**触发**：作者在群戏界面发一条消息，或点"让某某回应"。

**Director 行为**：和 Mode S 几乎一样，区别只在每一拍可以由作者直接指定下一个发言角色，或者由 Director 自动选择。作者也可以在拍之间手动改写任何角色的发言（改完之后那条进 Scene Log 时标 `edited_by_author: true`）。

**输出**：和 Mode S 同一份 Scene Log，区别在条目会有 `mode: G` 标记。

**状态影响**：和 Mode S 一致。这意味着群戏跑出来的对话、散文转写时拿到的素材、采访时角色"记得"的内容是同一份。

### 3.3 散文转写（Mode P = Prose）

**输入**：一个或多个 Scene Log 段落（可以是 Mode S 跑出来的、Mode G 聊出来的、或手写的 outline）+ 章节级 Voice Note + 章节级 Tone Note + 可选风格示例。

**触发**：作者在编辑器里选定要转写的源段落，按"转写为散文"。

**Director 行为**：这是个"作家 session"而不是"角色 session"。它不分摊到每个角色，而是单独起一个 Narrator session，system prompt 是当前 POV / 叙事时态 / Voice Note，context 是源 Scene Log + 相关 Lorebook + 已写完的前一章末尾几段（保连贯）+ 已写部分的 voice 样本（从 Vector Store 拉同 POV 的几段近邻）。

**输出**：`chapters/<id>.md`，作者直接编辑。同一个章节可以多次转写覆盖，旧版本进 `chapters/<id>.history/`。

**状态影响**：写完后散文 chunk（按 ~500 token 切块）进 Vector Store，标记 `chapter_id / pov / scene_refs`。Story Graph 不直接由散文更新（散文是产物不是事实源）。Lorebook 不变。

### 3.4 角色采访（Mode I = Interview）

**输入**：一个角色 + 时间锚点（"在第 3 章开始之前的 Maria"vs"现在的 Maria"）+ 作者的问题。

**触发**：作者在角色档案页或场景任意时间点点"问她"。

**Director 行为**：极简——只起一个角色的 session，按时间锚点过滤 Scene Log 和 Story Graph（只暴露该锚点之前角色"知道"的事实），把作者的问题作为采访者的发言塞进 context，让角色用自己的声音回答。

**输出**：`interviews/<character>/<ts>.md`。每条采访可以由作者标记 `canonical: true`（写回角色档案的 secrets / arc 字段）或 `exploratory: true`（不写回，只是探索）。

**状态影响**：默认不影响其他状态。canonical 采访可以触发 Reverse Updater 把回答里的关键事实写进 Story Graph 和角色档案。

### 3.5 模式切换契约

四模式都通过同一份 `SceneContext` 对象进出：

```
SceneContext = {
  scene_id, present_characters, time_anchor,
  active_director_notes, active_lorebook_keys,
  scene_log_ref
}
```

任何模式开始时都从这个对象初始化，任何模式结束时都把变更写回。这就是"切换不丢状态"的实现基础。

---

## 4. Per-Agent 隔离的具体机制

这是 INKFISH 区别于 SillyTavern group chat 最根本的承诺。SillyTavern 的群聊是一次 LLM 调用扮演多个角色，结果是风格沾染、思想穿透、身份漂移。INKFISH 用 MiroFish 式的进程隔离 + 知道集隔离 + 风格锚点重打来对抗。

### 4.1 Director Coordinator 的角色和职责

Director 是一个独立的 LLM session，但它不扮演任何角色。它的 system prompt 框架是"你是一个戏剧导演，你不进入任何角色，你只决定接下来发生什么"。它的职责清单：

1. **拍序决策**：在每一拍前，决定本拍由谁行动（可以多人）。判据是当前 beat 的紧张度曲线、上一拍的发言者、每个角色的 `activity_bias`、导演 Beat Note 的硬约束。
2. **可见性管理**：维护 per-character 的 known set。每个角色 session 取上下文时，必须经过 Director 的 visibility filter——Pedro 心里想了什么不出现在 Maria 的 context 里。
3. **导演 Notes 注入**：把当前生效的 Pacing / Tone / Beat / Voice / Constraint Notes 按规则塞进对应 session 的 system prompt 或 context（不同 note 类型注入位置不同，详见 §6.5）。
4. **终止判定**：检测 Beat Note 的硬约束达成、拍数上限、作者中断信号。
5. **冲突仲裁**：两个角色同一拍同时想说话时，Director 决定时序（不是同时输出）。

Director 不做：扮演角色、改写角色台词、生成散文、最终落盘。这些事都由其他 session 或作者本人做。

### 4.2 单个角色 Session 的 System Prompt 构成

每个角色 session（Maria、Pedro……）都是独立子进程 + 独立 LLM 客户端。system prompt 按固定顺序拼装：

```
[1] 元指令              "你是 Maria。完全进入角色。永不破除第四面墙。"
[2] CCv3 核心字段        name + description + personality + scenario
[3] INKFISH 扩展          arc 当前阶段 + secrets + voice_rules
[4] Voice Anchor          mes_example 5-8 条 + 从已写章节中抽的 voice exemplar 2-3 段
[5] Per-Character Note    Director 注入的本场角色级 note（"她内心动摇但表面平静"）
[6] 输出格式协议           {channel: speech|action|inner|observe, content: ...}
```

第 4 块是关键——CCv3 的 mes_example 每一拍都要重新塞进 system prompt（不是塞一次就放手）。LLM 的风格收敛是统计性的，每次注入都把风格 anchor 拉回原点。从已写章节抽 voice exemplar 是 INKFISH 扩展——比 mes_example 更新鲜，因为它来自已经写好的本作品。

### 4.3 单个角色 Session 的 Context 构成

context（每一拍重新组装，不是滚动 chat history）：

```
[A] 场景基础摘要           Director 在场景开始时生成的"你在哪、和谁、刚发生什么"
[B] 角色已知世界事实        从 Story Graph 按 known_by 过滤 + Lorebook 关键词触发，
                          再过 Director 的 visibility filter，硬上限 token budget
[C] 本场已发生的外显日志     Scene Log 中本场所有 channel ∈ {speech, action, observe} 的条目
                          但只保留该角色"看见过"的（视角过滤）
[D] 自己的 inner 历史       Scene Log 中本角色自己的 channel=inner 条目（其他人看不到，自己看得到）
[E] 当前导演的 in-context note  比如 "[Director: Maria 这一拍要试探性地问一个危险的问题]"
[F] 上一拍触发她行动的 trigger  Director 给的"轮到你了，对刚才 X 的话做出反应"
```

context **不**包含：其他角色的 inner 独白、其他角色不在场时发生的事、其他角色单独和 Director 的对话、角色未知的 Lorebook 条目。

### 4.4 知道集（Per-Character Knowledge Mask）

Story Graph 里每条边和每条事实节点都带 `known_by: Set<character_id>` 属性。检索 API 必须传 `viewer_id`，返回时自动过滤。

更新规则：
- 角色 A 在场景里说出一句话 → 在场所有角色的 known_by 自动加上这条新事实
- 角色 A 行动被在场角色看见 → 同上
- 角色 A 内心独白 → 只 A 自己的 known_by
- 作者通过 Lorebook constant 条目声明的设定 → 默认 known_by=ALL，可以手动改
- 采访模式角色 A 自己说出一个之前 inner 的事实 → 视作"她让对面知道了"，对面 known_by 加上

边界情况：
- 角色 A 听到角色 B 说谎 → A 的 known_by 加的是"B 说了 X"，不是"X"。事实节点和"谁说了它"是分开的边。
- 角色 A 推理出某事 → Director 可以显式调用 "A 现在知道 Y" 的 API 注入（既可以由 A 的 session 输出 inner channel 时附带 propose_known(Y)，也可以由作者手动加）

### 4.5 风格锚点的注入策略

三类风格锚点，按强度递增：

1. **Voice Rules（弱锚）**：角色档案 voice 字段里的几条规则文本（"短句"、"避免书面语"、"口头禅 '诶'"）。塞 system prompt 第 3 块。
2. **mes_example（中锚）**：CCv3 的示例对话 5-8 条。每拍重塞 system prompt 第 4 块。
3. **Voice Exemplar（强锚）**：从已写章节里抽 2-3 段该角色的对话或 POV 段落，作为"你最近在小说里就是这样说话的"。每拍从 Vector Store 按 `character_id + recency` 拉。塞 system prompt 第 4 块末尾。

强锚是 INKFISH 相对 SillyTavern 的关键升级。SillyTavern 只能用作者预写的 mes_example，写得越久越脱节。INKFISH 因为有 Vector Store 标记了每段散文的归属角色，可以让 LLM 一直对齐"自己最近的真实声音"。

### 4.6 角色之间通信只走"外显行为日志"

这是隔离模型的核心约束，写成代码就是：

```
class CharacterSession:
    def assemble_context(viewer_id, scene_id):
        log = SceneLog.get(scene_id)
        return [
            entry for entry in log
            if entry.actor_id == viewer_id
            or entry.channel in ('speech', 'action')
            or (entry.channel == 'observe' and viewer_id in entry.observers)
        ]
```

`channel == 'inner'` 的条目永远不会跨 viewer 流通。这是 INKFISH 的一根硬线。

实现层面，这条线由两件事保证：
- Scene Log 是 append-only JSONL，每条都有明确 channel 标签
- 任何 LLM session 拉 context 都必须经过 `assemble_context(viewer_id, scene_id)`，没有别的口子直接读 raw log

---

## 5. 三层世界知识的合并检索策略

三层知识各管一段：Lorebook 管"作者已经想好的设定"，Story Graph 管"模拟过程演化出的事实"，Vector Store 管"已经写出来的散文"。检索时三源合并、去重、按知道集过滤。

### 5.1 Lorebook 的触发逻辑

格式直接复用 SillyTavern World Info：每个 entry 有 `keys` / `secondary_keys` / `content` / `position` / `depth` / `selective` / `constant` / `vectorized` / `disabled` / `scan_depth` / `token_budget`。

触发流程：
1. **Constant entries** 永远进，不需要触发
2. **Selective entries**：扫最近 `scan_depth` 条 Scene Log（包含本场和前几场）+ Director 给的当前查询字符串，按主次关键词的 `selectiveLogic` 命中
3. **Vectorized entries**：把当前查询字符串 embed，和 entry 的 vectorized 字段做余弦相似度，超过阈值命中
4. **递归扫描（Recursive Scan）**：第一轮命中的 entries 的 content 再扫一遍找触发其他 entries 的关键词，最多 N 跳（默认 3）。MiroFish 没有这个机制，SillyTavern 有，INKFISH 全盘借。
5. **Token Budget 裁切**：所有命中的 entries 按 priority 排序，超过 budget 的截断

### 5.2 Story Graph 的查询模式

KuzuDB 嵌入式图数据库，schema 大概：

```
NODE Character     {id, name, ...}
NODE Place         {id, name, ...}
NODE Fact          {id, content, valid_from, valid_to, source_scene, known_by[]}
NODE Theme         {id, name, ...}

REL  RELATIONSHIP  Character -> Character {kind: love|rival|kin|..., strength, valid_from, valid_to}
REL  PRESENT_IN    Character -> Place     {scene_id, ts}
REL  KNOWS         Character -> Fact      {since_scene}
REL  TOUCHES       Fact      -> Theme     {weight}
```

查询模式三种：
- **节点查询**：给个角色 id 拉它的所有当前关系（带时序过滤 `valid_at = now`）
- **路径查询**：Maria 和 Pedro 之间的最短关系链（Cypher-like）
- **时序事实查询**：给个时间锚点 + 一组实体，拉所有 `valid_from <= t <= valid_to` 且 `viewer_id ∈ known_by` 的事实

KuzuDB 的语义类似 Neo4j 但是嵌入式（无独立 server 进程），文件就是数据库。完美匹配"一个文件夹一个故事"的形态。

### 5.3 Vector Store 的角色

只装一类东西：**已写章节散文的 chunk**。每 chunk 标 `chapter_id / scene_refs / pov_character / chunk_idx / token_count`。

主要被三种地方用：
- 散文转写时拉前文末尾几段（连贯性）
- Voice exemplar 抽取（按 `pov_character + recency`）
- 写新章节前的"自检"（拉同主题的旧章节，给 Critic session 看是否设定矛盾）

技术：sqlite-vec 扩展。本地嵌入式，单文件，无服务进程。embedding 用 OpenAI text-embedding-3-small 或本地 bge-m3，由 backend config 切换。

### 5.4 三源结果的合并与去重

`HybridRetrieve(query, viewer_id, scene_id, budget) -> List[ContextChunk]`：

```
1. lore_hits   = LorebookEngine.scan(query, scan_depth, recursive_n=3)
2. graph_hits  = StoryGraph.query(query_terms, viewer_id, time_anchor)
3. vector_hits = VectorStore.knn(query_embed, top_k=10)
4. all_hits    = lore_hits + graph_hits + vector_hits
5. 去重：       按 normalized content 的 minhash 相似度合并（阈值 0.85）
6. 按 source 优先级排序：lorebook(constant) > lorebook(selective) > graph(direct) > graph(path) > vector
7. 在 budget 内截断（按 priority 从高到低）
8. 返回 List[ContextChunk{source, content, priority, tokens}]
```

调用方（任何 LLM session）拿到的就是合并好、过滤好、按预算切好的纯文本块列表。

---

## 6. 角色档案设计

角色档案是一个目录而不是单文件：

```
characters/maria/
├── card.png           # CCv3 PNG（社区可移植格式）
├── ext.json           # INKFISH 扩展字段
├── voice/             # voice exemplar 缓存（自动从 Vector Store 同步）
│   └── recent.json
└── interviews/        # 该角色的所有采访记录
    └── 2026-05-10T14:22.md
```

`card.png` 的 tEXt chunk 里是 CCv3 JSON。`ext.json` 是 INKFISH 扩展字段。两者合并使用。

### 6.1 CCv3 必填字段（直接借用，作者可手编）

| 字段 | 用途 |
|---|---|
| `name` | 角色显示名 |
| `description` | 外貌、出身、背景的纯文本描述（300-800 字） |
| `personality` | 性格倾向、价值观、口头禅（200-400 字） |
| `scenario` | 默认场景设定（角色被单独拉出来对话时的开场背景） |
| `first_mes` | 默认开场白（Mode I 第一次问她时她的开场，可以为空） |
| `mes_example` | 5-8 条示例对话，每条形如 `{{user}}: ... \n {{char}}: ...`。**Voice 中锚** |
| `system_prompt` | 角色级 system prompt 覆盖（可空，空则用 INKFISH 默认） |
| `post_history_instructions` | 角色级 post-history 指令（可空） |
| `character_book` | 嵌入式 lorebook（只在和这个角色相关的场景激活） |
| `tags` | 自由标签 |
| `creator` / `character_version` | 元数据 |

### 6.2 INKFISH 扩展字段（`ext.json`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `arc` | object | 角色弧光。`{ stages: [{name, summary, target_scene}], current_stage: 0 }`。Director 在判断 Beat Note 进度时参考 |
| `arc.observed_actions` | string[] | 该角色在 Scene Log 里被记录过的关键行为引用（自动维护） |
| `secrets` | object[] | 秘密清单。每条 `{content, knowers: [character_ids], reveal_trigger?: string}`。检索时按 viewer 过滤 |
| `voice` | object | 声音规则。`{rules: [...], speech_patterns: [...], avoid: [...]}`。塞 system prompt 第 3 块 |
| `voice_exemplar_refs` | object | 缓存指针，指向 voice/recent.json 里抽好的几段 |
| `activity_bias` | float | 0-1，Director 在拍序决策时用作权重（越高越爱主动开口） |
| `relations_seed` | object[] | 初始关系列表，会被首次写入 Story Graph 后清零标记。`{target_character, kind, strength, valid_from}` |
| `pov_eligible` | bool | 是否可以做 POV 角色（影响 Mode P 的 Narrator session 选择） |
| `inkfish_version` | string | ext schema 版本 |

`arc` / `secrets` / `voice` 这三个是 INKFISH 区别于纯 CCv3 的核心扩展。其他 SillyTavern 角色卡导入时这三个字段为空，作者按需填写。

---

## 7. 数据模型 / 项目文件布局

一个故事 = 一个文件夹。文件夹长这样：

```
my-novel/
├── inkfish.toml                 # 项目配置：LLM backend、embedding model、token budgets
├── characters/
│   ├── maria/
│   │   ├── card.png
│   │   ├── ext.json
│   │   ├── voice/recent.json
│   │   └── interviews/*.md
│   └── pedro/...
├── lorebook/
│   ├── world.json               # 全局 lorebook
│   └── chapters/
│       └── ch01.json            # 章节级 lorebook（被 ch01 写作时激活）
├── graph/
│   └── story.kuzu/              # KuzuDB 数据库目录
├── vectors/
│   └── prose.sqlite             # sqlite-vec 数据库
├── scenes/
│   ├── 001_cafe/
│   │   ├── meta.json            # 场景元数据：present, time_anchor, mode, status
│   │   ├── transcript.jsonl     # append-only Scene Log，权威版本
│   │   ├── transcript.md        # 人类可读版（每次写入时自动同步）
│   │   └── director_notes.json  # 本场生效的 director notes 快照
│   └── 002_kitchen/...
├── chapters/
│   ├── ch01.md                  # 章节散文
│   ├── ch01.meta.json           # POV、scene_refs、voice preset、pacing
│   └── ch01.history/            # 旧版本归档
├── presets/
│   ├── manuscript_default.json  # prompt preset
│   └── interview_probing.json
├── director/
│   ├── notes_active.json        # 当前生效的导演控制台
│   └── notes_archive/*.json     # 历史 notes 快照（可回滚）
├── outline/
│   ├── beats.json               # 故事 beat 大纲
│   └── threads.md               # 主题线、伏笔、悬念清单
└── .inkfish/
    ├── locks/                   # 子进程文件锁
    ├── ipc/                     # 子进程 IPC 命令/响应文件
    └── cache/                   # 临时缓存
```

所有 `.json` / `.md` UTF-8，`.jsonl` append-only，`.kuzu` 和 `.sqlite` 是二进制数据库但都是单文件可备份。整个文件夹 git init 直接走（`.gitignore` 屏蔽 `.inkfish/`）。

---

## 8. 模块拆分 + 接口契约

按依赖方向自下而上：

### M1: storage

负责：filesystem layout、文件读写、CCv3 PNG 解析、JSON schema 校验。
入：路径。
出：Python 对象（CharacterCard、SceneLog、LorebookEntry、DirectorNote……）。
关键：所有上层模块都通过 storage 取数据，不能直接读文件。

### M2: knowledge

负责：Lorebook 触发引擎 + Story Graph (KuzuDB) + Vector Store (sqlite-vec) + HybridRetrieve。
入：query、viewer_id、scene_id、budget。
出：`List[ContextChunk]`。
关键：所有 LLM session 取上下文都走 `HybridRetrieve.run(...)`，没有别的口子。Reverse Updater 也住在这层。

### M3: llm

负责：多 backend LLM 客户端（Anthropic SDK / OpenAI SDK / Ollama 本地）+ 长上下文档位调度（粗活档 / 精修档，见 §9）+ 通用 retry / json repair。
入：messages、model_tier、tools。
出：response 或流式 chunks。
关键：上层只指定 tier 不指定具体模型，便于切换。

### M4: director

负责：Director coordinator 的所有逻辑——拍序决策、可见性管理、notes 注入、终止判定。
入：SceneContext、用户行动事件。
出：下一拍指令（actor_id, trigger, in_context_note）。
依赖：M2 (knowledge)、M3 (llm)。

### M5: agent

负责：单角色 session 生命周期、system prompt 拼装、context 拼装、子进程化运行、IPC。
入：character_id、SceneContext、Director 指令。
出：Scene Log entry。
依赖：M1, M2, M3。
关键：每个角色一个子进程；进程间通过 `.inkfish/ipc/` 文件通信，学 MiroFish。

### M6: modes

负责：四种模式的执行流程（Mode S/G/P/I），把 director 和 agents 编排起来。
入：UI 来的模式启动指令 + SceneContext。
出：Scene Log 增长 + Reverse Updater 触发。
依赖：M4, M5。

### M7: api

负责：FastAPI 后端 + GraphQL endpoint + WebSocket 推送（场景演化的实时流）。
入：HTTP / WS。
出：GraphQL 响应。
关键：前后端唯一接口是 GraphQL，schema 在这一层定义。所有 mutation 走 M6。

### M8: ui

负责：Prompt Manager / Director Console / Scene Browser / Editor。
形态：HTMX + 服务端渲染（MVP 起步）；后续可以包成 Tauri desktop。
依赖：只通过 GraphQL 调 M7。

模块间依赖是单向的（M8 → M7 → M6 → M4/M5 → M3/M2 → M1）。M5 不直接调 M4，M4 不直接调 M5；它们都被 M6 编排。

---

## 9. 长上下文使用原则

2026 年 5 月的现实：Claude Opus 4.6 / Sonnet 4.6 都有 1M context GA 标准定价；GPT-5.4 ~1.05M；Gemini 3.1 Pro 1M。但检索质量差距大（Sonnet 4.6 在 MRCR 上 ~78%，GPT-5.4 ~37%，Gemini ~26%），且 "lost in the middle" 在 1M context 中段仍然丢 30%+ 精度。

这意味着 INKFISH 必须做两档：

### 9.1 粗活档（fast tier）

适用：Mode S 跑场景骨架、Mode G 推非关键对话、长段散文初稿、批量 voice 探索、Critic session 做粗筛。

策略：1M context 全开。让模型自己处理大量历史。允许把整本 lorebook、整章 Scene Log 一股脑塞进去。模型选 Claude Sonnet 4.6（性价比最好）或 GPT-5.4（如果作者偏好）。

容忍：中段精度损失。粗活只要骨架对就行，细节后面精修档补。

### 9.2 精修档（precise tier）

适用：Mode P 写最终散文章节、关键章节连贯性审查、voice 校准、关键 beat 的群戏推演、Critic 做最终验证。

策略：context 严格压在 200K 以内。手工 curate context：HybridRetrieve 的 budget 卡死在 ~80K，不允许整章塞。Voice exemplar 必须主动选 3 段而不是默认 top-k。Director notes 全开。模型选 Claude Opus 4.6。

代价：作者要花更多时间挑 context 块（UI 上要露出"哪些块进了 context"的预览）。

### 9.3 Prompt Manager 必须支持两档预设

UI 上每个 preset 都要标 `tier: fast | precise` 字段。切档不只是换模型——是换整个 context 装配策略。precise 档的 preset 默认带"context preview & approval"步骤，让作者在调 LLM 前看一眼最终装好的 prompt 长什么样。fast 档默认跳过这一步。

实施细节见 [`04-build.md`](./04-build.md) 的对应阶段切片。

---

## 10. 技术栈选择 + 为什么

### 10.1 后端：Python + FastAPI

候选：Python (FastAPI / Flask) / Node (Express / Hono) / Go / Rust。
选 Python + FastAPI。
理由：LLM SDK 在 Python 最完整（Anthropic / OpenAI / Ollama 都是 Python 一等公民）；FastAPI 的 async 支持和 pydantic schema 拼 GraphQL 很顺；个人工具不需要极致性能；KuzuDB 和 sqlite-vec 都有 Python 绑定。Flask 不选是因为 async 模型差、依赖第三方扩展才能做 WebSocket。Node 不选是因为 LLM 工具链生态比 Python 弱一档。Go/Rust 不选是因为 LLM SDK 不全，开发速度慢，对个人工具不划算。

### 10.2 前后端接口：GraphQL

候选：REST / GraphQL / tRPC / gRPC-Web。
选 GraphQL（Strawberry 实现）。
理由：四模式共享同一份 state，前端不同 view 需要的字段切片差别大（场景浏览器要 transcript 摘要，编辑器要章节散文 + meta，导演控制台要 notes + active scene），REST 会催生大量 bespoke endpoint。GraphQL 让前端按需取字段。tRPC 不选是因为它假设全栈 TypeScript，前后端不同语言时优势消失。gRPC-Web 不选是因为浏览器调试不友好且对手编 query 不友好（个人工具我会经常直接 curl）。

### 10.3 前端：HTMX 起步，可升级 Tauri

候选：React/Vue SPA / HTMX + 服务端渲染 / Tauri desktop / Electron。
MVP 选 HTMX；后续可包 Tauri。
理由：HTMX 的"服务端渲染 + 局部刷新"心智模型最匹配单用户工具（不需要 client-side state 管理）。React/Vue SPA 是为多用户协作和复杂前端 state 设计的，单人写小说用不上。Tauri 比 Electron 轻一个数量级，包出来 ~10MB 而非 ~100MB；如果以后想做"双击打开"的 native app 体验，包成 Tauri 即可，HTMX UI 直接在 webview 里跑。

### 10.4 图数据库：KuzuDB

候选：KuzuDB / DuckDB / Neo4j / Memgraph / SQLite + 自建图层。
选 KuzuDB。
理由：嵌入式（无独立 server 进程）；列式存储查询快；Cypher 兼容；MIT license；C++/Python 绑定都成熟。Neo4j / Memgraph 都需要独立 server 进程，"一个文件夹一个故事"形态下太重。SQLite + 自建图层早期可以但路径查询性能扛不住。DuckDB 不是图原生（虽然能用 recursive CTE 模拟，但 schema 和查询语法都别扭）。

### 10.5 向量库：sqlite-vec

候选：sqlite-vec / Chroma / LanceDB / FAISS / Qdrant local。
选 sqlite-vec。
理由：单文件嵌入式；和 SQLite 同进程；性能对个人规模（几万 chunk）足够；备份就是拷贝文件。Chroma / Qdrant 需要独立服务进程。LanceDB 也是嵌入式但生态相对小且 schema 演化体验差。FAISS 没有元数据查询，要自己建一层 k-v store 配它。

### 10.6 子进程容器 + 文件 IPC

候选：multiprocessing.Pool / subprocess + filesystem IPC / asyncio task / Ray / Dask。
选 subprocess + filesystem IPC（学 MiroFish）。
理由：进程隔离 = 状态隔离 = 故障隔离，一个角色的 LLM 调用挂掉不影响其他；filesystem IPC 调试友好（命令是 JSON 文件可以肉眼看可以手动改）；不依赖任何 message broker。代价是 IPC 延迟（~0.5s 轮询），但小说写作不是实时游戏，这个延迟无所谓。multiprocessing.Pool 不选是因为它的进程间通信走 pickle，调试痛苦。asyncio task 不选是因为没有进程隔离（一个 task 挂可以拖整个 event loop）。Ray / Dask 是分布式工具，对单机个人工具是过度设计。

### 10.7 LLM 接入：多 backend 抽象

候选：写死单 provider / litellm / langchain / 自己抽象。
选自己抽象（薄一层）。
理由：实际只需要 chat completion + streaming + tool calling 三件事；litellm 引入大量我用不到的依赖且 schema 经常变；langchain 是抽象灾难且为 SaaS 应用设计。自己写一个 ~200 行的 `LLMClient` 基类 + 三个 backend 实现（Anthropic / OpenAI / Ollama）成本可控且完全掌控行为。tier 调度也住在这一层。

### 10.8 文件持久化：纯 filesystem

候选：filesystem only / SQLite 主索引 + filesystem 内容 / 全 SQLite。
选 filesystem only。
理由：手编、git diff、备份都最简单；个人规模（几百场景、几十章节）filesystem scan 性能完全够；不需要事务（没有并发写者）。全 SQLite 会把所有内容塞进二进制文件，失去文本编辑器直接编的能力——违背 §1 立场。

---

## 11. Sources

- [`01-mirofish.md`](./01-mirofish.md) — MiroFish 七步骨架与进程隔离范式
- [`02-tavern.md`](./02-tavern.md) — SillyTavern 资产格式与作者控制机制；per-agent 隔离决策的反面教训来源
- [`04-build.md`](./04-build.md) — 实施路线图、功能切片、阶段切片、开放问题
- [Character Card Spec V3](https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md) — `card.png` 兼容格式
- [SillyTavern World Info docs](https://docs.sillytavern.app/usage/core-concepts/worldinfo/) — Lorebook 触发逻辑参考
- [KuzuDB docs](https://kuzudb.com/) — 嵌入式图数据库
- [sqlite-vec](https://github.com/asg017/sqlite-vec) — 嵌入式向量扩展
- [Strawberry GraphQL](https://strawberry.rocks/) — Python GraphQL 框架
- [HTMX](https://htmx.org/) / [Tauri](https://tauri.app/) — 前端方案
- [Anthropic Claude 1M context (May 2026 GA)](https://www.anthropic.com/) — 长上下文档位决策的依据
