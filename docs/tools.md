# Tool inventory

Every tool wired into the live agent graph, and nothing else. The authoritative source is `FLOOD_TOOLS` (16 tools) and `LANDSLIDE_TOOLS` (9 tools) in `react_agent/graph.py`, re-verified directly against that file for this document. All 19 distinct tools across both lists are documented below with their exact Python signature, the agent(s) that call them, the data source, and what they return.

Two tools defined in the source tree (`get_soil_type`, `get_vegetation_index` in `terrain_data.py`) and four calculators (`calculate_landslide_risk`, `calculate_slope_stability`, `calculate_id_threshold`, `calculate_debris_flow_initiation` in `calculator.py`) are **not** documented here: none of them appear in `FLOOD_TOOLS` or `LANDSLIDE_TOOLS`, so the agent can never call them. They are deliberately pruned from this release.

Every tool is decorated with `@tool` from `langchain_core.tools`. All Layer 2 (data retrieval) functions are `async def`; all four Layer 1 (calculator) functions are plain synchronous `def` — they perform no I/O.

**Agent column**: F = flood agent only, L = landslide agent only, F, L = both.

## Overview

| Tool | Agent | Layer | Module | Data source |
|---|---|---|---|---|
| `get_historical_rainfall` | F, L | 2 | weather.py | Open-Meteo Archive API (ERA5) |
| `get_rainfall_forecast` | F, L | 2 | weather.py | Open-Meteo Forecast API |
| `get_rainfall_after_event` | F, L | 2 | weather.py | Open-Meteo Archive API (ERA5) |
| `get_soil_moisture` | F, L | 2 | weather.py | Open-Meteo Archive API (ERA5-Land) |
| `get_antecedent_precipitation_index` | F, L | 2 | weather.py | Open-Meteo Archive API (ERA5, computed) |
| `get_elevation_slope` | F, L | 2 | geo_data.py | Supabase cache → Open-Meteo Elevation → OpenTopoData SRTM30m → OpenTopoData ASTER30m |
| `get_terrain_profile` | L | 2 | geo_data.py | Open-Meteo Elevation API (grid-sampled) |
| `get_catchment_slope` | F | 2 | geo_data.py | Open-Meteo Elevation API (radial-sampled) |
| `get_historical_tide_level` | F | 2 | geo_data.py | Open-Meteo Marine API + 35-station tidal proxy table |
| `get_distance_to_river` | F | 2 | geo_data.py | OpenStreetMap Overpass API |
| `get_nearby_mountain_road` | L | 2 | geo_data.py | OpenStreetMap Overpass API |
| `get_river_discharge` | F | 2 | geo_data.py | Open-Meteo Flood API (GloFAS v4) |
| `get_imperviousness` | F | 2 | terrain_data.py | GHSL GHS-BUILT-S (GEE) → local GeoTIFF → OSM proxy → hardcoded default |
| `get_twi` | F | 2 | terrain_data.py | MERIT Hydro (GEE) → local raster → elevation-grid proxy → hardcoded default |
| `get_catchment_info` | F | 2 | terrain_data.py | HydroBASINS shapefile (if present) → elevation-based estimate |
| `calculate_flash_flood_risk` | F | 1 | calculator.py | pure function (no I/O) |
| `calculate_river_water_level` | F | 1 | calculator.py | pure function (no I/O) |
| `calculate_hybrid_api` | F | 1 | calculator.py | pure function (no I/O) |
| `calculate_doyin_threshold` | L | 1 | calculator.py | pure function (no I/O) |

---

## Layer 2 — Meteorological (`react_agent/tools/weather.py`)

### `get_historical_rainfall(lat: float, lon: float, event_date: str, days_before: int = 3) -> Dict[str, any]`

- **Agent:** F, L
- **Source:** Open-Meteo Archive API (`archive-api.open-meteo.com/v1/archive` or the `customer-archive-` paid endpoint if `OPEN_METEO_API_KEY` is set), `models=era5` (Hersbach et al. 2020 reanalysis, data from 1940–present). Hourly `rain` and daily `rain_sum`.
- **Returns:** `total_mm`, `max_1h_mm`, `max_2h_mm`, `max_3h_mm`, `max_6h_mm`, `max_12h_mm`, `max_24h_mm` (all computed via a sliding-window-max helper over the hourly series), `daily_breakdown` (list of `{date, rain_mm}`), `period`, `days`.
- Fetches N days before `event_date` (default 3). Peak windows matter because urban flooding responds to short (2h) bursts while flash floods and landslides respond to longer (6h–24h) accumulation.

### `get_rainfall_forecast(lat: float, lon: float, hours: int = 24) -> Dict[str, any]`

- **Agent:** F, L
- **Source:** Open-Meteo Forecast API (`api.open-meteo.com/v1/forecast`), hourly `rain`, `forecast_days=2`.
- **Returns:** `total_mm`, `period_hours`.
- Used for real-time/lead-time-positive scenarios, as opposed to historical hindcast analysis.

### `get_rainfall_after_event(lat: float, lon: float, event_date: str, hours: int = 24) -> Dict[str, any]`

- **Agent:** F, L
- **Source:** Open-Meteo Archive API (ERA5), hourly `rain`, spanning from `event_date` through `event_date + ceil(hours/24)` days.
- **Returns:** `total_mm`, `period_hours`, `note`.
- Simulates what a forecast would have shown, using the actual recorded post-event rainfall — used as a "perfect forecast" proxy in hindcast evaluation. For the landslide agent this window is also the trigger-day rainfall input to `calculate_doyin_threshold`.

### `get_soil_moisture(lat: float, lon: float, event_date: str) -> Dict[str, any]`

- **Agent:** F, L
- **Source:** Open-Meteo Archive API, daily `soil_moisture_0_to_7cm_mean` (ERA5-Land HTESSEL land-surface model, surface layer 0–7cm).
- **Returns:** `soil_moisture_m3_per_m3` (rounded to 4dp), `saturation`, `date`. If the single-day value is missing, returns `{"soil_moisture_m3_per_m3": None, "saturation": "unknown", "note": "Data unavailable"}` — no `"error"` key in that case.
- Saturation classification (in the tool itself, distinct from any calculator-level threshold): `sm > 0.4` → `"saturated"`; `sm > 0.3` → `"wet"`; `sm > 0.2` → `"moist"`; else `"dry"`.

### `get_antecedent_precipitation_index(lat: float, lon: float, event_date: str, days: int = 7, decay: float = 0.85) -> Dict[str, any]`

- **Agent:** F, L
- **Source:** Open-Meteo Archive API, daily `rain_sum` over the `days` days preceding `event_date` (the event day itself is excluded from the query window).
- **Returns:** `api_value` (mm, rounded 2dp), `interpretation`, `decay_factor`, `period_days`, `total_rainfall_mm`, `daily_breakdown`.
- Formula: `API = Σ k^i · P_i` for `i = 0..days-1`, most recent day weighted `k^0 = 1.0`, `k = 0.85` by default (Kohler & Linsley 1951 decay factor). Interpretation bands: `> 50mm` → `very_high_saturation`; `> 30mm` → `high_saturation`; `> 15mm` → `moderate_saturation`; else `low_saturation`.

---

## Layer 2 — Terrain & Geospatial (`react_agent/tools/geo_data.py`)

### `get_elevation_slope(lat: float, lon: float) -> Dict[str, any]`

- **Agent:** F, L — the first tool called by both agents.
- **Source:** Multi-provider fallback chain, tried in order: (1) Supabase table `elevation_slope_cache` keyed on lat/lon rounded to 4dp (~11m); (2) Open-Meteo Elevation API (SRTM-based, ~90m); (3) OpenTopoData `srtm30m`; (4) OpenTopoData `aster30m` (independent dataset). All providers use a 5-point stencil (center, N, S, E, W at ~100m/0.0009° offset).
- **Returns:** `elevation` (m, 2dp), `slope` (degrees, 2dp), `terrain` (`"mountain"` if slope > 15°, `"hilly"` if > 5°, else `"plain"`), `source` (which provider answered, or `"cache"`). A successful non-cache result is written back to the Supabase cache (best-effort, failure is silent).
- **On total failure** (all four sources exhausted): returns `{"error": ..., "slope": None, "elevation": None, "terrain": "unknown", "data_quality": "unavailable", "agent_instruction": "STOP: Slope data unavailable. Per protocol STEP 1d, conclude Risk Level = NONE with INCOMPLETE_DATA flag. DO NOT call calculate_landslide_risk or rainfall tools."}` — the tool embeds an explicit agent-facing stop instruction in its own output. (Note: the referenced `calculate_landslide_risk` is the deprecated, unregistered calculator — the instruction text predates its removal from the tool list; the operative directive for a released agent is the "STOP" / "INCOMPLETE_DATA" part.)

### `get_terrain_profile(min_lat: float, max_lat: float, min_lon: float, max_lon: float, grid_size: int = 5) -> Dict[str, any]`

- **Agent:** L
- **Source:** Open-Meteo Elevation API, sampled on a `grid_size × grid_size` lattice (default 25 points) across the given bounding box; slope at each point computed via the same 4-neighbor finite-difference method as `get_elevation_slope` (single-provider, no fallback chain, no cache).
- **Returns:** `max_slope`, `avg_slope`, `elevation_range` (`{min, max}`), `terrain`, `sample_count`, `note`.
- Used to find the steepest section within an area (e.g. around a geocoded event) rather than trusting a single potentially-offset point.

### `get_catchment_slope(lat: float, lon: float, radius_km: float = 5.0) -> Dict[str, any]`

- **Agent:** F
- **Source:** Open-Meteo Elevation API, 24 points sampled at 8 compass directions × 3 radii (`0.4×`, `0.7×`, `1.0×` of `radius_km`), plus the center point (25 total).
- **Returns:** `max_slope_deg`, `mean_slope_deg`, `channel_slope_deg` (slope from the single highest sampled point to the center — used as the channel gradient proxy), `elevation_drop_m`, `center_elevation_m`, `terrain_class` (`"steep_mountain"` if channel slope > 5°, `"moderate_hill"` if > 2°, else `"gentle_plain"`), `radius_km`, `sample_count`, `note`.
- Distinct from `get_elevation_slope`'s local hillslope gradient (~100m) — this is the catchment/basin-scale gradient governing concentration time for flash floods.

### `get_historical_tide_level(lat: float, lon: float, event_date: str, elevation_m: float = None) -> Dict[str, any]`

- **Agent:** F
- **Source:** Open-Meteo Marine API, hourly `sea_level_height_msl`. If the direct query returns no usable marine data (inland point, or a 400 response), falls back to the **Nearest Coastal Proxy** system: a hardcoded table of 35 tidal stations across Vietnam (source: tidechecker.com, PSMSL, IOC), querying the nearest one within 190km (chosen so Mekong Delta points ~190km inland, e.g. Tân Châu/Châu Đốc, still resolve to a proxy).
- **Elevation gate:** if `elevation_m` is passed and `> 10.0`, the tool short-circuits and returns `tide_level_cm=0.0`, `location_type="highlands"` without any API call.
- **Returns:** `tide_level_cm` (peak of the 24h window, ×100 to cm), `avg_tide_cm`, `location_type` (`"coastal"`, `"nearest_coastal_proxy"`, `"inland"`, `"highlands"`, or `"unknown"`), `date`; when a proxy was used, also `proxy_station`, `proxy_distance_km`, `note`.
- The docstring notes storm surge (50–200cm above astronomical tide during typhoons) is **not** captured — there is no storm-surge field or flag in the returned dict; this is a narrative caveat only, not a machine-readable output.

### `get_distance_to_river(lat: float, lon: float) -> Dict[str, any]`

- **Agent:** F
- **Source:** OpenStreetMap via the Overpass API (endpoint from `config.get_random_overpass_url()`), querying nodes/ways/relations tagged `waterway` (river/canal/stream/drain/ditch) or `natural=water` within a 5km radius.
- **Returns:** `distance_m` (straight-line/haversine distance to the nearest waterway geometry point, rounded to whole meters), `river_name` (from the OSM `name` tag, or `"unnamed"`/`"none_found"`), `risk_note` (a qualitative distance-band string generated by the tool, not the agent). If no waterway is found within 5km, `distance_m=5000, river_name="none_found"`.
- **On Overpass failure:** `{"distance_m": -1, "error": "Overpass API error: ..."}`.

### `get_nearby_mountain_road(lat: float, lon: float, radius_m: int = 2000) -> Dict[str, any]`

- **Agent:** L
- **Source:** OpenStreetMap Overpass API, querying `highway` ways (primary/secondary/tertiary/unclassified/residential) and `mountain_pass=yes` nodes within `radius_m`.
- **Returns:** `has_mountain_road` (bool, true if any matching road/pass was found), `nearby_roads` (list of up to 10 `{type, name}` — no per-road distance field is returned), `road_count`, `cut_slope_warning` (string, non-empty when a road or pass was found), `source`.
- **On failure:** `{"has_mountain_road": False, "error": ..., "note": "Could not detect nearby roads due to Overpass rate limit or timeout."}`.
- Detects potential "cut-slope" (taluy) risk: road construction on slopes creates artificial cuts that are a leading cause of human-induced landslides in Vietnam.

### `get_river_discharge(lat: float, lon: float, event_date: str) -> Dict[str, any]`

- **Agent:** F
- **Source:** Open-Meteo Flood API (`models=seamless_v4`, GloFAS v4 reanalysis/forecast, 1984–present), daily `river_discharge`.
- **Returns:** `river_discharge_m3s` (max of the day's values, 2dp), `date`, `unit`, `model`, `river_scale` (`"large"` if > 500 m³/s, `"medium"` if > 50, else `"small"`). If the API returns no discharge series (no significant river within the grid cell), returns `{"river_discharge_m3s": 0.0, "note": "No significant river within 5km of this location.", "river_scale": "none"}` — this is a legitimate zero, not a failure.
- **On HTTP/network failure:** also defaults to `{"river_discharge_m3s": 0.0, "error": ...}` — the zero-discharge default is returned for both "no river" and "API failed" cases, distinguishable only by the presence/absence of the `"error"` key.

---

## Layer 2 — Static Terrain (`react_agent/tools/terrain_data.py`)

These tools are lead-time invariant — their values don't change with forecast horizon.

### `get_imperviousness(lat: float, lon: float, year: int = 2025, radius_m: int = 500) -> Dict[str, any]`

- **Agent:** F
- **Source (tiered):** (1) GHSL GHS-BUILT-S P2023A via Google Earth Engine (`JRC/GHSL/P2023A/GHS_BUILT_S`, 100m sample, 2020 epoch preferred); (2) a locally pre-downloaded GHSL GeoTIFF under `react_agent/data/ghsl/` (nearest of the 12 GHSL epochs 1975–2030, windowed mean at `radius_m`); (3) an OpenStreetMap landuse/building/highway density proxy within `radius_m` (Overpass API); (4) a hardcoded neutral default.
- **Returns:** `imperviousness_pct`, `alpha_modifier`, `epoch_used`, `source`, `radius_m`. `alpha_modifier = imperviousness_pct / 60.0`, clamped to `[0.5, 2.5]` (`60.0` is the HCMC 2010 average imperviousness, the calibration reference — Ho Long Phi 2012). Verified directly (live GEE calls plus a scan of every `get_imperviousness` call in the released traces, 7,586 calls total): the primary GEE tier returns `imperviousness_pct` correctly on a 0–100 scale (e.g. 63.86 for central Ho Chi Minh City, 0.0 for a rural highland point), and `alpha_modifier` varies correctly with it (1.064 and 0.5 respectively for those two points). Every one of the 7,586 calls in the released evaluation data resolved via this GEE tier — the fallback tiers below were never exercised. About 60% of calls land exactly at the 0.5 floor; this reflects that most evaluated locations have real imperviousness below the 60%-HCMC reference, not a computation error. The OSM-proxy fallback tier (tier 3 below) does have a genuine unit mismatch — it computes its own `imp_pct` as a 0–1 fraction and divides by the same 60.0 percent-scale baseline, which would permanently clamp its `alpha_modifier` to 0.5 regardless of input — but since it never fired in the released data, it did not affect any reported result.
- GEE unavailable → falls to local GeoTIFF if present → falls to OSM proxy (returns `osm_element_count` and a heuristic mapping of element density to imperviousness) → falls to the hardcoded default `{"imperviousness_pct": 0.60, "alpha_modifier": 1.0, "epoch_used": "default", "source": "fallback_default", "error": ...}` if the OSM query itself also fails.

### `get_twi(lat: float, lon: float) -> Dict[str, any]`

- **Agent:** F
- **Source (tiered):** (1) MERIT Hydro via Google Earth Engine (`MERIT/Hydro/v1_0_1`, upstream area `upa` band + slope from the `elv` band, 90m sample); (2) a local pre-computed raster at `react_agent/data/twi_vietnam.tif`; (3) an elevation-grid proxy (3×3 grid at ~333m spacing via Open-Meteo Elevation, approximating flow accumulation from the count of higher neighboring cells); (4) a hardcoded default.
- **Returns:** `twi_value` (clamped to `[2, 20]`), `twi_modifier` (`1.0 + 0.3 × (twi − 9.0) / 9.0`, clamped to `[0.7, 1.3]`), `interpretation` (`"depression — high water accumulation"` if TWI > 12, `"flat — moderate accumulation"` if > 9, `"slope — limited accumulation"` if > 6, else `"ridge — good drainage"`), `source`.
- TWI formula: `TWI = ln(a / tan β)`, where `a` = specific catchment area and `β` = local slope. The hardcoded default (all tiers fail) is `{"twi_value": 9.0, "twi_modifier": 1.0, "interpretation": "unknown — using baseline default", "source": "fallback_default"}`.

### `get_catchment_info(lat: float, lon: float) -> Dict[str, any]`

- **Agent:** F
- **Source (tiered):** (1) a pre-downloaded HydroBASINS Level 12 shapefile under `react_agent/data/hydrobasins/` (spatial-indexed point-in-polygon lookup via GeoPandas, falling back to nearest-polygon if the point isn't contained in any basin); (2) an elevation-based estimate (9-point grid at 5km spacing, heuristically mapping elevation range to catchment/upstream area size classes).
- **Returns:** `catchment_area_km2`, `upstream_area_km2`, `position_in_basin` (`"headwater"`/`"midstream"`/`"downstream"`/`"delta"` from the HydroBASINS path, ratio-based; or the elevation-estimate path's own class labels), `flood_receiving` (bool, `upstream_area_km2 > 500`), `source`; the HydroBASINS path additionally returns `hybas_id`.
- If the shapefile directory is absent, the estimate path is used directly. If the estimate's own elevation query fails, returns the hardcoded default: `{"catchment_area_km2": 50.0, "upstream_area_km2": 200.0, "position_in_basin": "unknown", "flood_receiving": False, "source": "fallback_default", "error": ...}`.

---

## Layer 1 — Calculators (`react_agent/tools/calculator.py`)

All four are pure, synchronous functions (`def`, not `async def`) — no network or database calls, no exceptions expected in normal operation, deterministic given their inputs. They return raw numeric values, triggered-rule lists, and factual flags; none of them classifies a risk level.

### `calculate_flash_flood_risk(rainfall_6h_mm: float, rainfall_24h_mm: float, local_slope_deg: float, channel_slope_deg: float, catchment_area_km2: float, soil_moisture: float, api_value: float) -> Dict[str, any]`

- **Agent:** F
- **Returns:** `triggered_rules` (list of human-readable strings), `rule_count`, `is_saturated`, `terrain_too_flat`, `formula_ref`, `inputs` (echo of all seven arguments).
- **Flat-terrain gate:** if `local_slope_deg < 5° AND channel_slope_deg < 2°`, `terrain_too_flat = True` and no rules are evaluated at all.
- **Saturation flag:** `is_saturated = soil_moisture > 0.35 m³/m³ OR api_value > 30 mm`.
- **Rules** (evaluated independently — more than one can fire):
  - **R1** (Trinh et al. 2022, SeAFFGS §3.4, DOI:10.36335/VNJHM.2022(13).25-36): `catchment_area_km2 < 20 AND rainfall_6h_mm > 20 AND is_saturated` — sub-20km² basins reach bankfull discharge at ≤20mm/6h.
  - **R2** (same source): `catchment_area_km2 < 50 AND rainfall_6h_mm > 35 AND is_saturated` — 20–50km² basins, 20–35mm/6h threshold class.
  - **R3** (Hoang et al. 2019 §3.3, DOI:10.3390/ijgi8050228, Level I proxy): `rainfall_24h_mm ≥ 100 AND local_slope_deg > 17 AND is_saturated`.
  - **R4** (Level II, slope factor): `rainfall_24h_mm ≥ 100 AND local_slope_deg > 17`.
  - **R5** (Level II, permeability factor): `rainfall_24h_mm ≥ 100 AND is_saturated`.
  - **R6** (extreme daily): `rainfall_24h_mm ≥ 220`.
  - The 17° threshold is the arctan of Hoang et al.'s 30% average-slope criterion (arctan 0.30 ≈ 16.7°, rounded to 17°). Forest coverage is omitted from R3–R5 (data unavailable in this pipeline); saturation stands in as a low-permeability proxy. 220mm is the upper bound of the threshold range stated in §3.3.

### `calculate_river_water_level(tide_level_cm: float, river_discharge_m3s: float, river_name: str = "generic", river_width_m: float = 50.0, c_override: float = None, d_override: float = None) -> Dict[str, any]`

- **Agent:** F
- **Returns:** `combined_level_cm`, `fluvial_rise_cm`, `tide_component_cm`, `method`, `parameters` (`{c, d}`), `formula` (string).
- **Formula:** `H_total = H_tide + c · Q^d` (hydraulic rating curve; `d = 0.6` follows Leopold & Maddock 1953 at-a-station hydraulic geometry, `H ∝ Q^0.6`).
- **Tiered parameter resolution:** (1) `c_override`/`d_override` if supplied (`d` defaults to 0.6 if only `c_override` is given); (2) a named-river literature lookup table, keyed on a normalized `river_name` (lowercased, spaces→underscores, "river" stripped):

  | Key | c | d | width (m) |
  |---|---|---|---|
  | `saigon` | 0.052 | 0.61 | 250 |
  | `dong_nai` | 0.041 | 0.62 | 600 |
  | `soai_rap` | 0.025 | 0.65 | 1500 |
  | `mekong_branch` | 0.030 | 0.63 | 1000 |
  | `red_river` | 0.045 | 0.62 | 800 |

  (Sourced in-code to SIWRR 2022, Ho Long Phi 2010, Mekong River Commission 2023.) (3) Otherwise, a physics-based approximation: `c = (1 / river_width_m)^0.6 × 0.1` (empirical constant for tropical lowland rivers), `d = 0.6`.
- `combined_level_cm = tide_level_cm + fluvial_rise_m × 100`. River-specific gauged rating curves weren't available in open-access form, so this is adequate for relative comparison of fluvial rise across events rather than absolute stage prediction.

### `calculate_hybrid_api(historical_rain_series: List[float], forecast_rain_series: List[float], k: float = 0.85) -> Dict[str, any]`

- **Agent:** F
- **Returns:** `api_value`, `interpretation`, `decay_factor`, `series_length`, `forecast_days`, `historical_days`, `is_hybrid: True`, `formula_ref`.
- **Formula:** `API = Σ k^i · R_i`, `i=0` at the day closest to the event. The merged series is `list(forecast_rain_series) + list(historical_rain_series)` (both passed in most-recent-day-first order), so the event day always gets weight `k^0 = 1.0` regardless of whether it falls in the historical or forecast period.
- Used for lead-time > 0 scenarios where the rainfall window spans an observed period and a forecast period — keeps the multi-day weighted sum out of the LLM layer. Same interpretation bands as `get_antecedent_precipitation_index` (`>50` very_high, `>30` high, `>15` moderate, else low saturation).

### `calculate_doyin_threshold(antecedent_3day_mm: float, trigger_day_rain_mm: float, antecedent_5day_mm: float = 0.0, antecedent_7day_mm: float = 0.0, antecedent_10day_mm: float = 0.0, antecedent_15day_mm: float = 0.0) -> Dict[str, any]`

- **Agent:** L
- **Returns:** `window_results` (list of per-window dicts: `window_days, antecedent_mm, threshold_mm, trigger_day_rain_mm, margin_mm, exceeded, formula`), `primary_result` (the 3-day window, always computed), `windows_exceeded` (count of windows where `trigger_day_rain_mm ≥ threshold_mm`), `study_area_note`, `formula_ref`.
- **Formula:** five conditional linear-threshold equations from Do & Yin (2018), *Open Journal of Geology* 8(7):674–696, DOI:10.4236/ojg.2018.87040, Figure 4: `RT = a − b × R_Nad`, floored at 0mm:

  | Window (days) | a | b |
  |---|---|---|
  | 3 | 40.8 | 0.201 |
  | 5 | 44.7 | 0.087 |
  | 7 | 47.36 | 0.047 |
  | 10 | 51.2 | 0.010 |
  | 15 | 53.3 | 0.001 |

  Windows whose antecedent input is `≤ 0` are skipped entirely (not scored as "not exceeded").
- Calibrated on 37 dated events from a 245-event landslide inventory in Hà Giang province, NW Vietnam (1990–2016); the agent is expected to judge geographic applicability to the target location — the tool itself applies no regional adjustment, and takes no slope input (no slope gate at the calculator level). Per the landslide system prompt, ERA5 rainfall inputs are corrected ×3–5 before being passed to this tool, to account for known ERA5 underestimation of mountain convective rainfall.
