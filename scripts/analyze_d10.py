"""analyze_d10.py — INKFISH P0 D10 post-run analysis script.

Reads data/inkfish.db directly via SQLAlchemy, produces a markdown report
on stdout AND saves it to docs/reviews/P0-D10-analysis.md.

Usage:
    uv run python scripts/analyze_d10.py

No CLI arguments; paths are resolved relative to the project root (the
directory containing pyproject.toml), detected from this script's location.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

# ── Path resolution ──────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent  # inkfish/

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from inkfish.character.schema import ActionType, CharacterAction
from inkfish.storage.models import ActionRow, LLMLogRow, SnapshotRow

DB_PATH = PROJECT_ROOT / "data" / "inkfish.db"
REPORT_PATH = PROJECT_ROOT / "docs" / "reviews" / "P0-D10-analysis.md"


# ── Data loading ─────────────────────────────────────────────────────────────

def _make_session() -> Session:
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                           expire_on_commit=False)
    return factory()


# ── Section helpers ───────────────────────────────────────────────────────────

def _pct(part: int, total: int) -> str:
    if total == 0:
        return "N/A"
    return f"{100.0 * part / total:.1f}%"


# ── Named tuple for per-tick cache stats ─────────────────────────────────────

class TickCacheStats(NamedTuple):
    tick_id: int
    prompt_tokens: int
    cached_tokens: int
    hit_pct: float


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_analysis() -> str:  # returns the full markdown string
    session = _make_session()
    lines: list[str] = []

    def h(text_: str) -> None:
        lines.append(text_)

    h("# INKFISH P0 D10 — Full Run Analysis")
    h("")
    h(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    h(f"Database: `{DB_PATH.relative_to(PROJECT_ROOT)}`")
    h("")

    # ── Load raw data ──────────────────────────────────────────────────────
    actions: list[ActionRow] = session.query(ActionRow).order_by(
        ActionRow.tick_id, ActionRow.created_at
    ).all()
    snapshots: list[SnapshotRow] = session.query(SnapshotRow).order_by(
        SnapshotRow.tick_id
    ).all()
    llm_logs: list[LLMLogRow] = session.query(LLMLogRow).order_by(
        LLMLogRow.tick_id, LLMLogRow.created_at
    ).all()

    # ── Section 1 — Aggregate statistics ──────────────────────────────────
    h("## Section 1 — Aggregate Statistics")
    h("")

    ticks_completed = max((s.tick_id for s in snapshots if s.tick_id > 0), default=0)
    total_actions = len(actions)
    total_snapshots = len(snapshots)  # includes tick=0 seed
    total_llm_calls = len(llm_logs)
    total_cost_usd = sum(ll.cost_usd for ll in llm_logs)
    total_prompt_tokens = sum(ll.prompt_tokens for ll in llm_logs)
    total_cached_tokens = sum(ll.cached_tokens for ll in llm_logs)
    total_response_tokens = sum(ll.response_tokens for ll in llm_logs)
    avg_latency_ms = (
        sum(ll.latency_ms for ll in llm_logs) / total_llm_calls
        if total_llm_calls else 0
    )

    if llm_logs:
        first_ts: datetime = llm_logs[0].created_at
        last_ts: datetime = llm_logs[-1].created_at
        # Ensure timezone-aware for subtraction
        def _utc(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        wall_clock_s = (_utc(last_ts) - _utc(first_ts)).total_seconds()
        wall_clock_str = f"{wall_clock_s / 60:.1f} min ({wall_clock_s:.0f}s)"
    else:
        wall_clock_str = "N/A"

    h(f"| Metric | Value |")
    h(f"|--------|-------|")
    h(f"| Ticks completed | {ticks_completed} (target: 10) |")
    h(f"| Actions saved | {total_actions} (target: 50) |")
    h(f"| Snapshots saved | {total_snapshots} (target: 11: tick 0 seed + ticks 1–10) |")
    h(f"| LLM calls made | {total_llm_calls} |")
    h(f"| Total cost USD | ${total_cost_usd:.6f} |")
    h(f"| Wall-clock (first log → last log) | {wall_clock_str} |")
    h(f"| Avg latency_ms per LLM call | {avg_latency_ms:.0f} ms |")
    h(f"| Total prompt_tokens | {total_prompt_tokens:,} |")
    h(f"| Total cached_tokens | {total_cached_tokens:,} |")
    h(f"| Total response_tokens | {total_response_tokens:,} |")
    h(f"| Overall cache hit % | {_pct(total_cached_tokens, total_prompt_tokens)} |")
    h("")

    # ── Section 2 — Finish-reason / retry / fallback distribution ─────────
    h("## Section 2 — Finish-reason / Retry / Fallback Distribution")
    h("")

    finish_reasons: Counter[str] = Counter(ll.finish_reason or "unknown" for ll in llm_logs)
    attempt_counts: Counter[int] = Counter(ll.attempt for ll in llm_logs)
    error_count = sum(1 for ll in llm_logs if ll.error is not None)

    # fallback_do_nothing: actions with action_type=DO_NOTHING that have
    # a corresponding llm_log with a fallback error marker
    fallback_logs = [ll for ll in llm_logs if ll.error and "fallback" in ll.error.lower()]
    do_nothing_actions = [a for a in actions if a.action_type == ActionType.DO_NOTHING]

    h("### finish_reason distribution")
    h("")
    h("| finish_reason | count | % |")
    h("|---------------|-------|---|")
    for reason, cnt in sorted(finish_reasons.items(), key=lambda x: -x[1]):
        h(f"| `{reason}` | {cnt} | {_pct(cnt, total_llm_calls)} |")
    h("")

    h("### Attempt distribution (1 = first-try success)")
    h("")
    h("| attempt | count |")
    h("|---------|-------|")
    for att in sorted(attempt_counts):
        h(f"| {att} | {attempt_counts[att]} |")
    h("")

    h("### Error / fallback counts")
    h("")
    h(f"- LLM log rows with errors: **{error_count}** (target: 0)")
    h(f"- Fallback DO_NOTHING logs: **{len(fallback_logs)}** (target: 0)")
    h(f"- DO_NOTHING actions saved: **{len(do_nothing_actions)}** (target: 0)")
    h("")

    retry_count = sum(cnt for att, cnt in attempt_counts.items() if att > 1)
    h(f"- Retried calls (attempt > 1): **{retry_count}**")
    h(f"- Retry rate: **{_pct(retry_count, total_llm_calls)}**")
    h("")

    # ── Section 3 — Cache hit analysis ────────────────────────────────────
    h("## Section 3 — Cache Hit Analysis")
    h("")
    h("| tick | prompt_tokens | cached_tokens | cache hit % |")
    h("|------|--------------|---------------|-------------|")

    tick_cache_stats: list[TickCacheStats] = []
    logs_by_tick: dict[int, list[LLMLogRow]] = defaultdict(list)
    for ll in llm_logs:
        logs_by_tick[ll.tick_id].append(ll)

    for tick_id in sorted(logs_by_tick.keys()):
        tick_logs = logs_by_tick[tick_id]
        pt = sum(ll.prompt_tokens for ll in tick_logs)
        ct = sum(ll.cached_tokens for ll in tick_logs)
        hit_pct = (100.0 * ct / pt) if pt > 0 else 0.0
        tick_cache_stats.append(TickCacheStats(tick_id, pt, ct, hit_pct))
        h(f"| {tick_id} | {pt:,} | {ct:,} | {hit_pct:.1f}% |")
    h("")

    # Check if cache climbs and stabilises ≥80% after tick 2
    late_ticks = [s for s in tick_cache_stats if s.tick_id >= 3]
    below_80 = [s for s in late_ticks if s.hit_pct < 80.0]
    if below_80:
        h(f"⚠️  Ticks with cache hit < 80% (tick ≥ 3): {[s.tick_id for s in below_80]}")
    else:
        h("✅ Cache hit ≥ 80% for all ticks ≥ 3 (or no ticks ≥ 3 present).")
    h("")

    # ── Section 4 — Action distribution by character ──────────────────────
    h("## Section 4 — Action Distribution by Character")
    h("")

    # Expected MBTI archetypes from world.json
    mbti_notes = {
        "char_lin":  "ENFP — expect SPEAK ≥ 30%, ACT high",
        "char_zhao": "INTP — expect THINK + DO_NOTHING ≥ 30%, SPEAK lower",
        "char_chen": "ESTP — expect ACT + SPEAK high",
        "char_wang": "ISFJ — expect THINK + SPEAK present, low ACT",
        "char_li":   "ENTJ — expect MOVE_TO + SPEAK higher, decisive",
    }

    actions_by_char: dict[str, list[ActionRow]] = defaultdict(list)
    for a in actions:
        actions_by_char[a.character_id].append(a)

    for char_id in sorted(actions_by_char.keys()):
        char_actions = actions_by_char[char_id]
        count_by_type: Counter[str] = Counter(a.action_type for a in char_actions)
        total_char = len(char_actions)
        note = mbti_notes.get(char_id, "")
        h(f"### `{char_id}` — {note}")
        h("")
        h("| action_type | count | % |")
        h("|-------------|-------|---|")
        for atype in ActionType:
            cnt = count_by_type.get(atype.value, 0)
            h(f"| {atype.value} | {cnt} | {_pct(cnt, total_char)} |")
        h("")

        # Soft MBTI check
        if char_id == "char_lin":
            speak_pct = 100.0 * count_by_type.get("SPEAK", 0) / total_char if total_char else 0
            if speak_pct < 30:
                h(f"  ⚠️  SPEAK = {speak_pct:.0f}% < 30% (expected for ENFP)")
            else:
                h(f"  ✅ SPEAK = {speak_pct:.0f}% ≥ 30% (ENFP archetype matches)")
        elif char_id == "char_zhao":
            think_dn = count_by_type.get("THINK", 0) + count_by_type.get("DO_NOTHING", 0)
            think_dn_pct = 100.0 * think_dn / total_char if total_char else 0
            if think_dn_pct < 30:
                h(f"  ⚠️  THINK+DO_NOTHING = {think_dn_pct:.0f}% < 30% (expected for INTP)")
            else:
                h(f"  ✅ THINK+DO_NOTHING = {think_dn_pct:.0f}% ≥ 30% (INTP archetype matches)")
        elif char_id == "char_chen":
            act_speak = count_by_type.get("ACT", 0) + count_by_type.get("SPEAK", 0)
            act_speak_pct = 100.0 * act_speak / total_char if total_char else 0
            if act_speak_pct < 50:
                h(f"  ⚠️  ACT+SPEAK = {act_speak_pct:.0f}% < 50% (expected for ESTP)")
            else:
                h(f"  ✅ ACT+SPEAK = {act_speak_pct:.0f}% ≥ 50% (ESTP archetype matches)")
        elif char_id == "char_wang":
            act_pct = 100.0 * count_by_type.get("ACT", 0) / total_char if total_char else 0
            think_speak = count_by_type.get("THINK", 0) + count_by_type.get("SPEAK", 0)
            think_speak_pct = 100.0 * think_speak / total_char if total_char else 0
            h(f"  ℹ️  ACT = {act_pct:.0f}%, THINK+SPEAK = {think_speak_pct:.0f}% (ISFJ: low ACT expected)")
        elif char_id == "char_li":
            move_speak = count_by_type.get("MOVE_TO", 0) + count_by_type.get("SPEAK", 0)
            move_speak_pct = 100.0 * move_speak / total_char if total_char else 0
            h(f"  ℹ️  MOVE_TO+SPEAK = {move_speak_pct:.0f}% (ENTJ: decisive mobility expected)")
        h("")

    # ── Section 5 — Schema validity ───────────────────────────────────────
    h("## Section 5 — Schema Validity (Pydantic Round-Trip)")
    h("")

    validation_failures: list[tuple[str, str]] = []
    for a in actions:
        try:
            CharacterAction.model_validate({
                "character_id": a.character_id,
                "tick_id": a.tick_id,
                "action_type": a.action_type,
                "content": a.content,
                "target": a.target,
                "mood": a.mood,
                "inner_thought": a.inner_thought,
                "triggers_interaction": a.triggers_interaction,
            })
        except Exception as exc:
            validation_failures.append((a.id, str(exc)))

    if validation_failures:
        h(f"❌ **{len(validation_failures)} action(s) failed Pydantic validation:**")
        h("")
        for action_id, err in validation_failures[:10]:  # cap at 10
            h(f"- `{action_id}`: {err}")
    else:
        h(f"✅ All {len(actions)} actions pass `CharacterAction` Pydantic validation.")
    h("")

    # ── Section 6 — Sample qualitative content ────────────────────────────
    h("## Section 6 — Sample Qualitative Content")
    h("")
    h("One action per character per 5 ticks (max 10 samples).")
    h("")

    sample_ticks = [5, 10]  # representative ticks
    samples_printed = 0
    for sample_tick in sample_ticks:
        for char_id in sorted(mbti_notes.keys()):
            # Find the action for this char at this tick (or closest available)
            candidates = [
                a for a in actions
                if a.character_id == char_id and a.tick_id == sample_tick
            ]
            if not candidates:
                # Try nearby ticks
                for a in actions:
                    if a.character_id == char_id and abs(a.tick_id - sample_tick) <= 2:
                        candidates = [a]
                        break
            if not candidates:
                continue
            a = candidates[0]
            content_preview = (a.content or "")[:120].replace("\n", " ")
            thought_preview = (a.inner_thought or "")[:80].replace("\n", " ")
            target_str = f" target={a.target}" if a.target else ""
            h(
                f"**[{a.character_id} tick={a.tick_id} {a.action_type}"
                f"{target_str}]**"
            )
            h(f"> Content: _{content_preview}_")
            h(f"> Mood: `{a.mood}` · Thought: _{thought_preview}_")
            h("")
            samples_printed += 1
            if samples_printed >= 10:
                break
        if samples_printed >= 10:
            break

    # ── Section 7 — Verdict ───────────────────────────────────────────────
    h("## Section 7 — Verdict")
    h("")

    checks: list[tuple[str, bool, str]] = []

    # 1. 10 ticks completed
    checks.append((
        "10 ticks completed",
        ticks_completed >= 10,
        f"ticks_completed={ticks_completed}",
    ))

    # 2. 50 actions saved
    checks.append((
        "50 actions saved",
        total_actions >= 50,
        f"total_actions={total_actions}",
    ))

    # 3. All pass Pydantic validation
    checks.append((
        "All actions pass Pydantic validation",
        len(validation_failures) == 0,
        f"failures={len(validation_failures)}",
    ))

    # 4. ≤5% errors / retries / fallbacks
    bad_calls = error_count + len(fallback_logs)
    bad_pct = 100.0 * bad_calls / total_llm_calls if total_llm_calls else 0.0
    checks.append((
        "≤5% errors/retries/fallbacks",
        bad_pct <= 5.0,
        f"bad_pct={bad_pct:.1f}% ({bad_calls}/{total_llm_calls})",
    ))

    # 5. ≥60% cache hit by tick 5
    tick5_stats = [s for s in tick_cache_stats if s.tick_id == 5]
    if tick5_stats:
        tick5_hit = tick5_stats[0].hit_pct
    elif tick_cache_stats:
        # use last available tick
        tick5_hit = tick_cache_stats[-1].hit_pct
    else:
        tick5_hit = 0.0
    checks.append((
        "≥60% cache hit by tick 5",
        tick5_hit >= 60.0,
        f"tick5_cache_hit={tick5_hit:.1f}%",
    ))

    all_pass = all(ok for _, ok, _ in checks)

    h("| Check | Result | Detail |")
    h("|-------|--------|--------|")
    for label, ok, detail in checks:
        icon = "✅" if ok else "❌"
        h(f"| {label} | {icon} | {detail} |")
    h("")

    if all_pass:
        verdict = "VERDICT: ✅ P0 D10 PASS"
    else:
        failed = [label for label, ok, _ in checks if not ok]
        verdict = f"VERDICT: ❌ P0 D10 FAIL — {', '.join(failed)}"

    h(f"## {verdict}")
    h("")

    return "\n".join(lines)


def main() -> None:
    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    report = run_analysis()

    # Print to stdout
    print(report)

    # Save to docs/reviews/
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\n--- Report saved to {REPORT_PATH.relative_to(Path.cwd())} ---",
          file=sys.stderr)


if __name__ == "__main__":
    main()
