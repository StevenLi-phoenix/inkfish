# P0 D8 Hotfix — max_tokens 800 → 2500 + length-aware retry

**日期**: 2026-05-11
**触发**: 用户指出"三次全是 length 结束导致 json 失败"
**状态**: ✅ 已验证修复有效

## 根因诊断

D8 mini-run 后看 `llm_logs` 数据：
- 5/14 logs `finish_reason=length`，`response_tokens=800` 顶到 max_tokens
- `content=''` 全空（JSON 都没开始输出）

**根因**：DeepSeek **v4-pro 是 reasoner 模型**，会先消耗大量 reasoning_tokens 做 chain-of-thought，再产 content。`max_tokens=800` 在 reasoning 阶段就用光，content 还没开始就被 cut。

D5 review 已经识别过 reasoning_tokens 现象（max_tokens=50 → empty content），但 D6/D7/D8 沿用了 plan 中的 800 默认值，没及时上调。

## 修复

### 1. `inkfish.toml` `[llm].max_tokens`：800 → 2500
含注释说明 2500 = reasoning (1500-2000) + content (500-800) 余量。

### 2. `src/inkfish/config.py` `SimConfig.max_tokens` 默认值：800 → 2500
一致性保持。

### 3. `src/inkfish/llm/retry.py` length-aware retry
当 `finish_reason == "length"` 且 content 为空时，下次 attempt 把 `current_max_tokens *= 1.5`（cap 8000）。
错误信息特化为 `length_truncation: response_tokens=N exhausted max_tokens=M before any content (v4-pro reasoning consumed full budget)`。

### 4. `tests/unit/test_config.py`
硬编码 `max_tokens == 800` 改为 `== 2500`。

## 验证（live mini-run 2 ticks）

仅过滤 post-hotfix 时段（`created_at > 05:09 UTC`）的 10 个 LLM logs：

| 指标 | Pre-hotfix (D8 14 logs) | Post-hotfix (10 logs) |
|---|---|---|
| `finish_reason=length` | 5 (35.7%) | **0** ✅ |
| `errors` | 5 (4 parse + 1 fallback) | **0** ✅ |
| `attempts > 1` (retries) | 4 | **0** ✅ |
| `cache_hit_rate` | 19.2% | **92.9%** ✅ |
| `response_tokens` 平均 | 800 (capped) | 783 (自然) |
| 单次成本 USD | 0.00345 | 0.00193 |

**Post-hotfix 全部 10 个 LLM call 一次成功，无截断、无 retry、无 fallback。**

## 经验沉淀

1. **Reasoner 模型必须给 reasoning 留充足预算**。v4-pro 实际 reasoning_tokens 估计 500-1500/call，加 content 500-800 → max_tokens 至少 2500 起步。
2. **reset() 保留 llm_logs 是双刃剑**：好处是审计完整；坏处是分析时容易混入历史 logs，过滤 cutoff 要小心。
3. **DeepSeek 自动前缀缓存超预期 work**：第二次起 cache hit 飙升到 92.9%。Persona 块字节稳定的 plan §D7 设计被实测确认。

## 影响

- D8 review 中"R2 真实发生"的诊断需更正——不是"JSON 模式丢字段"，是"reasoner 推理消耗预算"。
- D10/D11/D12 可以以稳定的 LLM 基线推进。
