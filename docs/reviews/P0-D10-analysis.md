# INKFISH P0 D10 — Full Run Analysis

Generated: 2026-05-11 05:49:52 UTC
Database: `data/inkfish.db`

## Section 1 — Aggregate Statistics

| Metric | Value |
|--------|-------|
| Ticks completed | 10 (target: 10) |
| Actions saved | 50 (target: 50) |
| Snapshots saved | 11 (target: 11: tick 0 seed + ticks 1–10) |
| LLM calls made | 55 |
| Total cost USD | $0.008345 |
| Wall-clock (first log → last log) | 30.1 min (1805s) |
| Avg latency_ms per LLM call | 30726 ms |
| Total prompt_tokens | 74,395 |
| Total cached_tokens | 44,032 |
| Total response_tokens | 45,900 |
| Overall cache hit % | 59.2% |

## Section 2 — Finish-reason / Retry / Fallback Distribution

### finish_reason distribution

| finish_reason | count | % |
|---------------|-------|---|
| `stop` | 54 | 98.2% |
| `fallback_do_nothing` | 1 | 1.8% |

### Attempt distribution (1 = first-try success)

| attempt | count |
|---------|-------|
| 1 | 51 |
| 2 | 2 |
| 3 | 1 |
| 4 | 1 |

### Error / fallback counts

- LLM log rows with errors: **5** (target: 0)
- Fallback DO_NOTHING logs: **0** (target: 0)
- DO_NOTHING actions saved: **1** (target: 0)

- Retried calls (attempt > 1): **4**
- Retry rate: **7.3%**

## Section 3 — Cache Hit Analysis

| tick | prompt_tokens | cached_tokens | cache hit % |
|------|--------------|---------------|-------------|
| 1 | 6,901 | 6,400 | 92.7% |
| 2 | 6,872 | 6,400 | 93.1% |
| 3 | 6,867 | 3,712 | 54.1% |
| 4 | 9,725 | 4,224 | 43.4% |
| 5 | 8,261 | 4,480 | 54.2% |
| 6 | 6,864 | 3,712 | 54.1% |
| 7 | 6,864 | 3,712 | 54.1% |
| 8 | 6,864 | 3,712 | 54.1% |
| 9 | 6,865 | 3,712 | 54.1% |
| 10 | 8,312 | 3,968 | 47.7% |

⚠️  Ticks with cache hit < 80% (tick ≥ 3): [3, 4, 5, 6, 7, 8, 9, 10]

## Section 4 — Action Distribution by Character

### `char_chen` — ESTP — expect ACT + SPEAK high

| action_type | count | % |
|-------------|-------|---|
| SPEAK | 10 | 100.0% |
| THINK | 0 | 0.0% |
| ACT | 0 | 0.0% |
| MOVE_TO | 0 | 0.0% |
| REACT | 0 | 0.0% |
| DO_NOTHING | 0 | 0.0% |

  ✅ ACT+SPEAK = 100% ≥ 50% (ESTP archetype matches)

### `char_li` — ENTJ — expect MOVE_TO + SPEAK higher, decisive

| action_type | count | % |
|-------------|-------|---|
| SPEAK | 0 | 0.0% |
| THINK | 0 | 0.0% |
| ACT | 10 | 100.0% |
| MOVE_TO | 0 | 0.0% |
| REACT | 0 | 0.0% |
| DO_NOTHING | 0 | 0.0% |

  ℹ️  MOVE_TO+SPEAK = 0% (ENTJ: decisive mobility expected)

### `char_lin` — ENFP — expect SPEAK ≥ 30%, ACT high

| action_type | count | % |
|-------------|-------|---|
| SPEAK | 10 | 100.0% |
| THINK | 0 | 0.0% |
| ACT | 0 | 0.0% |
| MOVE_TO | 0 | 0.0% |
| REACT | 0 | 0.0% |
| DO_NOTHING | 0 | 0.0% |

  ✅ SPEAK = 100% ≥ 30% (ENFP archetype matches)

### `char_wang` — ISFJ — expect THINK + SPEAK present, low ACT

| action_type | count | % |
|-------------|-------|---|
| SPEAK | 0 | 0.0% |
| THINK | 3 | 30.0% |
| ACT | 7 | 70.0% |
| MOVE_TO | 0 | 0.0% |
| REACT | 0 | 0.0% |
| DO_NOTHING | 0 | 0.0% |

  ℹ️  ACT = 70%, THINK+SPEAK = 30% (ISFJ: low ACT expected)

### `char_zhao` — INTP — expect THINK + DO_NOTHING ≥ 30%, SPEAK lower

| action_type | count | % |
|-------------|-------|---|
| SPEAK | 0 | 0.0% |
| THINK | 3 | 30.0% |
| ACT | 6 | 60.0% |
| MOVE_TO | 0 | 0.0% |
| REACT | 0 | 0.0% |
| DO_NOTHING | 1 | 10.0% |

  ✅ THINK+DO_NOTHING = 40% ≥ 30% (INTP archetype matches)

## Section 5 — Schema Validity (Pydantic Round-Trip)

✅ All 50 actions pass `CharacterAction` Pydantic validation.

## Section 6 — Sample Qualitative Content

One action per character per 5 ticks (max 10 samples).

**[char_chen tick=5 SPEAK target=char_li]**
> Content: _嘿，哥们儿，你这块表挺有意思，薄得跟纸似的，什么牌子的？我刷视频见过类似的设计，但没见过实物。_
> Mood: `curious` · Thought: _这男的看起来像管事的，背挺得比我带课还直，那表一看就不便宜。我好奇他会不会跟我聊，反正再坐五分钟就得走了。_

**[char_li tick=5 ACT]**
> Content: _迅速走向靠墙的安静角落，放下电脑包，取出笔记本电脑，连接电源和咖啡馆的Wi-Fi_
> Mood: `焦躁` · Thought: _这地方太吵闹了，但眼下没有更好的选择。距离第一个视频会议还有15分钟，必须确保网络稳定。任何延误都不可接受。_

**[char_lin tick=5 SPEAK target=char_zhao]**
> Content: _你在算什么吗？我观察你好一会儿了，你眼睛转得飞快。_
> Mood: `好奇` · Thought: _这个男人的大脑似乎永远不会闲着，说不定正在解一道数学题或者构思什么发明，我得问清楚。_

**[char_wang tick=5 THINK]**
> Content: _今天咖啡馆人不多，那个穿橙色衣服的女孩挺有精神的。_
> Mood: `平静` · Thought: _那个女孩的T恤上印的不知名小动物，有点像以前教科书上的插图。回家可以记下来。_

**[char_zhao tick=5 ACT]**
> Content: _手指在机械键盘上有节奏地敲击，屏幕上光标在一段SQL查询上闪烁，他盯着看了一会儿，又删掉几个字符，重新输入。_
> Mood: `neutral` · Thought: _这个索引策略在B+树上的表现理论上应该更优，但执行计划还是走了全表扫描。难道是优化器的样本统计偏差？_

**[char_chen tick=10 SPEAK target=char_linxia]**
> Content: _嘿！你衣服上那个动物是什么？我看了半天没认出来。_
> Mood: `curious` · Thought: _这女的橙色T恤挺显眼，图案怪有意思的，正好无聊，搭个话。_

**[char_li tick=10 ACT]**
> Content: _从公文包中取出笔记本电脑，连接电源线和耳机，检查WiFi信号强度_
> Mood: `焦躁` · Thought: _这地方比想象中吵，但总比没有会议室强。两个会议，第一个十五分钟后开始，希望别出岔子。_

**[char_lin tick=10 SPEAK target=char_wang]**
> Content: _你好，我注意到你手上没有戒指但有一道印子。可以问一下你以前是做什么的吗？——抱歉，我是不是太直接了？我就是真的好奇。_
> Mood: `curious` · Thought: _她看起来是个有故事的人。那种平静的专注背后一定有事情。戒指的印记是最近才消失的，这可能是篇好文章的开头。_

**[char_wang tick=10 THINK]**
> Content: _默默观察着咖啡馆里的其他人，注意到他们各自的状态，心里想着今天元旦，大家却都还在这里消磨时光。_
> Mood: `平静` · Thought: _那女孩的橙色T恤真是扎眼，但又有种说不出的自在。年轻人真好，不过这个点不出去走走，都窝在咖啡馆里，也是奇怪。_

**[char_zhao tick=10 ACT]**
> Content: _暂停打字，端起咖啡杯抿了一口，目光扫过屏幕上的错误日志。_
> Mood: `neutral` · Thought: _这个索引碎片化的问题比我预估的复杂，但肯定能找到模式。旁边那个人又用眼神抱怨键盘声了——我不可能换轴体。_

## Section 7 — Verdict

| Check | Result | Detail |
|-------|--------|--------|
| 10 ticks completed | ✅ | ticks_completed=10 |
| 50 actions saved | ✅ | total_actions=50 |
| All actions pass Pydantic validation | ✅ | failures=0 |
| ≤5% errors/retries/fallbacks | ❌ | bad_pct=9.1% (5/55) |
| ≥60% cache hit by tick 5 | ❌ | tick5_cache_hit=54.2% |

## VERDICT: ❌ P0 D10 FAIL — ≤5% errors/retries/fallbacks, ≥60% cache hit by tick 5
