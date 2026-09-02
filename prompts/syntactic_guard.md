# Syntactic guard

Hydra's base system prompts (`system_prompt_flood.md`, `system_prompt_landslide.md`) already end with a structured output template (`### Final Risk Assessment` / `Risk Level: **LEVEL**`). For backbones that drift from this format under native tool-calling, one additional line is appended to the base prompt — verbatim, unchanged, no other text added:

```
Return your final risk assessment as: RISK LEVEL: <LEVEL>
```

## Which of the three reported backbones get it

| Backbone | Adapter prompt appended? |
|---|---|
| Gemini 3.1 Flash Lite | No |
| GPT-4.1 mini | No |
| Ministral 3 14B | **Yes** |

This is a per-backbone formatting hint only — it does not add, remove, or alter any methodology, threshold, or reasoning instruction. The base prompt text is identical across all three backbones; this line is the only backbone-specific addition, and it exists purely to stabilize the regex-based risk-level parser (`_extract_risk_level` in `src/agent/agent.py`) against models more prone to format drift under function-calling.
