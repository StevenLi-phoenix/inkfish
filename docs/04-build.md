# INKFISH 实施路线图

> 状态：**实施规划**。设计已锁定（详见 [`03-design.md`](./03-design.md)）。
> 受众：六个月后的 Steven。
> 目的：回答"接下来做什么、什么时候做完算完成、什么风险要警惕"。
> 形态约束已固化：个人本地工具，非 SaaS。

---

## 1. 锁定的前提清单

下面这些是入场前提，路线图不再回头讨论。如果未来要改，那是"下一份文档"的事。

- **使用者**：Steven 一个人，写中文长篇小说为主，偶尔英文。
- **根本目标**：管理读者每一秒钟想不想翻下一页。所有功能都服务于这条。
- **形态**：本地优先 / 文件友好 / git 友好 / 个人桌面或浏览器使用。
- **后端**：Python（FastAPI）。
- **API**：GraphQL（前端按需取字段，避免 REST 的 N 套 endpoint）。
- **前端**：轻量。先 HTMX，必要时升级到 Tauri，不用 React/Vue 全家桶。
- **存储**：filesystem-first。结构化图 KuzuDB，向量索引 sqlite-vec，纯文本一律 markdown / json。
- **LLM 接入**：多 backend——Anthropic（主力，Sonnet 4.6 / Opus 4.6）、OpenAI、Ollama 本地（降级）。
- **四模式共享同一份状态**：场景模拟 / 群戏对话 / 散文转写 / 角色采访。详见 `03 §3`。
- **Per-agent 隔离执行**：Director coordinator + 每角色独立 LLM session + 独立知道集。详见 `03 §4`。
- **三层世界知识**：lorebook + story graph + vector store。详见 `03 §5`。
- **角色档案强制字段**：want / need / signature_lines / voice 必填。其他字段从 CCv3 继承。详见 `03 §6.2`。
- **节拍引擎**：三层节拍（Story Circle / Save the Cat / 起承转结）+ 张力曲线 + 微结构模板（装逼打脸 / scene-sequel / 反转）+ 伏笔三档 + Imagined Reader。详见 `03 §7`。
- **梗管理**：大 meme（trope library）+ 小梗（catchphrase tracker，带半衰期）+ 协同造梗循环。详见 `03 §8`。
- **散文质量保障**：show vs tell 分层规则 + Detail Seeds 强制注入 + Critic 多任务按需 + Imagined Reader 反馈。详见 `03 §9`。
- **场景容器**：scene 作为子进程，filesystem-based IPC（学 MiroFish）。
- **不 fork SillyTavern**：从零写后端，借鉴概念但不背历史包袱。CCv3 PNG 角色卡和 lorebook JSON 资产可导入互通。
- **长上下文档**：粗活档 1M context（Sonnet 4.6 1M GA, $3/M input），精修档 200K（Opus 4.6）。

---

## 2. 用户实际写作场景

把 Steven 写一本 15 万字中文长篇当成一根线，看 INKFISH 在每一段路上做什么。这一节不是功能列表，而是"凭什么这个功能必须存在"的现场证据。

**起步：从 premise 到世界 + 人物雏形 + 高概念。** Steven 脑子里有一句 premise（"一个失去记忆的捕鱼人在沿海小镇追查自己是谁"）。INKFISH 帮他从这句话扩出：3-5 个核心人物（CCv3 兼容档案，**强制填写 want / need / signature_lines / voice**）、一个小型 lorebook、story graph 初始关系边、`outline/high_concept.md`（一句话讲清世界设定）。痛点：白屏恐惧。INKFISH 必须默认给草案；强制字段缺失时 critic 立刻 flag。

**规划：大纲 + 节拍 + 场景列表 + 选 trope。** Steven 想要一个三幕结构 + 12 个核心场景的草案。他从 trope library 选 0-N 个骨架（"修真境界"、"重生流"、"群聊设定"）；从 Pacing Engine 选张力曲线模板（"Save the Cat 标准曲线"或"网文升级流锯齿型"）；填三层节拍 schema（外层 Story Circle 卷 + 中层 Save the Cat beat + 内层起承转结章节）。痛点：节拍是隐性的，作者凭直觉容易写废。INKFISH 把节拍显式化、可视化、可调整。

**起草：场景骨架 → 散文章节。** 这是 INKFISH 的核心闭环。先在场景规划时埋 Detail Seeds（"必须出现：Maria 摸了一下耳坠"），跑场景模拟（per-agent 隔离的多角色对话，Director 应用相应的微结构模板比如"装逼打脸"），输出 scene log；再过散文转写器，scribe 受 show vs tell 分层规则约束，必须消耗所有 mandatory Detail Seeds，输出第三人称限知 POV 的中文散文。痛点：直接让 LLM 写散文章节，结果是"AI 腔"——人物声音糊在一起、没有节奏、缺细节。三步走（骨架 → 模拟 → 转写）+ Detail Seeds + 分层规则把这些缺陷一个一个堵上。

**修订：一致性 + 风格 + 节奏 + want/need + 梗半衰期。** Steven 写到第 8 章，可以按需调用 Critic 的多个独立任务：consistency_check（找设定矛盾）、voice_drift_check（某角色对白是否出戏）、want_need_check（自动每章末跑，主角 want 是否推进 / need 是否靠近）、meme_audit（自动每章末跑，short-half-life 梗是否在关键节点）、pacing_check（卷末跑，张力曲线是否偏离模板）、detail_density_check（按需，散文细节密度是否够）。**critic 是工具不是闸门**——按需触发，不强制接受。

**推进：状态延续到下一场。** 场景结束时，Director 把"本场关键事件 + 状态变化"反向写入 story graph + 把作者标记的"意外有趣的句子"写入 Meme Registry candidate 池 + 把消耗的 Detail Seeds 标记。下一场场景启动时三源检索自动带上这些更新。痛点：长篇最大的杀手是"第 12 章的 Maria 还记得第 4 章在码头说过的那句话吗"。反向写入 + 知道集隔离是答案。

**回查：临时找信息。** Steven 写到一半想知道："Maria 第一次提到她父亲是在哪一章？""有没有 must 伏笔过期未揭？" INKFISH 的多源检索（lorebook + graph + 向量）合并出答案；伏笔状态查询直接拉 Foreshadow 节点。

**共创探索：和角色对话、做 if 探索、问 Imagined Reader。** 写不下去的时候三个工具：(a) 切到 Mode I 和 Maria 长聊（探索 vs canonical 二选一）；(b) 把当前场景 fork 一个分支让 Pedro 选不同行动；(c) 调用 Imagined Reader，问"以网文老读者视角，你刚才那一章哪里想关 App"。

---

## 3. 功能切片清单

每个 F 是一个原子可验证单元。

| ID | 名称 | 输入 | 输出 | 依赖 |
|---|---|---|---|---|
| **F1** | 角色档案管理 | CCv3 PNG / 手输 / LLM 草案 | character.json（CCv3 + INKFISH 扩展，含强制 want/need/signature_lines/voice） | M3 LLM |
| **F2** | 世界书管理 | lorebook JSON / 手编 entry | lorebook.json（三态 + position/depth + 递归扫描 + token budget） | M2 knowledge |
| **F3** | 故事图谱管理 | 手编 / Director 反向写入 / 散文 ingest | KuzuDB：实体 + 时序事实 + 关系 + Foreshadow 节点 | KuzuDB |
| **F4** | 多源检索（HybridRetrieve） | query + viewer_id + scene_id + budget | 合并去重过滤后的 ContextChunk 列表 | F2 / F3 / sqlite-vec |
| **F5** | 场景规划 | 大纲位置 + 在场角色 + 目标 + Detail Seeds 草案 | scene_skeleton.md + seeds.json | F1 / F4 |
| **F6** | 场景执行（per-agent 隔离） | scene_skeleton + visibility mask | scene_log.jsonl + 反向更新 graph | F1 / F4 / Director / 子进程 IPC |
| **F7** | 散文转写（含分层规则 + Seeds 强制） | scene_log + POV + 风格 preset + mandatory Seeds | chapter.md + 已消耗 Seed 标记 | F6 / F10 / F15 |
| **F8** | Critic 多任务（按需） | 段落/章节 + 任务类型 | critique.md（按任务给疑似问题 + evidence） | F4 / F1 / F13 / F14 |
| **F9** | 角色采访 | 角色 ID + 时间锚点 + 问题 | 单角色对话 session（exploratory 默认不写图） | F1 / F4 |
| **F10** | 提示词管理 | preset JSON / 手编 block | 装配后的完整 prompt（block 可 enable/order/depth/role） | 全局 |
| **F11** | 导演控制台 | 多维度 note（Pacing/Tone/Beat/Voice/Constraint/PerCharacter） | 注入下一次 LLM 调用的对应 block | F10 |
| **F12** | 项目持久化 | 项目根目录 | filesystem 布局 + git 集成 | OS |
| **F13** | **节拍引擎** | beats.json + 当前 chapter/scene | tension_target / 当前 beat / 微结构模板 / 待收伏笔 / Imagined Reader 反馈 | M9 Pacing |
| **F14** | **梗管理** | trope library + catchphrase 标记事件 | active signature_lines / candidates / half-life warnings | M10 Memes |
| **F15** | **细节种子机制** | 场景规划 / Mode S 标记 / 自动 propose | mandatory Seeds 强制注入 Mode P + 消耗校验 | M11 Detail Seeds |
| **F16** | **want/need 双轨追踪** | character.json want/need 字段 + chapter 完成事件 | 每章自动 want/need 推进检查报告 | F1 / F8 |
| **F17** | **伏笔三档管理** | Foreshadow 节点 (must/may/hidden) | 待收提醒 / 隔离硬线（hidden 不能提前泄露）/ 状态追踪 | F3 / F8 |

补充说明：
- F6 是架构最重的一块（per-agent 隔离 + 子进程 + 知道集 mask），独占 P2。
- F13/F14/F15 是 03 文档新加的横向模块，独占 P4。
- F16/F17 是落在 character schema 和 graph schema 上的强制约束，分散在 P1（want/need 入档）和 P3（Foreshadow 入图）。

---

## 4. 非功能需求

- **性能**：场景执行单 turn 端到端 ≤ 8s（含 LLM）。检索 F4 在 ≤ 50 万字 + ≤ 200 角色实体规模下 ≤ 300ms。散文转写一章 ~3000 字端到端 ≤ 60s。Pacing/Meme 查询 ≤ 50ms。
- **可用性**：Steven 一个人用，无登录 / 账户 / 多用户隔离。CLI 起步必须能跑通整个写作流，UI 是糖衣。
- **可移植**：macOS 原生跑通；项目目录拷到另一台机器后立刻能继续写。无云端依赖（除 LLM API）。
- **成本约束**：日常写作单章成本目标 ≤ ¥10（Sonnet 4.6 1M ctx $3/M input 估算）。一本 15 万字小说全程 LLM 成本目标 ≤ ¥1500。超出阈值能切 Ollama 本地降级。
- **可观测**：所有 LLM 调用记 prompt + response + token + latency 到本地 jsonl，方便事后调 prompt。
- **可回滚**：场景目录是 git 友好的，回到任意 commit 即回到任意状态。

---

## 5. 显式不做的

写在这里防止三个月后手痒乱加。

- **多用户 / 协作**。INKFISH 永远是单人工具。
- **出版工作流**。不做 EPUB 导出 / 投稿格式化 / ISBN 元数据。导出止于 markdown。
- **移动端**。手机不是写小说的终端。
- **视觉化生成**。不接 image generation。立绘要的话外面工具做完拖进 PNG 卡。
- **社区分享 / 角色市场**。不做账号体系。CCv3 互通靠手动拷文件。
- **实时协同光标**。不是 Notion。
- **AI 自动写整本书**。INKFISH 是协作工具，Steven 始终是作者。
- **流派模板市集**。先打磨核心闭环，trope library 起步预设几十个就够。

---

## 6. 实现阶段切片

每个 phase 是一个"完成后能用 INKFISH 多做一件事"的里程碑。时间估算按"Steven 业余时间，每周净 6-10h"。

### P0 散文质量 PoC（不写代码）

**目标**：在投入任何工程之前，先验证"LLM 能不能把 scene log + Detail Seeds + 分层规则翻译成可读的中文小说散文"。如果这一步不过关，整个项目终止。

**工作内容**：
- 手工准备 1 份完整角色档案：name + description + personality + want + need + signature_lines (3 条) + voice + mes_example (5-8 条)。约 1500 字。
- 手工准备 1 份场景骨架：500 字结构化对白 + 行动 + 5 条 mandatory Detail Seeds。
- 写 3 版 prompt 配方，每版都包含 show vs tell 分层规则（设定 tell / 情绪 show / 关系第一次 tell 后续 show / 主题永不 tell）+ Detail Seeds 强制清单。
- 准备 3 个候选 backend：Claude Sonnet 4.6（粗活档候选）、Claude Opus 4.6（精修档候选）、GPT-5.4（对照）。
- 9 个组合各跑 1 次，输出 800-1200 字小说散文。
- 多维度评估，**不是只评"能不能读"**：
  - **声音不串**：主角对白和配角对白能不能听出是不同的人？
  - **show/tell 分层正确**：设定有没有立刻交代清楚？情绪有没有侧写？
  - **Detail Seeds 全部消耗**：5 条 mandatory 是不是都出现在散文里且不突兀？
  - **AI 腔程度**：陈词滥调密度（"心如刀绞"、"波澜不惊"等）≤ 1 处/500 字
  - **令人愉悦的细节**：除 Detail Seeds 外，LLM 自发写出至少 1 个"作者读了会标记"的细节
  - **整体可读**：3 轮编辑能用，编辑量 ≤ 20%

**Done 定义**：至少有 1 个组合在上述 6 个维度全过；让 1-2 个朋友盲评通过。

**Killer test**：上面这条本身就是 killer test。失败则项目终止；成功则锁定该配方为 P1 基线。

**时间估算**：1-2 周。

**风险**：评判主观。缓解：用同一份 reference 段落（自己以前手写或读过的小说片段）做对照基准；6 个维度每条都给量化或半量化标准。

### P1 CLI 单角色 demo

**目标**：命令行能跑：从 premise 创建 character.json（含强制字段）→ 运行一段独白 scene → 转散文。验证基础 IO + LLM 集成 + want/need 落地。

**工作内容**：
- FastAPI 项目骨架 + LLMClient 抽象层（Anthropic / OpenAI / Ollama 三个 backend）。
- F1 CLI 子集：`inkfish character create --premise "..."`（草案版，强制 want/need/signature_lines/voice 必填，缺失 LLM 提议候选让作者选）、`inkfish character edit`。
- F6 退化版：单角色 monologue scene，Director 退化成"提一个问题让角色独白回答"。
- F7 最简版：scene_log → markdown 散文，单一 POV，含 P0 锁定的 prompt 配方（show/tell 分层 + 简化 Detail Seeds 注入）。
- F12：项目目录布局确定（详见 `03 §10`）。
- F16 简化版：want/need 字段写入 character.json + 章节末输出"want 是否推进 / need 是否变化"的简单文本反馈（critic agent 还没建，先用裸 LLM 调用）。

**Done 定义**：`inkfish init my-novel && inkfish character create ... && inkfish scene run ... && inkfish chapter render ...` 端到端跑通，最终生成的 chapter.md 质量不低于 P0；强制字段缺失时报错不允许继续。

**Killer test**：从零项目到第一段 800 字散文 ≤ 5 分钟（Steven 操作时间）；character.json 强制字段全有。

**时间估算**：3-4 周。

**风险**：
- 选错 backend 抽象层（接口太僵）。缓解：先只支持 Anthropic 一家，P3 再泛化。
- CLI 设计自我斗争。缓解：照 git 命令形态走，不发明新风格。

### P2 CLI 多角色场景 + per-agent 隔离落地

**目标**：核心架构验证。Director coordinator + 多角色 LLM session + 知道集隔离全跑通，能产出 5-10 turn 的多角色对白。微结构模板首次落地（"装逼打脸"作为 P2 的硬目标）。

**工作内容**：
- Director coordinator：决定"下一个谁说"、"场景何时收尾"、"是否插入 narrator beat"。系统 prompt 框架是"你是戏剧导演，不进入任何角色"。
- 每个角色独立 LLM session + 独立子进程：独立 system prompt（来自 character.json，含强制字段全部）、独立 chat history、独立 voice anchor。
- 知道集 mask（基础版）：每场景内角色看 scene log 时只看到 channel ∈ {speech, action} 或自己的 inner；其他角色 inner 严格不可见。先做内存版，graph 版到 P3。
- Scene 子进程容器：每个 scene 启子进程，filesystem 写 turn log，主进程通过文件 watch + 文件锁 IPC（学 MiroFish 的 ipc_commands/ + ipc_responses/）。
- F11 简化版：单维度 Author Note 注入（"用更紧张的语气"）。
- **微结构模板首次落地**：实现 `power_trip`（装逼打脸）和 `scene_sequel` 两个模板。Director 在拍序决策时按模板的 phase + duration_ratio 安排紧张度。
- 风格锚点：mes_example 每 turn 重塞 + signature_lines 作为软提示注入。

**Done 定义**：能跑 3 角色 / 15 turn 场景，scene log 完整，散文转写后人物对白能看出三个不同的声音。"装逼打脸"模板跑出来的 5-turn 场景能看出明显的"压抑 → 宣泄 → 二阶反转 → 余韵"四段式。

**Killer test**：15 turn 长场景结束后，把任意两个角色的所有对白单独抽出来读，能否听出"这是两个不同的人在说话"。如果三个角色的对白都像同一个 LLM 在演——架构需要重做（可能要切 stronger persona injection 或 few-shot voice anchor 重塞策略）。

**时间估算**：6-8 周。

**风险**：
- 子进程 + filesystem IPC 协调复杂度被低估。缓解：先做同进程 asyncio 版本跑通逻辑，再切子进程。Q3 在这一阶段必须落地。
- 角色串味（最大风险）。缓解：mes_example + signature_lines + 已写散文的 voice exemplar 三层叠加。如果还串，挂 Voice Drift Check 作为 hard check 而非 soft warning。
- Director 不知道何时收尾。缓解：Q4 在这阶段必须有答案。

### P3 lorebook + graph + 三源检索 + Foreshadow

**目标**：场景不再是孤岛，能跨场景共享世界知识。伏笔系统首次落地。

**工作内容**：
- F2 lorebook 完整实现：三态（constant/selective/vectorized）+ position/depth + 递归扫描 + token budget。
- F3 KuzuDB schema 设计 + 实体/事实/关系 CRUD + Foreshadow 节点（带 reveal_tier: must/may/hidden + status）+ 反向写入接口。
- sqlite-vec 接入：场景日志和散文段落的 embedding（含 catchphrase_used 元数据）。
- F4 三源检索 HybridRetrieve：query + viewer_id 过滤 + 三源合并 + 按 priority 排序 + budget 截断。
- 散文 ingest pipeline：已写完章节 markdown → 抽实体/事实写图 + 段落写向量库。
- F17 伏笔三档管理：Foreshadow 节点 + Director 在拍序决策前查待收伏笔 + hidden 隔离硬线（hidden 伏笔目标章节前不能被角色 session 主动暴露，违反时 Director 强制改写）。
- 知道集 mask 从内存版升级到 KuzuDB 持久版（Q5 在此回答）。

**Done 定义**：写 3 个连续场景（至少跨 2 场的同一角色 + 同一地点），第 4 场启动时检索能拿出前 3 场关键事实，且每个角色 session 看到的检索结果按知道集过滤。Foreshadow 节点能在大纲中规划，目标章节前 Director 提醒待收。

**Killer test**：写到第 8-10 场后故意问"第 2 场提到的某细节"是否还在角色记忆里。失败则三源检索或知道集隔离需要回炉。

**时间估算**：6-8 周。

**风险**：
- KuzuDB 在小说级数据规模上实测表现未知（R6）。缓解：early benchmark，跑 50 万字 ingest 看延迟和体积。如不行 fallback 到 SQLite + 自建关系表。
- 三源合并策略难调（Q6）。缓解：先简单加权合并，留 hook 让 LLM 重排序作为可选。

### P4 Pacing Engine + Meme Registry + Detail Seeds

**目标**：03 文档里三个新增横向模块（M9/M10/M11）落地。这是 INKFISH 区别于"另一个 AI 写作工具"的关键差异化 phase。

**工作内容**：
- **F13 节拍引擎**：
  - `outline/beats.json` schema 定义 + 三层节拍（Story Circle / Save the Cat / 起承转结）+ 张力曲线模板（Save the Cat 标准 / 网文升级流锯齿 / 起承转结 / 无限流）。
  - 微结构模板库：实现 `power_trip`（P2 已有）、`scene_sequel`、`kishōtenketsu`、`reveal_chain`，作为可复用 yaml 文件。
  - Director 调用接口：`pacing_engine.get_target(chapter_id, scene_idx)` 返回当前 beat / tension / 微结构模板。
  - **Imagined Reader session**：实现至少 2 个目标读者画像 preset（"网文老读者"、"严肃文学读者"），章节末和卷末可调用。
- **F14 梗管理**：
  - Trope Library：预置 8-10 个 trope JSON（修真境界、异世界転生、系统流、重生流、克苏鲁式力量体系、无限流、群聊设定、英雄之旅）。新项目可选 0-N 个激活。
  - Catchphrase Tracker：`memes/catchphrases.json` + candidate 池 + 半衰期评估（long/medium/short 三档手动标 + LLM 提议自动估）。
  - 协同造梗循环 UI（CLI/简单 web）：作者标记句子 → 进 candidate → Director 自动塞进角色 system prompt 第 4 块 → 重复 N 次后作者 promote 为 signature。
  - meme_audit 任务：扫章节中 short-half-life 梗是否在关键节点。
- **F15 细节种子机制**：
  - 场景规划时埋种 UI（CLI 命令 + 编辑器协议）。
  - Mode S 中标记 keep / replace。
  - 自动 propose（critic 模式扫已写章节识别"细节出现得很妙"）。
  - Mode P 强制注入 + 消耗校验（未消耗的 mandatory Seed 触发"重写或确认放弃"）。
- **F16 升级**：want/need 双轨自动 critic 化（每章末自动跑，不再裸 LLM）。

**Done 定义**：
- 用一个微结构模板（"装逼打脸"）写一个 4000 字爽点章节，模板的四段式在散文里能识别。
- 注册 5 条 catchphrase，跑 3 个场景看是否被角色自然复用。
- 一个 Detail Seed 强制注入 → 散文中显式出现且不突兀。
- Imagined Reader 给一章已写章节的反馈，至少 1 条反馈能让作者真的回去改。

**Killer test**：用 INKFISH P4 写完一段 5000 字的章节，对比 P3 写的同等长度章节，"工程化的节拍 + 梗 + 细节"是否真的让散文质量提升一档（Steven 自评 + 朋友盲评）。如果没有可观察到的差距，这一 phase 的设计被推翻，回头思考节拍/梗/细节是否真的需要工程化。

**时间估算**：5-7 周。

**风险**：
- 节拍/梗/细节的工程化反而限制创作（"白屏好过烂模板"）。缓解：所有功能都是可选的，作者随时能跳过。
- Imagined Reader 给的反馈不靠谱。缓解：让作者自定义读者画像 prompt，并支持多个画像并行跑互相参照。

### P5 Director Note + Critic 多任务 + 角色采访

**目标**：完整闭环。导演控制台多维度 + critic 多任务按需 + 角色采访。从这里开始 INKFISH 真的能用来写一本书。

**工作内容**：
- F11 完整：多维度 Author Note（Pacing / Tone / Beat / Voice / Constraint / PerCharacter）+ depth 控制 + 启用开关 + 持续场景数 + preset 保存。
- F8 多任务 critic：consistency_check / voice_drift_check / want_need_check / meme_audit / detail_density_check / pacing_check 六个独立任务，按需触发或在指定时机自动触发（如每章末跑 want_need + meme_audit）。每个任务输出带 evidence 链 + confidence。
- F9 角色采访：Mode I 完整版，时间锚点过滤 + canonical/exploratory 标记 + canonical 写回机制。
- F10 提示词管理器：所有 block 暴露给作者编辑，preset 系统能保存和切换；preset 标 `tier: fast | precise`，切档同时换 context 装配策略（详见 `03 §12.3`）。

**Done 定义**：Steven 用 INKFISH 写完一个完整中篇章节（3000-5000 字），全程没有跳出去用别的工具，且最终质量他自己满意（"愿意挂在博客上"）。critic 至少抓到 1 个真实问题且 false positive ≤ 30%。

**Killer test**：连续工作日内（约 4-6h 实际写作时间）用 INKFISH 写完一章 4000 字小说，作者疲劳度低于直接手写一章。如果工具的认知负担反而大于直接写作——回头砍功能或换 UX。

**时间估算**：5-7 周。

**风险**：
- Critic false positive 太多让人想关掉。缓解：每个 critic 任务输出带 evidence + confidence；UI 默认隐藏 confidence ≤ 0.6 的项；让作者可以快捷标"误报"反馈调阈值。
- 角色采访发散到偏离世界设定。缓解：默认 exploratory 不写图，要写图必须显式 promote。

### P6 GraphQL + 轻量前端

**目标**：从 CLI 升级到能在浏览器里舒服写作的形态。

**工作内容**：
- FastAPI GraphQL endpoint（Strawberry），schema 覆盖 F1-F17。
- 前端选型决策（Q7）：默认 HTMX + Alpine.js，如发现需离线/原生体验再升 Tauri。
- 核心视图：
  - 项目仪表盘
  - **Character Studio**（角色卡编辑器，强制字段红色提示，signature_lines 候选生成器）
  - 场景执行 live view（每 turn 流式显示）
  - 章节编辑器（左原文右散文 split view）
  - **Pacing Board**（三层节拍可视化 + 张力曲线 + 待收伏笔列表）
  - **Meme Registry UI**（catchphrase 列表 + 半衰期警告 + candidate promote 操作）
  - **Director Console**（多维度 note 切换面板）
  - 检索面板（HybridRetrieve 查询 + 结果分源高亮）
- 不做：拖拽布局编辑、丰富的 WYSIWYG、协同。

**Done 定义**：CLI 95% 操作在浏览器里能做，且核心写作流（场景 → 散文）在浏览器里比 CLI 更顺。Pacing Board 和 Meme Registry UI 让作者真的会用（不是装饰）。

**Killer test**：连续两周只用 UI 不用 CLI 写作，没有"我要切回终端"的冲动。

**时间估算**：6-8 周。

**风险**：
- HTMX 撑不起场景 live view 的复杂度。缓解：场景 live view 是唯一可能需要 SPA 风格的页面，可单独用 mini React island 嵌入。
- UI 设计自我斗争。缓解：Pacing Board / Meme Registry 抄 SillyTavern 的 World Info 布局打底，再迭代。

### P7+ 实战写一本小说，根据痛点迭代

**目标**：不再做新功能，**真的用 INKFISH 写完一本 10-15 万字的中文小说**。

**工作内容**：
- 启动一本新书。每周记录痛点日志：哪里慢、哪里烦、哪里 LLM 给的烂答案最浪费时间、哪个 critic 任务真的救命、哪个梗真的复用了。
- 每月一次"工具迭代日"，根据日志改 INKFISH（不是写新书的日子）。
- 不再加大功能，**只优化已有路径**。

**Done 定义**：完成一本书。INKFISH 完成本职：让 Steven 真的写完一本想写的小说。

**Killer test**：写完后回头看，INKFISH 是帮 Steven 写得更快/更好，还是其实只是"写得更分心"？前者继续，后者大砍。具体指标：(a) 完书时间是否短于 Steven 历史上手写中篇的速度估算；(b) 朋友盲评下，INKFISH 写的章节和 Steven 纯手写的章节是否能区分（无法区分 = 工具成功；明显劣化 = 工具失败）。

**时间估算**：6-12 个月（取决于书本身的体量）。

**风险**：详见 §8 全部风险。

---

## 7. 真正剩下的开放问题

只列出"必须在某个 phase 之前回答"的。

| ID | 问题 | 何时必须回答 |
|---|---|---|
| Q1 | 哪个 LLM + 哪份 prompt 配方能把 scene log + Detail Seeds + 分层规则 → 中文散文做到 6 维度全过？ | **P0 之前**（这就是 P0） |
| Q2 | 角色弧光在数据模型上怎么表达？离散 episode（节点） vs 独立 arc state 字段（角色身上的 stage 机） vs 两者都要？ | P1 之前（影响 character.json schema） |
| Q3 | character_runtime 是真子进程还是同进程异步 task？子进程隔离干净但 IPC 复杂；asyncio 简单但故障难调。 | P2 之前 |
| Q4 | 场景结束的判定条件谁说了算？Director 自主判断 / 用户手动结束 / 多角色 LLM 投票 / 达到 turn 上限自动结束 / 微结构模板的 phase 全部消耗自动结束？ | P2 之前 |
| Q5 | 知道集（per-character knowledge mask）的存储方案？KuzuDB 边属性 / 独立 mask 表 / 内存里每场重算？ | P3 之前 |
| Q6 | 三源合并策略？按相关性加权 / 按层级优先（lorebook(constant) > graph(direct) > vector）/ 让 LLM 重排序？ | P3 之前 |
| Q7 | Trope library 的 schema：每个 trope 文件应该包含什么字段才足以让 INKFISH 自动激活相应 lorebook constant 条目和 Pacing Engine 微结构模板？ | P4 之前 |
| Q8 | Catchphrase 半衰期如何评估？纯人工标 / LLM 给候选档位 / 检测是否含 2024-2026 网络流行语 reference？ | P4 之前 |
| Q9 | Imagined Reader 的目标读者画像怎么写？至少需要哪几个维度（年龄 / 阅读偏好 / 流派经验 / 容忍度）？ | P4 之前 |
| Q10 | 前端形态：纯 HTMX 够用还是必须 Tauri 桌面？涉及离线、文件访问、性能。 | P6 之前 |
| Q11 | 中英双语写作的 UX：同一项目里中英混存 / 项目级 locale 锁定 / 角色档案双语字段？ | 持续 |

---

## 8. 风险清单

按严重度排序。

**R1【最高】LLM 写中文小说散文的质量天花板。** 即使是 Sonnet 4.6 / Opus 4.6，写中文小说散文都会暴露训练数据偏好——AI 腔、辞藻堆砌、节奏单调、缺细节。这是项目最基础的不确定性。
缓解：P0 直接验证（6 维度评估）。失败就停项目。成功就锁定该配方为 P1+ 的基线。把 Detail Seeds + show/tell 分层 + voice exemplar 三层叠加视为"对抗 AI 腔"的最低工程武装。

**R2【高】世界状态长程一致性。** Per-agent 隔离 + 三源检索 + 知道集 mask 的设计理论上能扛长篇，但没人验证过几十章后还能保住。
缓解：P3 的 killer test 故意拉长（8-10 场后回查事实）。P7 实战写作设置"每 5 章做一次全量 consistency_check"的 ritual。Foreshadow 节点强制每章末跑 status check。

**R3【高】节拍/梗/细节的工程化反而限制创作。** P4 加了一堆模板和 critic，可能让"自由写作"的乐趣消失。
缓解：所有功能默认可关；preset 系统让作者保留"白屏一切关"的最简模式；Imagined Reader 是建议不是命令。P4 的 killer test 直接问"工程化是否真的让质量提升"——答案是否会推翻整个 P4。

**R4【中】成本。** Sonnet 4.6 $3/M input × 一本书几百次迭代 × 1M 长上下文 → 单本书 LLM 成本可能爆。
缓解：粗活档（场景模拟 / scene log 草案 / consistency_check 粗筛）走 1M context 但用便宜模型；精修档（散文转写 / 关键采访 / pacing_check）走 200K 高质量模型。日常写作目标单章 ≤ ¥10。设置预算上限警告。

**R5【中】Steven 自己懒。** 工具再好，作者懒就出不了书。INKFISH 必须默认给草案——白屏比烂草案更劝退。
缓解：每个创作动作（创建角色 / 起场景 / 写章节）默认有"先给我个草案我再改"的入口。P5 的 UX 验收里强制评估这条。

**R6【中】流派偏置。** LLM 训练数据对某些流派（言情 / 仙侠 / 都市）有强偏好；对纯文学 / 实验文学输出力不从心。
缓解：preset 系统支持"流派 + 风格"组合。每个流派维护一份反套路 prompt 注入（"避免 XXX 句式 / 避免 XXX 比喻"）。Steven 写的具体流派固定后专门调一份。

**R7【中】Critic 假阳性疲劳。** Critic 多任务输出大量"疑似问题"，作者每次都得判断要不要看，最后会关掉所有 critic。
缓解：每个 critic 任务输出带 evidence + confidence；UI 默认隐藏 confidence ≤ 0.6 的项；作者标"误报"的反馈调阈值。critic 永远不强制接受。

**R8【中】Imagined Reader 是个糟糕的近似。** 没有真实读者，LLM 演的"读者"可能给方向错误的反馈。
缓解：让作者自定义多个读者画像并行跑（"网文老读者"+"严肃文学读者"+"流派内行"），互相参照差异。Imagined Reader 的反馈永远标"AI 模拟，仅供参考"。

**R9【低】KuzuDB / sqlite-vec 在小说级文本规模上的实测表现未知。** 都是相对新或小众的栈。
缓解：P3 进 phase 时做 early benchmark。撑不住时 KuzuDB → SQLite + 自建关系表，sqlite-vec → Chroma local。架构层留好抽象。

**R10【低】LLM API 成本/能力变化。** 2026-05 是 Sonnet 4.6 1M GA $3/M 的环境。半年内可能 GPT-6 出来 / Anthropic 调价 / Gemini 反超。
缓解：backend 抽象层从 P1 就建好，切换成本 = 改一个 config 文件。每季度做"用当前最强模型重跑 P0 评估"，决定是否换主力。

---

## 9. Sources

- 项目设计上下文：[`01-mirofish.md`](./01-mirofish.md)、[`02-tavern.md`](./02-tavern.md)、[`03-design.md`](./03-design.md)
- SillyTavern 文档：https://docs.sillytavern.app/
- Character Card V3 spec：https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md
- KuzuDB：https://kuzudb.com/
- sqlite-vec：https://github.com/asg017/sqlite-vec
- Anthropic 1M context（Sonnet/Opus 4.6）公告与定价：Anthropic 官方文档（2026-05 GA）
- "Lost in the middle" 长上下文中段精度衰减：Liu et al., 2023, *Lost in the Middle: How Language Models Use Long Contexts*
- 节拍 / 角色 / 梗 / 散文质量四个维度的方法论来自一份关于网文-轻小说-严肃小说的 compass 文档（核心论点：所有小说背后只有一套机制——控制读者每一秒钟想不想翻下一页）。详见 03 §14 末段的方法论作者与作品列表。
