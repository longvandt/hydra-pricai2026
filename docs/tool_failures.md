# Failure handling

How Hydra's tools behave when an upstream data source is slow, rate-limited, unavailable, or returns unusable data — built directly from the `try`/`except`, retry, and fallback logic in `react_agent/tools/weather.py`, `geo_data.py`, and `terrain_data.py`, plus the one agent-level (Layer 3) failure-handling rule that lives in the system prompt itself.

None of the Layer 2 data tools ever raise an exception out to the agent. Every `@tool`-decorated function has an outer `try/except Exception` that converts a failure into a returned `dict` — usually (but not always) carrying an `"error"` key — so the ReAct loop always receives a tool result it can reason about, never a crash. The four Layer 1 calculators (`calculator.py`) are pure functions with no I/O and no error handling of their own; they are not part of this taxonomy.

## Failure-class table

| Class | Example | Detection | Handling |
|---|---|---|---|
| **Invalid input** | `event_date` not in `YYYY-MM-DD` format | `datetime.strptime(...)` raises `ValueError`, caught explicitly before any network call | Returns `{"error": "Invalid date format: ...", ...}` with a safe numeric default alongside (e.g. `total_mm: 0`). No API call is attempted. |
| **Transient upstream failure (retried, then recovers)** | Open-Meteo/Overpass 5xx or 429 during a burst of calls | `tenacity`-wrapped inner fetch helper (`_fetch_from_open_meteo` in weather.py, `_fetch_from_api` in geo_data.py) retries before returning | Succeeds silently after 1–4 retries; the tool function never sees the intermediate failures. |
| **Transient upstream failure (retries exhausted)** | Sustained outage or timeout | Same retry helper raises after its `stop_after_attempt` budget | Caught by the tool's own outer `try/except`, converted to `{"error": "Failed to fetch ...: <exception str>", ...}` plus a safe default (e.g. `total_mm: 0`, `river_discharge_m3s: 0.0`, `distance_m: -1`). |
| **Multi-provider chain exhaustion** | All four elevation providers fail | `_fetch_5point_elevations` in geo_data.py returns `(None, "all_failed")` after trying every provider in order | `get_elevation_slope` returns `data_quality: "unavailable"` plus an explicit `agent_instruction` string embedded in the tool output telling the agent to stop (see below). This is the one Layer 2 tool that speaks directly to agent behavior in its return value rather than just reporting data. |
| **Null/missing value in an otherwise-successful response** | ERA5-Land returns `null` for `soil_moisture_0_to_7cm_mean` on a given day | Value is `None` after parsing, checked explicitly (not via exception) | `get_soil_moisture` returns `{"soil_moisture_m3_per_m3": None, "saturation": "unknown", "note": "Data unavailable"}` — **no `"error"` key**, so this failure mode is invisible to any check that only looks for `"error"`. |
| **Legitimate zero vs. failure, same default value** | No river within the GloFAS grid cell vs. Open-Meteo Flood API request failing | `discharges` list empty/all-`None` (no river) vs. `httpx.HTTPStatusError`/other exception (API failure) | Both paths in `get_river_discharge` return `river_discharge_m3s: 0.0`; only the failure path also sets `"error"`. A caller reading only the numeric field cannot distinguish "no river here" from "the API failed." |
| **Same default on success-empty and on failure, discriminable only via `"error"`** | `get_nearby_mountain_road`: a genuinely road-free area vs. an Overpass timeout | Empty `elements` list (success) vs. caught exception (failure) | Both paths return `has_mountain_road: False`; only the failure path also adds `"error"` and a `"note"` string. A check that only reads `has_mountain_road` cannot tell "confirmed no roads nearby" from "couldn't check." |
| **Cache write failure** | Supabase unreachable when `get_elevation_slope` tries to persist a fresh lookup | Bare `except Exception: pass` in `_elev_cache_set` | Completely silent — no field in the tool's return value reflects whether the cache write succeeded. Non-fatal by design (the fetched result is still returned to the agent). |
| **Optional dependency / cloud auth unavailable** | Google Earth Engine not authenticated in the current environment | `_init_gee()` catches the `ee.Initialize()` exception, sets `_gee_available = False`, logs a warning | `get_imperviousness`, `get_twi`, `get_catchment_info` fall through to their next-tier source (local raster/GeoTIFF, then a proxy computed from OpenStreetMap or the elevation API, then a hardcoded default). See fallback chains below. |
| **Rate-limit pacing (proactive, not reactive)** | Open-Meteo Archive API free tier | Hardcoded `await asyncio.sleep(1.0)` before every Archive API call in `_fetch_from_open_meteo`; OpenTopoData calls sleep `1.1s` between providers in the elevation chain | Not a failure at all — a fixed delay inserted unconditionally to stay under the free-tier rate limit before it can be hit. |

## Retry configuration by call site

Retry policy is not uniform across tools — each site is tuned to its upstream's tolerance:

| Call site | Library | Stop | Wait | Retry condition |
|---|---|---|---|---|
| `weather.py` `_fetch_from_open_meteo` (used by all 5 weather tools) | `tenacity` | `stop_after_attempt(3)` | exponential, `multiplier=1, min=2, max=10` | any exception (unconditional) |
| `geo_data.py` `_fetch_from_api` (used by `get_elevation_slope`'s Open-Meteo tier, `get_catchment_slope`, `get_historical_tide_level`, `get_river_discharge`) | `tenacity` | `stop_after_attempt(3)` | exponential, `multiplier=1, min=2, max=10` | only on 5xx/429 HTTP status or a non-HTTP exception (`_should_retry`) — a 4xx client error other than 429 is **not** retried |
| `geo_data.py` `get_distance_to_river`'s Overpass fetch | `tenacity` | `stop_after_attempt(3)` | exponential, `multiplier=1, min=5, max=30` | unconditional |
| `geo_data.py` `get_nearby_mountain_road`'s Overpass fetch | `tenacity` | `stop_after_attempt(5)` | exponential, `multiplier=2, min=5, max=60` | same `_should_retry` (5xx/429/non-HTTP) — longest budget of any tool, reflecting Overpass's tendency to rate-limit |
| `geo_data.py` elevation provider chain (`_fetch_5point_elevations`) | manual loop, no `tenacity` | tries each of 3 providers once per call to `get_elevation_slope` | fixed `1.1s` sleep before each OpenTopoData attempt | any exception on a given provider moves to the next provider, not a retry of the same one |

## Multi-provider fallback chains

Two tools chain multiple independent data sources rather than retrying the same one; each tier's failure is caught individually and the next tier is tried, with a final hardcoded default if every tier fails. These are not failures per se from the agent's perspective — the agent always gets a usable-looking result — but the source and confidence of that result can vary silently between tool calls.

**`get_elevation_slope`** (`geo_data.py`):
1. Supabase cache (`elevation_slope_cache` table, lat/lon rounded to 4dp) — read is attempted first on every call; a cache hit skips all network tiers entirely.
2. Open-Meteo Elevation API (SRTM-based, ~90m).
3. OpenTopoData `srtm30m` (higher resolution).
4. OpenTopoData `aster30m` (independent dataset, final fallback).
5. All four exhausted → returns `data_quality: "unavailable"` and the embedded `agent_instruction` (see RAINFALL DATA GATE section below for the analogous flood-side pattern; this is the landslide/flood-shared elevation equivalent).

**`get_imperviousness`** and **`get_twi`** (`terrain_data.py`), each independently:
1. Google Earth Engine (GHSL GHS-BUILT-S for imperviousness; MERIT Hydro for TWI).
2. A locally pre-downloaded raster (`react_agent/data/ghsl/*.tif` or `react_agent/data/twi_vietnam.tif`) — only reached if that directory/file exists in the deployment.
3. A computed proxy with no external geospatial dataset: OpenStreetMap landuse/building density for imperviousness, or a 3×3 elevation-grid flow-accumulation approximation for TWI.
4. A hardcoded neutral default (`imperviousness_pct: 0.60` / `twi_value: 9.0`) if even the proxy tier throws.

**`get_catchment_info`** (`terrain_data.py`) follows the same two-tier pattern: a pre-downloaded HydroBASINS Level 12 shapefile (if `react_agent/data/hydrobasins/` exists) with spatial-indexed lookup, falling back to an elevation-based heuristic estimate, falling back to a hardcoded default (`catchment_area_km2: 50.0, upstream_area_km2: 200.0, position_in_basin: "unknown"`) if the estimate's own elevation query also fails.

In all three cases, which tier actually answered is reported in the `source` field of the returned dict (e.g. `"GHSL_GEE_P2023A"`, `"OSM_proxy_estimate"`, `"fallback_default"`) — the agent has no separate signal that a degraded tier was used unless it inspects `source`, since none of the non-final tiers return an `"error"` key on success.

## Agent-level (Layer 3) handling: the RAINFALL DATA GATE

Distinct from all of the above tool-level (Layer 2) behavior, the flood agent's system prompt (`build_flood_system_prompt()` in `react_agent/calibration.py`, ~line 321; verbatim in `prompts/system_prompt_flood.md`) encodes one explicit, hard-stop rule for a specific tool failure:

> ```
> RAINFALL DATA GATE — enforce BEFORE proceeding to Step 3:
>   After calling get_historical_rainfall, check the result:
>   • Result has no "error" key → proceed normally. 0mm = genuine dry conditions.
>   • Result has "error" key (API failure) → STOP. Output EXACTLY:
>       Risk Level: NONE — ⚠️ INCOMPLETE_DATA
>       Reason: Rainfall API failed. Cannot assess flood risk without rainfall data.
>       Static factors (tide, discharge, imperviousness) are amplifiers only —
>       they cannot independently trigger a flood classification.
>       Re-run this event when data is available. This is not a model prediction.
>     Do NOT proceed to Step 3. Do NOT use tide or river data to infer rainfall.
> ```

This is the only point in either system prompt where a specific tool's `"error"` key is checked by name and given a mandatory, verbatim-output response. The rule exists because `get_historical_rainfall` returning `total_mm: 0` is ambiguous between "genuinely dry" and "API failed, defaulted to zero" (see the failure-class table above) — the gate forces the agent to check for the `"error"` key rather than trusting the numeric default, and explicitly forbids substituting a secondary signal (tide, river discharge) to infer rainfall it doesn't have.

The landslide system prompt (`build_landslide_system_prompt()`, `prompts/system_prompt_landslide.md`) has no equivalent named gate. Its only related instruction is a single line in the reasoning section: *"If slope data failed entirely, note it and flag the result as INCOMPLETE_DATA"* — softer and slope-focused (matching `get_elevation_slope`'s own embedded `agent_instruction` on total provider-chain failure) rather than a rainfall-specific, verbatim-output hard stop.
