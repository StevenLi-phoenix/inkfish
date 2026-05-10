# SillyTavern 设计参考

> 这是对 SillyTavern（中文社区俗称"酒馆"/"酒馆 AI"）这个开源 AI 角色扮演前端的客观技术参考。范围：它的核心数据格式、调度机制、记忆扩展生态、提示词管理范式，以及它在多角色场景下的核心架构局限。
>
> 资料截止：2026-05。所有 URL 见末尾 Sources。

---

## 0. TL;DR

[SillyTavern](https://docs.sillytavern.app/) 是一个**本地运行的 LLM 角色扮演前端**——它不提供模型，本身只是一个极度可定制的"提示词组装器"：把角色卡、世界书、对话历史、作者注按用户配置的顺序拼成完整 prompt，发给后端（Anthropic / OpenAI / Google / Ollama / koboldcpp 等任意兼容后端）。它真正擅长的事情有四件：(1) **资产可移植**——一张 PNG = 一个完整角色，社区可以无门槛地分享、衍生、fork；(2) **提示词全暴露**——每个 prompt 块的位置、角色、深度、内容都可以由用户编辑并存为 preset；(3) **关键词触发的动态注入**——World Info / Lorebook 用一个透明、可调试的规则系统决定每轮把哪些设定塞进上下文；(4) **作者级实时干预**——Author's Note / Character's Note 在指定深度注入指令文本，让用户在不重写场景的前提下推动 AI 偏向某个走向。它的核心局限在多角色场景下尤为突出，详见 §9。

---

## 1. 是什么

SillyTavern（缩写 ST）的产品定位是 **"Power user front-end for text generation"**——给愿意折腾的用户用的角色扮演与文字生成前端。它本身：

- 不附带 LLM；后端可以是任意 OpenAI 兼容 API、Anthropic、Google、Cohere、Mistral、本地 koboldcpp / ollama / TabbyAPI / text-generation-webui 等
- 默认本地运行（Node.js 服务 + 浏览器前端）；存储是文件系统上的 JSON / PNG / chat log
- 数据归用户所有，没有云端账号也能完整使用
- 从早期 TavernAI 分叉而来，发展出了独立的角色卡 V2/V3 规范、Lorebook 引擎、Group Chat、Prompt Manager 等

**中文社区生态**。中文圈把 SillyTavern 简称为"酒馆"。围绕它形成了相当庞大的资源生态——角色卡、世界书、preset 在 Discord 频道（如"类脑 ΟΔΥΣΣΕΙΑ"）、专门的角色卡站点（aicharactercards.com、Chub 等）以及国内的 B 站、博客圈大量流通。中文文档站点包括 [SillyTavern 傻酒馆中文文档](https://sillytavern.wiki/) 和 [艾萝工坊教程](https://www.erocraft.com/silly-tavern/)。社区主流话题分两条线：一是 RP（roleplay，沉浸式角色扮演），二是写作辅助（同人、长篇、剧本骨架）。两条线共用同一套资产格式，所以大量"角色卡"实际上是写作向的角色档案，而非聊天对象。

---

## 2. Character Card V3（角色卡）

**形态**。Character Card V3（CCv3）的数据是 **JSON 嵌入到 PNG（或 APNG）的 tEXt chunk** 里，chunk 名为 `ccv3`，值为 base64 编码的 UTF-8 JSON 字符串。一张图就是一个完整角色——拖到任何兼容工具里直接可用，不依赖云端、不依赖账号。CCv3 是 [V2 spec](https://github.com/malfoyslastname/character-card-spec-v2) 的超集，旧 V2 卡片可被无损读取，新字段在 V3 才出现。完整 spec 见 [character-card-spec-v3](https://github.com/kwaroran/character-card-spec-v3)。

**核心字段**：

- `name` / `description` / `personality` / `scenario`——基础人格描述，传统的纯文本字段
- `first_mes`——开场白，决定 LLM 第一轮要扮演的样子
- `mes_example`——**示例对话**，给 LLM 看几条"这个角色应该这样说话"的样本
- `system_prompt` / `post_history_instructions`——角色级别的提示词覆盖
- `character_book`——**嵌入式 Lorebook**（见 §3），只在和这个角色对话时激活，让"角色 + 世界观"作为一个整体被分发
- `tags` / `creator` / `character_version` / `creator_notes`——元数据
- `assets`——CCv3 新增，支持把头像、表情立绘、场景背景、声音样本一并嵌入卡片
- `extensions`——任意 namespace 下的自定义扩展字段

**设计哲学**：

1. **可移植胜于完备**。一张 PNG 文件即一个完整人格——这是社区生态能成立的根本。任何兼容前端都能解析，复制粘贴一张图就完成了"分发"。
2. **`mes_example` 作为 voice anchor**。V2/V3 的关键创新：与其用一长段散文描述"她说话什么风格"，不如直接给 LLM 看 3–5 条示范对话。LLM 的语言模仿能力远强于风格抽象能力，几条具体样本通常比千字描述更有效。这是对抗"所有角色越聊越像 AI 助手"的一道防线。
3. **角色自带世界书**。`character_book` 字段允许把和这个角色强绑定的世界观条目嵌入卡片本体，不依赖外部全局 Lorebook。导入这张卡 = 同时获得它的人格 + 它的微型世界。
4. **超集兼容**。CCv3 读取时优先 V3 字段，缺失则回退 V2，从设计上避免社区分裂。

---

## 3. World Info / Lorebook

World Info（也叫 Lorebook，社区中文叫"世界书"）是 SillyTavern **最核心也最被低估的引擎**。它本质是一个**关键词触发的动态字典**：每轮发请求前，引擎扫描最近 N 条消息，命中关键词的条目按规则注入到 prompt 的指定位置。完整文档见 [docs.sillytavern.app/usage/core-concepts/worldinfo](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)。

### 3.1 条目（Entry）字段

每个 entry 主要字段：

- `keys`——主关键词列表，逗号分隔；支持 JavaScript regex（用 `/.../` 包起来）
- `secondary_keys` + `selectiveLogic`——次关键词与逻辑组合：`AND ANY` / `AND ALL` / `NOT ANY` / `NOT ALL`
- `content`——命中后注入到 prompt 的实际文本
- `position`——注入位置：`Before/After Char Defs`、`Before/After Example Messages`、`Top/Bottom of AN`、`@ Depth N`（in-chat 指定深度）、`Outlet`（命名插槽，由 prompt 模板里的 `{{outlet::Name}}` 宏拉取）
- `order`——同位置多条目的排序优先级，越大越靠近 prompt 末尾，影响越强
- `probability`——0–100，命中后的实际注入概率，用于制造随机事件
- `inclusion_group` + `group_weight`——同组只能选一条注入，按权重抽取，可用于做多版本变体
- `scan_depth`（条目级可覆盖全局）——往前扫多少条消息找关键词
- `case_sensitive` / `match_whole_words`——匹配规则覆盖
- `character_filter`——只对某些角色或 tag 激活
- `triggers`——只在特定生成类型触发：Normal / Continue / Impersonate / Swipe / Regenerate / Quiet
- `automation_id`——和 STscript Quick Reply 联动的钩子

### 3.2 三态：Constant / Selective / Vectorized

每个 entry 的"激活策略"分三种：

- **Constant（蓝圈）**：永远在上下文里，不依赖关键词。适合开篇就要交代的世界设定。
- **Selective（绿圈）**：被关键词命中才注入。适合大量长尾的"被提到才需要"的细节。
- **Vectorized（链条）**：通过 Vector Storage 扩展，做嵌入相似度匹配——不是字面命中关键词，而是语义近的就触发。适合表达模糊、关键词难穷举的事实。

三态可以在同一个 Lorebook 里混用：开篇大设定走 constant，细节走 selective，半结构化的叙事事实走 vectorized。

### 3.3 递归扫描（Recursive Scan）

被触发的 entry 的 `content` 会被加进一个 `#recurseBuffer`，再扫一遍找新关键词，可能触发新的 entry，如此循环。

例：

```
Entry #1  key: Bessie    content: "Bessie 是一头牛，和 Rufus 是朋友。"
Entry #2  key: Rufus     content: "Rufus 是一只狗。"
```

用户消息只提到 "Bessie"，两条都会被拉进上下文。这是一种**多跳激活**——廉价版的图遍历："Maria → 她出生在 Aldea → Aldea 的历史 → 那场叛乱"。

控制递归的字段：

- 全局 `Recursive Scan` 开关
- 条目级 `Non-recursable`（不能被别人激活）
- 条目级 `Prevent further recursion`（自己被激活后不再递归触发别人）
- 条目级 `Delay until recursion`——只在递归阶段才能被触发（首轮不会进），配合 **Recursion Level** 可以分层级展开
- 全局 `Max Recursion Steps`——限制最大递归深度

### 3.4 Token Budget

承认上下文有限是 World Info 设计哲学的核心。`Context %` 或绝对 `Budget` 设定 World Info 总占用上限：

- Constant 条目优先注入
- Selective 条目按 `order` 注入，token 用尽则停止激活后续
- 直接命中关键词的条目优先级高于被递归触发的

`Alert on overflow` 可在超额时弹提醒。这种**显式的、可量化的预算系统**是对"上下文 = 资源"这一现实的工程化回应。

### 3.5 Timed Effects（时序效果）

让 World Info 突破"无状态评估"，引入持续状态：

- **Sticky N**：被触发后强制保持激活 N 条消息，期间忽略 probability
- **Cooldown N**：被触发后 N 条消息内不能再激活
- **Delay N**：聊天达到 N 条消息后才允许激活

可叠加：sticky 期结束后进入 cooldown。这套机制让 Lorebook 能模拟"一旦发生就持续 X 轮的事件"和"间隔触发"。

### 3.6 上下文范围分层

Lorebook 可以绑定到不同范围，覆盖关系按层叠：

- **Chat Lore**——只在当前 chat 生效
- **Persona Lore**——绑定到当前 user persona
- **Character Lore**——绑定到角色卡（包括嵌入式 `character_book`）
- **Global**——全局选中的 World Info 文件

注入顺序按 `Sorted Evenly` / `Character Lore First` / `Global Lore First` 三种策略可选。

---

## 4. Group Chat

文档：[docs.sillytavern.app/usage/core-concepts/groupchats](https://docs.sillytavern.app/usage/core-concepts/groupchats/)。

Group Chat 让多个角色卡同处一个会话，每条消息明确归属一个角色。**轮转机制**有四种：

- **Manual**——用户从菜单或 `/trigger` 命令手动选下一个发言者
- **Natural Order**——LLM 模拟自然对话流：先扫最后一条消息找名字提及，再用每个角色的 `Talkativeness`（0–100% 主动发言概率）筛选，无人激活则随机抽
- **List Order**——按角色在群成员列表的顺序轮
- **Pooled Order**——抽一个本轮还没发过言的角色，全部发过则重置

**角色卡组合策略**有两种：

- **Swap character cards**（默认）——每次生成只把当前发言者的角色卡注入上下文
- **Join character cards**——所有成员的描述、性格、scenario、示例对话、character note 全部拼到一起注入；可选包含/排除 muted 角色。文档明确警告：这会"导致角色相互混淆、人格融合、特征模糊"

辅助操作包括：Mute（让某角色暂时不发言）、Force Talk（强制点名一个角色发言）、Auto-mode（无用户输入也持续轮转，5 秒间隔，用户输入时自动暂停）、Allow Self Responses（允许同一角色连续回复）、Group Chat Scenario Override（覆盖所有成员的 scenario）。

---

## 5. Author's Note 与 Character's Note

文档：[docs.sillytavern.app/usage/core-concepts/authors-note](https://docs.sillytavern.app/usage/core-concepts/authors-note/)。

**Author's Note** 是一段**永远停留在指定深度**的特殊文本块——独立于聊天历史，但被插入到 prompt 的固定位置。配置项：

- **Placement**：`After Scenario`（角色定义后、示例对话前）或 `In-Chat`（在聊天历史的指定 depth 处）
- **Depth**：`In-Chat` 模式下指定深度，0 = 紧贴最末，N = 在最近第 N 条之前。越靠近末尾对下一轮影响越大
- **Frequency**：每 N 轮注入一次，0 = 关闭

典型用法：

- `[Author: 接下来场景应该让 Maria 主动暴露秘密]`——节奏与剧情指引
- `[Style: 短句，少形容词，用 noir 风格]`——风格控制
- `[OOC: {{char}} 现在受了腿伤，跑不动]`——临时世界状态

**Character's Note**（也叫 depth prompt）是 Author's Note 的角色级版本：每个角色卡可以带自己的 note，独立的 depth 和 role（system / user / assistant）。常用作"在场提醒"——`[Remember, you cannot reveal your true identity]`。Group Chat 在 Join 模式下会聚合所有成员的 character note。

这两套机制本质都是**带定位参数的 prompt 注入**：内容 + 位置 + 深度 + 频率。它们解决的是"用户如何在不重写场景的前提下持续影响 AI 行为"的问题。

---

## 6. 多层记忆系统（社区扩展概览）

SillyTavern 核心**没有内置长程记忆**——超出上下文窗口的早期对话会自然丢失。社区填补这个缺口的扩展数十个，主流方案是**多层混合**：

| 层级 | 内容 | 实现 | 代表扩展 |
|---|---|---|---|
| L0 短期 | 最近 N 条原文 | 直接拼到 prompt | 内置 |
| L1 场景级 | 一段对话的 AI 摘要 | 触发式生成，写回 Lorebook | [MemoryBooks](https://github.com/aikohanasaki/SillyTavern-MemoryBooks) |
| L2 角色级 | 角色的关键事实清单 | 后台抽取 + Data Bank | [character-memory](https://github.com/bal-spec/sillytavern-character-memory) |
| L3 长期向量 | 全部历史的 embedding | ChromaDB / Vector Storage + RAG | [Smart Context](https://docs.sillytavern.app/extensions/smart-context/) |
| L4 弧光级 | 整个故事到目前的核心走向 | 滚动摘要 + 多层压缩 | [Smart Memory](https://github.com/senjinthedragon/Smart-Memory) / [Summaryception](https://github.com/Lodactio/Extension-Summaryception) |

几个关键扩展的设计要点：

- **MemoryBooks**——把 chat 中标记的场景片段用 LLM 生成结构化（JSON）摘要，写回为 Lorebook entry。优点：摘要被纳入 World Info 的统一调度，命中关键词才注入，token 预算可控。
- **Smart Memory**——一个多层全栈方案：自动场景摘要 + 角色事实持久化 + 故事弧光抽取 + 离开重启时的"recap"。
- **Summaryception**——递归分层摘要："最新轮保留原文，老内容压成短摘要，更老的摘要再被压成更短的元摘要"。每个角色卡在群聊中维护**独立的摘要记忆**，对抗多角色记忆相互渗透。
- **MessageSummarize / [qvink/SillyTavern-MessageSummarize](https://github.com/qvink/SillyTavern-MessageSummarize)**——逐条消息生成短摘要，按需调用。
- **Smart Context**——基于 ChromaDB 的向量召回，可跨同一角色的所有 chat 检索"记忆"。

**关键启示**：长期记忆在这个生态里被工程界视作"多层缓存 + 不同失效策略"的组合问题，而不是单一技术能解的问题。每一层有不同的颗粒度、保留策略、注入时机。

---

## 7. Prompt Manager

文档：[docs.sillytavern.app/usage/prompts/prompt-manager](https://docs.sillytavern.app/usage/prompts/prompt-manager/)。

Prompt Manager 是**使用 Chat Completion 类后端时的 prompt 装配器**，把整个 prompt 拆成有序的 prompt 块（main prompt、character description、persona description、scenario、character personality、world info、chat history、jailbreak、author's note、自定义块……），每一块都暴露给用户编辑。

可调维度：

- **启用/禁用**——逐块开关
- **Role**——System / User / AI Assistant
- **Order**——同位置同 role 内的排序
- **Position**——`relative`（在固定槽里）或 `In-Chat`（注入到聊天历史的指定 depth）
- **Depth**（仅 in-chat 模式）——和 Author's Note 同义
- **内容**——纯文本编辑，支持 SillyTavern 宏（`{{char}}`、`{{user}}`、`{{outlet::Name}}`、各种条件宏等）

**排序规则**：同 Role + 同 Depth 的 prompt 按 Order 内部排序；多 role 内部组合的全局顺序为 User → AI Assistant → System。

**Preset 系统**。所有 Prompt Manager 的配置（包括块定义、采样参数、jailbreak、context template、instruct template）打包成一份 **preset JSON**。用户可以保存、导出、分享、互相 fork preset。社区有数百个流通的 preset，专门优化某个模型 + 某种 RP 风格的组合。这是 SillyTavern 个性化深度的核心载体——和 [Marinara's LLM Hub](https://spicymarinara.github.io/) 这类专门 preset 仓库构成了"角色卡 + 世界书 + 预设"三件套生态。

**关键启示**：Power user 工具的核心交互是"用户折腾内部参数"。把 prompt 写死在代码里对 SaaS 合理，对个人工具是反模式。

---

## 8. 核心局限：共享 LLM call 的上下文导致的串味问题

SillyTavern 的**多角色场景架构上是单 agent**——这是它最深的局限。

### 8.1 机制

无论是单角色聊天还是 Group Chat 的 Swap / Join 模式，**每一轮生成都是对后端 LLM 的一次单调用**。这次调用喂进去的 context 是：

- 角色描述（单角色：当前角色；Join 模式：所有成员的描述拼起来）
- 当前角色的 `mes_example`
- 全部相关 World Info 条目
- 全部 Author's Note 与 Character's Note
- 整段共享对话历史（所有角色发过的全部消息原文，按顺序）

然后让 LLM 生成"下一条消息"——Group Chat 的 Swap 模式下，这条消息属于当前调度选中的角色。

这意味着：**每个角色的"扮演"实际上是同一个 LLM 在同一坨上下文里推理时的视角切换**，而不是不同 agent 的独立思考。

### 8.2 后果

1. **风格沾染（Style Bleed）**。Pedro 不知不觉用上了 Maria 的句式——同一个 LLM 在同一段 context 里推理时，统计上各角色的语言模式互相吸引，越聊越向中位回归。
2. **思想穿透（Information Bleed）**。Pedro 的回复来自一次 LLM call，这次 call 的 context 包含 Maria 之前的全部消息，包括她的内心独白。如果 Maria 说过"我决定杀了 Pedro，但绝不能让他知道"，下一轮 Pedro 的 LLM call 完全看得见这句话——Pedro 角色的"无知"只能靠 prompt 嘱咐 LLM 假装不知道，没有任何机制保证。
3. **身份漂移（Identity Drift）**。跑过二十轮以上，所有角色的差异在统计上被磨平，向"乐于助人的 assistant 中位"回归。`mes_example` 在前几轮还能稳住 voice，但越往后影响越被新生成的对话稀释。
4. **作者注与 Character Note 缓解不了**。它们是同一坨 context 里塞进去的更多文本——不构成隔离，只是改变 LLM 的注意力权重。Group Chat 文档自己也警告 Join 模式会导致"角色相互混淆、人格融合"。
5. **Lorebook 命中也是共享的**。某个角色私有的世界观条目被关键词触发后，被注入的还是同一份共享 context，所有"角色"在那一轮都"看到了"它。

### 8.3 根因

这不是 prompt 不够细的问题，也不是 preset 不够好的问题。**根因是架构层面的：所有角色描述、所有 character note、所有 lorebook 条目、所有对话历史拼成一次共享 context 给单个 LLM call**。在这个架构下，无论怎么调 prompt 都不可能实现"Pedro 真的不知道 Maria 内心想什么"——因为 Pedro 那一轮的 LLM call 物理上看得见 Maria 的全部消息。

要解决这个问题，需要**每个角色一个独立的 LLM session**，且角色之间的信息流转只走"外显行为"（说出口的话、做出来的动作、被观察到的反应），由一个调度层（导演）做协调。这是另一种架构，不是 SillyTavern 通过加扩展能补上的——它的整个数据流（消息历史 + 提示词组装）都是按"单 agent 多视角切换"切的。

---

## 9. 值得借鉴的资产格式与 UX 模式

不绑定 SillyTavern 的实现，但值得任何同类工具学习的资产与设计模式：

**资产格式**：

- **CCv3 PNG 角色卡**——把人格 + 嵌入式世界书 + 资产打包进单文件，跨工具可移植。任何角色档案系统都应该考虑兼容这个格式。
- **Lorebook JSON 格式**——条目级三态（constant / selective / vectorized）+ 关键词与正则 + position/depth + 递归扫描 + token budget。这是一套被验证的"上下文动态注入"语义。
- **Preset JSON**——把整套 prompt 装配规则打包分享。用户 vs 用户的知识传递就靠这个。

**UX 模式**：

- **提示词全暴露 + Preset 系统**——所有 prompt 块可见可编辑可保存可共享。
- **Author's Note 作为一等公民**——把"作者实时干预"的入口做成核心交互，不是埋在设置里的边角功能。
- **In-Chat depth 作为通用注入坐标**——Author's Note、Character's Note、World Info、Prompt Manager 块全都用同一套 `@ Depth N` 语义控制位置。统一坐标系让用户的心智模型简单。
- **Token Budget 作为可见预算**——而非"上下文满了你猜哪些被丢了"。
- **Timed Effects（sticky / cooldown / delay）**——让无状态的注入规则获得有状态的时序行为。
- **Inclusion Group**——用同组互斥 + 权重抽取做内容变体。
- **多层记忆作为可组合的扩展**——核心保持小，让长期记忆策略多样化竞争。
- **Outlet 命名插槽**——`{{outlet::Name}}` 把"什么内容"和"放在哪里"解耦，让 prompt 模板的设计更模块化。

---

## 10. Sources

核心文档：

- [SillyTavern 主文档站](https://docs.sillytavern.app/)
- [World Info / Lorebook](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)
- [Group Chats](https://docs.sillytavern.app/usage/core-concepts/groupchats/)
- [Author's Note](https://docs.sillytavern.app/usage/core-concepts/authors-note/)
- [Prompt Manager](https://docs.sillytavern.app/usage/prompts/prompt-manager/)
- [Smart Context 扩展](https://docs.sillytavern.app/extensions/smart-context/)
- [DeepWiki: World Info System](https://deepwiki.com/SillyTavern/SillyTavern/6.1-world-info-system)
- [DeepWiki: Prompt Management and Construction](https://deepwiki.com/SillyTavern/SillyTavern/3.3-prompt-management-and-construction)

Spec：

- [Character Card V3 spec](https://github.com/kwaroran/character-card-spec-v3)
- [Character Card V2 spec](https://github.com/malfoyslastname/character-card-spec-v2)
- [World Info Encyclopedia (rentry)](https://rentry.co/world-info-encyclopedia)

记忆扩展：

- [SillyTavern-MemoryBooks](https://github.com/aikohanasaki/SillyTavern-MemoryBooks)
- [Smart-Memory](https://github.com/senjinthedragon/Smart-Memory)
- [SillyTavern-MessageSummarize](https://github.com/qvink/SillyTavern-MessageSummarize)
- [Extension-Summaryception](https://github.com/Lodactio/Extension-Summaryception)
- [sillytavern-character-memory](https://github.com/bal-spec/sillytavern-character-memory)
- [SillyTavern-ReMemory](https://github.com/InspectorCaracal/SillyTavern-ReMemory)
- [st-memory-enhancement](https://github.com/muyoou/st-memory-enhancement)

中文社区资料：

- [SillyTavern 傻酒馆中文文档](https://sillytavern.wiki/)
- [艾萝工坊 SillyTavern 教程](https://www.erocraft.com/silly-tavern/)
- [SillyTavern 中文文档（eigeen 镜像）](https://docs.eigeen.cc/)
- [LINUX DO: SillyTavern 入门指北](https://linux.do/t/topic/223253)
- [ForkSilly（兼容酒馆资产的 Android 客户端）](https://github.com/fatsnk/forksilly.doc)

Preset 仓库 / 工具：

- [Marinara's LLM Hub](https://spicymarinara.github.io/)
- [SillyTavern-CCPromptManager](https://github.com/aikohanasaki/SillyTavern-CCPromptManager)
- [aicharactercards.com](https://aicharactercards.com/)
