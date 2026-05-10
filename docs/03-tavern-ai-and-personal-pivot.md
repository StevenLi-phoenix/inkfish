# 酒馆 AI 调研 + INKFISH 个人化改向

> 写在前面的两个新约束（覆盖 01 / 02 的部分假设）：
> 1. **INKFISH 是个人写作工具，不是 SaaS。** 用户就是我自己（Steven）。
> 2. **要纳入"酒馆 AI"（SillyTavern）的经验。** 这是中文 AI 角色扮演圈子里事实标准的工具，已经把"角色档案 + 世界书 + 长期记忆 + 多角色互动"这套问题打磨了三四年。
>
> 本文先做酒馆 AI 的核心机制提炼（§1-2），然后把它和 MiroFish 范式做并列对照（§3），最后给出**修正版的 INKFISH 方向**（§4-5），明确哪些 02 文档的设计要改、改成什么样。

---

## 1. 酒馆 AI 是什么

[SillyTavern](https://docs.sillytavern.app/) 是一个本地运行的 AI 角色扮演前端。它本身不是 LLM，而是一个**极其可定制的"提示词组装器"**——把角色卡、世界书、对话历史、作者指令按用户配置的顺序拼成一个完整 prompt 发给后端 LLM（Claude / GPT / Gemini / 本地 ollama 都行）。

中文社区俗称"酒馆"（Tavern），围绕它发展出了庞大的**角色卡 / 世界书 / 预设**生态——用户互相分享 PNG 形式的角色卡、JSON 格式的世界书、定制好的 prompt 预设。它的产品哲学是**"任何东西都可以被用户编辑"**——和 MiroFish 的"全自动化"哲学完全相反。

---

## 2. 酒馆 AI 的核心机制

### 2.1 Character Card V3（角色卡）

**形态**：JSON 数据**嵌入到 PNG 图片的 tEXt chunk** 里。一张图就是一个角色，可以拖到任何兼容工具里直接用。极度便携。

**核心字段**（[V3 spec](https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md)）：
- `name` / `description` / `personality` / `scenario`
- `first_mes`（开场白）/ `mes_example`（示例对话）—— 给 LLM 风格 anchor
- `system_prompt` / `post_history_instructions` —— 角色级别的提示词覆盖
- `character_book` —— **嵌入式世界书**，只在和这个角色对话时激活
- `tags` / `creator` / `character_version` / `extensions`

**关键设计**：
1. **可移植**。一个 PNG 文件即一个完整人格。社区因此能成立——大家可以互相分享、衍生、 fork。
2. **示例对话作为 voice anchor**。`mes_example` 是 V2/V3 的关键创新——给 LLM 看几条"这个角色应该这样说话"，比纯描述效果好得多。
3. **角色自带世界书**。和"全局世界书 + 选择性关联"两层并存。

### 2.2 World Info / Lorebook（世界书）

**核心机制**：一个**关键词触发的动态字典**。每个 entry 有：
- `keys`（主关键词，逗号分隔）/ `secondary_keys`
- `content`（被触发后注入的文本）
- `position`（注入位置：在角色描述前/后/作者注前/聊天底部等）
- `depth`（注入深度，越靠近最新消息影响越大）
- `selective` / `selectiveLogic`（AND/OR/NOT 逻辑组合主次关键词）
- `constant`（永久注入 vs 触发注入）/ `vectorized`（语义匹配触发）/ `disabled`
- `scan_depth`（往前扫描多少条消息找关键词）
- `token_budget`（总 token 数上限，超出按优先级裁切）

**关键创新**：
1. **三态：constant / selective / vectorized**。同一个 lorebook 可以混用：开篇设定走 constant（永远在），世界观细节走 selective（被提到才进），半结构化的事实走 vectorized（语义匹配）。
2. **递归扫描（Recursive Scan）**。entry A 被触发后，A 的内容会被扫一遍找触发其他 entry 的关键词，形成多跳激活。"Maria → 她出生在 Aldea → Aldea 的历史 → 那场叛乱..."。这是 graph traversal 的廉价版。
3. **Token Budget**。承认上下文有限，必须有取舍机制。
4. **Position + Depth** 给出了**精确的提示词布局控制**——这是 MiroFish 完全没有的。

**和图谱 RAG 的对比**：
- 图谱 RAG（MiroFish 的 Zep）：基于语义+关系做检索，召回更智能但调试黑盒
- 世界书：基于关键词触发，规则透明，调试简单，但召回死板（关键词不匹配就漏）
- **INKFISH 应该两者并存**——常驻设定 + 显式知识 → 世界书；演化事实 + 隐式关系 → 图谱

### 2.3 Group Chat（群聊）

多个角色在同一个对话里，每条消息明确归属某个角色。轮转机制可选：自然轮转（LLM 决定下一个谁说）/ 手动指定 / 列表轮转。

**和 MiroFish 多 Agent 模拟对比**：
- 群聊是**实时人机互动**——用户每发一条，AI 回一条，用户可以打断、引导、分叉
- MiroFish 模拟是**离线批跑**——用户配置完按"开始"，跑几十轮后看结果
- 这两种**不是替代关系，是互补**：模拟生成"自然演化的世界状态"，群聊提供"用户即时干预的入口"
- 酒馆群聊有一个 INKFISH 必须借鉴的细节：**Character Note（角色注）**——每个角色可以在 chat 的某个 depth 注入 reminder（"记住，你不能透露你的真实身份"）。这是非常优雅的"在场提醒"机制。

### 2.4 Author's Note（作者注）

一个永远停留在最近 N 条消息之前的特殊文本块。常用法：
- `[OOC: 接下来场景应该让 Maria 主动暴露秘密]`
- `[Author: 用更阴郁的语气]`
- `[Style: 短句，少形容词]`

**这是 MiroFish 完全没有、INKFISH 必须有的核心功能**。它解决了"作者如何在不重写场景的前提下引导 AI"的问题。在 INKFISH 里，作者注就是**"导演的耳麦"**。

### 2.5 多层记忆系统（社区扩展）

酒馆的核心系统没解决长程记忆，但社区有数十个扩展。主流方案是**多层混合**：

| 层级 | 内容 | 实现 | 例子扩展 |
|---|---|---|---|
| L0 短期 | 最近 N 条对话原文 | 直接拼到 prompt | 内置 |
| L1 场景级 | 每个 scene 的 AI 摘要 | 触发式生成 + lorebook | MemoryBooks |
| L2 角色级 | 角色的关键事实清单 | 后台抽取 + Data Bank | CharMemory |
| L3 长期向量 | 全部历史的 embedding | Vector DB + RAG | Smart Context / Chat Vectorization |
| L4 弧光 / 主题级 | 故事到目前为止的核心走向 | 最远期摘要 | Smart Memory |

**关键启示**：长期记忆不是单一技术，是**多层次缓存 + 不同失效策略**的组合。INKFISH 的世界状态层应该做同样的多层。

### 2.6 Prompt Manager（提示词管理器）

完全暴露的 prompt 装配器：每个块（main prompt / character description / world info / chat history / author's note 等）都能：
- 启用/禁用
- 改 role（system / user / assistant）
- 改 order
- 改 position（in-chat 时改 depth）
- 改实际内容

用户可以**保存预设**并互相分享。社区有几百个 preset。

**关键启示**：personal-use 工具的核心交互是"用户折腾内部参数"。**INKFISH 必须把所有 prompt 暴露给用户编辑**，并且支持 preset 系统。MiroFish 把 prompt 写死在 Python 代码里——对 SaaS 合理，对 personal tool 是反模式。

---

## 3. 三方对照：MiroFish vs 酒馆 vs INKFISH 应有的样子

| 维度 | MiroFish | 酒馆 | INKFISH 应该 |
|---|---|---|---|
| **范式定位** | 多 Agent 模拟引擎 | 角色对话前端 | 模拟 + 对话的混合 |
| **角色档案** | 自动生成（2000 字 persona） | 用户编辑 PNG 卡（CCv3） | 兼容 CCv3，可手编可 LLM 起草 |
| **世界知识** | Zep 时序图谱 | 关键词 / 向量世界书 | **图谱 + 世界书并存**（图谱建模演化事实，世界书建模常驻设定） |
| **多角色互动** | OASIS 自动模拟 | Group Chat 用户驱动 | **模拟跑场景骨架 + 用户对话精修** |
| **作者引导** | 无（一次性配置） | Author's Note 实时注入 | **"导演耳麦"作为一等公民** |
| **长期记忆** | 单层（Zep） | 多层混合（社区扩展） | 多层：当前场景 + 章节摘要 + 角色卡 + 图谱 + 向量 |
| **Prompt 控制** | 黑盒 | 完全开放 | **完全开放 + preset 系统** |
| **配置自动化** | 全自动 | 几乎全手动 | **混合**：LLM 给草案，用户随时编辑 |
| **持久化形态** | Zep cloud + filesystem | 本地文件夹 | **纯本地文件夹**（personal use） |
| **运行规模** | Cloud + 长时间跑 | 本地 + 实时交互 | 本地 + 可长可短 |
| **可移植性** | 项目级（导入导出整个项目） | 文件级（角色卡 / 世界书可单独分享） | **文件级**（学酒馆，方便备份和借用社区资源） |
| **成本模型** | API + Zep 订阅 | API only（或本地） | **API only，可选本地 LLM** |

---

## 4. 修正版 INKFISH 设计（个人使用 + 双源借鉴）

### 4.1 哲学转向

读完 02 文档再回看，受 SaaS 思维污染的几个设计应该退掉：

1. ❌ "全自动通过按钮，让懒用户能跑通"——我自己用，不需要为其他用户兼顾
2. ❌ "项目隔离 + multi-tenant" ——一个用户一个文件夹，不需要项目这层抽象
3. ❌ "manuscript track + prose track 双轨"——已经在 02 §9.3 自检掉了
4. ❌ "Critique Agent 作为标准化质检"——我可以临时调用，不需要每章必跑

**新立场**：INKFISH 是我的写作工作台。它应该：
- 暴露所有 prompt 和参数（学酒馆）
- 默认本地存储，文件可移植可手编（学酒馆）
- 兼容 CCv3 和世界书格式（直接借用社区已有资源）
- 把"作者干预"作为核心交互而非边角功能（学酒馆）
- 用图谱解决酒馆解决不了的"长程一致性"和"演化事实"（学 MiroFish）
- 用模拟解决酒馆解决不了的"自然演化"和"群戏"（学 MiroFish）

### 4.2 修正后的核心组件

```
┌─────────────────────────────────────────────────────────┐
│              用户工作台（本地 web UI 或 desktop）        │
│  ─────────────────────────────────────────────────────  │
│  Prompt Manager  |  Author's Note  |  Quick Edit        │
│  (所有 prompt    |  (实时导演耳麦)  |  (随时改任何东西)  │
│   暴露+preset)   |                  |                    │
└──────┬──────────────────┬─────────────────┬─────────────┘
       │                  │                 │
       ▼                  ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌─────────────────┐
│ 角色档案库   │  │ 世界知识库   │  │ 故事时间线      │
│ ─────────    │  │ ─────────    │  │ ─────────       │
│ CCv3 PNG     │  │ Lorebook     │  │ Scenes/         │
│ + INKFISH    │  │ (酒馆兼容)   │  │ Chapters/       │
│   扩展字段   │  │ + Story Graph│  │ + Beat Plan     │
│ (弧光/秘密)  │  │   (KuzuDB或  │  │                 │
│              │  │    SQLite)   │  │                 │
└──────────────┘  └──────────────┘  └─────────────────┘
       │                  │                 │
       └──────────┬───────┴─────────────────┘
                  ▼
       ┌─────────────────────────┐
       │  混合执行引擎            │
       │  ─────────              │
       │  Mode A: 群聊模式        │  ← 用户实时对话，推动场景
       │  Mode B: 模拟模式        │  ← 离线跑场景骨架
       │  Mode C: 手稿模式        │  ← LLM 把场景骨架 → 散文
       │  Mode D: 采访模式        │  ← 任何时候问任何角色任何问题
       │                          │
       │  四种模式共享同一份角色 + │
       │  世界状态 + 时间线        │
       └─────────────────────────┘
```

### 4.3 关键设计：Lorebook + Graph 二元世界知识

这是综合两边经验的核心设计：

**Lorebook（学酒馆）** —— 用户**显式声明**的设定
- 世界观条目：地理、组织、技术、规则
- 用户写好不变，永远准确
- 用关键词或语义触发注入
- 适合"写小说前已经想好的东西"

**Story Graph（学 MiroFish）** —— 模拟过程中**演化的事实**
- 角色之间的关系状态
- 谁发生了什么、谁知道什么
- 时序：事实有 valid_at 时间属性
- 适合"写的时候自然涌现的东西"

两者的**混合检索**：当 Manuscript Agent 写章节时，同一个 query 同时查 lorebook（关键词+向量）和 story graph（图遍历），结果合并去重后注入 prompt。

### 4.4 关键设计：四种模式共享同一份状态

不再像 MiroFish 那样"先模拟，再报告"线性流程。INKFISH 用户在写作过程中可以**任意切换模式**：

- **群聊模式**：拉几个角色进 chat，实时推动一段对话（学酒馆 group chat）。产物变成"场景"。
- **模拟模式**：给一个场景骨架（"晚饭桌上 Maria 和 Pedro 第一次正面冲突"），让模拟引擎跑出一个对话+动作记录。比群聊快，少干预。
- **手稿模式**：把场景（无论从哪种模式来的）转成正式章节散文。Manuscript Agent + 用户编辑。
- **采访模式**：在任何场景的任何时间点，问角色"你现在在想什么？"或"你为什么这么做？"。回答可以选择写回 character profile（让她以后记得自己说过这话）或不写回（纯探索）。

四种模式都改的是同一份 character profile / lorebook / story graph / scene log。任何模式下的产出都成为后续模式的素材。

### 4.5 关键设计：Author's Note 升级为"导演控制台"

借鉴酒馆 Author's Note + Character Note，但扩展为多个维度：

```
导演控制台:
├─ Pacing Note      "接下来三个 beat 应该越来越紧"
├─ Tone Note        "用 noir 风格，多用感官描写"
├─ Beat Note        "Maria 这场必须暴露她对父亲的恨"
├─ Voice Note       "Pedro 不要再用书面语，他是工人"
├─ Constraint Note  "本场不能出现枪"
└─ Per-Character Notes
    ├─ Maria: "她内心动摇但表面平静"
    └─ Pedro: "他知道但还在装不知道"
```

每个 note 都有：内容 + 注入位置（system / chat depth N / 章节级）+ 启用开关 + 持续场景数。

### 4.6 修正后的目录结构（极简版）

```
inkfish/
├── characters/                   # CCv3 兼容 PNG + 扩展 JSON
│   ├── maria.png
│   ├── maria.ext.json            # INKFISH 扩展字段（弧光/秘密/声音）
│   └── pedro.png
├── lorebook/
│   ├── world.json                # 全局世界书
│   └── chapter_specific/         # 章节级世界书
├── graph/
│   └── story.kuzudb              # 本地图数据库
├── scenes/
│   ├── 001_cafe.scene.json       # 场景结构化记录
│   └── 001_cafe.transcript.md    # 自然语言版
├── chapters/
│   ├── ch01.md                   # 章节散文
│   └── ch01.notes.md             # 章节级 critique / 笔记
├── presets/
│   ├── manuscript_v1.preset.json # prompt preset
│   └── interrogation_v2.preset.json
├── director/
│   └── notes.json                # 当前生效的导演控制台
└── inkfish.toml                  # 项目级配置
```

无 SaaS 需要的 project / user / task / billing 抽象。一个文件夹一个故事，git 友好。

### 4.7 修正后的技术栈建议

| 组件 | 02 文档原方案 | 修正方案 | 理由 |
|---|---|---|---|
| 存储后端 | Zep cloud | **本地 KuzuDB 或 SQLite + sqlite-vec** | 个人用，不上 SaaS 依赖 |
| Web 前端 | Vue 3 + 完整 SPA | **轻量：HTMX 或 Astro 或 Tauri desktop** | 单用户不需要重前端，可以更接近 SillyTavern 风格 |
| 后端 | Flask + 多服务 | **FastAPI 单文件起步** | 最小化 |
| 模拟引擎 | OASIS fork | **从零写场景循环**（更轻） | OASIS 假设社媒，移除社媒部分等于重写 |
| LLM 接入 | OpenAI 单 client | **多 backend**：Anthropic / OpenAI / Ollama 本地 | 个人用对成本敏感，要灵活 |
| Embedding | Zep 内置 | **本地 sentence-transformers 或 openai embedding** | 同上 |

### 4.8 不变的（确认保留 02 文档里的设计）

- LLM 设计本体（但放宽到允许抽象类型如 Theme / Secret）
- 节点 → 角色 1:1 铸造，6 层 character profile
- 进程隔离 + 文件 IPC（personal use 也用得上，崩溃保护 + 调试友好）
- 模拟跑完保持子进程 alive 供采访
- Manuscript Agent 用 ReACT + 工具栈
- Critique Agent 作为可选检查（**改为按需调用**，不再每章必跑）
- 世界状态实时更新 + 知道集隔离

---

## 5. 修正后的 MVP 路线（更适合 personal use）

放弃"7 阶段流水线 + 全 UI"的产品式想法。**走酒馆式渐进**：

见 [`04-requirements.md`](./04-requirements.md) 的 §8 阶段切片。本节早期版本提议的"先在 SillyTavern 里做 PoC"路线已废弃，理由见 §7 和 §8。

---

## 6. 对 02 文档的补丁清单

下面这些是 02 文档里需要被 03 覆盖的具体点：

| 02 §位置 | 原说法 | 应改为 |
|---|---|---|
| §3.1 流水线图 | 7 阶段线性 | **混合执行引擎四模式并存**（见 §4.2） |
| §3.2 目录结构 | backend/app/api/services 多层 | **极简单文件夹**（见 §4.6） |
| §3.3 7 视图前端 | Vue 3 SPA | **轻量前端**（HTMX / Tauri / 甚至 SillyTavern fork） |
| §4 决策清单 | "用 Zep 起步" | **本地 KuzuDB / SQLite，不依赖 SaaS** |
| §4 决策清单 | "提供全自动通过按钮" | 删除——个人用户就是高阶用户 |
| §5 R3 用户介入成本 | 担心普通用户放弃 | **改为：担心我自己懒，所以默认要给草案不要白屏** |
| §5 R7 Zep 依赖 | 列为低风险 | 改为不依赖（用本地存储） |
| §6 MVP 之前的 PoC | 散文转换 PoC | **改为先跑酒馆 PoC**（见 §5 Phase 0） |
| §7 开放问题 1 | "目标用户是谁" | **删除**——目标用户是我 |
| §7 开放问题 8 | 国际化顺序 | **删除**——我自己用决定 |
| §7 新增 | — | **新问题：是否 fork SillyTavern 而不是从零写** |

---

## 7. 总结

读完酒馆 AI 的设计 + 想清楚 INKFISH 是个人工具后，结论变了：

1. **MiroFish 提供了"可演化世界"的范式**——本体设计、图谱、模拟、ReACT 综合
2. **酒馆 AI 提供了"可控对话"的范式**——角色卡、世界书、作者注、提示词管理
3. **INKFISH 应该是这两套范式的并集**——用 MiroFish 的图谱+模拟解决长程一致性和涌现，用酒馆的卡片+作者注+提示词管理解决用户控制权
4. **最小验证从酒馆开始**——先看现成工具能走多远，再决定要不要自己造
5. **如果造，走 CLI → 工具集 → 轻量 UI 路径**，不要一上来就想做 SaaS 风格的完整产品

最大的开放问题：**到底应不应该 fork SillyTavern 而不是从零写 INKFISH？** 这个问题在做 PoC 之前没法回答。

---

## Sources
- [SillyTavern docs](https://docs.sillytavern.app/)
- [Character Card Spec V3](https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md)
- [Character Card Spec V2](https://github.com/malfoyslastname/character-card-spec-v2/blob/main/spec_v2.md)
- [World Info docs](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)
- [Group Chats docs](https://docs.sillytavern.app/usage/core-concepts/groupchats/)
- [Author's Note docs](https://docs.sillytavern.app/usage/core-concepts/authors-note/)
- [Prompt Manager docs](https://docs.sillytavern.app/usage/prompts/prompt-manager/)
- [Smart Memory extension](https://github.com/senjinthedragon/Smart-Memory)
- [SillyTavern-MessageSummarize](https://github.com/qvink/SillyTavern-MessageSummarize)
- [SillyTavern-MemoryBooks](https://github.com/aikohanasaki/SillyTavern-MemoryBooks)
- [sillytavern-character-memory](https://github.com/bal-spec/sillytavern-character-memory)
- [Summaryception](https://github.com/Lodactio/Extension-Summaryception)
- [艾萝工坊 SillyTavern 中文教程](https://www.erocraft.com/silly-tavern/)
- [SillyTavern 傻酒馆中文文档](https://sillytavern.wiki/)
- [st-memory-enhancement](https://github.com/muyoou/st-memory-enhancement)
