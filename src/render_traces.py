"""
Render a single released agent trace as a readable Markdown transcript.

Reads ../traces/raw/traces.jsonl.gz (one JSON object per line, gzip-compressed)
and ../data/hydra_bench/{flood,landslide}_events.json (for location metadata,
looked up by event_id) and renders ONE matching trace as Markdown.

Each trace record has the shape:
  {
    "disaster_type": "flood" | "landslide",
    "event_id": str,
    "label": "positive" | "negative",
    "model_id": str,
    "lead_time_days": int,
    "run_number": int,
    "risk_level": str,
    "reasoning": str,
    "tool_trace": [ {"type": "tool_call", "tool": ..., "args": {...}},
                     {"type": "tool_result", "tool": ..., "result": {...}},
                     {"type": "thought", "text": ...},   # occasional, may be absent
                     ... ],
    "total_tokens": int | null,
    "latency_seconds": float,
  }

Usage:
  python render_traces.py --event-id <id> --model gemini-3.1-flash-lite --lead 1
  python render_traces.py --event-id <id> --model gpt-4.1-mini --lead 3 --out trace.md
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
TRACES_PATH = SCRIPT_DIR.parent / "traces" / "raw" / "traces.jsonl.gz"
BENCH_DIR = SCRIPT_DIR.parent / "data" / "hydra_bench"
POS_RISK = {"MEDIUM", "HIGH", "CRITICAL"}
MODELS = ["gemini-3.1-flash-lite", "gpt-4.1-mini", "ministral-3-14b"]
HAZARDS = ["flood", "landslide"]


def find_trace(event_id: str, model_id: str, lead_time_days: int,
                run_number: Optional[int] = None) -> Optional[dict]:
    """Scan the compressed trace log for the first matching record."""
    with gzip.open(TRACES_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if (rec.get("event_id") == event_id
                    and rec.get("model_id") == model_id
                    and rec.get("lead_time_days") == lead_time_days):
                if run_number is not None and rec.get("run_number") != run_number:
                    continue
                return rec
    return None


def load_event_metadata(disaster_type: str, event_id: str) -> Optional[dict]:
    """Look up an event's location metadata from the ground-truth bench file."""
    path = BENCH_DIR / f"{disaster_type}_events.json"
    if not path.exists():
        return None
    events = json.loads(path.read_text(encoding="utf-8"))
    for e in events:
        if e.get("id") == event_id:
            return e
    return None


def _location_label(event: Optional[dict], trace: dict) -> str:
    """Build the location string for the H1, preferring a human-readable place name."""
    if event:
        parts = [p for p in [
            event.get("location_name"),
            event.get("district"),
            event.get("province"),
        ] if p]
        if parts:
            return ", ".join(parts)
        lat = event.get("geo_latitude")
        lon = event.get("geo_longitude")
        if lat is not None and lon is not None:
            return f"lat={lat}, lon={lon}"
    return f"event {trace.get('event_id', 'unknown')}"


def _format_args(args: Dict) -> str:
    """Render tool call args as key=value, comma-separated."""
    parts = []
    for k, v in (args or {}).items():
        parts.append(f"{k}={v!r}" if isinstance(v, str) else f"{k}={v}")
    return ", ".join(parts)


def _pair_calls_and_results(tool_trace: list) -> tuple[list, list]:
    """Pair tool_call -> tool_result by POSITION, not adjacency. A single agent
    turn can issue several tool_calls at once (seen live: GPT-4.1-mini batches
    up to 8 calls in one message), in which case the flat trace has a run of
    tool_call entries followed by a run of tool_result entries, not a strict
    call/result/call/result alternation. LangGraph's ToolNode always returns
    results in the same order calls were issued, so the Nth call pairs with
    the Nth result regardless of how they're interleaved in the flat list.

    Returns (calls, results) where calls is [(pending_thought_or_None, tool_call_entry), ...]
    and results is [tool_result_entry, ...], both in original order.
    """
    calls = []
    results = []
    pending_thought = None
    for entry in tool_trace:
        etype = entry.get("type")
        if etype == "thought":
            pending_thought = entry.get("text", "")
        elif etype == "tool_call":
            calls.append((pending_thought, entry))
            pending_thought = None
        elif etype == "tool_result":
            results.append(entry)
    return calls, results


def _render_header(trace: dict, event: Optional[dict]) -> list:
    disaster_label = "Flood" if trace.get("disaster_type") == "flood" else "Landslide"
    location = _location_label(event, trace)
    tool_trace = trace.get("tool_trace") or []
    tool_call_count = sum(1 for e in tool_trace if e.get("type") == "tool_call")

    lines = [f"# {disaster_label} assessment, {location}", ""]
    lines.append(
        f"**Event** {trace.get('event_id')} | "
        f"**Backbone** {trace.get('model_id')} | "
        f"**Lead** T-{trace.get('lead_time_days')}"
    )
    lines.append(
        f"**Ground truth** {trace.get('label')} | "
        f"**Predicted** {trace.get('risk_level')}"
    )
    lines.append(
        f"**Tool calls** {tool_call_count} | "
        f"**Latency** {trace.get('latency_seconds')}s | "
        f"**Tokens** {trace.get('total_tokens')}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    return lines


def render_markdown_chronological(trace: dict, event: Optional[dict]) -> str:
    """Chronological Step N format: Thought/Action/Observation inline, in call
    order, Final Assessment at the bottom. Use this for a live run — it has
    real per-step thought text, so watching it unfold step by step is the
    point. (For the released historical archive, which mostly predates
    per-step thought capture, use render_markdown() instead — see its
    docstring for why "Step N" is the wrong framing there.)
    """
    lines = _render_header(trace, event)
    calls, results = _pair_calls_and_results(trace.get("tool_trace") or [])

    for step_num, (thought, call_entry) in enumerate(calls, start=1):
        lines.append(f"### Step {step_num}")
        lines.append("")
        if thought:
            lines.append(f"**Thought.** {thought}")
            lines.append("")

        tool_name = call_entry.get("tool", "unknown")
        args_str = _format_args(call_entry.get("args", {}))
        lines.append(f"**Action.** `{tool_name}({args_str})`")
        lines.append("")

        result_entry = results[step_num - 1] if step_num - 1 < len(results) else None
        if result_entry is not None:
            result_json = json.dumps(result_entry.get("result"), indent=2, ensure_ascii=False)
            lines.append("**Observation.**")
            lines.append("```json")
            lines.append(result_json)
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")

    lines.append("### Final Assessment")
    lines.append("")
    lines.append(trace.get("reasoning", "").strip())
    lines.append("")
    lines.append(f"**Risk Level: {trace.get('risk_level')}**")
    lines.append("")

    return "\n".join(lines)


def render_markdown(trace: dict, event: Optional[dict]) -> str:
    lines = _render_header(trace, event)
    calls, results = _pair_calls_and_results(trace.get("tool_trace") or [])

    # Final Assessment comes first — it's what a reviewer wants to read first,
    # and the tool-call log below is supporting evidence, not a narrated
    # sequence (many released traces predate per-step "thought" capture, and
    # even where thought is present, a single turn can batch several tool
    # calls together, so numbering these as reasoning "Steps" overclaims a
    # sequence that isn't really there — see "Call N" below instead).
    lines.append("### Final Assessment")
    lines.append("")
    lines.append(trace.get("reasoning", "").strip())
    lines.append("")
    lines.append(f"**Risk Level: {trace.get('risk_level')}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("### Tool Call Traces")
    lines.append("")

    call_num = 0
    for call_num, (thought, call_entry) in enumerate(calls, start=1):
        lines.append(f"**Call {call_num}.** `{call_entry.get('tool', 'unknown')}({_format_args(call_entry.get('args', {}))})`")
        lines.append("")
        if thought:
            lines.append(f"**Thought.** {thought}")
            lines.append("")

        result_entry = results[call_num - 1] if call_num - 1 < len(results) else None
        if result_entry is not None:
            result_json = json.dumps(result_entry.get("result"), indent=2, ensure_ascii=False)
            lines.append("**Observation.**")
            lines.append("```json")
            lines.append(result_json)
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Any results beyond len(calls) would mean more results than calls, which
    # shouldn't happen given ToolNode's 1:1 semantics — render defensively
    # rather than silently drop them if it ever does.
    for extra in results[len(calls):]:
        call_num += 1
        lines.append(f"**Call {call_num}.** (unmatched — tool: {extra.get('tool', 'unknown')})")
        lines.append("")
        lines.append("**Observation.**")
        lines.append("```json")
        lines.append(json.dumps(extra.get("result"), indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _has_tool_error(trace: dict) -> bool:
    for e in trace.get("tool_trace") or []:
        if e.get("type") == "tool_result":
            result = e.get("result")
            if isinstance(result, dict) and "error" in result:
                return True
    return False


def _tool_call_count(trace: dict) -> int:
    return sum(1 for e in (trace.get("tool_trace") or []) if e.get("type") == "tool_call")


def _is_correct(trace: dict) -> bool:
    pred_positive = trace.get("risk_level") in POS_RISK
    truth_positive = trace.get("label") == "positive"
    return pred_positive == truth_positive


def select_traces(seed: int) -> list[dict]:
    """Implements the stratified selection rule documented in ../traces/SELECTION.md."""
    rng = random.Random(seed)
    all_traces = list(load_all_traces())

    by_cell = defaultdict(list)          # (hazard, model, outcome) -> [trace, ...]
    by_hazard_model = defaultdict(list)  # (hazard, model) -> [trace, ...]
    for t in all_traces:
        outcome = "correct" if _is_correct(t) else "incorrect"
        by_cell[(t["disaster_type"], t["model_id"], outcome)].append(t)
        by_hazard_model[(t["disaster_type"], t["model_id"])].append(t)

    selected: list[dict] = []
    selected_ids = set()

    def _pick(pool: list[dict], n: int):
        pool = [t for t in pool if id(t) not in selected_ids]
        rng.shuffle(pool)
        for t in pool[:n]:
            selected.append(t)
            selected_ids.add(id(t))

    # 12 cells: hazard x 3 backbones x {correct, incorrect} -> 2 each = 24
    for hazard in HAZARDS:
        for model in MODELS:
            for outcome in ("correct", "incorrect"):
                _pick(by_cell.get((hazard, model, outcome), []), 2)

    # 3 tool-failure examples, one per backbone (search both hazards)
    for model in MODELS:
        pool = [t for h in HAZARDS for t in by_hazard_model.get((h, model), []) if _has_tool_error(t)]
        _pick(pool, 1)

    # 3 correct-but-incomplete-coverage examples, one per backbone: correct outcome,
    # tool-call count below the median for that (hazard, model) cross-section.
    for model in MODELS:
        pool = []
        for hazard in HAZARDS:
            cell = by_hazard_model.get((hazard, model), [])
            if not cell:
                continue
            median_calls = statistics.median(_tool_call_count(t) for t in cell)
            pool.extend(
                t for t in cell
                if _is_correct(t) and _tool_call_count(t) < median_calls
            )
        _pick(pool, 1)

    return selected


def load_all_traces():
    with gzip.open(TRACES_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _safe_filename(trace: dict) -> str:
    outcome = "correct" if _is_correct(trace) else "incorrect"
    if _has_tool_error(trace):
        outcome = "toolfail"
    return (
        f"{trace['disaster_type']}_{trace['model_id']}_T{trace['lead_time_days']}"
        f"_{outcome}_{trace['event_id'][:8]}.md"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render released agent traces as readable Markdown transcripts."
    )
    parser.add_argument("--event-id", help="Event id to render (single-trace mode)")
    parser.add_argument("--model",
                         help="Model id, e.g. gemini-3.1-flash-lite, gpt-4.1-mini, ministral-3-14b")
    parser.add_argument("--lead", type=int, help="Lead time in days, e.g. 1, 3, or 7")
    parser.add_argument("--run", type=int, default=None,
                         help="Run number to disambiguate if multiple runs exist (optional)")
    parser.add_argument("--out", type=str, default=None,
                         help="Output .md file (single-trace mode) or directory (--select mode)")
    parser.add_argument("--select", action="store_true",
                         help="Batch mode: run the stratified selection in ../traces/SELECTION.md")
    parser.add_argument("--seed", type=int, default=20260901,
                         help="Random seed for --select (default: 20260901, per SELECTION.md)")
    args = parser.parse_args()

    if args.select:
        out_dir = Path(args.out) if args.out else (SCRIPT_DIR.parent / "traces" / "highlighted")
        out_dir.mkdir(parents=True, exist_ok=True)
        traces = select_traces(args.seed)
        print(f"Selected {len(traces)} traces (seed={args.seed})", file=sys.stderr)
        for t in traces:
            event = load_event_metadata(t.get("disaster_type", ""), t["event_id"])
            markdown = render_markdown(t, event)
            fname = _safe_filename(t)
            (out_dir / fname).write_text(markdown, encoding="utf-8")
            print(f"  wrote {fname}", file=sys.stderr)
        return 0

    if not (args.event_id and args.model and args.lead is not None):
        parser.error("--event-id/--model/--lead are required unless --select is given")

    trace = find_trace(args.event_id, args.model, args.lead, run_number=args.run)
    if trace is None:
        print(
            f"ERROR: no trace found for event_id={args.event_id!r} "
            f"model={args.model!r} lead={args.lead}"
            + (f" run={args.run}" if args.run is not None else ""),
            file=sys.stderr,
        )
        return 1

    event = load_event_metadata(trace.get("disaster_type", ""), args.event_id)
    markdown = render_markdown(trace, event)

    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(markdown)

    return 0


if __name__ == "__main__":
    sys.exit(main())
