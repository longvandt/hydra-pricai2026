"""
Weather data tools for historical disaster analysis.
Fetches historical and forecast rainfall + soil moisture from Open-Meteo API.
"""

import math
import httpx
from datetime import datetime, timedelta
from typing import Dict
from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_exponential
from config import get_open_meteo_urls


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def _fetch_from_open_meteo(url: str, params: Dict[str, any], timeout: float = 15.0) -> Dict[str, any]:
    """Helper: fetch data from Open-Meteo with retry logic. Injects API key if available."""
    om = get_open_meteo_urls()
    if om["api_key"] and "customer-" in url:
        params = {**params, "apikey": om["api_key"]}
    
    # Pace free Archive API calls to avoid 429
    if "://archive-api.open-meteo.com" in url:
        import asyncio
        await asyncio.sleep(1.0)

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()


def _sliding_window_max(hourly_rain: list, window_hours: int) -> float:
    """Compute the maximum sum over a sliding window of given hours."""
    if not hourly_rain or window_hours <= 0:
        return 0.0
    if len(hourly_rain) <= window_hours:
        return round(sum(hourly_rain), 1)
    max_sum = 0.0
    current_sum = sum(hourly_rain[:window_hours])
    max_sum = current_sum
    for i in range(window_hours, len(hourly_rain)):
        current_sum += hourly_rain[i] - hourly_rain[i - window_hours]
        if current_sum > max_sum:
            max_sum = current_sum
    return round(max_sum, 1)


@tool
async def get_historical_rainfall(lat: float, lon: float, event_date: str, days_before: int = 3) -> Dict[str, any]:
    """Fetches HOURLY rainfall for N days BEFORE a historical event date.

    Uses Open-Meteo Archive API (ERA5-based, data from 1940 to present).
    Returns both cumulative totals AND peak intensity windows critical for
    distinguishing flood types:
    - max_1h_mm, max_2h_mm, max_3h_mm, max_6h_mm, max_12h_mm, max_24h_mm
    (Used for urban flood, flash flood, and landslide threshold checking)

    Args:
        lat: Latitude of the location
        lon: Longitude of the location
        event_date: The date of the historical event in YYYY-MM-DD format
        days_before: Number of days before the event to fetch (default: 3)

    Returns:
        Dictionary with total_mm, max levels for each window,
        daily_breakdown, and period.
    """
    try:
        end_date = datetime.strptime(event_date, "%Y-%m-%d").date()
        start_date = end_date - timedelta(days=days_before)
    except ValueError:
        return {"error": f"Invalid date format: {event_date}. Use YYYY-MM-DD.", "total_mm": 0}

    url = get_open_meteo_urls()["archive"]
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "hourly": "rain",
        "daily": "rain_sum",
        "models": "era5",       # ERA5 atmospheric reanalysis (Hersbach et al. 2020, DOI:10.1002/qj.3803)
        "timezone": "auto"
    }

    try:
        data = await _fetch_from_open_meteo(url, params)

        # --- Hourly data for peak intensity windows ---
        hourly_rain = data.get("hourly", {}).get("rain", [])
        hourly_rain = [r if r is not None else 0.0 for r in hourly_rain]

        max_1h = _sliding_window_max(hourly_rain, 1)
        max_2h = _sliding_window_max(hourly_rain, 2)
        max_3h = _sliding_window_max(hourly_rain, 3)
        max_6h = _sliding_window_max(hourly_rain, 6)
        max_12h = _sliding_window_max(hourly_rain, 12)
        max_24h = _sliding_window_max(hourly_rain, 24)

        # --- Daily data for cumulative totals ---
        daily_rain = data.get("daily", {}).get("rain_sum", [])
        daily_rain = [r if r is not None else 0 for r in daily_rain]
        total = sum(daily_rain)
        dates = data.get("daily", {}).get("time", [])

        return {
            "total_mm": round(total, 1),
            "max_1h_mm": max_1h,
            "max_2h_mm": max_2h,
            "max_3h_mm": max_3h,
            "max_6h_mm": max_6h,
            "max_12h_mm": max_12h,
            "max_24h_mm": max_24h,
            "daily_breakdown": [{"date": d, "rain_mm": r} for d, r in zip(dates, daily_rain)],
            "period": f"{start_date} to {end_date}",
            "days": days_before
        }
    except Exception as e:
        return {"error": f"Failed to fetch rainfall data: {str(e)}", "total_mm": 0}


@tool
async def get_rainfall_forecast(lat: float, lon: float, hours: int = 24) -> Dict[str, any]:
    """Fetches forecasted rainfall for the next N hours from Open-Meteo.
    
    Use this tool for REAL-TIME risk assessment (not historical analysis).
    For historical events, use get_rainfall_after_event instead.
    
    Args:
        lat: Latitude of the location
        lon: Longitude of the location
        hours: Number of future hours to forecast (default: 24)
        
    Returns:
        Dictionary with total_mm and period_hours.
    """
    url = get_open_meteo_urls()["forecast"]
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "rain",
        "forecast_days": 2,
        "timezone": "auto"
    }
    
    try:
        data = await _fetch_from_open_meteo(url, params, timeout=10.0)
        hourly_rain = data.get("hourly", {}).get("rain", [])
        forecast_total = sum(r for r in hourly_rain[:hours] if r is not None)
        
        return {
            "total_mm": round(forecast_total, 1),
            "period_hours": hours
        }
    except Exception as e:
        return {"error": f"Failed to fetch forecast: {str(e)}", "total_mm": 0}


@tool
async def get_rainfall_after_event(lat: float, lon: float, event_date: str, hours: int = 24) -> Dict[str, any]:
    """Fetches ACTUAL rainfall for N hours AFTER a historical event date.
    
    This simulates what a 'forecast' would have predicted for historical validation.
    Uses Open-Meteo Archive API.
    
    Args:
        lat: Latitude of the location
        lon: Longitude of the location
        event_date: The event date in YYYY-MM-DD format
        hours: Number of hours after event to fetch (default: 24)
        
    Returns:
        Dictionary with total_mm (actual post-event rainfall).
    """
    try:
        event_dt = datetime.strptime(event_date, "%Y-%m-%d").date()
        days_needed = math.ceil(hours / 24)
        end_date = event_dt + timedelta(days=days_needed)
    except ValueError:
        return {"error": f"Invalid date format: {event_date}", "total_mm": 0}

    url = get_open_meteo_urls()["archive"]
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": event_dt.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "hourly": "rain",
        "models": "era5",       # ERA5 atmospheric reanalysis (Hersbach et al. 2020)
        "timezone": "auto"
    }

    try:
        data = await _fetch_from_open_meteo(url, params)
        hourly_rain = data.get("hourly", {}).get("rain", [])
        hourly_rain = [r if r is not None else 0 for r in hourly_rain]
        post_event_total = sum(hourly_rain[:hours])  # truncate to exact hours requested
        
        return {
            "total_mm": round(post_event_total, 1),
            "period_hours": hours,
            "note": "Actual recorded rainfall after event (simulates forecast for historical validation)"
        }
    except Exception as e:
        return {"error": f"Failed to fetch post-event rainfall: {str(e)}", "total_mm": 0}


@tool
async def get_soil_moisture(lat: float, lon: float, event_date: str) -> Dict[str, any]:
    """Fetches surface soil moisture at a location on a specific historical date.
    
    Uses Open-Meteo Archive API (ERA5-Land soil moisture 0-7cm).
    High soil moisture before an event indicates saturated ground, increasing
    both flood and landslide risk.
    
    Args:
        lat: Latitude of the location
        lon: Longitude of the location
        event_date: Date to query in YYYY-MM-DD format
        
    Returns:
        Dictionary with soil_moisture_m3_per_m3 and saturation level.
    """
    try:
        dt = datetime.strptime(event_date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": f"Invalid date format: {event_date}"}
    
    url = get_open_meteo_urls()["archive"]
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": dt.strftime("%Y-%m-%d"),
        "end_date": dt.strftime("%Y-%m-%d"),
        "daily": "soil_moisture_0_to_7cm_mean",
        "timezone": "auto"
    }
    
    try:
        data = await _fetch_from_open_meteo(url, params)
        values = data.get("daily", {}).get("soil_moisture_0_to_7cm_mean", [])
        sm = values[0] if values and values[0] is not None else None
        
        if sm is None:
            return {"soil_moisture_m3_per_m3": None, "saturation": "unknown", "note": "Data unavailable"}
        
        # Classify saturation level
        if sm > 0.4:
            saturation = "saturated"
        elif sm > 0.3:
            saturation = "wet"
        elif sm > 0.2:
            saturation = "moist"
        else:
            saturation = "dry"
        
        return {
            "soil_moisture_m3_per_m3": round(sm, 4),
            "saturation": saturation,
            "date": event_date
        }
    except Exception as e:
        return {"error": f"Failed to fetch soil moisture: {str(e)}"}


@tool
async def get_antecedent_precipitation_index(lat: float, lon: float, event_date: str, days: int = 7, decay: float = 0.85) -> Dict[str, any]:
    """Calculates Antecedent Precipitation Index (API) for a location.
    
    API = Σ(k^i × P_i) where k is the decay factor and P_i is daily rainfall.
    Higher API values indicate greater soil saturation from accumulated prior rainfall.
    
    Args:
        lat: Latitude of the location
        lon: Longitude of the location
        event_date: Event date in YYYY-MM-DD format
        days: Number of preceding days to consider (default: 7)
        decay: Decay factor per day (default: 0.85, standard literature value)
        
    Returns:
        Dictionary with api_value, interpretation, and daily breakdown.
    """
    try:
        end_date = datetime.strptime(event_date, "%Y-%m-%d").date()
        start_date = end_date - timedelta(days=days)
    except ValueError:
        return {"error": f"Invalid date format: {event_date}"}
    
    url = get_open_meteo_urls()["archive"]
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": (end_date - timedelta(days=1)).strftime("%Y-%m-%d"),  # Day before event
        "daily": "rain_sum",
        "models": "era5",       # ERA5 atmospheric reanalysis (Hersbach et al. 2020)
        "timezone": "auto"
    }
    
    try:
        data = await _fetch_from_open_meteo(url, params)
        daily_rain = data.get("daily", {}).get("rain_sum", [])
        daily_rain = [r if r is not None else 0 for r in daily_rain]
        dates = data.get("daily", {}).get("time", [])
        
        # Calculate API: most recent day has highest weight
        daily_rain_reversed = list(reversed(daily_rain))
        api_value = sum(decay**i * p for i, p in enumerate(daily_rain_reversed))
        
        # Interpret
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
            "decay_factor": decay,
            "period_days": days,
            "total_rainfall_mm": round(sum(daily_rain), 1),
            "daily_breakdown": [{"date": d, "rain_mm": r} for d, r in zip(dates, daily_rain)]
        }
    except Exception as e:
        return {"error": f"Failed to calculate API: {str(e)}"}
