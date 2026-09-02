"""
Geographical and terrain data tools for disaster analysis.
Uses a multi-provider elevation API chain with Supabase caching.

Elevation fallback order (Fix #1 + #2):
  1. Supabase cache (lat/lon rounded to 4dp ~11m, persistent across runs)
  2. Open-Meteo Elevation API (primary, SRTM 90m)
  3. OpenTopoData SRTM-30m   (fallback-1, higher resolution)
  4. OpenTopoData ASTER-30m  (fallback-2, independent dataset)
  5. FAIL → return data_quality=unavailable → agent STOP (STEP 1d)
"""

import os
import math
import functools
import aiohttp
from typing import Dict, Optional
from langchain_core.tools import tool
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception, RetryError
from config import get_open_meteo_urls, get_random_overpass_url

# --- TIDE PROXY DATA (35 Stations across 21 regions) ---
# Source: tidechecker.com, PSMSL, IOC
TIDAL_STATIONS = [
    {"name": "Da Nang", "lat": 16.1167, "lon": 108.2170},
    {"name": "Mui Vung Tau", "lat": 10.3333, "lon": 107.0670},
    {"name": "Poulo Condore", "lat": 8.6667, "lon": 106.6330},
    {"name": "Qui Nhon-A", "lat": 13.7667, "lon": 109.2500},
    {"name": "Tam Kwam", "lat": 14.5833, "lon": 109.0500},
    {"name": "Phan Thiet", "lat": 10.9167, "lon": 108.1000},
    {"name": "Pointe De Ke Ga", "lat": 10.7000, "lon": 107.9830},
    {"name": "Pointe de Lagan", "lat": 11.1667, "lon": 108.7000},
    {"name": "Pulau Cecir De Mer", "lat": 10.5000, "lon": 108.9500},
    {"name": "Hon Nieu", "lat": 18.8000, "lon": 105.7670},
    {"name": "Vung Ang", "lat": 18.0833, "lon": 106.2830},
    {"name": "Apowan", "lat": 20.7167, "lon": 107.0500},
    {"name": "Hon Dau", "lat": 20.6667, "lon": 106.8167},
    {"name": "Do Son", "lat": 20.7167, "lon": 106.7833},
    {"name": "Ile Bach Long Vi", "lat": 20.1333, "lon": 107.7170},
    {"name": "Port Dayot", "lat": 12.6667, "lon": 109.3830},
    {"name": "Hon Me", "lat": 19.4333, "lon": 105.8830},
    {"name": "Hon Tho Chau", "lat": 9.3000, "lon": 103.4670},
    {"name": "Cua Ba Lat", "lat": 20.3500, "lon": 106.6333},
    {"name": "Cap Padaran", "lat": 11.3667, "lon": 109.0170},
    {"name": "Vung Ro", "lat": 12.8667, "lon": 109.4000},
    {"name": "Quang Khe", "lat": 17.7000, "lon": 106.4670},
    {"name": "Vung Chua", "lat": 17.9333, "lon": 106.4830},
    {"name": "Cu Lao Cham", "lat": 15.9500, "lon": 108.5000},
    {"name": "Kikuik", "lat": 15.4000, "lon": 108.7500},
    {"name": "Hon Gay", "lat": 20.9500, "lon": 107.0670},
    {"name": "Loc Chuc San", "lat": 21.2500, "lon": 107.9500},
    {"name": "Passe des Hydres", "lat": 20.7667, "lon": 107.1333},
    {"name": "Sha Pak Wan", "lat": 20.9667, "lon": 107.7333},
    {"name": "Tsieng Mun", "lat": 21.1333, "lon": 107.6167},
    {"name": "Hon Ne", "lat": 19.9167, "lon": 105.9830},
    {"name": "Mui Can Gio", "lat": 10.4167, "lon": 106.9830},
    {"name": "Chon May", "lat": 16.3333, "lon": 107.9830},
    {"name": "Thuan An", "lat": 16.5833, "lon": 107.6170},
    {"name": "Ha Tien", "lat": 10.3667, "lon": 104.4670},
]

def _haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2) * math.sin(dlat/2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlon/2) * math.sin(dlon/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def _get_nearest_tidal_proxy(lat: float, lon: float, max_dist_km: float = 100.0) -> Dict[str, any]:
    """Finds the nearest verified coastal station from the 3 hubs."""
    nearest = None
    min_dist = float('inf')
    
    for station in TIDAL_STATIONS:
        dist = _haversine_distance(lat, lon, station["lat"], station["lon"])
        if dist < min_dist:
            min_dist = dist
            nearest = station
            
    if nearest and min_dist <= max_dist_km:
        return {**nearest, "distance_km": round(min_dist, 2)}
    return None


def _should_retry(exception):
    """Internal helper: decide if we should retry based on the exception."""
    if isinstance(exception, httpx.HTTPStatusError):
        # Only retry on server errors (5xx) or rate limits (429)
        return exception.response.status_code >= 500 or exception.response.status_code == 429
    # Retry on other network/timeout issues
    return not isinstance(exception, httpx.HTTPStatusError)


@retry(
    stop=stop_after_attempt(3), 
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(_should_retry)
)
async def _fetch_from_api(url: str, params: Dict[str, any] = None, timeout: float = 15.0) -> Dict[str, any]:
    """Helper: fetch data from an API with retry logic. Injects Open-Meteo API key if available."""
    om = get_open_meteo_urls()
    if om["api_key"] and "customer-" in url:
        if params is None:
            params = {}
        params = {**params, "apikey": om["api_key"]}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()


# ══════════════════════════════════════════════════════════════════════
# ELEVATION CACHE + MULTI-PROVIDER FALLBACK (Fix #1 + #2)
# ══════════════════════════════════════════════════════════════════════

# Provider list in fallback order
_ELEVATION_PROVIDERS = [
    {"name": "open_meteo",          "style": "open_meteo"},
    {"name": "opentopodata_srtm30m", "style": "opentopodata",
     "url": "https://api.opentopodata.org/v1/srtm30m"},
    {"name": "opentopodata_aster30m", "style": "opentopodata",
     "url": "https://api.opentopodata.org/v1/aster30m"},
]


@functools.lru_cache(maxsize=1)
def _get_sb_client():
    """Module-level cached Supabase client (lazy init). Returns None if secrets missing."""
    try:
        from supabase import create_client
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY", "")
        if url and key:
            return create_client(url, key)
    except Exception:
        pass
    return None


def _elev_cache_get(lat_r: float, lon_r: float) -> Optional[Dict]:
    """Check Supabase elevation cache. Returns dict or None."""
    try:
        sb = _get_sb_client()
        if not sb:
            return None
        r = (sb.table("elevation_slope_cache")
             .select("elevation_m,slope_deg,terrain,source")
             .eq("lat", lat_r).eq("lon", lon_r)
             .limit(1).execute())
        if r.data:
            d = r.data[0]
            return {
                "elevation": d["elevation_m"],
                "slope": d["slope_deg"],
                "terrain": d["terrain"],
                "source": d.get("source", "cache"),
                "cached": True,
            }
    except Exception:
        pass
    return None


def _elev_cache_set(lat_r: float, lon_r: float, elevation: float,
                    slope: float, terrain: str, source: str) -> None:
    """Write to Supabase elevation cache. Non-fatal if it fails."""
    try:
        sb = _get_sb_client()
        if not sb:
            return
        sb.table("elevation_slope_cache").upsert(
            {"lat": lat_r, "lon": lon_r,
             "elevation_m": elevation, "slope_deg": slope,
             "terrain": terrain, "source": source},
            on_conflict="lat,lon"
        ).execute()
    except Exception:
        pass  # Cache write failure is non-fatal


def _compute_slope_from_elevs(elevs: list, offset_deg: float = 0.0009) -> float:
    """Compute slope in degrees from 5-point stencil [center, N, S, E, W]."""
    dist = offset_deg * 111_000  # ~100m per 0.001 deg
    dz_dx = (elevs[3] - elevs[4]) / (2 * dist)
    dz_dy = (elevs[1] - elevs[2]) / (2 * dist)
    gradient = math.sqrt(dz_dx**2 + dz_dy**2)
    return math.degrees(math.atan(gradient))


async def _fetch_5point_elevations(lat: float, lon: float) -> tuple[Optional[list], str]:
    """
    Try each provider in order. Returns (elevations_list, source_name) or (None, 'all_failed').
    Uses 5-point stencil: [center, N, S, E, W] with 0.0009° offset (~100m).
    """
    offset = 0.0009
    coords = [
        (lat,          lon),
        (lat + offset, lon),
        (lat - offset, lon),
        (lat,          lon + offset),
        (lat,          lon - offset),
    ]

    for provider in _ELEVATION_PROVIDERS:
        try:
            if provider["style"] == "open_meteo":
                om = get_open_meteo_urls()
                params = {
                    "latitude": ",".join(str(c[0]) for c in coords),
                    "longitude": ",".join(str(c[1]) for c in coords)
                }
                data = await _fetch_from_api(om['elevation'], params=params, timeout=12.0)
                elevs = data.get("elevation", [])
                if len(elevs) == 5 and all(e is not None for e in elevs):
                    return elevs, provider["name"]

            elif provider["style"] == "opentopodata":
                locs = "|".join(f"{c[0]},{c[1]}" for c in coords)
                url = f"{provider['url']}?locations={locs}&interpolation=bilinear"
                # OpenTopoData: rate limit 1 req/sec — add small delay for batch safety
                import asyncio
                await asyncio.sleep(1.1)
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, timeout=20.0)
                    resp.raise_for_status()
                    data = resp.json()
                results = data.get("results", [])
                if len(results) == 5:
                    elevs = [r.get("elevation") for r in results]
                    if all(e is not None for e in elevs):
                        return elevs, provider["name"]
        except Exception:
            continue  # Try next provider

    return None, "all_failed"



async def _calculate_slope_at_point(lat: float, lon: float, session: aiohttp.ClientSession) -> float:
    """Helper: calculate slope at a single point using 4-neighbor elevation grid."""
    offset = 0.0009  # ~100m
    
    coords = [
        (lat, lon),              # Center
        (lat + offset, lon),     # North
        (lat - offset, lon),     # South
        (lat, lon + offset),     # East
        (lat, lon - offset)      # West
    ]
    
    lats = ",".join([str(c[0]) for c in coords])
    lons = ",".join([str(c[1]) for c in coords])
    
    om = get_open_meteo_urls()
    url = f"{om['elevation']}?latitude={lats}&longitude={lons}"
    if om["api_key"]:
        url += f"&apikey={om['api_key']}"
    
    try:
        async with session.get(url) as response:
            if response.status != 200:
                return 0.0
            
            data = await response.json()
            elevs = data.get("elevation", [])
            
            if len(elevs) < 5:
                return 0.0

            dist = 100.0
            dz_dx = (elevs[3] - elevs[4]) / (2 * dist)
            dz_dy = (elevs[1] - elevs[2]) / (2 * dist)
            
            gradient = math.sqrt(dz_dx**2 + dz_dy**2)
            return math.degrees(math.atan(gradient))
    except Exception:
        return 0.0


@tool
async def get_elevation_slope(lat: float, lon: float) -> Dict[str, any]:
    """Fetches real elevation and calculates slope from multi-provider API chain.

    Provider fallback order (Fix #1 + #2):
      1. Supabase cache (lat/lon rounded to 4dp, persistent across batch runs)
      2. Open-Meteo Elevation API (primary, SRTM 90m)
      3. OpenTopoData SRTM-30m (fallback, higher resolution)
      4. OpenTopoData ASTER-30m (fallback, independent dataset)
      5. Returns data_quality=unavailable → agent MUST STOP (STEP 1d rule)

    Args:
        lat: Latitude of the location (min 4 decimal places)
        lon: Longitude of the location (min 4 decimal places)

    Returns:
        Dict with elevation (m), slope (degrees), terrain type, and source.
        On total failure: {error, slope=None, data_quality='unavailable'}.
    """
    # 1. Check Supabase cache first (slope is static, safe to cache permanently)
    lat_r = round(lat, 4)
    lon_r = round(lon, 4)

    cached = _elev_cache_get(lat_r, lon_r)
    if cached:
        return cached

    # 2. Fetch from provider chain
    elevs, source = await _fetch_5point_elevations(lat_r, lon_r)

    if elevs is None:
        # All providers failed — return unavailability signal for agent STEP 1d
        return {
            "error": "Elevation API failed: all providers exhausted "
                     "(open-meteo, opentopodata-srtm30m, opentopodata-aster30m)",
            "slope": None,
            "elevation": None,
            "terrain": "unknown",
            "data_quality": "unavailable",
            "agent_instruction": (
                "STOP: Slope data unavailable. Per protocol STEP 1d, "
                "conclude Risk Level = NONE with INCOMPLETE_DATA flag. "
                "DO NOT call calculate_landslide_risk or rainfall tools."
            )
        }

    # 3. Compute slope from 5-point stencil
    slope_deg = _compute_slope_from_elevs(elevs)

    if slope_deg > 15:
        terrain = "mountain"
    elif slope_deg > 5:
        terrain = "hilly"
    else:
        terrain = "plain"

    result = {
        "elevation": round(elevs[0], 2),
        "slope": round(slope_deg, 2),
        "terrain": terrain,
        "source": source,
    }

    # 4. Write to cache (non-fatal if Supabase unavailable)
    _elev_cache_set(lat_r, lon_r, result["elevation"], result["slope"], terrain, source)

    return result



@tool
async def get_terrain_profile(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float, grid_size: int = 5
) -> Dict[str, any]:
    """Samples terrain across a bounding box to find the steepest sections.
    
    Use for linear features like mountain passes, valleys, or roads
    where a single point may not capture the most hazardous terrain.
    
    Args:
        min_lat: Southern boundary latitude
        max_lat: Northern boundary latitude
        min_lon: Western boundary longitude
        max_lon: Eastern boundary longitude
        grid_size: Number of sample points per axis (default 5 = 25 total)
        
    Returns:
        Dictionary with max_slope, avg_slope, elevation_range, and terrain type.
    """
    lat_step = (max_lat - min_lat) / (grid_size - 1) if grid_size > 1 else 0
    lon_step = (max_lon - min_lon) / (grid_size - 1) if grid_size > 1 else 0
    
    sample_points = []
    for i in range(grid_size):
        for j in range(grid_size):
            sample_lat = min_lat + (i * lat_step)
            sample_lon = min_lon + (j * lon_step)
            sample_points.append((sample_lat, sample_lon))
    
    slopes = []
    elevations = []
    
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        for lat, lon in sample_points:
            slope = await _calculate_slope_at_point(lat, lon, session)
            slopes.append(slope)
            
            om = get_open_meteo_urls()
            url = f"{om['elevation']}?latitude={lat}&longitude={lon}"
            if om["api_key"]:
                url += f"&apikey={om['api_key']}"
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        elev = data.get("elevation", [0])[0]
                        elevations.append(elev)
            except Exception:
                continue
    
    max_slope = max(slopes) if slopes else 0.0
    avg_slope = sum(slopes) / len(slopes) if slopes else 0.0
    min_elev = min(elevations) if elevations else 0.0
    max_elev = max(elevations) if elevations else 0.0
    
    if max_slope > 15:
        terrain = "mountain"
    elif max_slope > 5:
        terrain = "hilly"
    else:
        terrain = "plain"
    
    return {
        "max_slope": round(max_slope, 2),
        "avg_slope": round(avg_slope, 2),
        "elevation_range": {"min": round(min_elev, 2), "max": round(max_elev, 2)},
        "terrain": terrain,
        "sample_count": len(sample_points),
        "note": f"Sampled {len(sample_points)} points. Max slope = steepest section."
    }


@tool
async def get_historical_tide_level(
    lat: float, 
    lon: float, 
    event_date: str,
    elevation_m: float = None
) -> Dict[str, any]:
    """Retrieves 24-hour peak astronomical tide level (cm) for a date.

    Automatically handles 'Inland' errors for riverine locations in 
    coastal/delta regions by utilizing a Nearest Coastal Proxy system 
    (35 stations across Vietnam).
    
    Args:
        lat: Latitude of the location
        lon: Longitude of the location
        event_date: Date in YYYY-MM-DD format
        elevation_m: Height above sea level (optional). 
                     If > 10m, tide is assumed 0.0.

    Returns:
        Dictionary with tide_level_cm, location_type, and station metadata.
    """
    # === Elevation Gate ===
    if elevation_m is not None and elevation_m > 10.0:
        return {
            "tide_level_cm": 0.0,
            "location_type": "highlands",
            "elevation_m": elevation_m,
            "note": "Location is above 10m elevation — beyond tidal reach."
        }

    from datetime import datetime
    try:
        dt = datetime.strptime(event_date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": f"Invalid date format: {event_date}"}
    
    query_lat, query_lon = lat, lon
    proxy_used = None

    async def _do_query(q_lat: float, q_lon: float):
        url = get_open_meteo_urls()["marine"]
        params = {
            "latitude": q_lat,
            "longitude": q_lon,
            "hourly": "sea_level_height_msl",
            "start_date": dt.strftime("%Y-%m-%d"),
            "end_date": dt.strftime("%Y-%m-%d"),
            "timezone": "auto"
        }
        return await _fetch_from_api(url, params)

    try:
        loc_type = "coastal"
        try:
            data = await _do_query(query_lat, query_lon)
            # Check for null data (common for near-shore inland points)
            hourly = data.get("hourly", {})
            heights = hourly.get("sea_level_height_msl", [])
            if not heights or all(h is None for h in heights):
                raise ValueError("No marine data returned (all null)")
        except (httpx.HTTPStatusError, RetryError, ValueError) as e:
            # Apply Nearest Coastal Proxy
            status_code = getattr(e, "response", None).status_code if hasattr(e, "response") else None
            if status_code == 400 or isinstance(e, ValueError):
                # Max distance 190km based on physical reach of tides in the Mekong Delta
                # (e.g., Tan Chau/Chau Doc are ~190km inland and still tidally influenced).
                proxy = _get_nearest_tidal_proxy(lat, lon, max_dist_km=190.0)
                if proxy:
                    proxy_used = proxy
                    query_lat, query_lon = proxy["lat"], proxy["lon"]
                    data = await _do_query(query_lat, query_lon)
                    loc_type = "nearest_coastal_proxy"
                else:
                    return {
                        "tide_level_cm": 0.0, 
                        "location_type": "inland", 
                        "note": "Location is inland and far from coast (>190km)."
                    }
            else:
                raise

        hourly = data.get("hourly", {})
        heights = hourly.get("sea_level_height_msl", [])
        
        if not heights or all(h is None for h in heights):
            return {"tide_level_cm": 0.0, "location_type": "inland", "note": "No marine data available (even after proxy check)"}
        
        valid_heights = [h for h in heights if h is not None]
        max_height = max(valid_heights) if valid_heights else 0.0
        avg_height = sum(valid_heights) / len(valid_heights) if valid_heights else 0.0
        
        result = {
            "tide_level_cm": round(max_height * 100.0, 2),
            "avg_tide_cm": round(avg_height * 100.0, 2),
            "location_type": loc_type,
            "date": event_date
        }
        
        if proxy_used:
            result.update({
                "proxy_station": proxy_used["name"],
                "proxy_distance_km": proxy_used["distance_km"],
                "note": f"Redirected to nearest coastal station: {proxy_used['name']}"
            })
            
        return result
        
    except Exception as e:
        return {"tide_level_cm": 0.0, "location_type": "unknown", "error": str(e)}


@tool
async def get_distance_to_river(lat: float, lon: float) -> Dict[str, any]:
    """Finds the nearest river to a location using OpenStreetMap data.
    
    Uses the Overpass API to query for waterways within a radius.
    Proximity to rivers is a key factor in riverine flood risk.
    
    Args:
        lat: Latitude of the location
        lon: Longitude of the location
        
    Returns:
        Dictionary with distance_m, river_name, and risk interpretation.
    """
    # Search within 5km radius for all types of waterways common in Vietnam
    overpass_url = get_random_overpass_url()
    query = f"""
    [out:json][timeout:60];
    (
      node["waterway"~"river|canal|stream|drain|ditch"](around:5000,{lat},{lon});
      way["waterway"~"river|canal|stream|drain|ditch|riverbank"](around:5000,{lat},{lon});
      relation["waterway"~"river|canal|stream|drain|ditch|riverbank"](around:5000,{lat},{lon});
      way["natural"="water"]["water"~"river|canal|stream|lake"](around:5000,{lat},{lon});
      relation["natural"="water"]["water"~"river|canal|stream|lake"](around:5000,{lat},{lon});
    );
    out geom;
    """
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=5, max=30))
    async def _fetch_overpass():
        async with httpx.AsyncClient() as client:
            response = await client.post(overpass_url, data={"data": query}, timeout=45.0)
            response.raise_for_status()
            return response.json()

    try:
        data = await _fetch_overpass()
        elements = data.get("elements", [])
        
        if not elements:
            return {
                "distance_m": 5000,
                "river_name": "none_found",
                "risk_note": "No river/canal within 5km. Low riverine flood risk."
            }
        
        # Find closest geometry point
        min_dist = float('inf')
        closest_name = "unnamed"
        
        for el in elements:
            # ways have 'geometry', relations have 'members' with 'geometry'
            geom = el.get("geometry", [])
            if not geom and "members" in el:
                for m in el["members"]:
                    geom.extend(m.get("geometry", []))
            
            # Fallback to center if geometry is still missing
            if not geom and "center" in el:
                geom = [el["center"]]
            
            for pt in geom:
                r_lat = pt.get("lat")
                r_lon = pt.get("lon")
                if r_lat is None or r_lon is None:
                    continue
                    
                # Haversine distance
                dlat = math.radians(r_lat - lat)
                dlon = math.radians(r_lon - lon)
                a = math.sin(dlat/2)**2 + math.cos(math.radians(lat)) * math.cos(math.radians(r_lat)) * math.sin(dlon/2)**2
                dist = 6371000 * 2 * math.asin(math.sqrt(a))  # meters
                
                if dist < min_dist:
                    min_dist = dist
                    closest_name = el.get("tags", {}).get("name") or closest_name
        
        # Interpret
        if min_dist < 200:
            risk_note = "Very close to river — high riverine flood risk"
        elif min_dist < 500:
            risk_note = "Near river — moderate riverine flood risk"
        elif min_dist < 1000:
            risk_note = "Within 1km of river — some riverine flood risk"
        else:
            risk_note = "Far from river — low riverine flood risk"
        
        return {
            "distance_m": round(min_dist, 0),
            "river_name": closest_name,
            "risk_note": risk_note
        }
    except Exception as e:
        return {"distance_m": -1, "error": f"Overpass API error: {str(e)}"}


@tool
async def get_catchment_slope(
    lat: float, lon: float, radius_km: float = 5.0
) -> Dict[str, any]:
    """Computes catchment-scale slope for flash flood assessment.

    DISTINCT from get_elevation_slope (100m offset, local hillslope):
    - This tool samples at 2-5km radius → channel/basin gradient
    - Determines how fast water concentrates from hillslopes to channels
    - Critical for flash flood timing (concentration time)

    Reference: Ecological Indicators [2024; DOI: 10.1016/j.ecolind.2023.111595]

    Args:
        lat: Latitude of the assessment point
        lon: Longitude of the assessment point
        radius_km: Sampling radius in km (default 5.0)

    Returns:
        max_slope_deg, mean_slope_deg, channel_slope_deg,
        elevation_drop_m, terrain_class.
    """
    # Sample ~24 points: 8 directions × 3 distances
    distances_km = [radius_km * 0.4, radius_km * 0.7, radius_km]
    coords_lat = [lat]
    coords_lon = [lon]

    for dist_km in distances_km:
        dist_deg = dist_km / 111.32
        for angle_deg in range(0, 360, 45):
            angle_rad = math.radians(angle_deg)
            sample_lat = lat + dist_deg * math.cos(angle_rad)
            sample_lon = lon + dist_deg * math.sin(angle_rad) / math.cos(math.radians(lat))
            coords_lat.append(sample_lat)
            coords_lon.append(sample_lon)

    lats_str = ",".join([f"{c:.6f}" for c in coords_lat])
    lons_str = ",".join([f"{c:.6f}" for c in coords_lon])
    om = get_open_meteo_urls()

    try:
        data = await _fetch_from_api(om['elevation'], params={"latitude": lats_str, "longitude": lons_str})
        elevs = data.get("elevation", [])

        if len(elevs) < 2:
            return {"error": "Insufficient elevation data returned"}

        center_elev = elevs[0]
        sample_elevs = elevs[1:]

        # Calculate slopes between center and each sample point
        slopes = []
        for i, elev in enumerate(sample_elevs):
            dist_idx = i // 8  # which distance ring (0, 1, 2)
            dist_m = distances_km[dist_idx] * 1000
            dz = elev - center_elev
            gradient = abs(dz) / dist_m if dist_m > 0 else 0
            slope_deg = math.degrees(math.atan(gradient))
            slopes.append((slope_deg, elev, dz, dist_m))

        max_slope = max(s[0] for s in slopes)
        mean_slope = sum(s[0] for s in slopes) / len(slopes)
        max_elev = max(s[1] for s in slopes)
        elevation_drop = max_elev - center_elev

        # Channel slope: from highest point to center
        highest = max(slopes, key=lambda s: s[1])
        channel_slope_deg = math.degrees(math.atan(abs(highest[2]) / highest[3])) if highest[3] > 0 else 0

        # Classify terrain at catchment scale
        if channel_slope_deg > 5:
            terrain_class = "steep_mountain"
        elif channel_slope_deg > 2:
            terrain_class = "moderate_hill"
        else:
            terrain_class = "gentle_plain"

        return {
            "max_slope_deg": round(max_slope, 2),
            "mean_slope_deg": round(mean_slope, 2),
            "channel_slope_deg": round(channel_slope_deg, 2),
            "elevation_drop_m": round(elevation_drop, 1),
            "center_elevation_m": round(center_elev, 1),
            "terrain_class": terrain_class,
            "radius_km": radius_km,
            "sample_count": len(sample_elevs) + 1,
            "note": (f"Catchment-scale slope (radius {radius_km}km). "
                     f"For local hillslope gradient, use get_elevation_slope instead.")
        }
    except Exception as e:
        return {"error": f"Catchment slope computation failed: {str(e)}"}
@tool
async def get_nearby_mountain_road(lat: float, lon: float, radius_m: int = 2000) -> Dict[str, any]:
    """Detects mountain roads and passes near a location using OpenStreetMap.
    
    This identifies potential 'cut-slope' (taluy) risks. Road construction on
    slopes creates steep, unstable cuts that are the primary sites for 
    human-induced landslides in Vietnam.
    
    Args:
        lat: Latitude
        lon: Longitude
        radius_m: Search radius in meters (default 2000m)
        
    Returns:
        roads (list), has_mountain_road (bool), and cut_slope_warning.
    """
    overpass_url = get_random_overpass_url()
    # Query for highways and mountain passes
    query = f"""
    [out:json][timeout:30];
    (
      way["highway"~"primary|secondary|tertiary|unclassified|residential"](around:{radius_m},{lat},{lon});
      node["mountain_pass"="yes"](around:{radius_m},{lat},{lon});
    );
    out tags center;
    """
    
    @retry(
        stop=stop_after_attempt(5), 
        wait=wait_exponential(multiplier=2, min=5, max=60), # Wait longer for Overpass
        retry=retry_if_exception(_should_retry)
    )
    async def _fetch_overpass_roads():
        async with httpx.AsyncClient() as client:
            response = await client.post(overpass_url, data={"data": query}, timeout=35.0)
            response.raise_for_status()
            return response.json()

    try:
        data = await _fetch_overpass_roads()
        elements = data.get("elements", [])
        roads = []
        has_pass = False
        
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name", "unnamed")
            highway = tags.get("highway")
            is_pass = tags.get("mountain_pass") == "yes"
            
            if is_pass:
                has_pass = True
                roads.append({"type": "mountain_pass", "name": name})
            elif highway:
                roads.append({"type": f"road_{highway}", "name": name})
                
        # Heuristic: any road in a mountainous region is a potential cut-slope risk
        has_mountain_road = len(roads) > 0
        warning = ""
        if has_mountain_road:
            warning = "CUT_SLOPE_RISK: Road detected on/near steep terrain. " \
                      "May have artificial cut-slopes (taluy) not visible in DEM."
        if has_pass:
            warning += " MOUNTAIN_PASS: High-risk corridor for debris flow."
            
        return {
            "has_mountain_road": has_mountain_road,
            "nearby_roads": roads[:10], # limit to 10
            "road_count": len(roads),
            "cut_slope_warning": warning,
            "source": f"OpenStreetMap_Overpass_{radius_m}m"
        }
    except Exception as e:
        return {
            "has_mountain_road": False,
            "error": str(e),
            "note": "Could not detect nearby roads due to Overpass rate limit or timeout."
        }


@tool
async def get_river_discharge(lat: float, lon: float, event_date: str) -> Dict[str, any]:
    """Retrieves daily river discharge (m3/s) for a given date.
    
    Uses Open-Meteo Global Flood API (GloFAS v4). Provides historical 
    and forecast discharge from 1984 to Present.
    
    Args:
        lat: Latitude of the location
        lon: Longitude of the location
        event_date: Date in YYYY-MM-DD format
        
    Returns:
        Dictionary with river_discharge_m3s.
    """
    from datetime import datetime
    try:
        dt = datetime.strptime(event_date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": f"Invalid date format: {event_date}"}

    url = get_open_meteo_urls()["flood"]
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "river_discharge",
        "start_date": dt.strftime("%Y-%m-%d"),
        "end_date": dt.strftime("%Y-%m-%d"),
        "models": "seamless_v4"
    }

    try:
        data = await _fetch_from_api(url, params)
        daily = data.get("daily", {})
        discharges = daily.get("river_discharge", [])
        
        if not discharges or all(d is None for d in discharges):
            return {
                "river_discharge_m3s": 0.0, 
                "note": "No significant river within 5km of this location.",
                "river_scale": "none"
            }
        
        # Take the maximum discharge for the day (usually only one value for daily)
        valid_q = [q for q in discharges if q is not None]
        max_q = max(valid_q) if valid_q else 0.0
        
        return {
            "river_discharge_m3s": round(max_q, 2),
            "date": event_date,
            "unit": "m3/s",
            "model": "GloFAS v4.0",
            "river_scale": "large" if max_q > 500 else ("medium" if max_q > 50 else "small")
        }
    except httpx.HTTPStatusError as e:
        return {"river_discharge_m3s": 0.0, "error": f"API HTTP Error: {e.response.status_code}"}
    except Exception as e:
        return {"river_discharge_m3s": 0.0, "error": str(e)}
