"""
LLM Client for the ReAct Disaster Agent.
Unified factory supporting Google Gemini and OpenAI-compatible providers
(GPT, Qwen via OpenRouter, Ministral via OpenRouter).
"""

from typing import Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI


def get_reasoning_llm(
    provider: str,
    api_key: str,
    model: str,
    base_url: Optional[str] = None,
    temperature: float = 0.1,
):
    """
    Unified LLM factory optimized for analytical reasoning (low temperature).

    Args:
        provider: 'google' for Gemini, 'openai' or 'openai_compatible' for OpenAI-compatible APIs
        api_key: API key for the provider
        model: Model ID (e.g. 'gemini-3-flash-preview', 'gpt-4.1-mini', 'qwen/qwen3-235b-a22b')
        base_url: Override base URL for OpenAI-compatible providers (OpenRouter, DashScope, etc.)
        temperature: Sampling temperature (default 0.1 = deterministic reasoning)

    Returns:
        LangChain chat model instance bound for tool use
    """
    if provider == "google":
        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            max_output_tokens=8192,
            google_api_key=api_key,
        )
    else:
        # openai / openai_compatible — works for GPT, Qwen via OpenRouter, Ministral via OpenRouter
        kwargs = dict(
            model=model,
            temperature=temperature,
            max_tokens=8192,
            api_key=api_key,
            timeout=45.0,
        )
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)
