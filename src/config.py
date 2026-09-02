"""
Shared config helpers used by src/tools/*.py — API endpoint resolution only.
For the model registry, see agent/config.py.
"""

import os


def get_open_meteo_urls() -> dict:
    """Returns Open-Meteo base URLs. Uses the paid customer endpoints if
    OPEN_METEO_API_KEY is set in the environment, otherwise the free public API."""
    key = os.environ.get("OPEN_METEO_API_KEY", "")
    if key:
        return {
            "forecast":  "https://customer-api.open-meteo.com/v1/forecast",
            "archive":   "https://customer-archive-api.open-meteo.com/v1/archive",
            "elevation": "https://customer-api.open-meteo.com/v1/elevation",
            "marine":    "https://customer-marine-api.open-meteo.com/v1/marine",
            "flood":     "https://customer-flood-api.open-meteo.com/v1/flood",
            "api_key":   key,
        }
    return {
        "forecast":  "https://api.open-meteo.com/v1/forecast",
        "archive":   "https://archive-api.open-meteo.com/v1/archive",
        "elevation": "https://api.open-meteo.com/v1/elevation",
        "marine":    "https://marine-api.open-meteo.com/v1/marine",
        "flood":     "https://flood-api.open-meteo.com/v1/flood",
        "api_key":   None,
    }


def get_random_overpass_url() -> str:
    """Public Overpass API endpoint for OSM queries (get_distance_to_river,
    get_nearby_mountain_road). The source project uses a self-hosted local mirror
    for unlimited concurrency during batch evaluation runs — not applicable here,
    so this points at the standard public instance instead."""
    return "https://overpass-api.de/api/interpreter"
