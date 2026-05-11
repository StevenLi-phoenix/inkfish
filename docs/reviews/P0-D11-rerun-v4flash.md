# P0 D11 Killer Test Rerun — v4-flash + tool calling + async + cache-aware

**日期**: 2026-05-11
**前置**: P0 hotfix v2 完成后重跑 killer test 验证全部修改无回归
**状态**: ✅ **PASSED**

## 测试命令

```bash
rm -f data/inkfish_killer.db data/inkfish_killer.db-wal data/inkfish_killer.db-shm
time uv run pytest tests/live/test_killer_reset.py -v -s
```

## 结果总览

```
======================== 1 passed in 401.33s (0:06:41) =========================
Content differs in 25/25 pairs (100.0%)
```

| 阶段 | actions | LLM calls | retries | fallback | cache hit | cost |
|---|---|---|---|---|---|---|
| Phase 1（seed + 10 ticks Set A）| 50 | 58 | 8 | **0** | 77.6% | $0.024 |
| Phase 2（reset 5 + 5 ticks Set B）| 25 | 57 | 7 | **0** | 87.5% | $0.021 |
| **总** | 75 | 115 | 15 | **0** | ~82% | **$0.045** |

## 与 v4-pro 版（45:31）对比

| 指标 | v4-pro killer test | **v4-flash killer test** | 改进 |
|---|---|---|---|
| Wall-clock | 45:31 | **6:41** | **6.8× 加速** |
| Fallback | 3 (char_zhao tick 4/9/10) | **0** | ✅ 全消除 |
| Cache hit | ~60% | **~82%** | +22pp |
| Content diff | 100/25=100% | **25/25=100%** | 同 |
| Cost | ~$0.03 | $0.045 | +50%（v4-flash 无 75% 折扣，但绝对仍便宜）|

## 8 + 7 retries 解析

15 次 retry 全部归因**单一现象**：v4-flash 偶发把 perception 块的 `[id=char_xx]` 装饰符整个复制进 target field：

```
WARNING: call_with_retry: action.target='[id=char_zhao]' not in allowed enum
   ['', 'char_chen', 'char_li', 'char_wang', 'char_zhao', 'loc_coffee']
   — treating as parse failure to trigger retry
```

**所有 retry 在 attempt 2 都成功** —— 加上 retry 层的 corrective prefix LLM 知道要去掉装饰。

## fuzzy match 修复（本次 run 之后落地）

观察到这一现象后，session 内已在 retry 层加入 `_normalize_target()` helper：

```python
def _normalize_target(raw: str, allowed: set[str]) -> str | None:
    # "[id=char_lin]" → "char_lin"
    # "id=char_lin"   → "char_lin"
    # "char_lin (ENFP)" → "char_lin" (longest substring match)
    ...
```

下次跑 killer test 时这 15 次 retry 应该消失（fuzzy match 在 attempt 1 就修复），retries 接近 0，wall 进一步降到 ~5 min。

## Set B 性格分布（archetype 一致性 soft check）

```
char_chen (ESTP):  ACT=2, SPEAK=3       ✅ 外向直接
char_zhao (INTP):  THINK=4, ACT=1       ✅ 高度内省
char_lin  (ENFP):  THINK=2, SPEAK=3     ✅ 外向 + 也会思考
char_li   (ENTJ):  ACT=5                ✅ 决断行动
char_wang (ISFJ):  ACT=2, THINK=3       ✅ 平静内敛
```

v4-flash 比 v4-pro 时代分布更"分散" —— 之前 char_lin / char_chen 都是 100% SPEAK，现在有 THINK / ACT 出现，群体感更丰富。这可能是因为 tool schema 强制 + corrective retry 让 LLM 不能"all SPEAK"偷懒。

## 全 50 actions Pydantic 校验

100% 通过（`CharacterAction(**)` 重构 25 次 set A 和 25 次 set B 全成功）。tool calling enum + Pydantic + retry 后置校验 + SPEAK→ACT 降级 + fuzzy match 五道防线让 schema 不变量牢固。

## 一句话

**v4-flash + tool calling 6.8× 加速 + 100% 内容差异 + 0 fallback，killer test 比 v4-pro 版更稳更快。**
