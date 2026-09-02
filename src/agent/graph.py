"""
ReAct Agent for Historical Disaster Validation — v2 (3-Layer Architecture).

3-Layer Design:
  Layer 3: ReAct Agent (LLM) — reasoning, tool selection, methodology
  Layer 2: Data Retrieval Tools — APIs for meteorological + terrain data
  Layer 1: Calculator Tools — deterministic, pure math, no API calls

Uses LangGraph to orchestrate a tool-calling loop with Gemini.
"""

from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, END, MessagesState
from langgraph.prebuilt import ToolNode

from agent.llm_client import get_reasoning_llm
from agent.calibration import (
    FloodCalibrationConfig,
    LandslideCalibrationConfig,
    VIETNAM_FLOOD,
    VIETNAM_LANDSLIDE,
    build_flood_system_prompt,
    build_landslide_system_prompt,
)

# Layer 2: Data Retrieval Tools — Meteorological
from tools.weather import (
    get_historical_rainfall,
    get_rainfall_forecast,
    get_rainfall_after_event,
    get_soil_moisture,
    get_antecedent_precipitation_index,
)

# Layer 2: Data Retrieval Tools — Terrain & Geospatial
from tools.geo_data import (
    get_elevation_slope,
    get_terrain_profile,
    get_historical_tide_level,
    get_river_discharge,
    get_distance_to_river,
    get_catchment_slope,
    get_nearby_mountain_road,
)

# Layer 2: Data Retrieval Tools — Static Terrain (P0-3, P0-4, P0-5, P1-2)
from tools.terrain_data import (
    get_imperviousness,
    get_twi,
    get_catchment_info,
)

# Layer 1: Calculator Tools — Deterministic, Pure Math
from tools.calculator import (
    calculate_doyin_threshold,
    calculate_flash_flood_risk,
    calculate_river_water_level,
    calculate_hybrid_api,
)


# ============================================================================
# FLOOD AGENT — 3-Layer System Prompt (Methodology Encoding)
# Calibration-specific thresholds live in agent/calibration.py.
# To adapt to a new country: create a FloodCalibrationConfig and pass it to
# create_flood_agent(calibration=your_config).
# ============================================================================



FLOOD_TOOLS = [
    # --- Layer 2: Data Retrieval Tools (Agent calls these iteratively) ---
    # Meteorological
    get_historical_rainfall,
    get_rainfall_forecast,
    get_rainfall_after_event,
    get_soil_moisture,
    get_antecedent_precipitation_index,
    # Terrain & Geospatial
    get_elevation_slope,
    get_catchment_slope,
    get_historical_tide_level,
    get_river_discharge,
    get_distance_to_river,
    # Static Terrain
    get_imperviousness,
    get_twi,
    get_catchment_info,

    # --- Layer 1: Calculator Tools (Agent calls with collected evidence) ---
    calculate_flash_flood_risk,
    calculate_river_water_level,
    calculate_hybrid_api,
]


# ============================================================================
# LANDSLIDE AGENT — 3-Layer System Prompt (Methodology Encoding)
# Calibration-specific thresholds live in agent/calibration.py.
# To adapt to a new country: create a LandslideCalibrationConfig and pass it to
# create_landslide_agent(calibration=your_config).
# ============================================================================



LANDSLIDE_TOOLS = [
    # --- Layer 2: Data Retrieval Tools (Agent calls iteratively) ---
    # Meteorological
    get_historical_rainfall,
    get_rainfall_forecast,
    get_rainfall_after_event,
    get_soil_moisture,
    get_antecedent_precipitation_index,
    # Terrain & Geospatial
    get_elevation_slope,
    get_terrain_profile,
    get_nearby_mountain_road,

    # --- Layer 1: Calculator Tools (Agent calls with collected evidence) ---
    # Do & Yin (2018) conditional antecedent rainfall thresholds
    calculate_doyin_threshold,
]


# ============================================================================
# Agent Factory
# ============================================================================

def _create_agent(
    api_key: str,
    system_prompt: str,
    tools: list,
    model: str,
    provider: str = "google",
    base_url: str = None,
    adapter_prompt: str = None,
):
    # Append adapter_prompt (format hint) to system prompt without altering base text.
    # The base prompt text stays unchanged for prompt_hash reproducibility tracking.
    effective_prompt = system_prompt
    if adapter_prompt:
        effective_prompt = system_prompt + f"\n\n{adapter_prompt}"

    llm = get_reasoning_llm(
        provider=provider, api_key=api_key, model=model, base_url=base_url
    )
    llm_with_tools = llm.bind_tools(tools)

    def call_model(state: MessagesState):
        messages = state["messages"]
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=effective_prompt)] + messages
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    def should_continue(state: MessagesState):
        messages = state["messages"]
        last_message = messages[-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return END

    workflow = StateGraph(MessagesState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")

    return workflow.compile()


def create_flood_agent(
    api_key: str,
    model: str = "gemini-3-flash-preview",
    provider: str = "google",
    base_url: str = None,
    adapter_prompt: str = None,
    calibration: FloodCalibrationConfig = None,
):
    """Creates a ReAct agent optimized for flood risk validation (v2 3-layer).

    Pass a FloodCalibrationConfig to adapt to a country other than Vietnam.
    Defaults to VIETNAM_FLOOD if not provided.
    """
    prompt = build_flood_system_prompt(calibration or VIETNAM_FLOOD)
    return _create_agent(api_key, prompt, FLOOD_TOOLS, model, provider, base_url, adapter_prompt)


def create_landslide_agent(
    api_key: str,
    model: str = "gemini-3-flash-preview",
    provider: str = "google",
    base_url: str = None,
    adapter_prompt: str = None,
    calibration: LandslideCalibrationConfig = None,
):
    """Creates a ReAct agent optimized for landslide risk validation.

    Pass a LandslideCalibrationConfig to adapt to a country other than Vietnam.
    Defaults to VIETNAM_LANDSLIDE if not provided.
    """
    prompt = build_landslide_system_prompt(calibration or VIETNAM_LANDSLIDE)
    return _create_agent(api_key, prompt, LANDSLIDE_TOOLS, model, provider, base_url, adapter_prompt)
