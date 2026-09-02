# Hydra: Dynamic Hydrological Reasoning Agents for Disaster Forecasting

Code, benchmark, execution traces, and evaluation artifacts for the PRICAI 2026 paper.

**Paper:** Hydra: Dynamic Hydrological Reasoning Agents for Disaster Forecasting (PRICAI 2026)
**Authors:** Duy-Thanh-Long Van, Vinh-Tiep Nguyen, Tu-Anh Nguyen-Hoang, Ngan Luu-Thuy Nguyen

Hydra is a multi-hazard flood and landslide risk assessment framework in which a large
language model acts as a ReAct-style orchestrator over deterministic hydrological and
geotechnical tools. This repository contains everything required to inspect and verify the
results reported in the paper.

## Reproducibility

Hydra queries commercial LLM APIs and external environmental services whose contents change
over time. Live re-execution therefore does not reproduce our runs exactly. We release the
artifacts required to verify every number in the paper without any API access.

### 1. Recompute the reported metrics, no API keys required

`data/predictions/` contains per-event predictions for all three backbones and three lead
times, alongside the Hydra-Bench ground truth in `data/hydra_bench/`.

```bash
pip install -r requirements.txt
python src/evaluate_metrics.py
```

This recomputes precision, recall, specificity, and F1 per (backbone, lead-time) cell, plus
tool coverage rate, M2, and M3, from the raw per-event predictions. Pass `--check` to verify
the recomputed point estimates fall within the paper's reported mean ± σ ranges.

### 2. Full execution traces

`traces/raw/traces.jsonl.gz` contains the complete tool-call record for every evaluated
event: tool names, call arguments, raw tool responses, tool failures, and the agent's full
final reasoning-and-conclusion text. `traces/raw/README.md` documents the exact record schema.

### 3. Readable trace samples

`traces/highlighted/` renders a stratified sample of 30 traces as Markdown, viewable directly
in the browser. The set is stratified across hazard, backbone, and outcome, and includes
correct assessments, incorrect assessments, and runs where a tool call failed. The sampling
rule and random seed are in `traces/SELECTION.md`, so the selection is reproducible and not
curated by hand.

Start with these three:

- [`flood_gemini-3.1-flash-lite_T1_correct_d32733a1.md`](traces/highlighted/flood_gemini-3.1-flash-lite_T1_correct_d32733a1.md):
  a full successful chain, from rainfall retrieval through threshold comparison to risk level
- [`flood_ministral-3-14b_T1_incorrect_3e1037eb.md`](traces/highlighted/flood_ministral-3-14b_T1_incorrect_3e1037eb.md):
  an incorrect assessment
- [`landslide_ministral-3-14b_T1_toolfail_c0411f50.md`](traces/highlighted/landslide_ministral-3-14b_T1_toolfail_c0411f50.md):
  a tool-call failure and how the agent proceeded

### 4. Methodology, in full

- `prompts/` contains the complete system prompts for both hazards and the judge prompts used
  for M2 and M3. `prompts/README.md` states exactly what is shared across backbones and what
  is not.
- `docs/tools.md` documents each tool's signature, upstream data source, spatial and temporal
  resolution, and units.
- `docs/tool_failures.md` documents the failure taxonomy and how each class is handled.
- `docs/efficiency.md` reports latency, mean tool calls, and tool-failure rate per backbone
  and hazard, computed from the released traces.

### 5. Live execution (bring your own keys)

`src/` contains the orchestrator and the tool implementations. Copy `.env.example` to `.env`,
supply your own API keys, load it into your environment, then from `src/`:

```bash
cd src
python -m agent.run --lat 21.0278 --lon 105.8342 --date 2024-09-08 --lead 3 --hazard flood
```

Results will differ from ours: LLM sampling is stochastic, and the upstream environmental
services are updated over time.

`SUPABASE_URL`/`SUPABASE_KEY` and `GEE_PROJECT_ID` in `.env.example` are both optional — every
tool that can use them has a working fallback without them. See
`docs/optional_local_cache.md` if you want to set up the Supabase elevation/slope cache.

## Benchmark

Hydra-Bench covers 1,000 labelled location-date pairs per hazard for Vietnam in 2024, split
evenly between positives and negatives, with negatives comprising both cross-season (easy) and
temporal-proximity (hard) samples. `data/hydra_bench/CONSTRUCTION.md` documents the extraction
pipeline, the landslide scope criteria, and the two-tier negative sampling design.

**Source text is not redistributed.** Positives are derived from Vietnamese news reports. We
release the source URL and the extracted structured fields for each event, not the article
text.

### Known limitations of these artifacts

- Labels are news-derived and therefore subject to reporting bias toward severe and densely
  populated events. Negative labels indicate no recorded report, not verified absence.
- Rainfall over the forecast window in the released traces comes from ERA5-Land reanalysis
  used as a perfect-forecast proxy, so trace-level rainfall values are not what an operational
  forecast would have supplied at the cutoff date.
- M2 and M3 scores are LLM-judged, not expert-annotated. The judge prompts are released so
  that alternative judges or human annotation can be substituted.
- The landslide calculator (`calculate_doyin_threshold`) applies no numeric slope gate or
  regional adjustment at the calculator layer — that reasoning happens at the prompt level
  instead (see `prompts/system_prompt_landslide.md`).

## Licence

Code in `src/` is released under Apache-2.0 (see `LICENSE`). Benchmark data, prompts,
documentation, and traces are released under CC BY 4.0 (see `LICENSE-DATA`). Neither covers
the underlying news articles, which remain with their publishers.

## Citation

```bibtex
@inproceedings{van2026hydra,
  title     = {Hydra: Dynamic Hydrological Reasoning Agents for Disaster Forecasting},
  author    = {Van, Duy-Thanh-Long and Nguyen, Vinh-Tiep and Nguyen-Hoang, Tu-Anh and Nguyen, Ngan Luu-Thuy},
  year      = {2026}
}
```
