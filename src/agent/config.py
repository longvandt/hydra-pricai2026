"""
Minimal model registry for live execution — only the 3 backbones reported in the paper.

This is a scoped-down stand-in for the source project's config.py (which lists 8 backbones
across several exploratory/ablation runs not part of this release). secret_key names the
.env variable each provider reads its API key from — see ../../.env.example.
"""

EXPERIMENT_MODELS = {
    "gemini-3.1-flash-lite": {
        "provider": "google",
        "model_id": "gemini-3.1-flash-lite",
        "base_url": None,
        "secret_key": "GEMINI_API_KEY",
        "display_name": "Gemini 3.1 Flash Lite",
        "adapter_prompt": None,
    },
    "gpt-4.1-mini": {
        "provider": "openai",
        "model_id": "gpt-4.1-mini",
        "base_url": "https://api.openai.com/v1",
        "secret_key": "OPENAI_API_KEY",
        "display_name": "GPT-4.1 mini",
        "adapter_prompt": None,
    },
    "ministral-3-14b": {
        "provider": "openai_compatible",
        "model_id": "mistralai/ministral-14b-2512",
        "base_url": "https://openrouter.ai/api/v1",
        "secret_key": "OPENROUTER_API_KEY",
        "display_name": "Ministral 3 14B",
        "adapter_prompt": "Return your final risk assessment as: RISK LEVEL: <LEVEL>",
    },
}
