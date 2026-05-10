# INKFISH 系统设计（权威版）

> 写给六个月后的 Steven。你已经不记得之前的所有讨论。这份文档就是 INKFISH 的全部。
>
> 配套文档：[`01-mirofish.md`](./01-mirofish.md)（灵感来源 1：MiroFish 参考）、[`02-tavern.md`](./02-tavern.md)（灵感来源 2：SillyTavern 参考）、[`04-build.md`](./04-build.md)（实施路线图）。

---

## 1. 设计立场

INKFISH 是 Steven 个人写中文长篇小说用的本地工作台。它把作者放在中央，把模型当成可调度的演员、世界记忆、风格守门人。它面向一个读者、一个使用者、一台机器——所有为多人协作、计费、租户隔离、社区分享而做的抽象都不存在。

它的根本目标只有一条：**管理读者每一秒钟想不想翻下一页**。这条规则对网文、轻小说、严肃文学是同一条，差别只在期望读者停留的时间尺度——网文是 30 秒决定要不要看下一章，严肃文学是几分钟一段、几小时一章。INKFISH 不假设作者要写哪种，但要求作者在每个层级都能显式控制这条曲线：开局要不要三章定律，章节内部要不要起承转结，卷与卷之间要不要 Story Circle，伏笔要不要做成博弈，节拍要不要装逼打脸——这些选择都暴露给作者，模型只是执行肌肉。

它要成为：一个可以让作者在同一份角色和同一份世界状态上，自由切换"模拟一个场景看会发生什么 / 把几个角色拉进群戏推一段对话 / 把场景骨架转写成正式散文 / 单独把某个角色拉出来追问"四种动作的工具。任何一种动作的产物都立即变成下一种动作的素材。所有提示词、所有参数、所有注入位置都对作者完全开放。文件直接落到磁盘，UTF-8 markdown / JSON / PNG，能 git 也能手编。

它要避免成为：另一个 SillyTavern 的 fork（角色对话能力强但缺图谱与隔离执行）；另一个 MiroFish 的小说皮（流水线漂亮但只能批跑且依赖 SaaS）；另一个把 LLM 当魔法箱的"AI 写作助手"（提示词写死在代码里，作者只能调参数）。INKFISH 的核心权力始终在作者手里——模型只是高带宽的执行肌肉。

---

## 2. 架构总览

```
┌────────────────────────────────────────────────────────────────────┐
│                       UI 层（HTMX 或 Tauri）                        │
│  Prompt Manager  |  Director Console  |  Pacing Board  |  Editor  │
│  Scene Browser   |  Meme Registry     |  Character Studio          │
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
│  │  - 拍序决策 / 可见性管理 / 终止判定                            │  │
│  │  - 注入 Pacing / Tone / Beat / Voice / Constraint Notes       │  │
│  │  - 调用 Pacing Engine 拿当前 beat 的张力目标 + 微结构模板      │  │
│  │  - 调用 Meme Registry 拿活跃 catchphrase + 半衰期警告           │  │
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
│  │            Reverse Updater（写回三层世界知识 + 梗追踪）         │  │
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

┌─────────────────────────────────────────────────────────────────┐
│                  独立的横向模块（不在主数据流上）                 │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐   │
│  │ Pacing Engine  │  │ Meme Registry  │  │ Detail Seeds    │   │
│  │ 多层结构叠加    │  │ 大 meme + 小梗 │  │ 必含细节注入     │   │
│  │ 张力曲线管理    │  │ 半衰期追踪     │  │ 给 Mode P 用    │   │
│  │ 微结构模板      │  │ 造梗循环       │  │                 │   │
│  └────────────────┘  └────────────────┘  └─────────────────┘   │
│         ↑                    ↑                    ↑             │
│         └──────── 被 Director 和 Mode P 显式调用 ──┘             │
└─────────────────────────────────────────────────────────────────┘
```

**两个数据流方向都标好了**：作者在 UI 上发起一次行动（任何一种模式）→ Mode Router 配出 Director + 角色 sessions 的拓扑 → Director 在每一拍前向 Pacing Engine 查"当前应该处在张力曲线哪个位置"+ 向 Meme Registry 查"哪些 catchphrase 当前活跃" → 每个角色 session 通过 Hybrid Retrieve 拉自己被允许看到的上下文 → 各自独立调 LLM → 输出汇入 Scene Log → Reverse Updater 把新事实写回 Story Graph、把新散文 chunk 写入 Vector Store、把读者意外觉得有趣的句子提示给作者标记进 Meme Registry。Lorebook 默认只读，由作者手动维护。

---

## 3. 四模式的执行模型

四种模式共享同一份角色档案、Lorebook、Story Graph、Scene Log、Pacing 状态、Meme Registry。任意时刻可以从一个模式切到另一个模式，所有产物互为素材。区别只在 Director 的拓扑配置和默认输出形态。

### 3.1 场景模拟（Mode S = Simulation）

**输入**：场景骨架（一段自然语言，"晚饭桌上 Maria 和 Pedro 第一次正面冲突"）+ 在场角色列表 + 可选时间长度（"推 10 拍"）+ 可选导演 notes + 可选 Pacing 目标（"这场要把 Pedro 的张力推到 0.7"）+ 可选 Detail Seeds（"必须出现：Maria 摸了一下耳坠 / Pedro 把杯子里的酒倒掉"）。

**触发**：作者在场景浏览器里新建场景或从已有场景骨架启动。

**Director 行为**：
- 第一拍前：从 Story Graph 拉相关边、从 Lorebook 拉激活条目、向 Pacing Engine 查本场在所属章节/卷的位置（"这是第 7 章的 sequel 段落，张力应该回落到 0.3"）、向 Meme Registry 查在场角色当前活跃的 catchphrase
- 每一拍：决定本拍谁应该开口或行动（基于当前 beat 紧张度、上一拍谁说过、角色 activity_bias、Detail Seeds 是否还未消耗）
- 拍间：把刚发生的所有外显行为追加到 Scene Log，按本场 visibility 规则更新每个角色的 known set
- 终止：达到拍数上限 / 达到导演 note 里的某个 beat / Detail Seeds 全部消耗 / 作者按停

**输出**：append-only JSONL（`scenes/<id>/transcript.jsonl`），每行 `{actor, channel: speech|action|inner|observe, content, ts, seeds_consumed?: [...]}`。同时写一份人类可读的 markdown 版（`scenes/<id>/transcript.md`）便于直接看。

**状态影响**：Scene Log 完整保留；Story Graph 增量更新（Reverse Updater 把"Pedro 知道了 Maria 在说谎"这种事实抽出来写进图）；角色档案的 `arc.observed_actions` 增加引用；Lorebook 不变；Meme Registry 中"被作者标记的意外有趣句子"进入 candidate 池。

### 3.2 群戏对话（Mode G = Group Chat）

**输入**：在场角色列表 + 当前场景上下文（可以是从 Mode S 续上的，或新起一场）+ 作者的发言（作者扮演旁白、画外音、或某个 NPC）。

**触发**：作者在群戏界面发一条消息，或点"让某某回应"。

**Director 行为**：和 Mode S 几乎一样，区别只在每一拍可以由作者直接指定下一个发言角色，或者由 Director 自动选择。作者也可以在拍之间手动改写任何角色的发言（改完之后那条进 Scene Log 时标 `edited_by_author: true`）。作者修改的内容会被 Reverse Updater 视作"权威发声"，比 LLM 自动生成的内容优先级高。

**输出**：和 Mode S 同一份 Scene Log，区别在条目会有 `mode: G` 标记。

**状态影响**：和 Mode S 一致。这意味着群戏跑出来的对话、散文转写时拿到的素材、采访时角色"记得"的内容是同一份。

### 3.3 散文转写（Mode P = Prose）

**输入**：一个或多个 Scene Log 段落（可以是 Mode S 跑出来的、Mode G 聊出来的、或手写的 outline）+ 章节级 Voice Note + 章节级 Tone Note + 可选风格示例 + **必含 Detail Seeds**（来自场景规划时埋的 + Mode S 里被作者标记成"这个细节必须保留"的）。

**触发**：作者在编辑器里选定要转写的源段落，按"转写为散文"。

**Director 行为**：这是个"作家 session"而不是"角色 session"。它不分摊到每个角色，而是单独起一个 Narrator session，system prompt 是当前 POV / 叙事时态 / Voice Note / show-vs-tell 分层规则（见 §9.1），context 是源 Scene Log + 相关 Lorebook + 已写完的前一章末尾几段（保连贯）+ 已写部分的 voice 样本（从 Vector Store 拉同 POV 的几段近邻）+ **Detail Seeds 强制清单**（每条都被标记 `mandatory: true`，散文中必须显式包含；输出时 Director 校验是否消耗，未消耗的 Seed 触发 Critic 提醒）。

**输出**：`chapters/<id>.md`，作者直接编辑。同一个章节可以多次转写覆盖，旧版本进 `chapters/<id>.history/`。

**状态影响**：写完后散文 chunk（按 ~500 token 切块）进 Vector Store，标记 `chapter_id / pov / scene_refs / catchphrase_used[]`。Story Graph 不直接由散文更新（散文是产物不是事实源）。Lorebook 不变。Meme Registry 自动检测散文中是否复用了已注册的 catchphrase，更新使用频率。

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
  active_pacing_target, active_meme_set, active_detail_seeds,
  scene_log_ref
}
```

任何模式开始时都从这个对象初始化，任何模式结束时都把变更写回。这就是"切换不丢状态"的实现基础。

---

## 4. Per-Agent 隔离的具体机制

这是 INKFISH 区别于 SillyTavern group chat 最根本的承诺。SillyTavern 的群聊是一次 LLM 调用扮演多个角色，结果是风格沾染、思想穿透、身份漂移。INKFISH 用 MiroFish 式的进程隔离 + 知道集隔离 + 风格锚点重打来对抗。

### 4.1 Director Coordinator 的角色和职责

Director 是一个独立的 LLM session，但它不扮演任何角色。它的 system prompt 框架是"你是一个戏剧导演，你不进入任何角色，你只决定接下来发生什么"。它的职责清单：

1. **拍序决策**：在每一拍前，决定本拍由谁行动（可以多人）。判据是当前 beat 的紧张度曲线（来自 Pacing Engine）、上一拍的发言者、每个角色的 `activity_bias`、导演 Beat Note 的硬约束、未消耗的 Detail Seeds。
2. **可见性管理**：维护 per-character 的 known set。每个角色 session 取上下文时，必须经过 Director 的 visibility filter——Pedro 心里想了什么不出现在 Maria 的 context 里。
3. **导演 Notes 注入**：把当前生效的 Pacing / Tone / Beat / Voice / Constraint Notes 按规则塞进对应 session 的 system prompt 或 context（不同 note 类型注入位置不同）。
4. **微结构模板调用**：当 Pacing Engine 标本场为"装逼打脸"或"sequel 段落"时，Director 取相应模板（见 §7.3）应用到拍序与张力分配。
5. **Meme 引导**：从 Meme Registry 拿在场角色的活跃 catchphrase 清单，作为 in-context note 提醒角色"你最近会用这个表达"——但不强制使用。
6. **终止判定**：检测 Beat Note 的硬约束达成、拍数上限、Detail Seeds 全部消耗、作者中断信号。
7. **冲突仲裁**：两个角色同一拍同时想说话时，Director 决定时序（不是同时输出）。

Director 不做：扮演角色、改写角色台词、生成散文、最终落盘。这些事都由其他 session 或作者本人做。

### 4.2 单个角色 Session 的 System Prompt 构成

每个角色 session（Maria、Pedro……）都是独立子进程 + 独立 LLM 客户端。system prompt 按固定顺序拼装：

```
[1] 元指令              "你是 Maria。完全进入角色。永不破除第四面墙。"
[2] CCv3 核心字段        name + description + personality + scenario
[3] INKFISH 扩展          want（当前一直在追求的） + need（自己未必意识到的更深需要）
                          + arc 当前阶段 + secrets + voice_rules + signature_lines
[4] Voice Anchor          mes_example 5-8 条 + 从已写章节中抽的 voice exemplar 2-3 段
                          + Meme Registry 给的活跃 catchphrase（作为"你最近爱说这个"提醒）
[5] Per-Character Note    Director 注入的本场角色级 note（"她内心动摇但表面平静"）
[6] 输出格式协议           {channel: speech|action|inner|observe, content: ...}
```

第 3 块的 want / need 双轨是 INKFISH 角色档案的灵魂（详见 §6.2）。第 4 块是关键——CCv3 的 mes_example 每一拍都要重新塞进 system prompt（不是塞一次就放手）。LLM 的风格收敛是统计性的，每次注入都把风格 anchor 拉回原点。

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
[G] 未消耗的 Detail Seeds   如果 Director 决定本拍是消耗某个 Seed 的好时机，作为软提示注入
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

**作者-读者信息差是显性建模的一等公民**。Story Graph 还有一个特殊 viewer：`reader`。"读者知道但某角色不知道"（重生流的核心机制）通过 `known_by={reader, ...}` 实现。Director 在拍序决策时会显式利用这个差——当读者已知而某角色未知的关键事实存在时，Director 倾向把那个角色推向"基于错误信息做关键决定"的拍，让悬念自然产生。

### 4.5 风格锚点的注入策略

四类风格锚点，按强度递增：

1. **Voice Rules（弱锚）**：角色档案 voice 字段里的几条规则文本（"短句"、"避免书面语"、"口头禅 '诶'"）。塞 system prompt 第 3 块。
2. **mes_example（中锚）**：CCv3 的示例对话 5-8 条。每拍重塞 system prompt 第 4 块。
3. **Voice Exemplar（强锚）**：从已写章节里抽 2-3 段该角色的对话或 POV 段落，作为"你最近在小说里就是这样说话的"。每拍从 Vector Store 按 `character_id + recency` 拉。塞 system prompt 第 4 块末尾。
4. **Signature Lines / Active Catchphrases（标志锚）**：角色档案里强制要求至少 3 条"这个角色脱离上下文能说出的、20 字以内的、有传播性的台词"，加上 Meme Registry 跟踪的当前活跃 catchphrase。作为"提示但不强制"塞 system prompt 第 4 块尾部。

强锚和标志锚是 INKFISH 相对 SillyTavern 的关键升级。SillyTavern 只能用作者预写的 mes_example，写得越久越脱节。INKFISH 因为有 Vector Store 标记了每段散文的归属角色 + Meme Registry 跟踪 catchphrase 演化，可以让 LLM 一直对齐"自己最近的真实声音"和"作者已经认证的标志台词"。

### 4.6 角色之间通信只走"外显行为日志"

这是隔离模型的核心约束，写成代码就是：

```python
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

Meme Registry 是第四个但不进 HybridRetrieve 主流程——它由 Director 和 Mode P 直接显式调用（详见 §8）。

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
NODE Foreshadow    {id, planted_at_scene, reveal_tier: must|may|hidden, status}

REL  RELATIONSHIP  Character -> Character {kind: love|rival|kin|..., strength, valid_from, valid_to}
REL  PRESENT_IN    Character -> Place     {scene_id, ts}
REL  KNOWS         Character -> Fact      {since_scene}
REL  TOUCHES       Fact      -> Theme     {weight}
REL  PLANTED       Foreshadow -> Fact     {plant_scene, target_reveal_scene?}
REL  REVEALED      Foreshadow -> Scene    {reveal_scene}
```

查询模式四种：
- **节点查询**：给个角色 id 拉它的所有当前关系（带时序过滤 `valid_at = now`）
- **路径查询**：Maria 和 Pedro 之间的最短关系链（Cypher-like）
- **时序事实查询**：给个时间锚点 + 一组实体，拉所有 `valid_from <= t <= valid_to` 且 `viewer_id ∈ known_by` 的事实
- **伏笔状态查询**：拉所有 `status = planted, not yet revealed` 的 Foreshadow 节点，按 `reveal_tier` 分桶。Director 在节拍决策时会查这个，催作者收没揭开的伏笔

KuzuDB 的语义类似 Neo4j 但是嵌入式（无独立 server 进程），文件就是数据库。完美匹配"一个文件夹一个故事"的形态。

### 5.3 Vector Store 的角色

只装一类东西：**已写章节散文的 chunk**。每 chunk 标 `chapter_id / scene_refs / pov_character / chunk_idx / token_count / catchphrase_used[]`。

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

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `want` | string | **是** | 角色嘴上要的、每章可见的目标。北极星，必须用一句话讲清。"打脸纳兰嫣然"、"长生"、"查母亲被杀的真相" |
| `need` | string | **是** | 角色实际缺的、可能 ta 自己都没意识到的更深需要。可以模糊，但必须存在。"在皇权下做想说就说的人"、"为活着本身而活着"。空着此字段在 §11.4 的 critic 检查里会被 flag |
| `want_need_distance` | enum | 否 | want 和 need 的错位程度：`tight` (网文式 want=need 几乎重合) / `wide` (主流路) / `tragic` (严肃文学式深度错位) |
| `signature_lines` | string[] | **是，至少 3 条** | 这个角色脱离上下文能说出、20 字以内、有传播性的台词清单。"如果想不出来，这个角色还没成立"是硬规则 |
| `arc` | object | 否 | 角色弧光。`{ stages: [{name, summary, target_scene_idx, completion_signal}], current_stage: 0 }`。Director 在判断 Beat Note 进度时参考 |
| `arc.observed_actions` | string[] | 否 | 该角色在 Scene Log 里被记录过的关键行为引用（自动维护） |
| `secrets` | object[] | 否 | 秘密清单。每条 `{content, knowers: [character_ids], reveal_trigger?: string}`。检索时按 viewer 过滤 |
| `voice` | object | 是 | 声音规则。`{rules: [...], speech_patterns: [...], avoid: [...]}`。塞 system prompt 第 3 块 |
| `voice_exemplar_refs` | object | 否 | 缓存指针，指向 voice/recent.json 里抽好的几段 |
| `activity_bias` | float | 否 | 0-1，Director 在拍序决策时用作权重（越高越爱主动开口） |
| `relations_seed` | object[] | 否 | 初始关系列表，会被首次写入 Story Graph 后清零标记。`{target_character, kind, strength, valid_from}` |
| `pov_eligible` | bool | 否 | 是否可以做 POV 角色（影响 Mode P 的 Narrator session 选择） |
| `inkfish_version` | string | 是 | ext schema 版本 |

`want` / `need` / `signature_lines` / `voice` 这四个是 INKFISH 区别于纯 CCv3 的硬扩展。其他 SillyTavern 角色卡导入时这四个字段为空，作者**必须**填写才能让该角色进入任何场景模拟——这是 INKFISH 强制的最低人物完成度。

### 6.3 want vs need 双轨追踪

want 是每章可见的引擎，need 是长程隐藏的灵魂。两者错位是戏剧动力。

INKFISH 在每个章节写完后让 Critic session 自动跑一次 `want_need_check`：
- 主角的 want 是否在本章被推进、阻碍、改变？（必须三选一，不能是"原地打转"）
- 主角的 need 是否在本章被靠近一点？连续 N 章 need 没有任何推进会被 flag
- want / need 是否还存在？（防止作者写到一半把角色目标写丢了——会说话的肘子《大王饶命》后期的疲软就是这个失败模式）

`want_need_distance` 字段提示作者**自己选定**这本书的写作姿态。tight 适合升级流爽文（萧炎），wide 适合主流类型小说（克莱恩），tragic 适合严肃文学（福贵）。Critic 的检查严格度按这个字段调——tragic 模式下 need 模糊允许度更高，tight 模式下 want 失焦容忍度更低。

---

## 7. 节拍引擎（Pacing Engine）

INKFISH 不预设作者用哪种结构，但要求结构是**显式叠加的**。Pacing Engine 让作者把多套结构工具栈在同一个项目里同时跑：外层 Story Circle 管卷，中层 Save the Cat 管卷内 beat，内层起承转结管章节内氛围。三章定律单独作为开局守则。

### 7.1 三层节拍 Schema

存在 `outline/beats.json`：

```json
{
  "story_circle": {
    "label": "全书 8 阶段",
    "stages": ["You", "Need", "Go", "Search", "Find", "Take", "Return", "Change"],
    "current_stage_idx": 2,
    "stage_to_volume": {0: "vol1", 1: "vol1", 2: "vol2", ...}
  },
  "volumes": [
    {
      "id": "vol1",
      "label": "第一卷·觉醒",
      "save_the_cat_beats": [
        {"beat": "Opening Image",     "target_chapter": 1,  "status": "done"},
        {"beat": "Theme Stated",      "target_chapter": 1,  "status": "done"},
        {"beat": "Set-Up",            "target_chapter": 2,  "status": "done"},
        {"beat": "Catalyst",          "target_chapter": 3,  "status": "in-progress"},
        {"beat": "Debate",            "target_chapter": 4,  "status": "planned"},
        {"beat": "Break Into Two",    "target_chapter": 5,  "status": "planned"},
        ...
        {"beat": "All Is Lost",       "target_chapter": 14, "status": "planned"},
        {"beat": "Dark Night of Soul","target_chapter": 15, "status": "planned"},
        {"beat": "Finale",            "target_chapter": 17, "status": "planned"}
      ]
    }
  ],
  "chapters": [
    {
      "id": "ch03",
      "kishōtenketsu": {"qi": ["scene_011"], "cheng": ["scene_012"], "zhuan": ["scene_013"], "jie": ["scene_014"]},
      "tension_target": 0.6,
      "scene_role": "catalyst-arrives"
    }
  ],
  "opening_rule": {
    "first_three_chapters": {
      "must_introduce_protagonist_within_words": 300,
      "must_show_first_conflict_within_words": 3000,
      "must_reveal_hook_within_chapters": 3,
      "high_concept": "克苏鲁 + 塔罗 + 蒸汽朋克"
    }
  }
}
```

每一层都是独立可启用/禁用的。作者写诡秘那种长篇可能三层都用，写一个独立短篇可能只用起承转结。

### 7.2 张力曲线管理

每个章节有 `tension_target`（0-1），作为 Director 在场景模拟时的核心拍序判据。

张力曲线的形状由作者选模板（在 `outline/beats.json` 顶层）：
- **Save the Cat 标准曲线**：缓上升 → All Is Lost 处掉 0 → 极速反弹到结局
- **网文升级流曲线**：每卷锯齿型，每个小高潮回落不深，整体缓上升
- **起承转结曲线**：起承平稳低位 → 转处突变（不一定上升，可能侧移）→ 结回归
- **十日终焉式无限流曲线**：每个副本独立曲线 + 整体缓涨

Director 在每场景开始前查询 `pacing_engine.get_target(chapter_id, scene_idx)`，拿到张力目标值 + 当前章节 beat 标签，作为本场拍序决策的硬约束。

### 7.3 微结构模板：装逼打脸 / scene-sequel / 起承转结 / 反转

Pacing Engine 维护一组**微结构模板**，作者可以在 Beat Note 里调用某个模板来强制本场结构：

**装逼打脸（Power Trip）模板**：
```yaml
template: power_trip
phases:
  - name: 极限施压
    duration_ratio: 0.40
    instruction: |
      反派或环境对主角施压，让读者产生"我想看这个人吃瘪"的负面情绪积压。
      压抑必须可读：反派必须做读者真的看不爽的事，不是无缘无故的恶。
  - name: 第一波宣泄
    duration_ratio: 0.30
    instruction: 主角反击，把第一波情绪宣泄掉
  - name: 二阶反转
    duration_ratio: 0.20
    instruction: '"反派以为赢了 → 主角更狠"。这一波必须在能量上压过第一波'
  - name: 余韵
    duration_ratio: 0.10
    instruction: 落幕，让读者带着满足感读下一章
```

**scene-sequel 模板**：
```yaml
template: scene_sequel
sequence:
  - phase: scene
    parts: [goal, conflict, disaster]
    instruction: 主角带明确目标进入，遇阻力，事情比预想更糟
  - phase: sequel
    parts: [reaction, dilemma, decision]
    instruction: 主角消化、面对两难、做出新决定 → 进入下一个 scene
```

**起承转结 模板**：
```yaml
template: kishōtenketsu
sequence:
  - phase: 起
    instruction: 平稳铺设状态，建立基础情境
  - phase: 承
    instruction: 延续状态，深化情境（无冲突激化）
  - phase: 转
    instruction: 视角偏移或新信息突然出现，让前两幕被重新理解（可不是冲突）
  - phase: 结
    instruction: 在新理解下回归
```

**多层反转模板**（reveal_chain）：参数化，作者指定反转层数 1-3，每层指定揭示什么，模板自动安排揭示节奏（前面密度低，最后一次密度集中）。

模板由 Director 应用到拍序：每一拍都映射到模板的某个 phase，Director 用 phase 的 instruction 作为该拍的 in-context note 注入对应角色 session。

### 7.4 伏笔的三档管理

`outline/threads.md` 是作者维护的主题线 / 伏笔 / 悬念清单。每条伏笔在 Story Graph 里也是一个 Foreshadow 节点，分三档：

- **必揭（must）**：写下时就规划好揭示章节。Director 在到达 target chapter 前会持续提醒"该收 X 这条伏笔了"
- **可揭（may）**：和读者博弈。如果作者想让读者猜到，揭得早；如果想要震撼感，藏到最后。Director 不主动催，但作者在每章末尾可以查"还有哪些 may 伏笔在飘"
- **藏到最后（hidden）**：卷尾或全书结尾才能爆。Director 严禁角色 session 在 hidden 伏笔的目标章节前主动暴露——这是知道集隔离硬线的延伸

伏笔状态字段：`planted` / `hinted` / `revealed_partial` / `revealed_full`。每章 Critic 检查"有没有 must 伏笔过期未揭"、"有没有 hidden 伏笔意外被角色提前说出"。

### 7.5 假想读者（Imagined Reader）

Pacing Engine 自带一个特殊 session：Imagined Reader。它不参与场景模拟，只在以下时机被作者主动调用：
- 章节写完后："以一个第一次读这本书的网文老读者视角，你在这一章哪里想关掉 App？"
- 卷写完后："以一个想看完整故事的读者视角，主角的 want 是否还清晰？need 推进了多少？哪些梗已经过气？"
- 任意时候："这一段你能猜到接下来要发生什么吗？"

Imagined Reader 的 system prompt 是从作者预设的"目标读者画像"生成的。作者可以在 `inkfish.toml` 里配置多个目标读者画像（"网文老读者"、"轻小说粉"、"严肃文学读者"），调用时选其中一个或全部并行跑。

这是 INKFISH 对"作者-读者博弈"的本地仿真——真实读者不在场，但用 LLM 演一个、定期听它的反馈，是个人写作工具下的最佳近似。

---

## 8. 梗管理（Meme Registry）

梗在小说里有两层意义，INKFISH 显式分开管理。

### 8.1 大 meme（Trope Library）

Dawkins 意义上的文化复制子——流派套路、世界观原型、结构模板。这些是**骨架**，决定一本书能活多久。

`presets/tropes/` 目录下放可复用的 trope 文件：
```
presets/tropes/
├── xianxia_cultivation_levels.json    # 修真九段制
├── isekai_truck_kun.json              # 异世界転生
├── system_progression.json            # 系统流
├── reincarnation_with_memory.json     # 重生流
├── cthulhu_pathway.json               # 克苏鲁式力量体系（《诡秘之主》序列）
├── infinite_world_loop.json           # 无限流
├── group_chat_setting.json            # 群聊流（设定即梗）
└── ...
```

每个 trope 文件是结构化描述：核心机制、读者预期、禁忌（不能这么用就崩）、经典作品引用。INKFISH 启动新项目时让作者从 trope library 选 0-N 个作为骨架——选了就在 Lorebook 自动生成对应 constant 条目，并在 Pacing Engine 里激活该 trope 推荐的微结构模板。

trope library 是**社区可贡献**的——预设几十个起步，作者可以自己加、可以从外部导入。

### 8.2 小梗（Catchphrase Tracker）

网生代意义上的梗——具体台词、running joke、二创素材。这是**调味**，决定发表那年读起来够不够脆，但有半衰期。

`memes/catchphrases.json`：
```json
[
  {
    "id": "mar_001",
    "text": "我家先生最棒了",
    "owner_character": "maria",
    "type": "catchphrase",
    "first_appearance": {"scene": "scene_007", "ts": "..."},
    "occurrences": ["scene_007", "scene_011", "scene_018", "ch03_para_42"],
    "user_marked_as_signature": true,
    "half_life_estimate": "long",
    "based_on_external_meme": null
  },
  {
    "id": "ext_001",
    "text": "city 不 city",
    "owner_character": null,
    "type": "external_meme",
    "first_appearance": {"scene": "scene_022", "ts": "..."},
    "occurrences": ["scene_022"],
    "user_marked_as_signature": false,
    "half_life_estimate": "short",
    "based_on_external_meme": "city-bu-city-2024",
    "expiry_warning": "2027 之后大概率读不出来了"
  }
]
```

`half_life_estimate` 三档：
- **long**（3+ 年）：基于通用人类经验、原创、或基于古老 meme 的台词。可以放在关键情节节点
- **medium**（1-3 年）：基于流派内部成熟梗。可以放在重要情节
- **short**（<1 年）：基于 2024-2026 网络流行语、综艺梗、明星梗。**只放在不重要的对话里，不放在关键情节节点**

Critic session 在每章写完后跑 `meme_audit`：扫描章节中出现的所有 catchphrase，检查 short 类型是否被放在关键节点（如果是，提醒作者"这个梗 2 年后会让本章过气"）。

### 8.3 协同造梗循环（个人版）

MiroFish 那种"作者-读者协同造梗"在 INKFISH 个人工具里没有真实读者，但循环可以仿真：

```
1. 作者写场景 / 跑 Mode S → 输出包含若干句子
2. 作者读 transcript，遇到一句"诶这句意外有趣"，按快捷键标记成 candidate
3. INKFISH 把这句进 Meme Registry 的 candidate 池，标 owner_character + first_scene
4. 之后每跑该角色的 session，Director 把这句作为"标志锚"塞进 system prompt 第 4 块尾部
   → 该角色在后续场景倾向重复或变奏这种表达
5. 重复 3-5 次后，作者可以"提升"这条 candidate 为 signature（自动写回角色档案的 signature_lines）
6. Imagined Reader 在卷末 review 时会汇报"这本书已经形成了 N 条标志台词，最强的是 X / Y / Z"
```

这把"作者最初造的不是梗、是普通笑话；后来被读者强化"的循环搬到个人工具——只是把"读者的本章说"换成了"作者自己重读时的标记"。

### 8.4 Meme 与 Director 的接口

Director 每场景开始时调用 `meme_registry.get_active_for(present_characters)`，拿到：
- 每个在场角色的 active signature_lines（来自 6.2 强制字段）
- 每个在场角色的 candidate catchphrases（被作者标记但还没提升到 signature）
- 当前章节是否在 short-half-life meme 的"安全区"（不是关键 beat 章节）

Director 把这些塞进对应角色的 system prompt 第 4 块，作为软提示。强度是"如果有合适机会就用，但别强塞"。

---

## 9. 散文质量保障

LLM 写中文小说散文最大的三个失败模式：(a) AI 腔（陈词滥调 + 空洞华丽）、(b) show vs tell 失衡（要么干瘪叙述要么空洞抒情）、(c) 缺少令人愉悦的细节。INKFISH 用三个机制对抗。

### 9.1 Show vs Tell 分层规则

Mode P 的 Narrator session system prompt 里包含一段硬规则：

```
分层处理：
- 设定信息（修真境界、世界规则、角色身份、地理）→ TELL，立刻交代清楚
  原因：连载读者没耐心解码新设定，纯 show 会被认为是水
- 角色情绪（悲伤、震惊、犹豫、决心）→ SHOW，用动作 / 细节 / 对白侧写
  原因：直接 tell 情绪会让重要情感时刻失重
- 关系状态（信任、敌意、暧昧）→ 第一次出现时简短 tell 一下，后续靠 show 维持
- 主题（命运、自由、孤独）→ 永不 tell，只 show
```

这段规则是写死在 Mode P 的默认 preset 里的。作者可以在 Prompt Manager 里看到、编辑、保存为不同 preset（"严肃文学版"可能把"设定"也改成 show）。

### 9.2 细节种子（Detail Seeds）

针对 LLM 不会自发写出"福贵把儿子有庆下葬时'用手把土盖上去，把小石子都捡出来，我怕石子硌得他身体疼'"这种细节的问题。

Detail Seed 是作者埋在场景或章节里的"必含细节"。三种来源：

1. **场景规划时埋**：作者写场景骨架时直接写 `[seed: Maria 摸了一下耳坠]`
2. **Mode S 中标记**：作者跑场景模拟，看到 LLM 自发写出的某个细节意外好（或某个细节明显是糟糕的 cliché），在 transcript 上标记 keep / replace
3. **从已写章节抽**：Critic 模式扫描已写章节，识别"这个细节出现得很妙"自动 propose 给作者标记

Seeds 存在 `scenes/<id>/seeds.json`：
```json
[
  {"id": "s1", "content": "Maria 摸了一下左耳的银耳坠", "source": "author", "consumed": false, "mandatory": true},
  {"id": "s2", "content": "Pedro 把杯子里剩下的酒倒在地上", "source": "author", "consumed": false, "mandatory": true},
  {"id": "s3", "content": "厨房窗外的雨声盖过了对话最后一句", "source": "scene_log_keep", "consumed": false, "mandatory": false}
]
```

Mode P 写散文时，Detail Seeds 强制清单作为 context 注入。Narrator session 输出后 Director 校验每个 mandatory seed 是否被消耗，未消耗的触发"重写或确认放弃"流程。

### 9.3 Critic Session 的按需触发

Critic 不是每章必跑。它有四种独立触发：

- **want_need_check**（每章末自动）：检查主角 want 推进、need 推进
- **consistency_check**（按需）：扫已写章节找设定矛盾、外貌前后不一、时间线 bug
- **voice_drift_check**（按需）：拉某角色的所有对白做风格回归分析，找"这一段不像她"的句子
- **meme_audit**（每章末自动）：扫 short-half-life 梗是否在关键节点
- **detail_density_check**（按需）：分析散文中"令人愉悦的细节"密度，太低提醒作者补
- **pacing_check**（每卷末自动）：拉本卷张力曲线对照 beat 模板，找偏差

每个 critic 任务都跑在精修档（Opus 4.6 + 200K context curate），结果写到 `chapters/<id>.critique.md`。作者决定接不接受。

### 9.4 假想读者反馈

见 §7.5。从散文质量角度，Imagined Reader 的最重要任务是回答："你看到这里有没有想停？哪一段让你想去刷小红书？"——这种"真实弃读触发点"是作者自己读不出来的（因为知道后面要写什么）。

---

## 10. 数据模型 / 项目文件布局

一个故事 = 一个文件夹。文件夹长这样：

```
my-novel/
├── inkfish.toml                 # 项目配置：LLM backend、embedding model、token budgets、
                                 #   高概念钩子、目标读者画像列表、默认 want_need_distance
├── characters/
│   ├── maria/
│   │   ├── card.png             # CCv3 PNG
│   │   ├── ext.json             # INKFISH 扩展（含强制 want/need/signature_lines）
│   │   ├── voice/recent.json    # voice exemplar 缓存
│   │   └── interviews/*.md
│   └── pedro/...
├── lorebook/
│   ├── world.json               # 全局 lorebook
│   └── chapters/
│       └── ch01.json            # 章节级 lorebook（被 ch01 写作时激活）
├── graph/
│   └── story.kuzu/              # KuzuDB 数据库目录（含 Foreshadow 节点）
├── vectors/
│   └── prose.sqlite             # sqlite-vec 数据库
├── scenes/
│   ├── 001_cafe/
│   │   ├── meta.json            # 场景元数据：present, time_anchor, mode, status,
                                 #   pacing_target, narrative_jobs[]（多任务标签）
│   │   ├── transcript.jsonl     # append-only Scene Log，权威版本
│   │   ├── transcript.md        # 人类可读版（每次写入时自动同步）
│   │   ├── seeds.json           # Detail Seeds 清单
│   │   └── director_notes.json  # 本场生效的 director notes 快照
│   └── 002_kitchen/...
├── chapters/
│   ├── ch01.md                  # 章节散文
│   ├── ch01.meta.json           # POV、scene_refs、voice preset、pacing、catchphrases_used
│   ├── ch01.critique.md         # Critic 输出（按需）
│   └── ch01.history/            # 旧版本归档
├── outline/
│   ├── beats.json               # 三层节拍 schema（§7.1）
│   ├── threads.md               # 主题线、伏笔、悬念清单（人类可读）
│   └── high_concept.md          # 一句话高概念钩子（强制存在）
├── memes/
│   ├── catchphrases.json        # 小梗追踪（§8.2）
│   ├── candidates.json          # 待提升的 candidate 池
│   └── tropes_active.json       # 本项目启用的 trope 列表（指向 presets/tropes/）
├── presets/
│   ├── tropes/                  # 大 meme 库（可跨项目复用）
│   │   ├── xianxia_cultivation_levels.json
│   │   └── ...
│   ├── prompts/                 # prompt preset
│   │   ├── manuscript_default.json     # tier: precise
│   │   ├── manuscript_fast.json        # tier: fast
│   │   ├── interview_probing.json
│   │   └── critique_consistency.json
│   └── readers/                 # 目标读者画像（用于 Imagined Reader）
│       ├── webnovel_veteran.json
│       ├── lightnovel_fan.json
│       └── literary_reader.json
├── director/
│   ├── notes_active.json        # 当前生效的导演控制台
│   └── notes_archive/*.json     # 历史 notes 快照（可回滚）
└── .inkfish/
    ├── locks/                   # 子进程文件锁
    ├── ipc/                     # 子进程 IPC 命令/响应文件
    └── cache/                   # 临时缓存
```

所有 `.json` / `.md` UTF-8，`.jsonl` append-only，`.kuzu` 和 `.sqlite` 是二进制数据库但都是单文件可备份。整个文件夹 git init 直接走（`.gitignore` 屏蔽 `.inkfish/`）。

---

## 11. 模块拆分 + 接口契约

按依赖方向自下而上：

### M1: storage

负责：filesystem layout、文件读写、CCv3 PNG 解析、JSON schema 校验。
入：路径。
出：Python 对象（CharacterCard、SceneLog、LorebookEntry、DirectorNote、PacingPlan、MemeEntry……）。
关键：所有上层模块都通过 storage 取数据，不能直接读文件。

### M2: knowledge

负责：Lorebook 触发引擎 + Story Graph (KuzuDB) + Vector Store (sqlite-vec) + HybridRetrieve。
入：query、viewer_id、scene_id、budget。
出：`List[ContextChunk]`。
关键：所有 LLM session 取上下文都走 `HybridRetrieve.run(...)`，没有别的口子。Reverse Updater 也住在这层。

### M3: llm

负责：多 backend LLM 客户端（Anthropic SDK / OpenAI SDK / Ollama 本地）+ 长上下文档位调度（粗活档 / 精修档，见 §12）+ 通用 retry / json repair。
入：messages、model_tier、tools。
出：response 或流式 chunks。
关键：上层只指定 tier 不指定具体模型，便于切换。

### M4: director

负责：Director coordinator 的所有逻辑——拍序决策、可见性管理、notes 注入、终止判定、调用 M9 / M10 / M11。
入：SceneContext、用户行动事件。
出：下一拍指令（actor_id, trigger, in_context_note）。
依赖：M2, M3, M9, M10, M11。

### M5: agent

负责：单角色 session 生命周期、system prompt 拼装、context 拼装、子进程化运行、IPC。
入：character_id、SceneContext、Director 指令。
出：Scene Log entry。
依赖：M1, M2, M3。
关键：每个角色一个子进程；进程间通过 `.inkfish/ipc/` 文件通信，学 MiroFish。

### M6: modes

负责：四种模式的执行流程（Mode S/G/P/I），把 director 和 agents 编排起来。Mode P 同时调 M11 拿 Detail Seeds。
入：UI 来的模式启动指令 + SceneContext。
出：Scene Log 增长 + Reverse Updater 触发。
依赖：M4, M5, M11。

### M7: api

负责：FastAPI 后端 + GraphQL endpoint + WebSocket 推送（场景演化的实时流）。
入：HTTP / WS。
出：GraphQL 响应。
关键：前后端唯一接口是 GraphQL，schema 在这一层定义。所有 mutation 走 M6。

### M8: ui

负责：Prompt Manager / Director Console / Scene Browser / Editor / Pacing Board / Meme Registry / Character Studio。
形态：HTMX + 服务端渲染（MVP 起步）；后续可以包成 Tauri desktop。
依赖：只通过 GraphQL 调 M7。

### M9: pacing

负责：节拍引擎——三层节拍 schema 管理、张力曲线、微结构模板（装逼打脸 / scene-sequel / 起承转结 / 反转）、伏笔三档管理、Imagined Reader session。
入：当前 chapter_id / scene_id、查询类型。
出：当前 beat 标签 / tension target / 微结构模板 instruction / 待收伏笔提醒 / Imagined Reader 反馈。
依赖：M1, M2, M3。
被谁用：M4 (Director) 在每场景每拍前显式调用。

### M10: memes

负责：梗管理——大 meme (trope library) + 小梗 (catchphrase tracker) + 半衰期评估 + 协同造梗循环。
入：当前 character set / chapter / 标记事件。
出：active signature_lines、candidate catchphrases、half-life warnings、trope-driven 微结构推荐。
依赖：M1。
被谁用：M4 (Director) 在每场景前调用拿 active memes；M6 (Mode P) 在散文转写时检测复用情况；UI 直接调（用户标记）。

### M11: detail_seeds

负责：Detail Seeds 清单维护、强制注入 Mode P、消耗校验、自动 propose 候选。
入：scene_id + seed_source。
出：未消耗 mandatory seeds 列表、消耗 status。
依赖：M1。
被谁用：M6 (Mode P) 写散文时把 mandatory seeds 塞 Narrator context；M4 (Director) 在 Mode S 拍序决策时考虑 seed 消耗机会。

模块间依赖是单向的（M8 → M7 → M6 → M4/M5 → M2/M3/M9/M10/M11 → M1）。M4 和 M5 不互相调；它们都被 M6 编排。M9/M10/M11 是横向工具模块，被 M4 和 M6 显式调用。

---

## 12. 长上下文使用原则

2026 年 5 月的现实：Claude Opus 4.6 / Sonnet 4.6 都有 1M context GA 标准定价；GPT-5.4 ~1.05M；Gemini 3.1 Pro 1M。但检索质量差距大（Sonnet 4.6 在 MRCR 上 ~78%，GPT-5.4 ~37%，Gemini ~26%），且 "lost in the middle" 在 1M context 中段仍然丢 30%+ 精度。

这意味着 INKFISH 必须做两档：

### 12.1 粗活档（fast tier）

适用：Mode S 跑场景骨架、Mode G 推非关键对话、长段散文初稿、批量 voice 探索、Critic session 做粗筛、Imagined Reader 的章节级反馈。

策略：1M context 全开。让模型自己处理大量历史。允许把整本 lorebook、整章 Scene Log 一股脑塞进去。模型选 Claude Sonnet 4.6（性价比最好）或 GPT-5.4（如果作者偏好）。

容忍：中段精度损失。粗活只要骨架对就行，细节后面精修档补。

### 12.2 精修档（precise tier）

适用：Mode P 写最终散文章节、关键章节连贯性审查、voice 校准、关键 beat 的群戏推演、Critic 做最终验证、卷末伏笔检查、关键反转章节的 Director 决策。

策略：context 严格压在 200K 以内。手工 curate context：HybridRetrieve 的 budget 卡死在 ~80K，不允许整章塞。Voice exemplar 必须主动选 3 段而不是默认 top-k。Director notes 全开。Detail Seeds 全部强塞。模型选 Claude Opus 4.6。

代价：作者要花更多时间挑 context 块（UI 上要露出"哪些块进了 context"的预览）。

### 12.3 Prompt Manager 必须支持两档预设

UI 上每个 preset 都要标 `tier: fast | precise` 字段。切档不只是换模型——是换整个 context 装配策略。precise 档的 preset 默认带"context preview & approval"步骤，让作者在调 LLM 前看一眼最终装好的 prompt 长什么样。fast 档默认跳过这一步。

实施细节见 [`04-build.md`](./04-build.md) 的对应阶段切片。

---

## 13. 技术栈选择 + 为什么

### 13.1 后端：Python + FastAPI

候选：Python (FastAPI / Flask) / Node (Express / Hono) / Go / Rust。
选 Python + FastAPI。
理由：LLM SDK 在 Python 最完整（Anthropic / OpenAI / Ollama 都是 Python 一等公民）；FastAPI 的 async 支持和 pydantic schema 拼 GraphQL 很顺；个人工具不需要极致性能；KuzuDB 和 sqlite-vec 都有 Python 绑定。Flask 不选是因为 async 模型差、依赖第三方扩展才能做 WebSocket。Node 不选是因为 LLM 工具链生态比 Python 弱一档。Go/Rust 不选是因为 LLM SDK 不全，开发速度慢，对个人工具不划算。

### 13.2 前后端接口：GraphQL

候选：REST / GraphQL / tRPC / gRPC-Web。
选 GraphQL（Strawberry 实现）。
理由：四模式共享同一份 state，前端不同 view 需要的字段切片差别大（场景浏览器要 transcript 摘要，编辑器要章节散文 + meta，Pacing Board 要 beats + tension curve + 伏笔状态，Meme Registry 要 catchphrase 时序），REST 会催生大量 bespoke endpoint。GraphQL 让前端按需取字段。tRPC 不选是因为它假设全栈 TypeScript，前后端不同语言时优势消失。gRPC-Web 不选是因为浏览器调试不友好且对手编 query 不友好（个人工具我会经常直接 curl）。

### 13.3 前端：HTMX 起步，可升级 Tauri

候选：React/Vue SPA / HTMX + 服务端渲染 / Tauri desktop / Electron。
MVP 选 HTMX；后续可包 Tauri。
理由：HTMX 的"服务端渲染 + 局部刷新"心智模型最匹配单用户工具（不需要 client-side state 管理）。React/Vue SPA 是为多用户协作和复杂前端 state 设计的，单人写小说用不上。Tauri 比 Electron 轻一个数量级，包出来 ~10MB 而非 ~100MB；如果以后想做"双击打开"的 native app 体验，包成 Tauri 即可，HTMX UI 直接在 webview 里跑。

### 13.4 图数据库：KuzuDB

候选：KuzuDB / DuckDB / Neo4j / Memgraph / SQLite + 自建图层。
选 KuzuDB。
理由：嵌入式（无独立 server 进程）；列式存储查询快；Cypher 兼容；MIT license；C++/Python 绑定都成熟。Neo4j / Memgraph 都需要独立 server 进程，"一个文件夹一个故事"形态下太重。SQLite + 自建图层早期可以但路径查询性能扛不住。DuckDB 不是图原生（虽然能用 recursive CTE 模拟，但 schema 和查询语法都别扭）。

### 13.5 向量库：sqlite-vec

候选：sqlite-vec / Chroma / LanceDB / FAISS / Qdrant local。
选 sqlite-vec。
理由：单文件嵌入式；和 SQLite 同进程；性能对个人规模（几万 chunk）足够；备份就是拷贝文件。Chroma / Qdrant 需要独立服务进程。LanceDB 也是嵌入式但生态相对小且 schema 演化体验差。FAISS 没有元数据查询，要自己建一层 k-v store 配它。

### 13.6 子进程容器 + 文件 IPC

候选：multiprocessing.Pool / subprocess + filesystem IPC / asyncio task / Ray / Dask。
选 subprocess + filesystem IPC（学 MiroFish）。
理由：进程隔离 = 状态隔离 = 故障隔离，一个角色的 LLM 调用挂掉不影响其他；filesystem IPC 调试友好（命令是 JSON 文件可以肉眼看可以手动改）；不依赖任何 message broker。代价是 IPC 延迟（~0.5s 轮询），但小说写作不是实时游戏，这个延迟无所谓。multiprocessing.Pool 不选是因为它的进程间通信走 pickle，调试痛苦。asyncio task 不选是因为没有进程隔离（一个 task 挂可以拖整个 event loop）。Ray / Dask 是分布式工具，对单机个人工具是过度设计。

### 13.7 LLM 接入：多 backend 抽象

候选：写死单 provider / litellm / langchain / 自己抽象。
选自己抽象（薄一层）。
理由：实际只需要 chat completion + streaming + tool calling 三件事；litellm 引入大量我用不到的依赖且 schema 经常变；langchain 是抽象灾难且为 SaaS 应用设计。自己写一个 ~200 行的 `LLMClient` 基类 + 三个 backend 实现（Anthropic / OpenAI / Ollama）成本可控且完全掌控行为。tier 调度也住在这一层。

### 13.8 文件持久化：纯 filesystem

候选：filesystem only / SQLite 主索引 + filesystem 内容 / 全 SQLite。
选 filesystem only。
理由：手编、git diff、备份都最简单；个人规模（几百场景、几十章节）filesystem scan 性能完全够；不需要事务（没有并发写者）。全 SQLite 会把所有内容塞进二进制文件，失去文本编辑器直接编的能力——违背 §1 立场。

---

## 14. Sources

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
- 节拍 / 角色 / 梗 / 散文质量四个维度的设计灵感来自一份关于网文-轻小说-严肃小说方法论的 compass 文档，核心论点：所有小说背后只有一套机制——控制读者每一秒钟想不想翻下一页；剩下的全是参数。INKFISH 的 §1、§7、§8、§9 是这个论点的工程化实现。
- 主要直接引用的方法论作者与作品：Joseph Campbell（英雄之旅）、Christopher Vogler（十二步）、Blake Snyder（Save the Cat）、Dan Harmon（Story Circle）、起承転結（kishōtenketsu）日本传统四段结构、E.M. Forster（flat vs round）、Robert McKee（character vs characterization）、John Truby（want vs need）、Dwight Swain（scene-sequel）、Hitchcock（suspense vs surprise）、Hemingway（冰山原则）、Chekhov（contextual gun）、Richard Dawkins（meme 1976）。具体作品参照：《凡人修仙传》《诡秘之主》《十日终焉》《修真聊天群》《雪中悍刀行》《全职高手》《赘婿》《仙逆》《庆余年》《大王饶命》《活着》《围城》《这个素晴らしい世界に祝福を！》《Re:Zero》《やはり俺の青春ラブコメはまちがっている。》。
