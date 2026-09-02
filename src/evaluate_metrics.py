"""
Recompute per-cell (hazard, model, lead) Precision / Recall / Specificity / F1
from the released prediction files — no database, no network, no API keys.

Reads:
  ../data/hydra_bench/{flood,landslide}_events.json      — ground truth events
  ../data/predictions/{flood,landslide}_{model}_T{lead}.json  — released predictions

Each prediction record already carries the ground-truth label alongside the
model's predicted risk_level:
  {"event_id": ..., "label": "positive"|"negative", "risk_level": "HIGH", ...}

Metric definitions mirror `scripts/compute_flood_eval_metrics.py::cell_metrics()`
in the source project:
  POS_RISK = {"MEDIUM", "HIGH", "CRITICAL"}  -> predicted positive
  everything else (NONE, LOW, ...)           -> predicted negative
  precision / recall / specificity / F1 computed from the resulting
  2x2 confusion matrix (labels=[negative=0, positive=1]).

IMPORTANT DIFFERENCE from the source script: the source project ran n=3
repetitions per (hazard, model, lead) cell and reported mean +/- std across
runs. This release ships only ONE run per cell, so this script reports a
single point estimate per cell -- there is no mean/std to compute here.

Usage:
  python evaluate_metrics.py                 # print metrics table
  python evaluate_metrics.py --check          # also check point estimates
                                               # against the paper's reported
                                               # mean +/- std ranges

--check does NOT verify that this run reproduces the paper's mean exactly
(that would require re-running all 3 seeds, which this release does not
ship). It only checks whether the single released point estimate falls
within [mean - 2*std, mean + 2*std] of the paper's reported range, as a
sanity check that the released run is consistent with the reported
distribution.
"""

from __future__ import annotations

import argparse
import json
import sys
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


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute precision/recall/specificity/F1 per (hazard, model, lead) cell "
            "from the released prediction files. No network access, no API keys, no "
            "database -- pure local JSON file reads. Only one run is released per cell "
            "(the paper reports mean +/- std across 3 runs), so this always reports a "
            "single point estimate, never a mean/std."
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

    if args.check:
        ok = run_check(cells)
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
