"""
Entry point for running historical disaster analysis on individual events.
Wraps the LangGraph agent and provides a clean interface for the UI.
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, Optional
from datetime import datetime, timedelta

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

from agent.config import EXPERIMENT_MODELS
from agent.graph import create_flood_agent, create_landslide_agent
from agent.llm_client import get_reasoning_llm

logger = logging.getLogger(__name__)


def _build_human_message(event: dict, lead_time_days: int = 0) -> str:
    """Build a structured prompt from an event record.

    Assessment Date is always event_date minus lead_time_days.
    For T-0, lead_time_days=0 so Assessment Date == event_date and forecast horizon is 0.
    event_date is never exposed to the agent to prevent data leakage.
    """
    disaster_type = event.get("disaster_type", "unknown")
    lat = event.get("geo_latitude", 0)
    lon = event.get("geo_longitude", 0)
    event_date = str(event.get("event_date", ""))

    try:
        assessment_date = (datetime.strptime(event_date, "%Y-%m-%d")
                           - timedelta(days=lead_time_days)).strftime("%Y-%m-%d")
    except ValueError:
        assessment_date = event_date

    forecast_hours = lead_time_days * 24
    horizon_label = f"{lead_time_days} {'day' if lead_time_days == 1 else 'days'} ahead ({forecast_hours}h)"

    return f"""A potential {disaster_type} event is being investigated:

**Coordinates**: lat={lat}, lon={lon}
**Assessment Date**: {assessment_date}
**Forecast Horizon**: {horizon_label}
**Disaster Type**: {disaster_type}

Use date={assessment_date} for all data tools.
For get_rainfall_after_event: use hours={forecast_hours} \
(0h = same-day observed conditions; >0h = forecast window leading up to the event).

Please assess whether conditions at these coordinates on this date are consistent \
with a {disaster_type} event occurring in {forecast_hours}h.
DO NOT assume the event occurred; evaluate purely based on the data."""


def _extract_tool_trace(messages: list) -> list:
    """Extract a structured trace of tool calls and results from the message history."""
    trace = []
    for msg in messages:
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            if msg.content:
                trace.append({
                    "type": "thought",
                    "text": msg.content,
                })
            for tc in msg.tool_calls:
                trace.append({
                    "type": "tool_call",
                    "tool": tc.get("name", "unknown"),
                    "args": tc.get("args", {}),
                })
        elif isinstance(msg, ToolMessage):
            try:
                content = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
            except (json.JSONDecodeError, TypeError):
                content = str(msg.content)
            trace.append({
                "type": "tool_result",
                "tool": msg.name if hasattr(msg, 'name') else "unknown",
                "result": content,
            })
    return trace


import re

def _extract_risk_level(final_text: str) -> str:
    """
    Parse the risk level from the agent's final response text.

    Priority order:
    1. Inside '### Final Risk Assessment' section — first 'Risk Level: LEVEL'
    2. First 'Risk Level: LEVEL' anywhere in text
    3. Standalone bold **LEVEL** in Final Risk Assessment section (word-boundary guard)
    4. Fallback: severity-ordered keyword scan

    Non-word characters (emojis, spaces) between ** and the level word are
    skipped via [^A-Za-z]* so that **⚪ NONE** and **NONE** both match.
    """
    if not final_text:
        return "UNKNOWN"

    _LEVELS = r"(CRITICAL|HIGH|MEDIUM|LOW|NONE|INCOMPLETE_DATA|INCOMPLETE\s+DATA)"
    _SKIP   = r"[^A-Za-z]*"   # absorbs emojis/spaces between ** and the word

    # Priority 1: inside ### Final Risk Assessment block
    section_match = re.search(
        r"###\s*Final Risk Assessment.*?Risk Level[:\s]*\*?\*?" + _SKIP + _LEVELS + r"\*?\*?",
        final_text, re.IGNORECASE | re.DOTALL
    )
    if section_match:
        return section_match.group(1).upper().replace(" ", "_")

    # Priority 2: first 'Risk Level: LEVEL' anywhere
    matches = re.findall(
        r"Risk Level[:\s]*\*?\*?" + _SKIP + _LEVELS + r"\*?\*?",
        final_text, re.IGNORECASE
    )
    if matches:
        return matches[0].upper().replace(" ", "_")

    # Priority 3: bold **LEVEL** inside Final Risk Assessment only
    # Scoping to the section prevents picking up 'Confidence: **HIGH**' etc.
    section_text = re.search(
        r"###\s*Final Risk Assessment(.*)", final_text, re.IGNORECASE | re.DOTALL
    )
    if section_text:
        bold = re.findall(r"\*\*" + _SKIP + _LEVELS + r"\*\*(?!\w)", section_text.group(1), re.IGNORECASE)
        if bold:
            return bold[0].upper().replace(" ", "_")

    # Priority 4: severity-ordered keyword scan
    text_upper = final_text.upper()
    for level in ["INCOMPLETE_DATA", "INCOMPLETE DATA", "CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"]:
        if level in text_upper:
            return level.replace(" ", "_")

    return "UNKNOWN"

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
def run_historical_analysis(
    event: dict,
    api_key: str,
    model_key: str = "gemini-3.1-flash-lite",
    lead_time_days: int = 0,
    run_number: int = 1,
    prompt_version_id: Optional[str] = None,
    on_complete: Optional[Callable] = None,
    # Legacy alias — accepts gemini_key for backwards compatibility with existing callers
    gemini_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the ReAct agent on a single historical event.

    Args:
        event: Event dict with geo_latitude, geo_longitude, event_date, disaster_type
        api_key: API key for the selected model provider
        model_key: Key from EXPERIMENT_MODELS (default: 'gemini-3-flash')
        lead_time_days: 0=T-0 baseline, >0=simulated early warning
        run_number: Run index for statistical significance (n=3 runs per cell)
        prompt_version_id: ID from prompt_versions table for reproducibility tracking
        on_complete: Optional callback(result_dict) — caller handles Supabase persistence
        gemini_key: Legacy alias for api_key (backwards compatibility)

    Returns:
        Dictionary with risk_level, reasoning, tool_trace, total_tokens,
        latency_seconds, model_key, lead_time_days, run_number,
        is_perfect_forecast, prompt_version_id, success, error
    """
    # Legacy alias support
    if gemini_key and not api_key:
        api_key = gemini_key

    # 1. Resolve model config
    model_cfg = EXPERIMENT_MODELS.get(model_key)
    if not model_cfg:
        return {
            "risk_level": "ERROR",
            "reasoning": f"Unknown model_key '{model_key}'. Check EXPERIMENT_MODELS in config.py.",
            "tool_trace": [], "success": False, "error": f"Unknown model_key: {model_key}",
            "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
        }
    provider = model_cfg["provider"]
    model_id = model_cfg["model_id"]
    base_url = model_cfg.get("base_url")
    adapter_prompt = model_cfg.get("adapter_prompt")

    # 2. Input Validation
    lat = event.get("geo_latitude")
    lon = event.get("geo_longitude")
    event_date = event.get("event_date")
    disaster_type = event.get("disaster_type", "unknown").lower()

    if lat is None or lon is None or lat == 0 or lon == 0:
        return {
            "risk_level": "ERROR",
            "reasoning": "Missing or invalid coordinates (lat/lon). Geocoding may have failed during crawl.",
            "tool_trace": [], "success": False, "error": "Invalid coordinates",
            "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
        }

    if not event_date:
        return {
            "risk_level": "ERROR",
            "reasoning": "Missing event date. Historical analysis requires a specific date.",
            "tool_trace": [], "success": False, "error": "Missing event date",
            "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
        }

    start_time = time.time()

    try:
        if disaster_type == "flood":
            app = create_flood_agent(
                api_key=api_key, model=model_id,
                provider=provider, base_url=base_url, adapter_prompt=adapter_prompt
            )
        elif disaster_type == "landslide":
            app = create_landslide_agent(
                api_key=api_key, model=model_id,
                provider=provider, base_url=base_url, adapter_prompt=adapter_prompt
            )
        else:
            return {
                "risk_level": "ERROR",
                "reasoning": f"Unknown disaster type: {disaster_type}. Cannot select appropriate agent.",
                "tool_trace": [], "success": False, "error": f"Unknown disaster type: {disaster_type}",
                "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
            }

        human_msg = _build_human_message(event, lead_time_days=lead_time_days)

        # Run the agent (handles both sync and async calling contexts)
        timeout_seconds = 240
        import concurrent.futures
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        app.ainvoke({"messages": [HumanMessage(content=human_msg)]}, config={"recursion_limit": 100})
                    )
                    result = future.result(timeout=timeout_seconds)
            else:
                result = loop.run_until_complete(
                    app.ainvoke({"messages": [HumanMessage(content=human_msg)]}, config={"recursion_limit": 100})
                )
        except concurrent.futures.TimeoutError:
            return {
                "risk_level": "ERROR",
                "reasoning": f"Analysis timed out after {timeout_seconds}s.",
                "tool_trace": [], "success": False, "error": "Timeout",
                "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
            }
        except RuntimeError:
            result = asyncio.run(
                app.ainvoke({"messages": [HumanMessage(content=human_msg)]}, config={"recursion_limit": 100})
            )

        latency_seconds = round(time.time() - start_time, 2)

        # Extract results
        messages = result.get("messages", [])
        final_message = messages[-1] if messages else None

        reasoning = ""
        if final_message and hasattr(final_message, 'content'):
            if isinstance(final_message.content, str):
                reasoning = final_message.content
            elif isinstance(final_message.content, list):
                reasoning = "\n".join(
                    block.get('text', str(block)) if isinstance(block, dict) else str(block)
                    for block in final_message.content
                )

        if not reasoning:
            return {
                "risk_level": "ERROR",
                "reasoning": "Agent returned an empty response. Check API status or key quota.",
                "tool_trace": _extract_tool_trace(messages),
                "success": False, "error": "Empty response",
                "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
                "latency_seconds": latency_seconds,
            }

        # Extract token usage from LangGraph response metadata if available
        total_tokens = None
        if final_message and hasattr(final_message, 'usage_metadata') and final_message.usage_metadata:
            total_tokens = final_message.usage_metadata.get("total_tokens")

        risk_level = _extract_risk_level(reasoning)
        tool_trace = _extract_tool_trace(messages)

        output = {
            "risk_level": risk_level,
            "reasoning": reasoning,
            "tool_trace": tool_trace,
            "total_tokens": total_tokens,
            "latency_seconds": latency_seconds,
            "model_key": model_key,
            "lead_time_days": lead_time_days,
            "run_number": run_number,
            "is_perfect_forecast": lead_time_days > 0,
            "prompt_version_id": prompt_version_id,
            "success": True,
            "error": None,
        }

        if on_complete:
            on_complete(output)

        return output

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Agent analysis failed: {error_msg}")

        user_reasoning = f"Analysis failed: {error_msg}"
        if "API_KEY_INVALID" in error_msg:
            user_reasoning = "API key is invalid. Please check your configuration."
        elif "quota" in error_msg.lower():
            user_reasoning = "API quota exceeded. Please wait or use a different key."

        output = {
            "risk_level": "ERROR",
            "reasoning": user_reasoning,
            "tool_trace": [], "success": False, "error": error_msg,
            "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
            "latency_seconds": round(time.time() - start_time, 2),
        }

        if on_complete:
            on_complete(output)

        return output


_DIRECT_LLM_SYSTEM_PROMPT = """You are a disaster risk assessment specialist for Vietnam. You must evaluate flood or landslide risk at a given location and date using only your general knowledge — you have no access to real-time weather data, gauge readings, terrain databases, or measurement tools.

Reason from:
- general knowledge of Vietnam's regional monsoon patterns
- general knowledge of Vietnam's terrain types
- Physical principles: steep slopes >15° are necessary for shallow landslides; high antecedent rainfall saturates soil and lowers factor of safety; coastal low-lying areas flood from tidal surge combined with river overflow; flash floods require intense short-duration rainfall on steep catchments

Structure your reasoning in 4 steps:
1. Identify what region and terrain type the coordinates most likely represent
2. State whether the assessment date falls within the regional rainy season and how deep into the season
3. Describe what general atmospheric and soil conditions would typically be expected at this location and time of year
4. Conclude whether those background conditions are consistent with a disaster-triggering event

Then output exactly:

### Final Risk Assessment
Risk Level: <NONE|LOW|MEDIUM|HIGH|CRITICAL>

Risk level definitions:
- NONE: no physical basis for event initiation
- LOW: conditions generally sub-threshold for triggering
- MEDIUM: conditions plausible but not probable
- HIGH: conditions consistent with a major event
- CRITICAL: conditions strongly consistent with a major event"""


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
def run_direct_llm_analysis(
    event: dict,
    api_key: str,
    model_key: str = "direct-llm-gemini-3.1-flash-lite",
    lead_time_days: int = 0,
    run_number: int = 1,
    prompt_version_id: Optional[str] = None,
    on_complete: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Direct LLM call with no tools and no ReAct loop — ablation baseline for the paper.
    Tests parametric LLM knowledge against physics-grounded tool retrieval.
    Returns the same dict structure as run_historical_analysis(); tool_trace is always [].
    """
    model_cfg = EXPERIMENT_MODELS.get(model_key)
    if not model_cfg:
        return {
            "risk_level": "ERROR",
            "reasoning": f"Unknown model_key '{model_key}'. Check EXPERIMENT_MODELS in config.py.",
            "tool_trace": [], "success": False, "error": f"Unknown model_key: {model_key}",
            "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
        }

    lat = event.get("geo_latitude")
    lon = event.get("geo_longitude")
    event_date = event.get("event_date")

    if lat is None or lon is None or lat == 0 or lon == 0:
        return {
            "risk_level": "ERROR",
            "reasoning": "Missing or invalid coordinates (lat/lon).",
            "tool_trace": [], "success": False, "error": "Invalid coordinates",
            "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
        }

    if not event_date:
        return {
            "risk_level": "ERROR",
            "reasoning": "Missing event date.",
            "tool_trace": [], "success": False, "error": "Missing event date",
            "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
        }

    start_time = time.time()

    try:
        llm = get_reasoning_llm(
            provider=model_cfg["provider"],
            api_key=api_key,
            model=model_cfg["model_id"],
            base_url=model_cfg.get("base_url"),
            temperature=0.1,
        )

        human_msg = _build_human_message(event, lead_time_days=lead_time_days)
        response = llm.invoke([
            SystemMessage(content=_DIRECT_LLM_SYSTEM_PROMPT),
            HumanMessage(content=human_msg),
        ])
        latency_seconds = round(time.time() - start_time, 2)

        reasoning = ""
        if isinstance(response.content, str):
            reasoning = response.content
        elif isinstance(response.content, list):
            reasoning = "\n".join(
                block.get("text", str(block)) if isinstance(block, dict) else str(block)
                for block in response.content
            )

        if not reasoning:
            return {
                "risk_level": "ERROR",
                "reasoning": "LLM returned an empty response.",
                "tool_trace": [], "success": False, "error": "Empty response",
                "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
                "latency_seconds": latency_seconds,
            }

        total_tokens = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            total_tokens = response.usage_metadata.get("total_tokens")

        risk_level = _extract_risk_level(reasoning)

        output = {
            "risk_level": risk_level,
            "reasoning": reasoning,
            "tool_trace": [],
            "total_tokens": total_tokens,
            "latency_seconds": latency_seconds,
            "model_key": model_key,
            "lead_time_days": lead_time_days,
            "run_number": run_number,
            "is_perfect_forecast": lead_time_days > 0,
            "prompt_version_id": prompt_version_id,
            "success": True,
            "error": None,
        }

        if on_complete:
            on_complete(output)

        return output

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Direct LLM analysis failed: {error_msg}")

        user_reasoning = f"Analysis failed: {error_msg}"
        if "API_KEY_INVALID" in error_msg:
            user_reasoning = "API key is invalid. Please check your configuration."
        elif "quota" in error_msg.lower():
            user_reasoning = "API quota exceeded. Please wait or use a different key."

        output = {
            "risk_level": "ERROR",
            "reasoning": user_reasoning,
            "tool_trace": [], "success": False, "error": error_msg,
            "model_key": model_key, "lead_time_days": lead_time_days, "run_number": run_number,
            "latency_seconds": round(time.time() - start_time, 2),
        }

        if on_complete:
            on_complete(output)

        return output
