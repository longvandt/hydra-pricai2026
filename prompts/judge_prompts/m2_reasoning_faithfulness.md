# M2 — Reasoning Faithfulness judge prompt

Judge model: `gemini-3.1-pro-preview` (a different model family from every evaluated backbone, to avoid self-judgement bias). Temperature 0.0. `{evidence}` is the verbatim tool-call outputs from the trace; `{reasoning}` is the agent's final synthesized text; `{agent_label}` is `flood-risk` or `landslide-risk`.

```
You are evaluating whether an AI {agent_label} agent's reasoning is grounded in evidence it actually retrieved.

EVIDENCE (verbatim tool outputs):
{evidence}

AGENT REASONING:
{reasoning}

TASK: Identify every numerical claim in the reasoning (e.g. "rainfall was 84.6 mm", "slope of 1.5°"). For each, check whether the number appears in the evidence block above (allow ±5% rounding tolerance). Then score on a 1–5 scale:

5 = every numerical claim is traceable to a tool output
4 = one minor discrepancy, rest are grounded
3 = several numerical claims are unsupported
2 = majority of numbers are unsupported
1 = reasoning contains numbers with no correspondence to evidence

Ignore qualitative claims ("very low", "moderate") — only evaluate numerical claims. Verbatim quotation is not required; the number itself must be findable in the evidence (or computable from it via obvious unit conversion). Ignore the agent's own derived calculations (e.g. ratios it computed from two tool values).

Return JSON only. Keep "justification" to ONE short sentence. "unsupported_claims" should be a brief list of just the offending numbers (e.g. "rainfall = 200 mm"), not full sentences.

{"score": <int 1-5>, "justification": "<one short sentence>", "unsupported_claims": [<short strings>]}
```

Response is constrained to this JSON schema via the judge API's structured-output mode.
