# INKFISH 系统设计规格

## 1. 系统概述

INKFISH 是一个自主角色模拟引擎，输出网络小说。

核心循环：

```
初始化 → tick 循环 → 导演决策 → 角色行动 → 互动 → 关系更新 → 写作输出
```

**作者角色**：天道——实时通过节点图监视模拟，通过对话框向导演下指令，可调整任意角色参数。作者不写作，只监视、审阅、调整。

**零输入能力**：无任何 premise 时系统自动生成完整世界（规则、地点、角色）并自动运行产出小说。

---

## 2. 模块架构

```
┌─────────────────────────────────────────────────────┐
│  M8 Frontend (React)                                │
│  角色关系图 | 剧情图 | 控制面板 | 对话面板 | 阅读页  │
└───────────────────────────┬─────────────────────────┘
                            │ REST + SSE
┌───────────────────────────▼─────────────────────────┐
│  M7 API (FastAPI)                                   │
│  REST endpoints + SSE 推送                           │
└───────────────────────────┬─────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  M5 Director │   │  M6 Writer   │   │  M3 Character│
│  剧情规划     │   │  网文输出     │   │  角色 agent   │
│  tool call   │   │  tool call   │   │  行动决策     │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                   │
       └──────────────────┼───────────────────┘
                          │
              ┌───────────▼───────────┐
              │  M4 LLM Gateway       │
              │  中央调度 + routing    │
              │  限流 + 优先级队列     │
              └───────────┬───────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  M2 Space    │ │  M1 Storage  │ │  M0 Config   │
│  多层空间     │ │  SQLite+ckpt │ │  全局配置     │
│  地点管理     │ │  快照系统     │ │  参数管理     │
└──────────────┘ └──────────────┘ └──────────────┘
```

| 模块 | 职责 | 输入 | 输出 | 依赖 |
|------|------|------|------|------|
| M0 Config | 全局配置（导演数、世界参数、routing 规则、tick 速度） | TOML 配置文件 | 配置对象 | 无 |
| M1 Storage | SQLite + 快照 + fork/reset | 世界状态 | 持久化/查询 | M0 |
| M2 Space | 多层空间模型 + 地点动态生成 + 跨层管理 | 移动请求 | 空间拓扑 | M0, M1 |
| M3 Character | 角色 agent 生命周期 + 感知 + 决策 | context(人设+记忆+感知) | 结构化 action | M0, M1, M2, M4 |
| M4 LLM Gateway | 中央调度器 + 队列 + 限流 + routing | LLM 请求 | LLM 响应 | M0 |
| M5 Director | 剧情规划 + tool call + pacing | 角色日志 | 事件/指令 | M0-M4 |
| M6 Writer | 事件 → 网文转写 | 事件日志 | 网文段落 | M0, M1, M4, M5 |
| M7 API | FastAPI REST + SSE | HTTP 请求 | JSON + SSE 流 | M0-M6 |
| M8 Frontend | React 节点图 + 控制面板 | SSE + REST | UI | M7 |

---

## 3. 模拟引擎

### 3.1 Tick 执行流程

一个 tick = 模拟世界内一小时。所有角色并发行动，执行顺序随机打乱避免惊群。

```python
async def run_tick(world_state: WorldState, tick_id: int) -> None:
    # 1. 导演先跑（最高优先级，不可跳过）
    director_actions = await run_directors(world_state)
    apply_director_actions(world_state, director_actions)

    # 2. 构建角色优先级队列（权重 + DPO 随机扰动）
    queue = build_priority_queue(world_state.active_characters)

    # 3. 过滤：跳过低权重 / 本 tick 更新过多的角色
    queue = filter_queue(queue, config.min_weight, config.max_updates_per_tick)

    # 4. 并发执行所有角色 LLM 调用
    actions = await gateway.process_queue(queue)

    # 5. 检测互动触发
    interactions = detect_interactions(actions)
    for interaction in interactions:
        await run_interaction_budget(interaction, config.interaction_max_limit)

    # 6. 关系提取（小模型，mandatory 队列）
    await extract_relationships(interactions)

    # 7. 处理新角色引用（动态生成）
    await spawn_referenced_characters(actions)

    # 8. 写入完整快照
    storage.save_snapshot(world_state, tick_id)

    # 9. SSE 推送
    sse.broadcast(tick_id, actions, interactions)
```

### 3.2 权重系统

```python
def compute_weight(character: Character, world_state: WorldState) -> float:
    base = character.appearance_count / world_state.total_ticks
    director_boost = 1.0 if character.id in world_state.director_focus else 0.0
    recency = decay(character.last_active_tick, world_state.current_tick)
    return base + director_boost * 0.5 + recency * 0.3
```

调度规则：
- `weight < config.min_weight` → 跳过本 tick
- `updates_this_tick > config.max_updates_per_tick` → 跳过本 tick
- 被跳过的角色恢复时 context 注入：`"你已跳过 {n} 个 tick，当前时间是 {time}"`

### 3.3 DPO 随机重排

```python
def build_priority_queue(characters: list[Character]) -> list[Character]:
    weighted = [(c, c.weight + random.gauss(0, config.dpo_sigma)) for c in characters]
    return sorted(weighted, key=lambda x: x[1], reverse=True)
```

加入高斯噪声避免高权重角色永远排在前面。`dpo_sigma` 可配置（默认 0.1）。

---

## 4. 角色系统

### 4.1 数据 Schema

```python
@dataclass
class Character:
    id: str
    name: str
    mbti: str                    # INTP / ENFJ / ...
    age: int
    birth_date: date
    id_number: str               # 身份证号
    background: str              # 背景故事（几百字）
    appearance: str              # 外貌描述（给不认识的人看）
    personality: str             # 性格详述
    current_location: str        # 当前地点 ID
    current_mood: str            # 当前情绪
    routine: list[RoutineItem]   # 日常作息表
    weight: float                # 当前权重
    alive: bool
    death_summary: str | None    # 死亡时生成的生平总结
    appearance_count: int        # 在故事中出场次数
    last_active_tick: int        # 最后活跃 tick
    skipped_ticks: int           # 连续被跳过的 tick 数

@dataclass
class RoutineItem:
    hour_start: int              # 0-23
    hour_end: int
    activity: str                # "上班" / "睡觉" / "逛街" / ...
    location: str                # 地点 ID
    weekdays: list[int]          # 0=周一, 6=周日
```

### 4.2 LLM Context 拼装

固定顺序，[1] 可缓存：

```
[1] 人设（稳定前缀，prompt 缓存命中）
    ├── 名字、年龄、MBTI、生日
    ├── 性格详述
    ├── 背景故事
    └── 日常 routine

[2] 记忆（图查询，每 tick 重新检索）
    ├── 关系网：{name: 关系类型 + 强度 + 最近互动摘要}
    └── 已知事实：经历过的重要事件（按时间倒序，带 token budget 截断）

[3] 当前感知（每 tick 不同）
    ├── 当前时间："2024年3月15日 周五 下午2点"
    ├── 当前地点：地点描述
    ├── 在场角色：
    │   ├── 认识的："{name}（{关系}），正在 {上一tick行为}"
    │   └── 不认识的："{appearance}，正在 {上一tick行为}"
    ├── 导演指令（如有）："你感到一股强烈的好奇心想去探索那个裂缝"
    ├── 特殊事件（如有）："你收到了一条微信：……"
    └── 跳过提示（如有）："你最近 {n} 小时一切正常，没有特别的事发生"
```

### 4.3 Action 输出

```python
@dataclass
class CharacterAction:
    character_id: str
    tick_id: int
    action_type: Literal["SPEAK", "THINK", "ACT", "MOVE_TO", "REACT", "DO_NOTHING"]
    content: str                  # 具体内容
    target: str | None            # 目标角色 ID 或地点 ID
    mood: str                     # 执行后的心情
    inner_thought: str            # 内心独白（永远不跨角色可见）
    triggers_interaction: bool    # 是否触发互动 budget
```

LLM 输出格式约束为结构化 JSON，不允许自由文本。

### 4.4 Action 鉴权

```python
class CharacterAgent:
    def can_perform(self, action: CharacterAction) -> tuple[bool, str]:
        match action.action_type:
            case "MOVE_TO":
                reachable = self.space.is_reachable(self.location, action.target)
                return (reachable, "" if reachable else "目标地点不可达")
            case "SPEAK":
                has_target = action.target in self.space.present_at(self.location)
                return (has_target, "" if has_target else "目标不在同一地点")
            case _:
                return (True, "")
```

鉴权失败 → action 被拒绝，角色本 tick 视为 DO_NOTHING。

### 4.5 生命周期

```
                    ┌─────────────────────────────────┐
                    ▼                                 │
生成 → 活跃 → 低频更新 → 冻结                        │
         │                                           │
         └── (故事中死亡) → 死亡                      │
                              ├── 生成生平总结        │
                              ├── 停止 LLM 调用       │
                              ├── 逐渐降低召回率      │
                              └── 关系数据保留         │
                                                     │
         (新角色被引用) ─────────────────────────────┘
```

新角色生成：当某角色 action 引用了不存在的角色（"我要去找我哥"）→ 立刻运行角色生成流程（受世界规则 + 已知关系约束）→ 新角色加入 active pool。

---

## 5. 感知与互动

### 5.1 感知规则

| 条件 | 感知内容 |
|------|----------|
| 同地点 + 认识 | 名字 + 关系 + 对方上一 tick 的外显 action |
| 同地点 + 不认识 | 外貌描述 + 对方上一 tick 的外显 action |
| 不同地点 | 不可见（除非通过数字空间） |
| 内心独白 | 永远只有自己可见 |

外显 action = `action_type ∈ {SPEAK, ACT, MOVE_TO, REACT}`。THINK 和 DO_NOTHING 不产生外显信息。

### 5.2 互动 Budget

```python
async def run_interaction_budget(
    interaction: Interaction,
    max_rounds: int
) -> list[CharacterAction]:
    a, b = interaction.initiator, interaction.target
    transcript: list[CharacterAction] = []

    for round in range(max_rounds):
        # A 先行动（看到 B 上一轮的外显 action）
        ctx_a = build_interaction_context(a, b, transcript, viewer=a)
        action_a = await gateway.call(a, ctx_a)
        transcript.append(action_a)

        # B 回应（看到 A 本轮的外显 action）
        ctx_b = build_interaction_context(b, a, transcript, viewer=b)
        action_b = await gateway.call(b, ctx_b)
        transcript.append(action_b)

        # 双方都 DO_NOTHING → 互动自然结束
        if action_a.action_type == "DO_NOTHING" and action_b.action_type == "DO_NOTHING":
            break

    return transcript
```

关键约束：
- `build_interaction_context(viewer=X)` 过滤掉对方的 `inner_thought`
- 互动循环异步运行，不阻塞主 tick 循环
- `max_rounds` 可由 config 或导演动态调整

### 5.3 关系提取

互动结束后自动触发：

```python
async def extract_relationships(interactions: list[Interaction]) -> None:
    for interaction in interactions:
        transcript = get_visible_transcript(interaction)  # 去掉 inner_thought
        delta = await gateway.call_small_model(
            prompt=RELATIONSHIP_EXTRACT_PROMPT,
            context=transcript
        )
        storage.apply_relationship_delta(delta, interaction.tick_id)
```

输出 schema：
```json
{
  "relationship_changes": [
    {"from": "char_a", "to": "char_b", "type": "acquaintance", "delta": 0.3, "reason": "首次交谈"}
  ],
  "knowledge_updates": [
    {"character": "char_a", "learned": "char_b 是律师", "confidence": 0.8}
  ],
  "mood_updates": [
    {"character": "char_a", "mood": "curious"}
  ]
}
```

路由：mandatory 队列，最小模型。

---

## 6. 多层空间模型

### 6.1 空间层

```python
class SpaceLayer(Enum):
    PHYSICAL = "physical"       # 现实世界地点
    DIGITAL = "digital"         # 微信群、社媒、邮件
    OTHERWORLD = "otherworld"   # 异界/平行空间
```

同一套角色系统跑在所有层上。层之间不是隔离的世界，是同一个模拟的不同空间维度。

### 6.2 地点 Schema

```python
@dataclass
class Location:
    id: str
    name: str
    layer: SpaceLayer
    description: str
    present_characters: list[str]
    connected_to: list[str]      # 相邻/可达地点 ID
    created_at_tick: int
    created_by: str              # "system" / "director" / "dynamic"
```

### 6.3 地点动态生成

角色 `MOVE_TO` 一个不存在的地点名 → 触发：

```python
async def generate_location(name: str, world_rules: WorldRules) -> Location:
    prompt = f"根据世界规则生成地点 '{name}' 的描述和连接关系"
    return await gateway.call_small_model(prompt, context=world_rules)
```

### 6.4 跨层移动

只有导演能创建跨层通道：

```python
# 导演 tool call
director.create_rift(location="downtown_plaza", target_layer="otherworld")
director.inject_motivation(char_id="maria", motivation="你感到一股强烈的好奇心想去探索广场上出现的裂缝")
```

角色收到动机后自主决定是否穿越（可能 MOVE_TO 裂缝，也可能忽略）。

---

## 7. 导演系统

### 7.1 Context 结构

```
[1] System prompt:
    "你是故事导演。你的工作是创造有趣、引人入胜的剧情。
     你不是角色，你是操控事件和环境的人。
     节奏判断：如果故事原地打转超过 5 tick，你必须注入新冲突。
     如果节奏太快角色来不及发展，你可以制造平静间隙。"

[2] 当前盯着的角色（最近 N tick 日志）

[3] 世界状态摘要：活跃角色数、当前剧情线、待处理事件

[4] 作者指令（如有）："让 Maria 和 Pedro 产生冲突"
```

### 7.2 Tool Call

```python
class DirectorTools:
    def get_character(self, id: str) -> Character:
        """查角色完整档案"""

    def update_character(self, id: str, patch: dict) -> None:
        """修改角色设定/动机/性格"""

    def get_location(self, id: str) -> Location:
        """查地点状态 + 在场角色"""

    def create_events(self, events: list[Event]) -> None:
        """批量创建事件（出现在指定地点，影响在场角色）"""

    def move_character(self, id: str, to_location: str) -> None:
        """强制移动角色到指定地点"""

    def create_character(self, constraints: dict) -> Character:
        """动态生成新角色（受约束）"""

    def create_rift(self, location: str, target_layer: str) -> None:
        """创建跨层通道"""

    def get_scene_log(self, char_ids: list[str], n_ticks: int) -> list[CharacterAction]:
        """拉指定角色最近 N tick 日志"""

    def inject_motivation(self, char_id: str, motivation: str) -> None:
        """给角色注入动机（下一 tick 出现在 context [3] 里）"""

    def query_graph(self, query: str) -> list[dict]:
        """任意图查询（关系、事实、事件）"""

    def spawn_director(self, focus_chars: list[str]) -> str:
        """启动新导演盯另一条剧情线，返回新导演 ID"""

    def signal_writer(self, arc_summary: str) -> None:
        """通知 Writer 当前故事弧可以切割输出"""

    def inject_hot_topic(self, topic: str, spread_via: str) -> None:
        """将社会热点注入数字空间层"""
```

所有写操作自动同步到 Storage 图 + 世界状态。

### 7.3 多导演并行

- 每个导演实例只盯一条剧情线
- `spawn_director` 创建新实例，各自独立运行
- 两个导演的角色在同一地点相遇 → 无需仲裁，碰撞产生涌现剧情
- 所有导演共享同一个 Storage、同一个 LLM Gateway

### 7.4 Pacing 意识

内置于导演 system prompt，不是独立模块：
- 导演自动判断"故事是否在原地打转 / 太快 / 太慢 / 需要新冲突"
- 基于判断决定是否 `create_events` / `inject_motivation` / 切换关注角色

### 7.5 社会热点注入

- 导演通过 `inject_hot_topic` 把现实热点注入数字空间层
- NPC 在微信群/社媒上传播讨论热点
- 数据源可配置：API 自动抓取（微博热搜 / Twitter trending）+ 作者手动输入

### 7.6 运行时机

- 每 tick 最先运行（Level 0 优先级）
- 永不被跳过或杀死
- 导演决策完成后才开始角色并发行动

---

## 8. 写作者系统

### 8.1 触发条件

三选一，先到先触发：
1. 导演调用 `signal_writer(arc_summary)`
2. 作者手动触发（通过 UI 按钮或 API）
3. step 迭代结束（达到配置的 step 上限）

### 8.2 Context

```
[1] System prompt:
    "你是网络小说写手。根据事件日志写出可读的网文段落。
     要求：第三人称限知视角，跟随主角，网文风格，节奏明快。"

[2] 导演当前盯着的角色的事件日志（从上次输出到现在的所有外显 action）

[3] 上一次输出的末尾 500 字（保持文风连贯）

[4] 相关角色的外貌/性格摘要（用于人物描写）

[5] 世界设定摘要
```

### 8.3 Tool Call

```python
class WriterTools:
    def get_character(self, id: str) -> Character:
        """查角色背景（写描写用）"""

    def get_scene_log(self, char_ids: list[str], tick_range: tuple[int, int]) -> list[CharacterAction]:
        """拉更多角色的日志补充上下文"""

    def query_graph(self, query: str) -> list[dict]:
        """查关系/事实（写伏笔/前情提要）"""

    def get_previous_output(self, n_chars: int) -> str:
        """拉前几段已写内容（保持文风连贯）"""

    def get_world_context(self, layer: str) -> str:
        """查当前空间层的世界设定"""
```

### 8.4 输出

- 格式：连续散文段落（网文风格）
- 长度：按场景段落输出，单次可达万字
- 视角：主角第三人称限知（导演引导的那个角色）
- 分割频率：作者可配置建议（导演在 `signal_writer` 时判断）
- 多导演线时：Writer 自主判断选最精彩的或群像交织
- 存储：`writer_outputs` 表，标记 `tick_id_start` / `tick_id_end`

---

## 9. LLM Gateway

### 9.1 队列优先级

```python
class Priority(IntEnum):
    DIRECTOR_WRITER = 0    # 插队，永不跳过
    HIGH_WEIGHT = 1        # 重要角色
    NORMAL = 2             # 普通角色
    MANDATORY = 3          # 自动更新（关系提取等）
```

### 9.2 Routing

```python
@dataclass
class RoutingRule:
    condition: str          # "role == director" / "weight > 0.8" / "task == extract"
    provider: str           # anthropic / deepseek / qwen / ollama
    model: str              # 具体模型名
    priority: int           # 规则优先级（高的先匹配）

# 默认规则（用户可在 config 覆盖）
DEFAULT_RULES = [
    RoutingRule("role == director",         "anthropic", "claude-sonnet-4-6", 100),
    RoutingRule("role == writer",           "anthropic", "claude-sonnet-4-6", 99),
    RoutingRule("weight > 0.8",            "qwen",      "qwen-max",          80),
    RoutingRule("task == extract",          "deepseek",  "deepseek-chat",     70),
    RoutingRule("*",                        "deepseek",  "deepseek-chat",     0),
]
```

### 9.3 限流

- 每个 provider 独立的 rate limit 计数器
- 429 → 自动退避重试（exponential backoff）
- 超时 → 该请求标记失败，角色本 tick 视为 DO_NOTHING
- 全局并发上限：`config.max_concurrent_llm_calls`（默认 50）

### 9.4 Prompt 缓存

- DeepSeek：自动前缀缓存（保证 context [1] 人设部分在最前且稳定）
- Anthropic：`cache_control: {"type": "ephemeral"}` 标记 [1] 块
- 效果：角色人设只传一次，后续 tick 只传变化部分的 token 费

---

## 10. 存储

### 10.1 ORM

SQLAlchemy，支持 SQLite（开发）↔ PostgreSQL（大规模）无缝切换。

### 10.2 核心表

```sql
-- 角色
characters (
    id TEXT PRIMARY KEY,
    tick_id INTEGER NOT NULL,
    name TEXT, mbti TEXT, age INTEGER,
    background TEXT, appearance TEXT, personality TEXT,
    id_number TEXT, birth_date TEXT,
    current_location TEXT, current_mood TEXT,
    routine JSON, weight REAL, alive BOOLEAN,
    death_summary TEXT, appearance_count INTEGER,
    last_active_tick INTEGER, skipped_ticks INTEGER
)

-- 地点
locations (
    id TEXT PRIMARY KEY,
    tick_id INTEGER NOT NULL,
    name TEXT, layer TEXT, description TEXT,
    connected_to JSON, created_at_tick INTEGER, created_by TEXT
)

-- 关系
relationships (
    id TEXT PRIMARY KEY,
    tick_id INTEGER NOT NULL,
    from_char TEXT, to_char TEXT,
    type TEXT, strength REAL, reason TEXT
)

-- 行动记录
actions (
    id TEXT PRIMARY KEY,
    tick_id INTEGER NOT NULL,
    character_id TEXT, action_type TEXT,
    content TEXT, target TEXT, mood TEXT,
    inner_thought TEXT, triggers_interaction BOOLEAN
)

-- 导演事件
events (
    id TEXT PRIMARY KEY,
    tick_id INTEGER NOT NULL,
    type TEXT, location TEXT, description TEXT,
    created_by_director TEXT
)

-- 快照索引
snapshots (
    tick_id INTEGER PRIMARY KEY,
    timestamp TEXT, hash TEXT,
    parent_tick_id INTEGER  -- fork 时指向分叉点
)

-- LLM 调用日志
llm_logs (
    id TEXT PRIMARY KEY,
    tick_id INTEGER, provider TEXT, model TEXT,
    prompt_tokens INTEGER, response_tokens INTEGER,
    latency_ms INTEGER, cost_usd REAL,
    character_id TEXT, task_type TEXT
)

-- 写作者输出
writer_outputs (
    id TEXT PRIMARY KEY,
    tick_id_start INTEGER, tick_id_end INTEGER,
    content TEXT, word_count INTEGER, timestamp TEXT
)
```

### 10.3 快照系统

每 tick 结束后存完整快照（不是差异）：

```python
class SnapshotManager:
    def save_snapshot(self, world_state: WorldState, tick_id: int) -> None:
        """将所有表当前状态写入，标记 tick_id"""

    def fork(self, from_tick_id: int) -> int:
        """从指定 tick 分叉，返回新分支的起始 tick_id"""

    def reset(self, to_tick_id: int) -> None:
        """回退到指定 tick，丢弃之后的所有数据"""

    def replay(self, from_tick: int, to_tick: int) -> list[WorldState]:
        """重放指定范围的快照"""

    def list_snapshots(self) -> list[SnapshotInfo]:
        """列出所有快照（含分支信息）"""
```

所有中间状态落盘，保证：
- 崩溃后从最后一个完整 tick 恢复
- 任意 tick 可回滚
- fork 后两条线完全独立

---

## 11. 世界初始化

### 11.1 三步流程

```python
async def initialize_world(premise: str | None = None) -> WorldState:
    # Step 1: 世界规则
    rules = await generate_world_rules(premise)
    # 输出：物理法则、社会规则、时代背景、魔法系统（如有）

    # Step 2: 初始地点
    locations = await generate_locations(rules)
    # 输出：10-50 个地点，含连接关系

    # Step 3: 角色（并行生成）
    characters = await generate_characters_parallel(rules, locations)
    # 输出：几百个角色完整档案

    return WorldState(rules=rules, locations=locations, characters=characters)
```

### 11.2 角色生成

每个角色的生成是一次独立 LLM 调用，输入约束：
- 世界规则
- 已生成的地点列表
- 随机种子（MBTI + 年龄范围 + 性别）

输出完整档案：MBTI、年龄、背景故事、身份证号、出生日期、性格、外貌、初始地点、日常 routine、初始关系网。

### 11.3 零输入

`premise = None` 时：
- Step 1 随机选择世界类型（现代都市 / 古代 / 玄幻 / 科幻 / ……）
- Step 2-3 基于随机世界规则生成
- 完全自动，无需人工干预

---

## 12. 前端

### 12.1 技术栈

React + SSE。

### 12.2 视图

| 视图 | 内容 |
|------|------|
| 角色关系图 | 节点 = 角色（大小 ∝ 权重），边 = 关系（颜色 = 类型，粗细 = 强度） |
| 剧情图 | 节点 = 事件，边 = 因果/时序 |
| 控制面板 | 设置参数 / 输入 premise / 启动/暂停/fork/reset |
| 对话面板 | 作者 ↔ 导演自然语言对话 + 结构化指令按钮 |
| 阅读页 | Writer 输出的网文（实时更新） |
| 成本仪表盘 | LLM 调用统计 / 每角色成本 / provider 分布 |

### 12.3 SSE 事件

```typescript
type SSEEvent =
  | { type: "tick_started"; tick_id: number }
  | { type: "character_action"; action: CharacterAction }
  | { type: "director_event"; event: DirectorEvent }
  | { type: "location_update"; location: Location }
  | { type: "writer_output"; content: string; tick_range: [number, number] }
  | { type: "checkpoint_saved"; tick_id: number }
  | { type: "simulation_paused"; reason: string }
  | { type: "llm_cost_update"; total_cost: number; tick_cost: number }
```

### 12.4 交互

- 点击角色节点 → 打开对话框 → 输入内容发送给导演（自动附带该角色上下文）
- 面板布局参考 MiroFish 前端（设置/图/premise 分离）

---

## 13. 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | Python + FastAPI | LLM SDK 生态完整；async 原生 |
| API | REST + SSE | 简单直接，调试方便 |
| 前端 | React | 节点图交互复杂度需要 |
| ORM | SQLAlchemy | SQLite ↔ PostgreSQL 无痛切换 |
| 存储 | SQLite（开发）→ PostgreSQL（生产） | 结构化快照 + git-like 操作 |
| LLM | 多 provider routing | DeepSeek（便宜）/ Anthropic（强）/ Qwen / Ollama |
| 部署 | Docker | macOS + Linux 统一环境 |

---

## 14. 配置项

```toml
[simulation]
tick_interval_hours = 1          # 模拟内一个 tick 代表的小时数
max_steps = 0                    # 0 = 无限跑
max_concurrent_llm_calls = 50

[characters]
min_weight = 0.05                # 低于此权重跳过
max_updates_per_tick = 3         # 单角色单 tick 最大更新次数
interaction_max_limit = 10       # 互动 budget 最大轮数
dpo_sigma = 0.1                  # 随机重排高斯噪声标准差

[directors]
count = 1                        # 初始导演数量
pacing_stale_threshold = 5       # 连续 N tick 无事件则导演必须干预

[routing]
default_provider = "deepseek"
default_model = "deepseek-chat"

[storage]
db_url = "sqlite:///inkfish.db"  # 或 postgresql://...

[hot_topics]
enabled = false
source = "manual"                # manual / weibo_api / twitter_api
poll_interval_minutes = 60

[writer]
suggested_split_ticks = 50       # 建议导演每 N tick 触发一次写作
```
