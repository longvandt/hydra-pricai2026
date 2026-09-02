# Raw trace schema

`traces.jsonl.gz` contains one JSON object per line, one line per evaluated event — 18,000 lines total (2 hazards × 3 backbones × 3 lead times × 1,000 events per cell, one verified run per cell; see `../../data/predictions/` for which run was selected per cell).

## Top-level fields

| Field | Type | Description |
|---|---|---|
| `disaster_type` | string | `"flood"` or `"landslide"` |
| `event_id` | string (UUID) | Matches `id` in `../../data/hydra_bench/{flood,landslide}_events.json` |
| `label` | string | `"positive"` or `"negative"` — ground truth |
| `model_id` | string | `gemini-3.1-flash-lite` / `gpt-4.1-mini` / `ministral-3-14b` |
| `lead_time_days` | int | 1, 3, or 7 |
| `run_number` | int | Which of the 3 evaluation runs this record is from |
| `risk_level` | string | Parsed final risk level: `NONE / LOW / MEDIUM / HIGH / CRITICAL`, or `ERROR` / `UNKNOWN` on a failed run |
| `reasoning` | string | The agent's final synthesized assessment text (the "Final Risk Assessment" / "audit trail" block) |
| `tool_trace` | list | The step-by-step trace — see below |
| `total_tokens` | int | Total tokens for the run (input + output combined; no split is recorded) |
| `latency_seconds` | float | Wall-clock time for the full run |

## `tool_trace` entries

Each entry has a `"type"` field:

- **`tool_call`** — `{"type": "tool_call", "tool": "<name>", "args": {...}}`
- **`tool_result`** — `{"type": "tool_result", "tool": "<name>", "result": {...}}`
- **`thought`** — `{"type": "thought", "text": "<one-sentence rationale>"}`, appearing immediately before the `tool_call` it explains, when present.

Every trace captures in full: every tool call, every tool result, and the agent's complete final reasoning-and-conclusion text — the "REASONING AUDIT TRAIL" the system prompt itself describes as "the primary scientific output... must allow a domain expert to independently verify or dispute the assessment without re-running the tools." Running `../../src/agent/` live (see the top-level README's "Live execution" section) also produces `thought` entries per step, since the trace extractor there captures them.
