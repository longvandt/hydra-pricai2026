"""
Recompute every quantitative result in the paper from released artifacts —
no database, no network, no API keys.

Three independent computations, each reading only local files:

1. Precision / Recall / Specificity / F1 per (hazard, model, lead) cell, from
   ../data/hydra_bench/{flood,landslide}_events.json (ground truth) and
   ../data/predictions/{flood,landslide}_{model}_T{lead}.json (predictions).
   Metric definitions mirror `scripts/compute_flood_eval_metrics.py::cell_metrics()`
   in the source project: POS_RISK = {"MEDIUM","HIGH","CRITICAL"} -> positive,
   everything else -> negative, then the standard 2x2-confusion-matrix formulas.
   Only ONE run is released per cell (the paper reports mean +/- std across 3),
   so this is always a single point estimate, never a mean/std.

2. Tool Coverage Rate (TCR) per (hazard, model, lead, label), from
   ../traces/raw/traces.jsonl.gz. Mirrors `scripts/compute_tool_coverage_rate.py`
   exactly: coverage = % of events where every tool in that hazard's CORE_TOOLS
   set was called at least once. Unlike (1), TCR in the paper (Table 6) was
   computed from a single canonical run per cell too, so this reproduces it
   exactly, not just within a distributional range.

3. M2 (Reasoning Faithfulness) / M3 (Conclusion Consistency) LLM-judge scores,
   from ../data/judge_scores/{flood,landslide}_judge_scores.csv — the actual
   judged results (144 traces per hazard, 48 per backbone) that produced the
   paper's Table 7, not just the judge prompts. Aggregated as mean +/- std per
   (hazard, model), reproducing Table 7 exactly.

Usage:
  python evaluate_metrics.py                 # print all three tables
  python evaluate_metrics.py --check          # also check every table above
                                               # against the paper's reported
                                               # values

--check does NOT verify that the P/R/Specificity/F1 point estimate reproduces
the paper's mean exactly (that would require re-running all 3 seeds, which
this release does not ship) — it checks that the point estimate falls within
[mean - 2*std, mean + 2*std] of the paper's reported range. TCR and M2/M3,
by contrast, are checked for an exact match, since both were computed from
the same single canonical run / same judged sample that produced the paper's
Table 6 and Table 7.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from sklearn.metrics import precision_score, recall_score, f1_score, confusion_matrix
    _HAVE_SKLEARN = True
except ImportError:
    _HAVE_SKLEARN = False

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"
BENCH_DIR = DATA_DIR / "hydra_bench"
PRED_DIR = DATA_DIR / "predictions"
JUDGE_DIR = DATA_DIR / "judge_scores"
TRACES_PATH = SCRIPT_DIR.parent / "traces" / "raw" / "traces.jsonl.gz"

HAZARDS = ["flood", "landslide"]
MODELS = ["gemini-3.1-flash-lite", "gpt-4.1-mini", "ministral-3-14b"]
MODEL_LABEL = {
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
    "gpt-4.1-mini": "GPT-4.1 mini",
    "ministral-3-14b": "Ministral 3B",
}
LEADS = [1, 3, 7]

POS_RISK = {"MEDIUM", "HIGH", "CRITICAL"}


# ============================================================================
# Paper-reported mean% +/- std% per (hazard, model, lead) cell, for --check.
# Values are (precision, recall, specificity, f1), each a (mean, std) pair
# in percent, taken verbatim from the paper.
# ============================================================================

FLOOD_EXPECTED = {
    ("gemini-3.1-flash-lite", 1): {"precision": (85.3, 0.5), "recall": (88.9, 2.1), "specificity": (84.7, 0.8), "f1": (87.1, 0.9)},
    ("gemini-3.1-flash-lite", 3): {"precision": (83.0, 1.4), "recall": (89.2, 1.4), "specificity": (81.7, 2.0), "f1": (86.0, 0.5)},
    ("gemini-3.1-flash-lite", 7): {"precision": (79.4, 0.6), "recall": (77.7, 0.2), "specificity": (79.9, 0.8), "f1": (78.6, 0.3)},
    ("gpt-4.1-mini", 1): {"precision": (67.4, 0.2), "recall": (95.8, 0.5), "specificity": (53.7, 0.1), "f1": (79.1, 0.3)},
    ("gpt-4.1-mini", 3): {"precision": (67.4, 0.3), "recall": (96.6, 0.5), "specificity": (53.3, 0.4), "f1": (79.4, 0.4)},
    ("gpt-4.1-mini", 7): {"precision": (65.8, 0.2), "recall": (94.2, 0.7), "specificity": (51.1, 0.3), "f1": (77.5, 0.3)},
    ("ministral-3-14b", 1): {"precision": (66.1, 0.8), "recall": (97.3, 0.6), "specificity": (50.1, 2.1), "f1": (78.7, 0.4)},
    ("ministral-3-14b", 3): {"precision": (64.4, 0.5), "recall": (96.4, 1.0), "specificity": (46.7, 1.5), "f1": (77.2, 0.2)},
    ("ministral-3-14b", 7): {"precision": (62.6, 0.4), "recall": (96.5, 0.7), "specificity": (42.3, 1.1), "f1": (75.9, 0.4)},
}

# From docs/paper_experiments_final.md, Table 5. Predictive performance on
# the landslide evaluation set (mean% +/- std% across runs).
LANDSLIDE_EXPECTED = {
    ("gemini-3.1-flash-lite", 1): {"precision": (83.0, 0.2), "recall": (86.1, 0.1), "specificity": (82.4, 0.2), "f1": (84.6, 0.1)},
    ("gemini-3.1-flash-lite", 3): {"precision": (78.1, 0.3), "recall": (92.0, 0.8), "specificity": (74.2, 0.5), "f1": (84.5, 0.3)},
    ("gemini-3.1-flash-lite", 7): {"precision": (72.7, 0.7), "recall": (97.3, 0.6), "specificity": (63.5, 1.6), "f1": (83.2, 0.3)},
    ("gpt-4.1-mini", 1): {"precision": (82.1, 1.1), "recall": (85.9, 4.2), "specificity": (81.3, 0.6), "f1": (84.0, 2.5)},
    ("gpt-4.1-mini", 3): {"precision": (79.7, 0.5), "recall": (90.7, 3.5), "specificity": (76.9, 0.2), "f1": (84.8, 1.8)},
    ("gpt-4.1-mini", 7): {"precision": (74.4, 0.7), "recall": (95.7, 2.2), "specificity": (67.1, 0.4), "f1": (83.7, 1.3)},
    ("ministral-3-14b", 1): {"precision": (63.4, 1.5), "recall": (97.4, 1.5), "specificity": (44.2, 2.5), "f1": (76.8, 1.5)},
    ("ministral-3-14b", 3): {"precision": (61.4, 1.0), "recall": (97.9, 0.6), "specificity": (38.4, 2.1), "f1": (75.4, 0.9)},
    ("ministral-3-14b", 7): {"precision": (59.3, 0.5), "recall": (98.9, 0.3), "specificity": (32.2, 1.1), "f1": (74.2, 0.5)},
}

EXPECTED_RANGES = {"flood": FLOOD_EXPECTED, "landslide": LANDSLIDE_EXPECTED}


# ============================================================================
# Tool Coverage Rate (TCR) — mirrors scripts/compute_tool_coverage_rate.py
# exactly: CORE tools are the minimum set the system prompt requires before a
# non-trivial risk classification is supportable. Coverage = % of events where
# every core tool was called at least once, computed per (model, lead, label).
# ============================================================================

FLOOD_CORE_TOOLS = frozenset({
    "get_elevation_slope", "get_historical_rainfall",
    "get_soil_moisture", "get_antecedent_precipitation_index",
})
LANDSLIDE_CORE_TOOLS = frozenset({
    "get_elevation_slope", "get_historical_rainfall", "get_soil_moisture",
    "get_antecedent_precipitation_index", "calculate_doyin_threshold",
})
CORE_TOOLS = {"flood": FLOOD_CORE_TOOLS, "landslide": LANDSLIDE_CORE_TOOLS}

# Paper Table 6, verbatim: (hazard, model) -> [T1pos, T3pos, T7pos, T1neg, T3neg, T7neg] in percent.
PAPER_TCR = {
    ("flood", "gemini-3.1-flash-lite"): [99.8, 99.0, 99.8, 96.2, 96.6, 95.4],
    ("flood", "gpt-4.1-mini"):          [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
    ("flood", "ministral-3-14b"):       [98.2, 95.0, 99.4, 89.2, 90.8, 90.4],
    ("landslide", "gemini-3.1-flash-lite"): [100.0, 99.0, 93.8, 99.8, 95.2, 90.6],
    ("landslide", "gpt-4.1-mini"):          [100.0, 99.8, 100.0, 100.0, 100.0, 99.0],
    ("landslide", "ministral-3-14b"):       [11.4, 19.0, 22.2, 26.8, 29.6, 34.8],
}

# Paper Table 7, verbatim: (hazard, model) -> {"m2": (mean, std), "m3": (mean, std)}, n=48 each.
PAPER_M2M3 = {
    ("flood", "gemini-3.1-flash-lite"): {"m2": (4.65, 0.64), "m3": (4.90, 0.42)},
    ("flood", "gpt-4.1-mini"):          {"m2": (4.85, 0.50), "m3": (4.04, 1.47)},
    ("flood", "ministral-3-14b"):       {"m2": (4.38, 0.84), "m3": (3.35, 1.71)},
    ("landslide", "gemini-3.1-flash-lite"): {"m2": (4.35, 0.67), "m3": (4.81, 0.64)},
    ("landslide", "gpt-4.1-mini"):          {"m2": (3.54, 0.74), "m3": (3.85, 1.29)},
    ("landslide", "ministral-3-14b"):       {"m2": (4.15, 0.90), "m3": (4.15, 1.47)},
}


# ============================================================================
# Data loading
# ============================================================================

def load_ground_truth(hazard: str) -> Dict[str, dict]:
    """Load ../data/hydra_bench/{hazard}_events.json, keyed by event id."""
    path = BENCH_DIR / f"{hazard}_events.json"
    events = json.loads(path.read_text(encoding="utf-8"))
    return {e["id"]: e for e in events}


def load_predictions(hazard: str, model: str, lead: int) -> List[dict]:
    """Load ../data/predictions/{hazard}_{model}_T{lead}.json."""
    path = PRED_DIR / f"{hazard}_{model}_T{lead}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================================
# Metric computation (mirrors scripts/compute_flood_eval_metrics.py::cell_metrics)
# ============================================================================

def cell_metrics(records: List[dict]) -> Optional[dict]:
    """Compute precision/recall/specificity/F1 for one (hazard, model, lead) cell.

    records: list of {"label": "positive"|"negative", "risk_level": "HIGH", ...}
    """
    y_true, y_pred = [], []
    for r in records:
        y_true.append(1 if r["label"] == "positive" else 0)
        risk = r.get("risk_level")
        y_pred.append(1 if risk in POS_RISK else 0)

    if not y_true:
        return None

    if _HAVE_SKLEARN:
        tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
        precision = precision_score(y_true, y_pred, zero_division=0)
        recall = recall_score(y_true, y_pred, zero_division=0)
        f1 = f1_score(y_true, y_pred, zero_division=0)
    else:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
        tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0

    return {
        "n": len(y_true),
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": f1,
        "tp": int(tp), "tn": int(tn), "fp": int(fp), "fn": int(fn),
    }


def compute_all_cells() -> Dict[Tuple[str, str, int], dict]:
    """Compute metrics for every (hazard, model, lead) cell from the released files."""
    cells: Dict[Tuple[str, str, int], dict] = {}
    for hazard in HAZARDS:
        ground_truth = load_ground_truth(hazard)
        for model in MODELS:
            for lead in LEADS:
                preds = load_predictions(hazard, model, lead)
                if not preds:
                    continue
                # Cross-check predictions against ground truth where possible
                # (predictions already embed "label", so this is a consistency
                # check, not a requirement for computing the metrics).
                records = []
                for p in preds:
                    eid = p.get("event_id")
                    label = p.get("label")
                    if eid in ground_truth and label != ground_truth[eid].get("label"):
                        print(
                            f"WARNING: label mismatch for {hazard}/{model}/T{lead} "
                            f"event {eid}: prediction says {label!r}, "
                            f"ground truth says {ground_truth[eid].get('label')!r}",
                            file=sys.stderr,
                        )
                    records.append(p)
                m = cell_metrics(records)
                if m is not None:
                    cells[(hazard, model, lead)] = m
    return cells


# ============================================================================
# TCR computation (from ../traces/raw/traces.jsonl.gz)
# ============================================================================

def load_traces():
    with gzip.open(TRACES_PATH, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _called_tools(tool_trace) -> frozenset:
    if not tool_trace:
        return frozenset()
    return frozenset(
        e.get("tool") for e in tool_trace
        if isinstance(e, dict) and e.get("type") == "tool_call" and e.get("tool")
    )


def compute_tcr() -> Dict[Tuple[str, str], List[float]]:
    """Returns {(hazard, model): [T1pos, T3pos, T7pos, T1neg, T3neg, T7neg]} in percent."""
    if not TRACES_PATH.exists():
        return {}
    by_cell: Dict[Tuple[str, str, int, str], List[frozenset]] = defaultdict(list)
    for t in load_traces():
        key = (t["disaster_type"], t["model_id"], t["lead_time_days"], t["label"])
        by_cell[key].append(_called_tools(t.get("tool_trace")))

    result = {}
    for hazard in HAZARDS:
        core = CORE_TOOLS[hazard]
        for model in MODELS:
            row = []
            for label in ("positive", "negative"):
                for lead in LEADS:
                    tools_lists = by_cell.get((hazard, model, lead, label), [])
                    if not tools_lists:
                        row.append(float("nan"))
                        continue
                    covered = sum(1 for tools in tools_lists if core.issubset(tools))
                    row.append(100.0 * covered / len(tools_lists))
            # by_cell iterated label-outer, lead-inner above -> reorder to
            # [T1pos,T3pos,T7pos,T1neg,T3neg,T7neg] to match PAPER_TCR layout
            pos, neg = row[:3], row[3:]
            result[(hazard, model)] = pos + neg
    return result


# ============================================================================
# M2/M3 LLM-judge score aggregation (from ../data/judge_scores/*.csv)
# ============================================================================

def load_judge_scores(hazard: str) -> Dict[str, dict]:
    """Returns {model: {"m2": [scores...], "m3": [scores...]}}."""
    path = JUDGE_DIR / f"{hazard}_judge_scores.csv"
    if not path.exists():
        return {}
    by_model: Dict[str, dict] = defaultdict(lambda: {"m2": [], "m3": []})
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_model[row["model_id"]]["m2"].append(float(row["m2_score"]))
            by_model[row["model_id"]]["m3"].append(float(row["m3_score"]))
    return dict(by_model)


def compute_judge_aggregates() -> Dict[Tuple[str, str], dict]:
    """Returns {(hazard, model): {"m2": (mean, std, n), "m3": (mean, std, n)}}."""
    result = {}
    for hazard in HAZARDS:
        scores = load_judge_scores(hazard)
        for model, s in scores.items():
            result[(hazard, model)] = {
                "m2": (statistics.mean(s["m2"]), statistics.stdev(s["m2"]), len(s["m2"])),
                "m3": (statistics.mean(s["m3"]), statistics.stdev(s["m3"]), len(s["m3"])),
            }
    return result


# ============================================================================
# Reporting
# ============================================================================

def print_console_table(cells: Dict[Tuple[str, str, int], dict]) -> None:
    print("=" * 92)
    print("  Point-estimate metrics recomputed from released predictions (1 run per cell)")
    print("=" * 92)
    print(f"  {'Hazard':<10}  {'Model':<22}  {'Lead':>4}  {'n':>5}  "
          f"{'Precision':>10}  {'Recall':>10}  {'Specificity':>12}  {'F1':>10}")
    print("  " + "-" * 90)
    for hazard in HAZARDS:
        for model in MODELS:
            for lead in LEADS:
                m = cells.get((hazard, model, lead))
                if m is None:
                    continue
                print(
                    f"  {hazard:<10}  {MODEL_LABEL[model]:<22}  T-{lead:<2}  {m['n']:>5}  "
                    f"{m['precision']*100:>9.1f}%  {m['recall']*100:>9.1f}%  "
                    f"{m['specificity']*100:>11.1f}%  {m['f1']*100:>9.1f}%"
                )
    print()


def print_markdown_table(cells: Dict[Tuple[str, str, int], dict]) -> None:
    print("=" * 92)
    print("  Markdown table (point estimates -- paste into paper appendix / README)")
    print("=" * 92)
    print()
    for hazard in HAZARDS:
        print(f"**{hazard.capitalize()}** (single released run per cell; no mean/std)")
        print()
        print("| Model | Lead | n | Precision | Recall | Specificity | F1 |")
        print("|---|---|---:|---:|---:|---:|---:|")
        for model in MODELS:
            for lead in LEADS:
                m = cells.get((hazard, model, lead))
                if m is None:
                    continue
                print(
                    f"| {MODEL_LABEL[model]} | T-{lead} | {m['n']} | "
                    f"{m['precision']*100:.1f}% | {m['recall']*100:.1f}% | "
                    f"{m['specificity']*100:.1f}% | {m['f1']*100:.1f}% |"
                )
        print()


def print_tcr_table(tcr: Dict[Tuple[str, str], List[float]]) -> None:
    print("=" * 96)
    print("  Tool Coverage Rate (%) -- from ../traces/raw/traces.jsonl.gz, core-tool sets")
    print("  defined in FLOOD_CORE_TOOLS / LANDSLIDE_CORE_TOOLS above")
    print("=" * 96)
    print(f"  {'Disaster':<10}  {'Model':<22}  {'T-1 Pos':>8}  {'T-3 Pos':>8}  {'T-7 Pos':>8}  "
          f"{'T-1 Neg':>8}  {'T-3 Neg':>8}  {'T-7 Neg':>8}")
    for hazard in HAZARDS:
        for model in MODELS:
            row = tcr.get((hazard, model))
            if row is None:
                continue
            cells = "  ".join(f"{v:7.1f}%" for v in row)
            print(f"  {hazard:<10}  {MODEL_LABEL[model]:<22}  {cells}")
    print()


def print_judge_table(judge: Dict[Tuple[str, str], dict]) -> None:
    print("=" * 92)
    print("  LLM-judge interpretability scores -- from ../data/judge_scores/*.csv")
    print("  (Judge: gemini-3.1-pro-preview; n=48 traces per row)")
    print("=" * 92)
    print(f"  {'Disaster':<10}  {'Model':<22}  {'M2 Faithfulness':>18}  {'M3 Consistency':>18}  {'n':>4}")
    for hazard in HAZARDS:
        for model in MODELS:
            j = judge.get((hazard, model))
            if j is None:
                continue
            m2_mean, m2_std, n = j["m2"]
            m3_mean, m3_std, _ = j["m3"]
            print(f"  {hazard:<10}  {MODEL_LABEL[model]:<22}  "
                  f"{m2_mean:6.2f} +/- {m2_std:<6.2f}  {m3_mean:6.2f} +/- {m3_std:<6.2f}  {n:>4}")
    print()


# ============================================================================
# --check: point estimate within [mean - 2*std, mean + 2*std] of paper range
# ============================================================================

def run_check(cells: Dict[Tuple[str, str, int], dict]) -> bool:
    print("=" * 92)
    print("  --check: is the released point estimate within [mean - 2*std, mean + 2*std]")
    print("  of the paper's reported mean +/- std for that cell?")
    print("  (This does NOT reproduce the paper's mean/std -- only one run is released")
    print("   per cell here, vs. n=3 in the paper.)")
    print("=" * 92)

    all_pass = True
    for hazard in HAZARDS:
        expected = EXPECTED_RANGES[hazard]
        for model in MODELS:
            for lead in LEADS:
                key = (model, lead)
                if key not in expected:
                    continue
                m = cells.get((hazard, model, lead))
                if m is None:
                    print(f"  {hazard:<10} {MODEL_LABEL[model]:<22} T-{lead}: "
                          f"NO DATA (prediction file missing) -- FAIL")
                    all_pass = False
                    continue

                cell_pass = True
                detail = []
                for metric_name in ["precision", "recall", "specificity", "f1"]:
                    mean, std = expected[key][metric_name]
                    lo, hi = mean - 2 * std, mean + 2 * std
                    point_pct = m[metric_name] * 100
                    ok = lo <= point_pct <= hi
                    cell_pass = cell_pass and ok
                    detail.append(
                        f"{metric_name}={point_pct:.1f}% "
                        f"[{lo:.1f},{hi:.1f}] {'OK' if ok else 'OUT'}"
                    )

                status = "PASS" if cell_pass else "FAIL"
                all_pass = all_pass and cell_pass
                print(f"  {hazard:<10} {MODEL_LABEL[model]:<22} T-{lead}: {status}  "
                      f"({', '.join(detail)})")

    print()
    print("OVERALL:", "PASS" if all_pass else "FAIL")
    return all_pass


def check_tcr(tcr: Dict[Tuple[str, str], List[float]]) -> bool:
    """TCR is deterministic from the same released run used for Table 6 in the
    paper, so this checks for an exact match (within 0.1pp rounding), not a
    distributional range."""
    print("=" * 92)
    print("  --check (TCR): recomputed value vs. paper Table 6 (expect exact match)")
    print("=" * 92)
    all_pass = True
    for hazard in HAZARDS:
        for model in MODELS:
            key = (hazard, model)
            paper = PAPER_TCR.get(key)
            computed = tcr.get(key)
            if paper is None or computed is None:
                continue
            deltas = [round(c - p, 1) for c, p in zip(computed, paper)]
            ok = all(abs(d) <= 0.1 for d in deltas)
            all_pass = all_pass and ok
            print(f"  {hazard:<10} {MODEL_LABEL[model]:<22}: {'PASS' if ok else 'FAIL'}  "
                  f"computed={['%.1f' % v for v in computed]}  paper={paper}")
    print()
    print("TCR CHECK:", "PASS" if all_pass else "FAIL")
    return all_pass


def check_judge(judge: Dict[Tuple[str, str], dict]) -> bool:
    """M2/M3 aggregates are deterministic from the same 144-trace judged sample
    reported in paper Table 7, so this also checks for an exact match."""
    print("=" * 92)
    print("  --check (M2/M3): recomputed mean+/-std vs. paper Table 7 (expect exact match)")
    print("=" * 92)
    all_pass = True
    for hazard in HAZARDS:
        for model in MODELS:
            key = (hazard, model)
            paper = PAPER_M2M3.get(key)
            computed = judge.get(key)
            if paper is None or computed is None:
                continue
            m2_ok = (abs(computed["m2"][0] - paper["m2"][0]) <= 0.01
                     and abs(computed["m2"][1] - paper["m2"][1]) <= 0.01)
            m3_ok = (abs(computed["m3"][0] - paper["m3"][0]) <= 0.01
                     and abs(computed["m3"][1] - paper["m3"][1]) <= 0.01)
            ok = m2_ok and m3_ok
            all_pass = all_pass and ok
            print(f"  {hazard:<10} {MODEL_LABEL[model]:<22}: {'PASS' if ok else 'FAIL'}  "
                  f"m2={computed['m2'][0]:.2f}+/-{computed['m2'][1]:.2f} (paper {paper['m2'][0]}+/-{paper['m2'][1]})  "
                  f"m3={computed['m3'][0]:.2f}+/-{computed['m3'][1]:.2f} (paper {paper['m3'][0]}+/-{paper['m3'][1]})")
    print()
    print("M2/M3 CHECK:", "PASS" if all_pass else "FAIL")
    return all_pass


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute precision/recall/specificity/F1, Tool Coverage Rate, and M2/M3 "
            "LLM-judge scores from released files -- no network, no API keys, no "
            "database. P/R/Specificity/F1 use one released run per cell (the paper "
            "reports mean +/- std across 3 runs), so those are a single point estimate. "
            "TCR and M2/M3 reproduce the paper's Table 6 and Table 7 exactly, since both "
            "come from a single canonical run / judged sample, same as what's released."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "For each cell, assert the recomputed point estimate falls within "
            "[mean - 2*std, mean + 2*std] of the paper's reported range. This checks "
            "consistency with the paper's reported distribution -- it does NOT verify "
            "exact reproduction of the paper's mean, since only 1 of the original 3 "
            "runs is released. Exits non-zero if any cell fails."
        ),
    )
    args = parser.parse_args()

    if not _HAVE_SKLEARN:
        print("NOTE: scikit-learn not available; using hand-rolled confusion-matrix math.",
              file=sys.stderr)

    cells = compute_all_cells()
    if not cells:
        print(f"ERROR: no prediction files found under {PRED_DIR}", file=sys.stderr)
        return 1

    print_console_table(cells)
    print_markdown_table(cells)

    tcr = compute_tcr()
    if tcr:
        print_tcr_table(tcr)

    judge = compute_judge_aggregates()
    if judge:
        print_judge_table(judge)

    if args.check:
        ok = run_check(cells)
        if tcr:
            ok = check_tcr(tcr) and ok
        if judge:
            ok = check_judge(judge) and ok
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
