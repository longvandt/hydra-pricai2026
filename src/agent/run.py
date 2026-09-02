"""
CLI entry point for live execution — bring your own API keys.

    cd src
    python -m agent.run --lat 21.0278 --lon 105.8342 --date 2024-09-08 --lead 3 --hazard flood

Reads the relevant API key from the environment (see ../../.env.example — load a .env file
yourself, e.g. with `python-dotenv` or `export $(cat .env | xargs)`, before running this).
Results will differ from the released data: sampling is stochastic and upstream environmental
APIs are updated over time — see the top-level README's "Reproducibility" section.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agent.agent import run_historical_analysis
from agent.config import EXPERIMENT_MODELS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from render_traces import render_markdown_chronological


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Hydra live on one location/date.")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--date", required=True, help="Assessment date, YYYY-MM-DD")
    parser.add_argument("--hazard", choices=["flood", "landslide"], required=True)
    parser.add_argument("--lead", type=int, default=0, help="Lead time in days (0, 1, 3, or 7)")
    parser.add_argument(
        "--model", default="gemini-3.1-flash-lite", choices=list(EXPERIMENT_MODELS),
        help="Backbone to run",
    )
    parser.add_argument("--json", action="store_true", help="Print the raw result dict as JSON instead of Markdown")
    parser.add_argument("--out", type=str, default=None, help="Write Markdown to this file instead of stdout")
    args = parser.parse_args()

    model_cfg = EXPERIMENT_MODELS[args.model]
    api_key = os.environ.get(model_cfg["secret_key"])
    if not api_key:
        print(
            f"ERROR: {model_cfg['secret_key']} not set in the environment. "
            f"Copy .env.example to .env, fill it in, and load it before running this.",
            file=sys.stderr,
        )
        return 1

    event = {
        "geo_latitude": args.lat,
        "geo_longitude": args.lon,
        "event_date": args.date,
        "disaster_type": args.hazard,
    }

    result = run_historical_analysis(
        event=event, api_key=api_key, model_key=args.model, lead_time_days=args.lead,
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    trace = {
        "disaster_type": args.hazard,
        "event_id": f"live run ({args.lat}, {args.lon})",
        "label": "unknown — live run, no ground truth",
        "model_id": args.model,
        "lead_time_days": args.lead,
        "risk_level": result.get("risk_level"),
        "reasoning": result.get("reasoning"),
        "tool_trace": result.get("tool_trace"),
        "total_tokens": result.get("total_tokens"),
        "latency_seconds": result.get("latency_seconds"),
    }
    markdown = render_markdown_chronological(trace, event=None)

    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
