# Highlighted trace selection

The traces in `highlighted/` are drawn from `../raw/traces.jsonl.gz` by a fixed rule, not selected by hand.

## Strata

Sampling is stratified over the cross product of:

- hazard: flood, landslide
- backbone: Gemini 3.1 Flash Lite, GPT-4.1 mini, Ministral 3 14B
- outcome: correct (predicted binary label matches ground truth), incorrect

That's 12 cells. Two traces are drawn uniformly at random from each cell, giving 24.

## Deliberate additions

Six further traces are added to cover cases random sampling under-represents:

- 3 traces where at least one tool call returned an error, one per backbone
- 3 traces where the assessment is correct but tool coverage is incomplete (fewer tool calls than the prompt's methodology prescribes for that terrain/routing branch), one per backbone

Each is drawn uniformly at random from the traces satisfying its condition, within whichever hazard has qualifying examples.

## Reproducing the selection

```bash
python src/render_traces.py --select --seed 20260901 --out traces/highlighted/
```

Random seed: 20260901. Lead time is not stratified; it's recorded in each rendered file's header.
