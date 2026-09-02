"""
Computes latency, tool-call, and tool-failure statistics from the released raw traces.

No network access, no API keys — reads only ../traces/raw/traces.jsonl.gz.

Note on cost: total_tokens is available per run (combined input+output; no split is
recorded), but no per-token price sheet is included in this release, since backbone
pricing changes over time and any figure baked in here would go stale silently. To
estimate cost, multiply the reported mean total_tokens by your own current per-token
rate for each backbone.
"""

from __future__ import annotations

import gzip
import json
import statistics
from collections import defaultdict
from pathlib import Path

TRACE_PATH = Path(__file__).resolve().parent.parent / "traces" / "raw" / "traces.jsonl.gz"
MODEL_LABEL = {
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
    "gpt-4.1-mini": "GPT-4.1 mini",
    "ministral-3-14b": "Ministral 3 14B",
}


def load_traces():
    with gzip.open(TRACE_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def cell_stats(records: list[dict]) -> dict:
    latencies = [r["latency_seconds"] for r in records if r.get("latency_seconds") is not None]
    tokens = [r["total_tokens"] for r in records if r.get("total_tokens") is not None]
    tool_calls_per_run = []
    tool_call_total = 0
    tool_call_errors = 0

    for r in records:
        n_calls = 0
        for entry in r.get("tool_trace") or []:
            if entry["type"] == "tool_call":
                n_calls += 1
            elif entry["type"] == "tool_result":
                tool_call_total += 1
                result = entry.get("result")
                if isinstance(result, dict) and "error" in result:
                    tool_call_errors += 1
        tool_calls_per_run.append(n_calls)

    def pctl(values, p):
        if not values:
            return float("nan")
        s = sorted(values)
        idx = min(len(s) - 1, int(len(s) * p))
        return s[idx]

    return {
        "n": len(records),
        "latency_median": statistics.median(latencies) if latencies else float("nan"),
        "latency_p90": pctl(latencies, 0.90),
        "tool_calls_mean": statistics.mean(tool_calls_per_run) if tool_calls_per_run else float("nan"),
        "tool_calls_median": statistics.median(tool_calls_per_run) if tool_calls_per_run else float("nan"),
        "tool_failure_rate": (tool_call_errors / tool_call_total) if tool_call_total else 0.0,
        "tokens_mean": statistics.mean(tokens) if tokens else float("nan"),
    }


def main():
    by_cell = defaultdict(list)
    for r in load_traces():
        by_cell[(r["disaster_type"], r["model_id"])].append(r)

    rows = []
    for (hazard, model), records in sorted(by_cell.items()):
        s = cell_stats(records)
        rows.append((hazard, model, s))

    print(f"{'Hazard':<12}{'Model':<24}{'n':>6}{'Lat.median(s)':>15}{'Lat.p90(s)':>13}"
          f"{'ToolCalls.mean':>16}{'ToolFailRate':>14}{'Tokens.mean':>14}")
    for hazard, model, s in rows:
        print(f"{hazard:<12}{MODEL_LABEL.get(model, model):<24}{s['n']:>6}"
              f"{s['latency_median']:>15.2f}{s['latency_p90']:>13.2f}"
              f"{s['tool_calls_mean']:>16.2f}{s['tool_failure_rate']*100:>13.2f}%"
              f"{s['tokens_mean']:>14.0f}")

    md_path = Path(__file__).resolve().parent.parent / "docs" / "efficiency.md"
    with open(md_path, "w") as f:
        f.write("# Efficiency: latency, tool calls, and failure rate\n\n")
        f.write(
            "Computed directly from `../traces/raw/traces.jsonl.gz` by `compute_efficiency.py` "
            "— reproduce with `python src/compute_efficiency.py`. No cost column is included: "
            "`total_tokens` is reported per run below (combined input+output, no split recorded "
            "in the trace), but this release ships no per-token price sheet, since backbone "
            "pricing changes over time and a number baked in here would go stale silently. "
            "Multiply the reported mean tokens by your own current rate to estimate cost.\n\n"
        )
        f.write("| Hazard | Model | n | Latency median (s) | Latency p90 (s) | Tool calls (mean) | "
                "Tool-call failure rate | Tokens (mean) |\n")
        f.write("|---|---|---:|---:|---:|---:|---:|---:|\n")
        for hazard, model, s in rows:
            f.write(
                f"| {hazard} | {MODEL_LABEL.get(model, model)} | {s['n']} | "
                f"{s['latency_median']:.2f} | {s['latency_p90']:.2f} | "
                f"{s['tool_calls_mean']:.2f} | {s['tool_failure_rate']*100:.2f}% | "
                f"{s['tokens_mean']:.0f} |\n"
            )
    print(f"\nWrote {md_path}")


if __name__ == "__main__":
    main()
