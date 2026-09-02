"""
Scientific calculation tools for disaster risk assessment.
Implements peer-reviewed formulas for landslide and flood prediction.

These are PURE CALCULATORS — they return numeric values and factual flags only.
Risk classification is performed by the ReAct Agent (Layer 3) using the
numeric outputs plus cross-referenced contextual data.
"""

from typing import Dict, List
from langchain_core.tools import tool


@tool
def calculate_flash_flood_risk(
    rainfall_6h_mm: float,
    rainfall_24h_mm: float,
    local_slope_deg: float,
    channel_slope_deg: float,
    catchment_area_km2: float,
    soil_moisture: float,
    api_value: float,
) -> Dict[str, any]:
    """Evaluates flash flood triggering conditions using six literature-grounded rules.

    This is a PURE CALCULATOR — returns which rules were triggered and saturation state.
    The Agent (Layer 3) interprets risk level based on the number and severity of triggered rules.

    Rules R1–R2: Trinh et al. (2022) SeAFFGS §3.4 — catchment-size × 6h threshold runoff
      classes for Vietnamese mountainous sub-basins (DOI: 10.36335/VNJHM.2022(13).25-36).
    Rules R3–R6: Hoang et al. (2019) §3.3 — Vietnamese flash flood risk levels I–III
      (DOI: 10.3390/ijgi8050228). Forest coverage factor omitted (data unavailable);
      saturation is used as a proxy for low permeability. Slope threshold 17° corresponds
      to the 30% average slope criterion in the original paper (arctan 0.30 ≈ 16.7°).
      The 220 mm/d upper bound in R6 is taken from the threshold range stated in §3.3.

    Args:
        rainfall_6h_mm: Peak 6-hour rainfall (mm)
        rainfall_24h_mm: Peak 24-hour rainfall (mm)
        local_slope_deg: Local slope in degrees (from get_elevation_slope)
        channel_slope_deg: Catchment-scale slope (from get_catchment_slope)
        catchment_area_km2: Local catchment area (km²)
        soil_moisture: Soil moisture (m³/m³)
        api_value: Antecedent Precipitation Index (mm)

    Returns:
        Dictionary with triggered_rules list, is_saturated flag, terrain_too_flat flag, and inputs.
    """
    is_saturated = soil_moisture > 0.35 or api_value > 30
    triggered_rules = []
    terrain_too_flat = local_slope_deg < 5 and channel_slope_deg < 2

    if not terrain_too_flat:
        # R1: Small catchment + 6h threshold runoff + saturated
        # Source: Trinh et al. (2022) §3.4 — basins <20km²: threshold runoff ≤20mm/6h
        if catchment_area_km2 < 20 and rainfall_6h_mm > 20 and is_saturated:
            triggered_rules.append("R1: small catchment (<20km²) + R_6h>20mm + saturated")

        # R2: Medium catchment + 6h threshold runoff + saturated
        # Source: Trinh et al. (2022) §3.4 — basins 20–50km²: threshold runoff 20–35mm/6h
        if catchment_area_km2 < 50 and rainfall_6h_mm > 35 and is_saturated:
            triggered_rules.append("R2: medium catchment (<50km²) + R_6h>35mm + saturated")

        # R3: Level I proxy — all three available risk factors
        # Source: Hoang et al. (2019) §3.3 Level I: rainfall ≥100mm/d + slope >30% + low permeability
        if rainfall_24h_mm >= 100 and local_slope_deg > 17 and is_saturated:
            triggered_rules.append("R3: R_24h≥100mm + slope>17° + saturated (Level I proxy)")

        # R4: Level II proxy — rainfall + steep slope
        # Source: Hoang et al. (2019) §3.3 Level II: rainfall ≥100mm/d + slope >30%
        if rainfall_24h_mm >= 100 and local_slope_deg > 17:
            triggered_rules.append("R4: R_24h≥100mm + slope>17° (Level II slope factor)")

        # R5: Level II proxy — rainfall + saturated ground
        # Source: Hoang et al. (2019) §3.3 Level II: rainfall ≥100mm/d + low permeability
        if rainfall_24h_mm >= 100 and is_saturated:
            triggered_rules.append("R5: R_24h≥100mm + saturated (Level II permeability factor)")

        # R6: Extreme daily rainfall — upper bound of Vietnamese flash flood threshold range
        # Source: Hoang et al. (2019) §3.3: thresholds range up to 220mm/d depending on basin
        if rainfall_24h_mm >= 220:
            triggered_rules.append("R6: R_24h≥220mm (extreme daily threshold)")

    return {
        "triggered_rules": triggered_rules,
        "rule_count": len(triggered_rules),
        "is_saturated": is_saturated,
        "terrain_too_flat": terrain_too_flat,
        "formula_ref": (
            "R1-R2: Trinh et al. (2022) SeAFFGS DOI:10.36335/VNJHM.2022(13).25-36; "
            "R3-R6: Hoang et al. (2019) §3.3 DOI:10.3390/ijgi8050228"
        ),
        "inputs": {
            "rainfall_6h_mm": rainfall_6h_mm,
            "rainfall_24h_mm": rainfall_24h_mm,
            "local_slope_deg": local_slope_deg,
            "channel_slope_deg": channel_slope_deg,
            "catchment_area_km2": catchment_area_km2,
            "soil_moisture": soil_moisture,
            "api_value": api_value,
        }
    }


@tool
def calculate_river_water_level(
    tide_level_cm: float,
    river_discharge_m3s: float,
    river_name: str = "generic",
    river_width_m: float = 50.0,
    c_override: float = None,
    d_override: float = None
) -> Dict[str, any]:
    """Calculates combined river water level using Tide and Discharge.

    Formula: H_total = H_tide + H_fluvial
    H_fluvial = c * Q^d (Hydraulic Rating Curve)

    Tiered Parameter Logic:
    1. If overrides provided, use them.
    2. If river_name in lookup table, use literature constants.
    3. Else, use physics-based approximation: H_fluvial = (Q/W)^0.6 * 0.1

    Args:
        tide_level_cm: Tide level in cm (from get_historical_tide_level)
        river_discharge_m3s: Discharge in m3/s (from get_river_discharge)
        river_name: Name of the river (e.g., 'Saigon', 'Dong Nai')
        river_width_m: Estimate of river width (default 50m)
        c_override: Manual coefficient c
        d_override: Manual exponent d

    Returns:
        Dictionary with combined_level_cm, fluvial_rise_cm, and metadata.
    """
    # Lookup table based on hydrological literature for SE Asia deltas
    # References: SIWRR (2022), Ho Long Phi (2010), Mekong River Commission (2023)
    RIVER_PROXIES = {
        "saigon": {"c": 0.052, "d": 0.61, "width": 250},
        "dong_nai": {"c": 0.041, "d": 0.62, "width": 600},
        "soai_rap": {"c": 0.025, "d": 0.65, "width": 1500},
        "mekong_branch": {"c": 0.030, "d": 0.63, "width": 1000},
        "red_river": {"c": 0.045, "d": 0.62, "width": 800}
    }

    # Normalize river name
    name_key = river_name.lower().replace(" ", "_").replace("river", "").strip("_")

    c, d = 0.0, 0.6 # Default d=0.6 is standard for channel hydraulics
    method = ""

    if c_override is not None:
        c = c_override
        d = d_override if d_override is not None else 0.6
        method = "manual_override"
    elif name_key in RIVER_PROXIES:
        proxy = RIVER_PROXIES[name_key]
        c, d = proxy["c"], proxy["d"]
        method = f"literature_proxy_{name_key}"
    else:
        # Physics-based approximation: H_rise = (Q/W)^0.6 * k
        # k=0.1 is an empirical constant for tropical lowland rivers
        c = (1.0 / river_width_m)**0.6 * 0.1
        method = "physics_approximation_width"

    # Calculate fluvial rise in meters
    fluvial_rise_m = c * (river_discharge_m3s ** d)

    # Total level relative to MSL
    # tide_level_cm is already relative to MSL
    combined_level_cm = tide_level_cm + (fluvial_rise_m * 100.0)

    return {
        "combined_level_cm": round(combined_level_cm, 2),
        "fluvial_rise_cm": round(fluvial_rise_m * 100.0, 2),
        "tide_component_cm": round(tide_level_cm, 2),
        "method": method,
        "parameters": {"c": round(c, 4), "d": round(d, 2)},
        "formula": f"H = H_tide + {c:.4f} * Q^{d:.2f}"
    }


@tool
def calculate_hybrid_api(
    historical_rain_series: List[float],
    forecast_rain_series: List[float],
    k: float = 0.85,
) -> Dict[str, any]:
    """Calculates Antecedent Precipitation Index (API) across a hybrid historical+forecast window.

    Use this tool for Lead Time > 0 scenarios where rainfall data spans two periods:
    - historical_rain_series: daily mm BEFORE cutoff_date (observed, most recent first)
    - forecast_rain_series: daily mm FROM cutoff_date TO event_date (perfect forecast proxy)

    Formula: API = Σ k^i * R_i  (i=0 is the day closest to the event)
    The merged series is: [forecast (reversed) + historical (already reversed)] so that
    day 0 = event day, day 1 = day before, etc.

    This is a PURE CALCULATOR — keeps arithmetic out of the LLM layer.

    Args:
        historical_rain_series: Daily rainfall before cutoff (most recent day first), mm
        forecast_rain_series: Daily rainfall in forecast window (most recent day first), mm
        k: Decay factor per day (default 0.85, literature standard)

    Returns:
        Dictionary with api_value, series_length, is_hybrid flag.
    """
    # Merge: forecast window is more recent than historical
    # forecast_rain_series[0] is closest to event; historical follows after
    merged = list(forecast_rain_series) + list(historical_rain_series)

    api_value = sum(k**i * r for i, r in enumerate(merged))

    if api_value > 50:
        interpretation = "very_high_saturation"
    elif api_value > 30:
        interpretation = "high_saturation"
    elif api_value > 15:
        interpretation = "moderate_saturation"
    else:
        interpretation = "low_saturation"

    return {
        "api_value": round(api_value, 2),
        "interpretation": interpretation,
        "decay_factor": k,
        "series_length": len(merged),
        "forecast_days": len(forecast_rain_series),
        "historical_days": len(historical_rain_series),
        "is_hybrid": True,
        "formula_ref": "API = Σ k^i * R_i, k=0.85 (standard literature value)"
    }


@tool
def calculate_doyin_threshold(
    antecedent_3day_mm: float,
    trigger_day_rain_mm: float,
    antecedent_5day_mm: float = 0.0,
    antecedent_7day_mm: float = 0.0,
    antecedent_10day_mm: float = 0.0,
    antecedent_15day_mm: float = 0.0,
) -> Dict[str, any]:
    """Calculates Do & Yin (2018) conditional antecedent rainfall thresholds.

    Five regression equations from Figure 4 of the paper:
      RT = 40.8  − 0.201 × R₃ₐd   (3-day antecedent window)
      RT = 44.7  − 0.087 × R₅ₐd   (5-day)
      RT = 47.36 − 0.047 × R₇ₐd   (7-day)
      RT = 51.2  − 0.010 × R₁₀ₐd  (10-day)
      RT = 53.3  − 0.001 × R₁₅ₐd  (15-day)

    Where:
      R_Nad = cumulative rainfall over N days BEFORE the event/trigger day (mm)
      RT    = conditional threshold: minimum trigger-day rainfall (mm) for landslide
    A window is exceeded when: trigger_day_rain_mm >= RT

    Study area: Hà Giang city, NW Vietnam (37 events from 245 landslides, 1990–2016).
    Agent must assess geographic applicability to the target location.

    Reference: Do, H.M. & Yin, K.L. (2018). Open Journal of Geology, 8(7), 674–696.
    DOI: 10.4236/ojg.2018.87040

    This is a PURE CALCULATOR — returns threshold values and exceedance flags only.

    Args:
        antecedent_3day_mm: Cumulative rainfall over the 3 days BEFORE the event day (mm)
        trigger_day_rain_mm: Actual rainfall on the event/trigger day (mm)
        antecedent_5day_mm: 5-day antecedent rainfall (mm), optional
        antecedent_7day_mm: 7-day antecedent rainfall (mm), optional
        antecedent_10day_mm: 10-day antecedent rainfall (mm), optional
        antecedent_15day_mm: 15-day antecedent rainfall (mm), optional

    Returns:
        window_results: per-window {window_days, antecedent_mm, threshold_mm,
                        trigger_day_rain_mm, margin_mm, exceeded, formula}
        primary_result: the 3-day window result (always computed)
        windows_exceeded: count of windows where trigger_day_rain_mm >= RT
    """
    WINDOWS = [
        {"days": 3,  "a": 40.8,  "b": 0.201, "antecedent": antecedent_3day_mm},
        {"days": 5,  "a": 44.7,  "b": 0.087, "antecedent": antecedent_5day_mm},
        {"days": 7,  "a": 47.36, "b": 0.047, "antecedent": antecedent_7day_mm},
        {"days": 10, "a": 51.2,  "b": 0.010, "antecedent": antecedent_10day_mm},
        {"days": 15, "a": 53.3,  "b": 0.001, "antecedent": antecedent_15day_mm},
    ]

    window_results = []
    windows_exceeded = 0

    for w in WINDOWS:
        if w["antecedent"] <= 0:
            continue
        # RT = a - b * R_Nad; floor at 0 (extreme antecedent alone exhausts threshold)
        threshold_mm = max(0.0, w["a"] - w["b"] * w["antecedent"])
        margin_mm = trigger_day_rain_mm - threshold_mm
        exceeded = trigger_day_rain_mm >= threshold_mm

        if exceeded:
            windows_exceeded += 1

        window_results.append({
            "window_days": w["days"],
            "antecedent_mm": round(w["antecedent"], 1),
            "threshold_mm": round(threshold_mm, 1),
            "trigger_day_rain_mm": round(trigger_day_rain_mm, 1),
            "margin_mm": round(margin_mm, 1),
            "exceeded": exceeded,
            "formula": f"RT = {w['a']} − {w['b']} × {w['antecedent']:.1f} = {threshold_mm:.1f}mm",
        })

    primary_result = next((r for r in window_results if r["window_days"] == 3), None)

    return {
        "window_results": window_results,
        "primary_result": primary_result,
        "windows_exceeded": windows_exceeded,
        "study_area_note": (
            "Calibrated for Hà Giang province, NW Vietnam (37 events, 1990–2016). "
            "Agent should assess applicability to the target location."
        ),
        "formula_ref": "Do & Yin (2018), Open Journal of Geology, DOI:10.4236/ojg.2018.87040",
    }
