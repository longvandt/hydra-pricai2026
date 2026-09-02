# Prompts

This directory contains the full text of every prompt used to produce the results in the paper, plus the judge prompts used to compute the M2/M3 interpretability metrics (Table 3).

## What is shared across backbones, and what is not

All three evaluated backbones (Gemini 3.1 Flash Lite, GPT-4.1 mini, Ministral 3 14B) receive the **exact same base prompt** — `system_prompt_flood.md` or `system_prompt_landslide.md`. There is no per-backbone prompt engineering of the methodology itself: the terrain classification steps, the rainfall data gate, the physical-reasoning instructions, the calibration thresholds, and the risk-level definitions are identical across every backbone, every lead time, and every run.

The only backbone-specific addition is `syntactic_guard.md` — one line appended after the base prompt for Ministral 3 14B only, to stabilize its output-format parsing under native tool-calling. Gemini and GPT-4.1 mini receive no addition. This is a formatting hint, not a change to what the agent is asked to do or how it should reason — see `syntactic_guard.md` for the exact line and the rationale.

This separation is deliberate: it means any difference in predictive performance or reasoning quality between backbones (Table 4, Table 5, Table 3) reflects the backbone's own tool-use and reasoning capability, not different instructions being given to different models.

## The reasoning-narration line

Both system prompts include one line, placed once at the start of the methodology section: *"For every tool call below, first state in one sentence why you are calling it and what you expect to learn — then call it."* This asks the model to narrate its rationale at each step of evidence collection, in addition to the consolidated reasoning synthesis the prompt already requires afterward (Step 3/"REASON" in the methodology). `src/agent/agent.py`'s trace extractor captures this narration as a `thought` entry alongside each tool call — see `traces/raw/README.md` for the resulting trace schema.

## Judge prompts

`judge_prompts/m2_reasoning_faithfulness.md` and `judge_prompts/m3_conclusion_consistency.md` are the exact prompts sent to the judge model (`gemini-3.1-pro-preview`, temperature 0.0 — a different model family from every evaluated backbone) to produce Table 3's M2/M3 scores. Each is templated with the trace's own evidence and reasoning text; M3 additionally includes a short disaster-specific domain primer (background framing, not a set of thresholds the judge is told to apply mechanically).
