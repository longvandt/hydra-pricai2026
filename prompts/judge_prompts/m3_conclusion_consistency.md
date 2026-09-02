# M3 — Conclusion Consistency judge prompt

Judge model: `gemini-3.1-pro-preview`, temperature 0.0. `{domain_primer}` is one of the two disaster-specific blocks below — background framing only, not a set of hard thresholds the judge is meant to apply.

```
You are evaluating whether an AI {agent_label} agent's conclusion logically follows from its evidence and reasoning.

DOMAIN PRIMER (background, not specific thresholds):
{domain_primer}

EVIDENCE (verbatim tool outputs):
{evidence}

AGENT REASONING:
{reasoning}

AGENT CONCLUSION: {risk_level}

TASK: Given the evidence and the agent's own reasoning, is the conclusion a logical inference? Score on a 1–5 scale:

5 = conclusion is the most defensible level given evidence and reasoning
4 = conclusion is one level off but defensible (borderline case)
3 = conclusion is plausible but not best-supported by the reasoning
2 = conclusion contradicts at least one major signal in the reasoning
1 = conclusion clearly contradicts the evidence and reasoning

DO NOT impose your own thresholds — judge by whether the *reasoning chain drives the conclusion*. If the agent's reasoning is internally consistent and points to the stated level, score high even if you might personally disagree.

Return JSON only. Keep "justification" to ONE short sentence.

{"score": <int 1-5>, "implied_level": "<NONE|LOW|MEDIUM|HIGH|CRITICAL>", "justification": "<one short sentence>"}
```

## Domain primers

**Flood** (`agent_label = "flood-risk"`):
```
- Flooding requires excess water (rainfall, river discharge, tide surge, or antecedent soil saturation) AND limited drainage (low elevation, flat slope, urban impervious surface, or proximity to river/coast).
- High antecedent moisture (API > ~40 mm or saturated soil) amplifies flood risk for any given rainfall.
- Steep terrain typically routes water away; very flat terrain accumulates.
- Risk levels are operational: NONE / LOW / MEDIUM / HIGH / CRITICAL. CRITICAL implies life-threatening conditions warranting evacuation.
```

**Landslide** (`agent_label = "landslide-risk"`):
```
- Rainfall-triggered shallow landslides require BOTH a rainfall trigger (intense short-duration or sustained multi-day) AND geomorphic predisposition (steep slope, weathered overburden, drainage concentration).
- Antecedent saturation (high API, saturated soil) reduces the rainfall amount needed for failure; this is the Do & Yin (2018) conditional-threshold relationship.
- Slope angle is the primary geomorphic factor: rainfall-triggered failure typically requires ≥ 15–20°; below ~10° the terrain is generally too flat for shallow failure regardless of rainfall.
- Proximity to mountain roads and weathered residual soils amplifies risk.
- Risk levels are operational: NONE / LOW / MEDIUM / HIGH / CRITICAL. CRITICAL implies life-threatening mass-movement events warranting evacuation.
```
