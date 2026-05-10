# INKFISH 实施路线图

> 状态：**实施规划**。设计已锁定（详见 [`03-design.md`](./03-design.md)）。
> 受众：六个月后的 Steven。
> 目的：回答"接下来做什么、什么时候做完算完成、什么风险要警惕"。
> 形态约束已固化：个人本地工具，非 SaaS。

---

## 1. 锁定的前提清单

下面这些是入场前提，路线图不再回头讨论。如果未来要改，那是"下一份文档"的事。

- **使用者**：Steven 一个人，写中文小说为主，偶尔英文。
- **形态**：本地优先 / 文件友好 / git 友好 / 个人桌面或浏览器使用。
- **后端**：Python（FastAPI）。
- **API**：GraphQL（client 拉自己想要的形状，避免 REST 的 N 套 endpoint）。
- **前端**：轻量。先 HTMX，必要时升级到 Tauri，不用 React/Vue 全家桶。
- **存储**：filesystem-first。结构化数据 KuzuDB（属性图），向量索引 sqlite-vec，纯文本一律 markdown / json，方便 grep/diff/git。
- **LLM 接入**：多 backend——Anthropic（Claude Sonnet/Opus）、OpenAI、Ollama 本地。Anthropic 为主力，Ollama 作降级选项。
- **四个写作模式共享同一份状态**：场景模拟 / 群戏对话 / 散文转写 / 角色采访。状态是共同的世界，模式只是不同入口。
- **Per-agent 隔离执行**：Director coordinator + 每个角色独立 LLM session + 独立知道集（per-character knowledge mask）。详见 `03 §4` 的 Per-agent 隔离机制。
- **三层世界知识**：lorebook（常驻设定）+ story graph（演化事实，KuzuDB）+ vector store（场景日志和散文段落，sqlite-vec）。
- **兼容 SillyTavern 资产**：CCv3 PNG 角色卡可导入导出，lorebook JSON 可导入。INKFISH 的扩展字段走 `extensions.inkfish.*` 命名空间。
- **场景容器**：scene 作为子进程，filesystem-based IPC（场景目录里写 turn log），方便回滚和事后审阅。
- **不 fork SillyTavern**：从零写后端，借鉴其概念但不背它的 PHP-style 历史包袱。
- **长上下文档**：粗活档 1M context（Sonnet 4.6 1M GA，$3/M input），精修档 200K。中段精度衰减约 30% 是已知约束，靠"重要内容塞前后段 + 关键事实重述"绕开。

---

## 2. 用户实际写作场景

把 Steven 写一本 15 万字中文长篇当成一根线，看 INKFISH 在每一段路上做什么。这一节不是功能列表，而是"凭什么这个功能必须存在"的现场证据。

**起步：从 premise 到世界 + 人物雏形。** Steven 脑子里有一句 premise（"一个失去记忆的捕鱼人在沿海小镇追查自己是谁"）。INKFISH 帮他从这句话扩出：3-5 个核心人物（CCv3 兼容档案）、一个小型 lorebook（小镇地理 / 海怪传说 / 时代背景），并在 story graph 里铺好初始关系边。痛点：白屏恐惧。INKFISH 必须**默认给草案**，Steven 不愿意从空文件起步。

**规划：大纲 + 节拍 + 场景列表。** Steven 想要一个三幕结构 + 12 个核心场景的草案。他不要"AI 给你写一份大纲"，他要"AI 提三个不同走向的大纲，他改一份"。INKFISH 的导演控制台在这里第一次出场，提供节奏建议和冲突密度可视化。

**起草：场景骨架 → 散文章节。** 这是 INKFISH 的核心闭环。先跑场景模拟（per-agent 隔离的多角色对话），输出 scene log（结构化的对白 + 行动 + 状态变化）；再过散文转写器，把 scene log 渲染成第三人称限知 POV 的中文散文。痛点：直接让 LLM 写散文章节，结果是"AI 腔"——人物声音糊在一起、没有节奏。两步走能把"角色心智"和"文字风格"解耦。

**修订：一致性 + 风格 + 节奏。** Steven 写到第 8 章发现某角色的口头禅在第 3 章是 A、在第 6 章变成 B。INKFISH 的一致性 critic 按需调用——他选中一个段落或整章，critic 读 character profile + 相关 graph 事实 + 历史散文段落（向量召回），列出疑似不一致点。**不强制每章都跑**——critic 是工具不是闸门。

**推进：状态延续到下一场。** 场景结束时，Director 把"本场关键事件 + 状态变化"反向写入 story graph（新增边、给旧边打过期、新增 episode 节点），下一场场景启动时三源检索自动带上这些更新。痛点：长篇最大的杀手是"第 12 章的 Maria 还记得第 4 章在码头说过的那句话吗"。这个反向写入是答案。

**回查：临时找信息。** Steven 写到一半想知道："Maria 第一次提到她父亲是在哪一章？" INKFISH 的多源检索（lorebook 关键词 + graph 关系 + 向量语义）三路并发，合并出答案 + 原文片段。

**共创探索：和角色对话、做"如果……"。** 写不下去的时候，Steven 切到角色采访模式，直接和 Maria 聊半小时——不为推进剧情，为找她的声音。或者把当前场景 fork 一个分支，让 Pedro 选择拒绝而不是接受，看分叉后的剧情走向。Fork 用 git branch 实现（场景目录是普通 markdown/json 文件夹）。

---

## 3. 功能切片清单

每个 F 是一个原子可验证单元。"输入 / 输出 / 依赖" 三栏，不展开实现。

| ID | 名称 | 输入 | 输出 | 依赖 |
|---|---|---|---|---|
| **F1** | 角色档案管理 | CCv3 PNG / 手输字段 / LLM 草案请求 | character.json（CCv3 + `extensions.inkfish` 扩展：声音层、秘密层、弧光层） | LLM backend |
| **F2** | 世界书管理 | lorebook JSON / 手编 entry | lorebook.json（keys, content, position, depth, constant/selective/vectorized 三态） | sqlite-vec（vectorized entry） |
| **F3** | 故事图谱管理 | 手编 / Director 反向写入 / 散文 ingest | KuzuDB 库：实体节点 + 时序边 + episode 节点 | KuzuDB |
| **F4** | 多源检索 | query string + scene context | 合并的检索结果（lorebook 命中 + graph 子图 + 向量段落） | F2 / F3 / sqlite-vec |
| **F5** | 场景规划 | 大纲位置 + 在场角色 + 目标 | scene_skeleton.md（节拍清单 + Director note 草案 + 在场知道集预设） | F1 / F4 |
| **F6** | 场景执行 | scene_skeleton + per-character knowledge mask | scene_log.json（按 turn 的对白/行动/思考/状态变化） | F1 / F4 / Director coordinator |
| **F7** | 散文转写 | scene_log + POV 配置 + 风格 preset | chapter.md（中文散文章节） | F6 / F10 |
| **F8** | 一致性检查（按需） | 段落或章节 + 检查维度（人物声音 / 事实 / 时间线） | critic_report.md（疑似问题清单 + 证据） | F4 / F1 |
| **F9** | 角色采访 | 角色 ID + 用户问题 | 单角色对话 session（不写入 graph，可手动 promote） | F1 / F4 |
| **F10** | 提示词管理 | preset JSON / 手编各 prompt block | 装配后的完整 prompt（每 block 可单独 enable/order/depth/role） | 全局 |
| **F11** | 导演控制台 | 多维度 note（节奏 / 视角 / 主题 / 张力 / OOC） | 注入到下一次 LLM 调用的 author note 块 | F10 |
| **F12** | 项目持久化 | 项目根目录 | filesystem 布局 + 备份 + git 集成 | 操作系统 |

补充说明：F6 是架构最重的一块（per-agent 隔离 + 子进程 + 知道集 mask），路线图里它独占一个 phase。F8 故意"按需"——强制 critic 会破坏写作的心流。

---

## 4. 非功能需求

- **性能**：场景执行单个 turn 端到端 ≤ 8s（含 LLM）。检索 F4 在小说级数据规模（≤ 50 万字 + ≤ 200 角色实体）下 ≤ 300ms。散文转写一章（约 3000 字）端到端 ≤ 60s。
- **可用性**：Steven 一个人用，不要任何登录 / 账户 / 多用户隔离。CLI 起步必须能跑通整个写作流，UI 只是糖衣。
- **可移植**：所有工程产物在 macOS 上原生跑通；项目目录拷到另一台机器后能立刻打开继续写。无云端依赖（除 LLM API 本身）。
- **成本约束**：日常写作单章成本目标 ≤ ¥10（按 Sonnet 4.6 1M ctx $3/M input 估算）。一本 15 万字小说全程 LLM 成本目标 ≤ ¥1500。超出阈值要能切到 Ollama 本地模型降级。
- **可观测**：所有 LLM 调用记 prompt + response + token + latency 到本地 jsonl，方便事后调 prompt。
- **可回滚**：场景目录是 git 友好的，回到任意 commit 即回到任意状态。

---

## 5. 显式不做的

写在这里防止三个月后手痒乱加。如果将来某条要做，那是"INKFISH 2"的事，不是这一版。

- **多用户 / 协作**。INKFISH 永远是单人工具。
- **出版工作流**。不做 EPUB 导出、不做投稿格式化、不做 ISBN 元数据。导出止于 markdown。
- **移动端**。手机不是写小说的终端。
- **视觉化生成**。不接 image generation。角色立绘要的话，去外面工具做完拖进 PNG 卡。
- **社区分享 / 角色市场**。不做账号体系，不做上传下载站。CCv3 互通靠用户手动拷文件。
- **实时协同光标**。不是 Notion。
- **AI 自动写整本书**。INKFISH 是协作工具，不是按一个按钮出书的机器。Steven 始终是作者。
- **流派模板市集**。先打磨核心闭环，模板生态等真用过几本书再说。

---

## 6. 实现阶段切片

每个 phase 是一个"完成后能用 INKFISH 多做一件事"的里程碑。时间估算按"Steven 业余时间，每周净 6-10h"。

### P0 散文质量 PoC（不写代码）

**目标**：在投入任何工程之前，先验证"LLM 能不能把 scene log 翻译成可读的中文小说散文"。如果这一步不过关，整个 INKFISH 项目终止。

**工作内容**：
- 手工准备 1 份角色档案（声音层 + 秘密层 + 关系层都填齐，约 1000 字）。
- 手工准备 1 份场景骨架（500 字结构化对白 + 行动）。
- 准备 3 个候选 backend：Claude Sonnet 4.6、Claude Opus 4.7、GPT-5。
- 写 3 版 prompt 配方（直接散文 / 先意译再润色 / 三段式：对白保留 + 心理插入 + 环境穿插）。
- 9 个组合各跑 1 次，输出 800 字小说散文。
- 自评 + 让两个朋友盲评（"如果你在书店翻到这一页，会不会读下去？"）。

**Done 定义**：至少有 1 个组合的输出，Steven 自己 3 轮内编辑能用（编辑量 ≤ 20%），且至少 1 名朋友盲评通过。

**Killer test**：上面这条本身就是 killer test。失败则项目终止；成功则进 P1。

**时间估算**：1-2 周（主要是 prompt 迭代和评估）。

**风险**：评判主观。缓解：用同一份 reference 段落（自己以前手写的小说片段）做对照基准。

### P1 CLI 单角色 demo

**目标**：命令行能跑：从 premise 创建 character.json → 运行一段独白 scene → 转散文。验证基础 IO 和 LLM 集成。

**工作内容**：
- FastAPI 项目骨架 + Anthropic / OpenAI / Ollama backend 抽象层。
- F1 的 CLI 子集：`inkfish character create --premise "..."`、`inkfish character edit`。
- F6 的退化版：单角色 monologue scene，Director 退化成"提一个问题让角色独白回答"。
- F7 的最简版：scene_log → markdown 散文，单一 POV，无风格 preset。
- F12：项目目录布局确定。`project/{characters,scenes,chapters,lorebook,graph}` 五个子目录定型。

**Done 定义**：`inkfish init my-novel && inkfish character create ... && inkfish scene run ... && inkfish chapter render ...` 端到端跑通，最终生成的 chapter.md 质量不低于 P0 的水平。

**Killer test**：从零项目到第一段 800 字散文 ≤ 5 分钟（Steven 操作时间）。

**时间估算**：3-4 周。

**风险**：
- 选错抽象层（backend 接口太僵）。缓解：先只写 Anthropic 一家，等 P3 再泛化。
- CLI 设计自我斗争。缓解：照着 git 命令的形态走，不发明新风格。

### P2 CLI 多角色场景 + per-agent 隔离落地

**目标**：核心架构验证。Director coordinator + 多角色 LLM session + 知道集隔离都跑通，能产出 5-10 turn 的多角色对白。

**工作内容**：
- Director coordinator：决定"下一个谁说"、"场景何时收尾"、"是否插入 narrator beat"。
- 每个角色独立 LLM session：独立 system prompt（来自 character.json），独立 chat history。
- 知道集 mask：每个角色看 scene log 时，只看到她"应该知道"的 turn（其他角色的内心独白不可见，秘密对白按 secret edge 过滤）。
- Scene 子进程容器：每个 scene 启一个子进程，filesystem 写 turn log，主进程通过文件 watch + 文件锁 IPC。
- F11 的最简版：单维度 Author Note 注入（"用更紧张的语气"）。

**Done 定义**：能跑一个 3 角色 / 15 turn 的场景，scene log 完整，散文转写后人物对白能看出三个不同的声音。

**Killer test**：15 turn 长场景结束后，把任意两个角色的所有对白单独抽出来读，能否听出"这是两个不同的人在说话"。如果三个人的对白都像同一个 LLM 在演——架构需要重做（可能要切 stronger persona injection 或 few-shot voice anchor）。

**时间估算**：5-7 周。

**风险**：
- 子进程 + filesystem IPC 的协调复杂度被低估。缓解：先做同进程 asyncio 版本跑通，证明逻辑对，再切子进程。Q3 在这一阶段必须落地。
- 角色"串味"。缓解：mes_example（对话样本）作为 voice anchor 强制注入；character.json 的"声音层"在 every turn 都重述。
- Director 不知道何时收尾。缓解：Q4 在这阶段必须有答案。

### P3 lorebook + graph + 三源检索

**目标**：场景不再是孤岛，能跨场景共享世界知识。

**工作内容**：
- F2 lorebook 完整实现：三态（constant/selective/vectorized）+ position/depth + 递归扫描 + token budget。
- F3 KuzuDB schema 设计 + 实体/边/episode CRUD + 反向写入接口（场景结束后 Director 总结状态变化写图）。
- sqlite-vec 接入：场景日志和散文段落的 embedding。
- F4 三源检索 API：query → lorebook 关键词命中 + graph 子图 + 向量召回，按相关性合并去重。
- 散文 ingest pipeline：已写完的章节 markdown → 抽实体/事实写图 + 段落写向量库。

**Done 定义**：写完 3 个连续场景（至少跨 2 个场景的同一角色 + 同一地点），第 4 场场景启动时检索能拿出前 3 场的关键事实，且 character session 看到的检索结果按知道集过滤过。

**Killer test**：写到第 8-10 个场景后，故意问一个"第 2 场提到过的某个细节"是否还在角色记忆里。如果三源检索 + 知道集 mask 都失效——架构需要回炉。

**时间估算**：6-8 周。

**风险**：
- KuzuDB 在小说级数据规模上的实测表现未知（R6）。缓解：early benchmark，跑 50 万字 ingest 看延迟和体积。如果不行 fallback 到 Neo4j embedded 或 SQLite + 自己的关系表。
- 三源合并策略难调（Q6）。缓解：先简单加权合并，留 hook 让 LLM 重排序作为可选。

### P4 Director Note + Critic + 角色采访

**目标**：完整闭环。导演控制台多维度 note + 按需 critic + 单角色采访。从这里开始 INKFISH 真的能用来写一本书。

**工作内容**：
- F11 完整：多维度 Author Note（节奏 / 视角 / 主题 / 张力 / 风格 / 显式 OOC）+ depth 控制 + preset 保存。
- F8 一致性 critic：按需调用，输入是段落或章节，输出是疑似不一致点的 evidence 链。
- F9 角色采访：和单个角色长聊的 session，结果**不**自动写入 graph（避免污染世界状态），但用户可以手动 promote 某段对话为"正史"。
- F10 提示词管理器：所有 block 暴露给用户编辑，preset 系统能保存和切换。

**Done 定义**：Steven 用 INKFISH 写完一个完整的中篇章节（3000-5000 字），全程没有跳出去用别的工具，且最终质量他自己满意（"愿意挂在博客上"）。

**Killer test**：一个连续工作日内（约 4-6h 实际写作时间），用 INKFISH 写完一章 4000 字小说，作者疲劳度低于直接手写一章。如果工具的认知负担反而大于直接写作——需要回头砍功能或换 UX。

**时间估算**：4-6 周。

**风险**：
- Critic 的 false positive 太多反而让人想关掉。缓解：critic 输出必须带"证据链 + 置信度"，让 Steven 一眼判断要不要管。
- 角色采访发散到偏离世界设定。缓解：采访 session 默认隔离，不写图；要写图必须显式 promote。

### P5 GraphQL + 轻量前端

**目标**：从 CLI 升级到能在浏览器里舒服写作的形态。

**工作内容**：
- FastAPI GraphQL endpoint（Strawberry 或 Ariadne），schema 覆盖前面所有 F。
- 前端选型决策（Q7）：默认 HTMX + Alpine.js，如果发现需要离线/原生体验再升 Tauri。
- 核心视图：项目仪表盘 / 角色卡编辑器 / 场景执行 live view（每 turn 流式显示）/ 章节编辑器（左原文右散文 split view）/ 检索面板。
- 不做：拖拽布局编辑、丰富的 WYSIWYG、协同。

**Done 定义**：CLI 上能做的 95% 操作在浏览器里能做，且核心写作流（场景 → 散文）在浏览器里比 CLI 更顺。

**Killer test**：连续两周只用 UI 不用 CLI 写作，没有"我要切回终端"的冲动。

**时间估算**：5-7 周。

**风险**：
- HTMX 撑不起场景 live view 的复杂度。缓解：场景 live view 是唯一可能需要 SPA 风格的页面，可以单独用一个 mini React island 嵌入。
- UI 设计自我斗争。缓解：抄 SillyTavern 的布局打底，再迭代。

### P6+ 实战写一本小说，根据痛点迭代

**目标**：不再做新功能，**真的用 INKFISH 写完一本 10-15 万字的中文小说**。

**工作内容**：
- 启动一本新书。每周记录痛点日志：哪里慢、哪里烦、哪里 LLM 给的烂答案最浪费时间。
- 每月一次"工具迭代日"，根据日志改 INKFISH（不是写新书的日子）。
- 不再加大功能，**只优化已有路径**。

**Done 定义**：完成一本书。INKFISH 完成它的本职：让 Steven 真的写完一本他想写的小说。

**Killer test**：写完之后回头看，INKFISH 是帮 Steven 写得更快/更好，还是其实只是"写得更分心"？前者继续，后者大砍。

**时间估算**：6-12 个月（取决于这本书本身的体量）。

**风险**：详见 §8 全部风险。

---

## 7. 真正剩下的开放问题

只列出"必须在某个 phase 之前回答"的。普通迭代里能现场决定的不入清单。

| ID | 问题 | 何时必须回答 |
|---|---|---|
| Q1 | 哪个 LLM + 哪份 prompt 配方能把 scene log → 中文散文做到 acceptable 质量？ | **P0 之前**（这就是 P0 本身） |
| Q2 | 角色弧光在数据模型上怎么表达？一系列离散 episode（节点） vs 独立 arc state 字段（角色身上的可变状态机） vs 两者都要？ | P1 之前（影响 character.json schema 与图谱 schema） |
| Q3 | character_runtime 是真子进程还是同进程异步 task？子进程隔离干净但 IPC 复杂；asyncio 简单但出问题难调。 | P2 之前（影响整个执行器架构） |
| Q4 | 场景结束的判定条件谁说了算？Director 自主判断 / 用户手动结束 / 多角色 LLM 投票 / 达到 turn 上限自动结束？ | P2 之前 |
| Q5 | 知道集（per-character knowledge mask）的存储方案？KuzuDB 边属性 / 独立 mask 表 / 内存里每场重算？ | P3 之前 |
| Q6 | lorebook 关键词触发 vs graph 检索 vs 向量召回的合并策略？按相关性加权 / 按层级优先（lorebook > graph > vector）/ 让 LLM 重排序？ | P3 之前 |
| Q7 | 前端形态：纯 HTMX web 够用还是必须 Tauri 桌面？涉及离线、文件访问、性能。 | P5 之前 |
| Q8 | 中英双语写作的 UX 怎么处理？同一项目里中英混存？还是项目级 locale 锁定？角色档案是否要双语字段？ | 持续，不强制单点回答 |

---

## 8. 风险清单

按严重度排序，每条带原因和缓解。

**R1【最高】LLM 写中文小说散文的质量天花板。** 即使是 Sonnet 4.6 / Opus 4.7，写中文小说散文都会暴露训练数据偏好——AI 腔、辞藻堆砌、节奏单调。这是项目最基础的不确定性。
缓解：P0 直接验证。失败就停项目。成功就锁定那份配方作为 P1+ 的基线，并把它做成第一个 preset。

**R2【高】世界状态长程一致性。** Per-agent 隔离 + 三源检索的设计是理论上能扛长篇，但没人验证过几十章后还能保住。
缓解：P3 的 killer test 故意拉长，在 8-10 场之后做事实回查。P6 实战写作时设置"每 5 章做一次全量一致性扫描"的 ritual，不靠系统自动捕获。

**R3【中】成本。** Sonnet 4.6 $3/M input × 一本书几百次迭代 × 1M 长上下文 → 单本书 LLM 成本可能爆。
缓解：粗活档（场景规划 / scene log 草案 / 一致性扫描）走 1M context 但用便宜模型；精修档（散文转写 / 角色采访）走 200K 高质量模型。日常写作目标单章 ≤ ¥10（§4 已写）。设置预算上限警告。

**R4【中】Steven 自己懒。** 工具再好，作者懒就出不了书。INKFISH 必须**默认给草案**——白屏比烂草案更劝退。
缓解：每个创作动作（创建角色 / 起场景 / 写章节）默认有"先给我个草案我再改"的入口。这条要写进 §6 各 phase 的 UX 验收标准里。

**R5【中】流派偏置。** LLM 训练数据对某些流派有强偏好（言情 / 仙侠 / 都市职场容易出"套路化"输出，硬科幻 / 实验文学容易出"力不从心"）。
缓解：preset 系统支持"流派 + 风格"组合，每个流派维护一份反套路 prompt 注入（"避免出现 XXX 句式 / 避免 XXX 比喻"）。Steven 写的具体流派固定后，专门调一份。

**R6【低】KuzuDB / sqlite-vec 在小说级文本规模上的实测表现未知。** 都是相对新或小众的栈，没有大量 production case。
缓解：P3 进 phase 时做 early benchmark。如果撑不住，KuzuDB → Neo4j embedded（Java 进程开销大但成熟），sqlite-vec → Chroma 或 Qdrant local。架构层留好抽象。

**R7【低】LLM API 成本/能力变化。** 2026-05 是 Sonnet 4.6 1M GA $3/M 的环境。半年内可能 GPT-6 出来 / Anthropic 调价 / Gemini 反超。
缓解：backend 抽象层从 P1 就建好，切换成本控制在改一个 config 文件。每季度做一次"用当前最强模型重跑 P0 评估"，决定要不要换主力。

---

## 9. Sources

- 项目设计上下文：[`01-mirofish.md`](./01-mirofish.md)、[`02-tavern.md`](./02-tavern.md)、[`03-design.md`](./03-design.md)
- SillyTavern 文档：https://docs.sillytavern.app/
- Character Card V3 spec：https://github.com/kwaroran/character-card-spec-v3/blob/main/SPEC_V3.md
- KuzuDB：https://kuzudb.com/
- sqlite-vec：https://github.com/asg017/sqlite-vec
- Anthropic 1M context（Sonnet）公告与定价：Anthropic 官方文档（2026-05 GA，$3/M input / $15/M output）
- "Lost in the middle" 长上下文中段精度衰减：Liu et al., 2023, *Lost in the Middle: How Language Models Use Long Contexts*
