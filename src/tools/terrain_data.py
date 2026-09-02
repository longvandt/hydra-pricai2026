"""
Static terrain and geospatial data tools for disaster analysis.

These tools retrieve pre-computed or slow-changing geophysical datasets.
They are lead-time invariant — their values do not change with forecast horizon.

Tools:
- get_imperviousness: GHSL Built-up surface → runoff amplification
- get_twi: MERIT Hydro → water accumulation tendency
- get_catchment_info: HydroBASINS → catchment characteristics
"""

import math
import os
import logging
from typing import Dict
from langchain_core.tools import tool
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from config import get_open_meteo_urls, get_random_overpass_url

logger = logging.getLogger(__name__)

# ============================================================================
# Data paths (relative to this file)
# ============================================================================
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# ============================================================================
# GEE Initialization — lazy, once per process
# ============================================================================

_gee_initialized = False
_gee_available = False


def _init_gee():
    """
    Lazy-initialize Google Earth Engine (once per process).

    Auth priority:
    1. Credentials in ~/.config/earthengine/credentials (interactive auth)
    2. GOOGLE_APPLICATION_CREDENTIALS env var (service account JSON)

    Call `earthengine authenticate` in terminal once to create credentials.
    """
    global _gee_initialized, _gee_available
    if _gee_initialized:
        return _gee_available

    try:
        import sys
        import ee

        # Resolve project ID: env var > streamlit secrets > fallback
        project_id = os.environ.get("GEE_PROJECT_ID")

        # Only try streamlit if env var is missing
        if not project_id:
            try:
                # Check if we are actually running inside streamlit before importing
                if 'streamlit' in sys.modules or os.environ.get('STREAMLIT_SERVER_PORT'):
                    import streamlit as st
                    project_id = st.secrets.get("GEE_PROJECT_ID") or st.secrets.get("VERTEX_PROJECT_ID")
            except Exception:
                pass

        if not project_id:
            project_id = "gen-lang-client-0397804618"  # current user's active project

        ee.Initialize(project=project_id)
        _gee_available = True
        logger.info(f"GEE initialized successfully (project={project_id})")
    except Exception as e:
        _gee_available = False
        logger.warning(f"GEE not available: {e}. Will use Open-Meteo SRTM as fallback.")

    _gee_initialized = True
    return _gee_available


def _get_fabdem_elevation(lat: float, lon: float) -> float:
    """
    Query FABDEM bare-earth elevation from Google Earth Engine.

    FABDEM = Forest And Buildings removed Copernicus DEM.
    - Removes vegetation canopy (critical for mangrove zones like Cà Mau)
    - Removes building footprints
    - Based on Copernicus GLO-30 (30m resolution)
    - Published: Hawker et al. (2022), doi:10.1088/1748-9326/ac4d4f

    Accuracy improvement over SRTM in Vietnam:
    - Mangrove zones (ĐBSCL coast): SRTM +4–8m bias → FABDEM ±0.5m
    - Rice paddy plains: SRTM +1–2m bias → FABDEM ±0.5m
    - Urban areas: SRTM +2–5m bias → FABDEM ±0.8m
    """
    import ee

    point = ee.Geometry.Point([lon, lat])

    # FABDEM Community Dataset on GEE (Samapriya Roy's open-datasets)
    fabdem = ee.ImageCollection("projects/sat-io/open-datasets/FABDEM")

    # Sample at the point, 30m scale
    result = fabdem.mosaic().sample(
        region=point,
        scale=30,
        geometries=False
    ).first()

    elev = result.get("b1").getInfo()  # b1 is the elevation band

    if elev is None:
        raise ValueError("FABDEM returned null elevation — point may be outside coverage")

    return float(elev)


# ============================================================================
# Imperviousness — GHSL GHS-BUILT-S
# ============================================================================

@tool
async def get_imperviousness(
    lat: float, lon: float, year: int = 2025, radius_m: int = 500
) -> Dict[str, any]:
    """Retrieves the fraction of impervious (built-up) surface around a coordinate.

    Used as a rainfall runoff amplification factor: more concrete = more runoff.

    Source (planned): GHSL GHS-BUILT-S R2023A (continuous fraction, 100m resolution,
    12 temporal epochs from 1975 to 2030).

    Current implementation: Estimates imperviousness from land cover classification
    via OpenStreetMap landuse data as a proxy until GHSL GeoTIFF is downloaded.

    Scientific basis:
    - Kontgis et al. [2014; DOI: 10.1016/j.apgeog.2014.06.029]
    - Dang & Kumar [2017; DOI: 10.1080/19475705.2017.1388853]

    Formula: α(IMP) = IMP_current / IMP_baseline
    where IMP_baseline = 60.0 (percent scale; HCMC average imperviousness in 2010, calibration year)

    Args:
        lat: Latitude center point
        lon: Longitude center point
        year: Year for temporal query (snapped to nearest GHSL epoch)
        radius_m: Averaging radius in meters (default 500m)

    Returns:
        imperviousness_pct, alpha_modifier, epoch_used, source.
    """
    # ── Primary: GHSL via GEE ──────────────────────────────────────────────
    if _init_gee():
        try:
            res = _get_gee_imperviousness(lat, lon)
            imp_pct = res['pct']

            # IMP_baseline = 60.0 (percent scale) = HCMC 2010 average (Ho Long Phi 2012)
            # imp_pct is in percent units (0–100), so divide by 60.0 not 0.60
            baseline = 60.0
            alpha = imp_pct / baseline if baseline > 0 else 1.0
            alpha = max(0.5, min(alpha, 2.5))

            return {
                "imperviousness_pct": round(imp_pct, 3),
                "alpha_modifier": round(alpha, 3),
                "epoch_used": res['epoch'],
                "source": "GHSL_GEE_P2023A",
                "method": "gee_ghsl_lookup",
                "radius_m": radius_m,
                "note": f"Built-up fraction {imp_pct:.1f}% from GHSL P2023A (GEE)."
            }
        except Exception as e:
            logger.warning(f"GHSL/GEE query failed ({e}). Falling back to local/OSM.")

    # ── Secondary: Local GeoTIFF ───────────────────────────────────────────
    ghsl_dir = os.path.join(_DATA_DIR, "ghsl")
    if os.path.isdir(ghsl_dir):
        try:
            return await _query_ghsl_geotiff(lat, lon, year, radius_m, ghsl_dir)
        except Exception as e:
            logger.warning(f"GHSL GeoTIFF query failed: {e}. Falling back to OSM proxy.")

    # ── Tertiary: OSM Proxy ────────────────────────────────────────────────
    return await _estimate_imperviousness_osm(lat, lon, radius_m)


def _get_gee_imperviousness(lat: float, lon: float) -> dict:
    """Query GHSL P2023A Built-up Surface from GEE."""
    import ee
    point = ee.Geometry.Point([lon, lat])

    # GHSL P2023A - Built-up surface fraction
    # Try 2020 as preferred epoch
    dataset = ee.ImageCollection("JRC/GHSL/P2023A/GHS_BUILT_S")
    image = dataset.filter(ee.Filter.eq('system:index', '2020')).first()

    # Sample at point
    data = image.sample(point, 100).first()

    try:
        pixel_info = data.getInfo()
    except Exception:
        # Fallback to the latest available if 2020 fails
        image = dataset.sort('system:time_start', False).first()
        data = image.sample(point, 100).first()
        pixel_info = data.getInfo()

    pixel_val = pixel_info['properties'].get('built_surface')
    if pixel_val is None:
        raise ValueError("GHSL 'built_surface' band not found in result")

    return {
        "pct": float(pixel_val) / 100.0,
        "epoch": "2020-2025"
    }


async def _query_ghsl_geotiff(lat, lon, year, radius_m, ghsl_dir):
    """Query pre-downloaded GHSL GeoTIFF for imperviousness."""
    try:
        import rasterio
        from rasterio.transform import rowcol
        import numpy as np

        # GHSL epochs: 1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025, 2030
        epochs = [1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020, 2025, 2030]
        epoch = min(epochs, key=lambda e: abs(e - year))

        # Find the appropriate tile
        tif_files = [f for f in os.listdir(ghsl_dir) if f.endswith('.tif') and str(epoch) in f]
        if not tif_files:
            raise FileNotFoundError(f"No GHSL tile for epoch {epoch}")

        with rasterio.open(os.path.join(ghsl_dir, tif_files[0])) as src:
            row, col = rowcol(src.transform, lon, lat)
            # Read a window around the point
            pixel_size_m = 100  # GHSL resolution
            px_radius = max(1, radius_m // pixel_size_m)
            window = rasterio.windows.Window(
                col - px_radius, row - px_radius, 2 * px_radius + 1, 2 * px_radius + 1
            )
            data = src.read(1, window=window)
            imp_pct = float(np.nanmean(data)) / 100.0  # GHSL gives 0-100

        # IMP_baseline = 60.0 (percent scale) = HCMC 2010 average (Ho Long Phi 2012)
        baseline = 60.0
        alpha = imp_pct / baseline if baseline > 0 else 1.0
        alpha = max(0.5, min(alpha, 2.5))

        return {
            "imperviousness_pct": round(imp_pct, 3),
            "alpha_modifier": round(alpha, 3),
            "epoch_used": epoch,
            "source": "GHSL_GHS_BUILT_S_R2023A",
            "radius_m": radius_m
        }
    except ImportError:
        raise RuntimeError("rasterio not installed")


async def _estimate_imperviousness_osm(lat, lon, radius_m):
    """Estimate imperviousness from OpenStreetMap landuse as a proxy."""
    overpass_url = get_random_overpass_url()
    query = f"""
    [out:json][timeout:30];
    (
      way["landuse"~"residential|commercial|industrial|retail"](around:{radius_m},{lat},{lon});
      way["building"](around:{radius_m},{lat},{lon});
      way["highway"~"primary|secondary|tertiary|motorway"](around:{radius_m},{lat},{lon});
    );
    out count;
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(overpass_url, data={"data": query}, timeout=30.0)
            response.raise_for_status()
            data = response.json()

        total_elements = data.get("elements", [{}])[0].get("tags", {}).get("total", "0") if data.get("elements") else "0"
        count = int(total_elements) if total_elements else len(data.get("elements", []))

        # Heuristic mapping: element density → imperviousness
        # Dense urban: >100 elements/500m → ~90%
        # Suburban: 30-100 → ~60%
        # Rural: <30 → ~20%
        if count > 100:
            imp_pct = min(0.95, 0.70 + count * 0.002)
        elif count > 30:
            imp_pct = 0.40 + (count - 30) * 0.004
        elif count > 5:
            imp_pct = 0.15 + (count - 5) * 0.01
        else:
            imp_pct = 0.10

        # IMP_baseline = 60.0 (percent scale) = HCMC 2010 average (Ho Long Phi 2012)
        baseline = 60.0
        alpha = imp_pct / baseline
        alpha = max(0.5, min(alpha, 2.5))

        return {
            "imperviousness_pct": round(imp_pct, 3),
            "alpha_modifier": round(alpha, 3),
            "epoch_used": "current",
            "source": "OSM_proxy_estimate",
            "radius_m": radius_m,
            "osm_element_count": count,
            "note": "Estimated from OpenStreetMap land use density. "
                    "For precise values, download GHSL GHS-BUILT-S GeoTIFF."
        }
    except Exception as e:
        # Return neutral default
        return {
            "imperviousness_pct": 0.60,
            "alpha_modifier": 1.0,
            "epoch_used": "default",
            "source": "fallback_default",
            "error": str(e),
            "note": "Could not estimate imperviousness. Using HCMC baseline default (60%)."
        }


# ============================================================================
# Topographic Wetness Index — MERIT Hydro
# ============================================================================

@tool
async def get_twi(lat: float, lon: float) -> Dict[str, any]:
    """Retrieves the Topographic Wetness Index (TWI) at a coordinate.

    TWI = ln(a / tan(β)), where a = specific catchment area, β = local slope.
    High TWI → natural depression that accumulates water.
    Low TWI → ridge/hilltop that drains well.

    Source (planned): Pre-computed from MERIT Hydro [Yamazaki et al., 2019]
    — hydrologically conditioned DEM at 90m resolution.

    Current implementation: Computes TWI from elevation grid using
    Open-Meteo Elevation API as a proxy.

    Scientific basis:
    - Tran et al. [2024; DOI: 10.2166/wcc.2024.035]: TWI is top-5 feature
      in flood susceptibility models for Vietnam (AUC > 0.9)
    - Pham et al. [2024; DOI: 10.1007/s12145-024-01285-8]: TWI + 11 features
      → Deep 1D-CNN achieves AUC 0.94 for flash flood

    TWI modifier: twi_mod = 1.0 + 0.3 × (TWI - TWI_baseline) / TWI_baseline
    where TWI_baseline = 9.0 (average for urban HCMC), capped at [0.7, 1.3].

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        twi_value, twi_modifier, interpretation.
    """
    # ── Primary: MERIT Hydro via GEE ────────────────────────────────────────
    if _init_gee():
        try:
            twi = _get_gee_twi(lat, lon)

            twi_baseline = 9.0
            twi_mod = 1.0 + 0.3 * (twi - twi_baseline) / twi_baseline
            twi_mod = max(0.7, min(twi_mod, 1.3))

            return {
                "twi_value": round(twi, 2),
                "twi_modifier": round(twi_mod, 3),
                "interpretation": _interpret_twi(twi),
                "source": "MERIT_Hydro_GEE",
                "method": "gee_merit_twi_calc",
                "note": "Topographic Wetness Index calculated from MERIT Hydro (90m, Cloud)."
            }
        except Exception as e:
            logger.warning(f"MERIT/GEE query failed ({e}). Falling back to local/proxy.")

    # ── Secondary: Local TWI Raster ─────────────────────────────────────────
    twi_tif = os.path.join(_DATA_DIR, "twi_vietnam.tif")
    if os.path.exists(twi_tif):
        try:
            return _query_twi_raster(lat, lon, twi_tif)
        except Exception as e:
            logger.warning(f"TWI raster query failed: {e}. Falling back to elevation-based estimate.")

    # ── Tertiary: Proxy Estimate ───────────────────────────────────────────
    return await _compute_twi_from_elevation(lat, lon)


def _get_gee_twi(lat: float, lon: float) -> float:
    """Calculate TWI from MERIT Hydro and Slope in GEE."""
    import ee
    point = ee.Geometry.Point([lon, lat])
    merit = ee.Image("MERIT/Hydro/v1_0_1")

    # Select upstream area (upa) in km2
    upa_img = merit.select('upa')
    # Calculate slope from elevation (elv)
    slope_img = ee.Terrain.slope(merit.select('elv'))

    # Sample both at the point (90m resolution)
    combined = upa_img.addBands(slope_img)
    data = combined.sample(point, 90).first()
    info = data.getInfo()

    if not info or 'properties' not in info:
        raise ValueError("MERIT Hydro data not found at this location")

    upa_km2 = float(info['properties'].get('upa', 0.01))
    slope_deg = float(info['properties'].get('slope', 0.1))

    # TWI = ln(a / tan(beta))
    # a = contributing area per unit contour length (~90m)
    a = (upa_km2 * 1_000_000) / 90.0
    tan_beta = math.tan(math.radians(max(0.01, slope_deg)))
    twi = math.log(a / tan_beta)

    # Clamp to reasonable range [2, 20]
    return max(2.0, min(twi, 20.0))


def _interpret_twi(twi: float) -> str:
    """Qualitative interpretation of TWI values."""
    if twi > 12:
        return "depression — high water accumulation"
    elif twi > 9:
        return "flat — moderate accumulation"
    elif twi > 6:
        return "slope — limited accumulation"
    else:
        return "ridge — good drainage"


def _query_twi_raster(lat, lon, twi_tif):
    """Query pre-computed TWI raster."""
    import rasterio
    from rasterio.transform import rowcol

    with rasterio.open(twi_tif) as src:
        row, col = rowcol(src.transform, lon, lat)
        twi = float(src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])

    if twi < 0 or twi > 30:
        twi = 9.0  # fallback to baseline

    twi_baseline = 9.0
    twi_mod = 1.0 + 0.3 * (twi - twi_baseline) / twi_baseline
    twi_mod = max(0.7, min(twi_mod, 1.3))

    if twi > 12:
        interpretation = "depression — high water accumulation"
    elif twi > 9:
        interpretation = "flat — moderate accumulation"
    elif twi > 6:
        interpretation = "slope — limited accumulation"
    else:
        interpretation = "ridge — good drainage"

    return {
        "twi_value": round(twi, 2),
        "twi_modifier": round(twi_mod, 3),
        "interpretation": interpretation,
        "source": "MERIT_Hydro_precomputed"
    }


async def _compute_twi_from_elevation(lat, lon):
    """Approximate TWI from elevation grid using Open-Meteo Elevation API.

    Method: Sample a 3×3 grid (300m spacing), compute local slope and
    approximate flow accumulation from surrounding terrain gradients.
    """
    spacing = 0.003  # ~333m in degrees

    # 3×3 grid centered on the point
    coords_lat = []
    coords_lon = []
    for di in [-1, 0, 1]:
        for dj in [-1, 0, 1]:
            coords_lat.append(lat + di * spacing)
            coords_lon.append(lon + dj * spacing)

    lats_str = ",".join([f"{c:.6f}" for c in coords_lat])
    lons_str = ",".join([f"{c:.6f}" for c in coords_lon])

    om = get_open_meteo_urls()
    url = f"{om['elevation']}?latitude={lats_str}&longitude={lons_str}"
    if om["api_key"]:
        url += f"&apikey={om['api_key']}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            data = response.json()

        elevs = data.get("elevation", [])
        if len(elevs) < 9:
            return _default_twi_result()

        center_elev = elevs[4]  # center of 3×3 grid
        dist_m = spacing * 111320  # approximate meters

        # Calculate slope at center using 4-neighbor
        dz_dx = (elevs[5] - elevs[3]) / (2 * dist_m)
        dz_dy = (elevs[1] - elevs[7]) / (2 * dist_m)
        slope_rad = math.atan(math.sqrt(dz_dx**2 + dz_dy**2))

        # Approximate flow accumulation: count neighbors higher than center
        higher_count = sum(1 for e in elevs if e > center_elev)
        # Approximate contributing area (cells draining toward center)
        cell_area = dist_m * dist_m
        contributing_area = max(cell_area, higher_count * cell_area)
        specific_area = contributing_area / dist_m  # per unit contour length

        # TWI = ln(a / tan(β))
        tan_slope = max(math.tan(slope_rad), 0.001)  # avoid log(inf)
        twi = math.log(specific_area / tan_slope)

        # Clamp to reasonable range
        twi = max(2.0, min(twi, 20.0))

        twi_baseline = 9.0
        twi_mod = 1.0 + 0.3 * (twi - twi_baseline) / twi_baseline
        twi_mod = max(0.7, min(twi_mod, 1.3))

        if twi > 12:
            interpretation = "depression — high water accumulation"
        elif twi > 9:
            interpretation = "flat — moderate accumulation"
        elif twi > 6:
            interpretation = "slope — limited accumulation"
        else:
            interpretation = "ridge — good drainage"

        return {
            "twi_value": round(twi, 2),
            "twi_modifier": round(twi_mod, 3),
            "interpretation": interpretation,
            "source": "elevation_proxy_estimate",
            "center_elevation_m": round(center_elev, 1),
            "note": "Approximate TWI from 3×3 elevation grid. "
                    "For precise values, use MERIT Hydro pre-computed raster."
        }
    except Exception as e:
        return _default_twi_result(error=str(e))


def _default_twi_result(error=None):
    """Default TWI when computation fails."""
    result = {
        "twi_value": 9.0,
        "twi_modifier": 1.0,
        "interpretation": "unknown — using baseline default",
        "source": "fallback_default",
        "note": "Could not compute TWI. Using urban baseline default (9.0)."
    }
    if error:
        result["error"] = error
    return result


# ============================================================================
# Catchment Info — HydroBASINS
# ============================================================================

_hb_gdf = None

def _load_hydrobasins(hybas_dir):
    """Lazy-load and cache the HydroBASINS GeoDataFrame with spatial index."""
    global _hb_gdf
    if _hb_gdf is not None:
        return _hb_gdf

    import geopandas as gpd
    import os

    shp_files = [f for f in os.listdir(hybas_dir) if f.endswith('.shp')]
    if not shp_files:
        _hb_gdf = "missing"
        return _hb_gdf

    shp_path = os.path.join(hybas_dir, shp_files[0])
    try:
        # Using pyogrio if available for 10x faster loading
        engine = 'pyogrio'
        try:
            import pyogrio
        except ImportError:
            engine = 'fiona'

        gdf = gpd.read_file(shp_path, engine=engine)
        # Ensure it has a spatial index for O(log N) lookups
        _ = gdf.sindex
        _hb_gdf = gdf
        logger.info(f"Loaded HydroBASINS Asia: {len(gdf)} sub-basins")
    except Exception as e:
        logger.error(f"Failed to load HydroBASINS shapefile: {e}")
        _hb_gdf = "missing"

    return _hb_gdf


@tool
async def get_catchment_info(lat: float, lon: float) -> Dict[str, any]:
    """Identifies which hydrological basin a coordinate falls within.

    Returns catchment characteristics for flood type routing:
    - Small steep catchment → flash flood risk
    - Large downstream basin → riverine flood risk
    - Delta position → compound flooding risk

    Source (planned): HydroBASINS Level 12 [Lehner & Grill, 2013]
    — finest delineation (~10-100 km² basins).

    Current implementation: Estimates from terrain analysis and river proximity
    using Open-Meteo and OpenStreetMap as proxies.

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        catchment_area_km2, upstream_area_km2, position_in_basin,
        flood_receiving (bool).
    """
    # Check for pre-downloaded HydroBASINS shapefile
    hybas_dir = os.path.join(_DATA_DIR, "hydrobasins")
    if os.path.isdir(hybas_dir):
        try:
            gdf = _load_hydrobasins(hybas_dir)
            if gdf is not None and not isinstance(gdf, str):
                return _query_hydrobasins_fast(lat, lon, gdf)
            elif gdf == "missing":
                logger.info("HydroBASINS data files not found in directory.")
        except Exception as e:
            logger.warning(f"HydroBASINS tool failed: {e}. Falling back to estimate.")

    # Fallback: estimate from elevation analysis
    return await _estimate_catchment_info(lat, lon)


def _query_hydrobasins_fast(lat, lon, gdf):
    """Query the pre-loaded HydroBASINS GeoDataFrame using spatial index."""
    from shapely.geometry import Point

    point = Point(lon, lat)

    # Fast spatial query using direct call to spatial index
    # We want to find the polygon that contains the point
    potential_indices = gdf.sindex.query(point, predicate="contains")

    if len(potential_indices) == 0:
        # If not contained, find the nearest polygon
        nearest_idx = gdf.sindex.nearest(point, return_all=False)[1]
        row = gdf.iloc[nearest_idx[0]]
    else:
        row = gdf.iloc[potential_indices[0]]

    sub_area = float(row.get('SUB_AREA', 50))
    up_area = float(row.get('UP_AREA', 100))

    # Classify position
    ratio = up_area / sub_area if sub_area > 0 else 1
    if ratio < 2:
        position = "headwater"
    elif ratio < 10:
        position = "midstream"
    elif ratio < 50:
        position = "downstream"
    else:
        position = "delta"

    flood_receiving = up_area > 500

    return {
        "catchment_area_km2": round(sub_area, 1),
        "upstream_area_km2": round(up_area, 1),
        "hybas_id": int(row.get('HYBAS_ID', 0)),
        "position_in_basin": position,
        "flood_receiving": flood_receiving,
        "source": "HydroBASINS_Level12_Cached"
    }


async def _estimate_catchment_info(lat, lon):
    """Estimate catchment info from terrain analysis."""
    # Use elevation data to estimate catchment characteristics
    spacing_km = 5.0
    spacing_deg = spacing_km / 111.32

    coords_lat = []
    coords_lon = []
    # Sample in 8 directions at 5km
    for angle_deg in range(0, 360, 45):
        angle_rad = math.radians(angle_deg)
        coords_lat.append(lat + spacing_deg * math.cos(angle_rad))
        coords_lon.append(lon + spacing_deg * math.sin(angle_rad) / math.cos(math.radians(lat)))

    # Add center
    coords_lat.insert(0, lat)
    coords_lon.insert(0, lon)

    lats_str = ",".join([f"{c:.6f}" for c in coords_lat])
    lons_str = ",".join([f"{c:.6f}" for c in coords_lon])
    om = get_open_meteo_urls()
    url = f"{om['elevation']}?latitude={lats_str}&longitude={lons_str}"
    if om["api_key"]:
        url += f"&apikey={om['api_key']}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            data = response.json()

        elevs = data.get("elevation", [])
        if len(elevs) < 9:
            return _default_catchment_result()

        center_elev = elevs[0]
        surrounding_elevs = elevs[1:]

        # Count how many surrounding points are higher → rough upstream area proxy
        higher = sum(1 for e in surrounding_elevs if e > center_elev)
        max_elev = max(surrounding_elevs)
        elev_range = max_elev - center_elev

        # Heuristic estimation
        if elev_range < 10:
            # Flat area — likely delta or plain
            est_catchment = 500.0
            est_upstream = 5000.0
            position = "delta" if center_elev < 5 else "downstream"
        elif elev_range < 50:
            est_catchment = 100.0
            est_upstream = 500.0
            position = "midstream"
        elif elev_range < 200:
            est_catchment = 30.0
            est_upstream = 100.0
            position = "midstream"
        else:
            est_catchment = 10.0
            est_upstream = 30.0
            position = "headwater"

        flood_receiving = est_upstream > 500

        return {
            "catchment_area_km2": round(est_catchment, 1),
            "upstream_area_km2": round(est_upstream, 1),
            "position_in_basin": position,
            "flood_receiving": flood_receiving,
            "center_elevation_m": round(center_elev, 1),
            "elevation_range_5km_m": round(elev_range, 1),
            "source": "elevation_proxy_estimate",
            "note": "Estimated from elevation analysis. "
                    "For precise values, download HydroBASINS Level 12 shapefile."
        }
    except Exception as e:
        return _default_catchment_result(error=str(e))


def _default_catchment_result(error=None):
    """Default catchment info when estimation fails."""
    result = {
        "catchment_area_km2": 50.0,
        "upstream_area_km2": 200.0,
        "position_in_basin": "unknown",
        "flood_receiving": False,
        "source": "fallback_default",
        "note": "Could not estimate catchment info. Using moderate defaults."
    }
    if error:
        result["error"] = error
    return result
