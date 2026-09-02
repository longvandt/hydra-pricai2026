# Efficiency: latency, tool calls, and failure rate

Computed directly from `../traces/raw/traces.jsonl.gz` by `compute_efficiency.py` — reproduce with `python src/compute_efficiency.py`. No cost column is included: `total_tokens` is reported per run below (combined input+output, no split recorded in the trace), but this release ships no per-token price sheet, since backbone pricing changes over time and a number baked in here would go stale silently. Multiply the reported mean tokens by your own current rate to estimate cost.

| Hazard | Model | n | Latency median (s) | Latency p90 (s) | Tool calls (mean) | Tool-call failure rate | Tokens (mean) |
|---|---|---:|---:|---:|---:|---:|---:|
| flood | Gemini 3.1 Flash Lite | 3000 | 22.82 | 29.34 | 9.21 | 0.08% | 9909 |
| flood | GPT-4.1 mini | 3000 | 29.09 | 40.67 | 10.91 | 0.02% | 9493 |
| flood | Ministral 3 14B | 3000 | 44.66 | 73.81 | 10.59 | 0.06% | 12201 |
| landslide | Gemini 3.1 Flash Lite | 3000 | 14.62 | 17.53 | 10.18 | 3.37% | 6744 |
| landslide | GPT-4.1 mini | 3000 | 21.62 | 28.62 | 10.00 | 0.04% | 5844 |
| landslide | Ministral 3 14B | 3000 | 33.06 | 70.75 | 9.24 | 4.97% | 7448 |
