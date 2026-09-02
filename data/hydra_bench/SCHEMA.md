# Hydra-Bench schema

`flood_events.json` and `landslide_events.json` each contain 1,000 records (500 positive + 500 negative) — the exact evaluation sets used to produce every number in the paper. Structured fields only; no article text is redistributed (see below).

## Common fields (all records)

| Field | Type | Description |
|---|---|---|
| `id` | string (UUID) | Event identifier, referenced by `event_id` in `../predictions/` and `../../traces/raw/traces.jsonl.gz` |
| `location_name` | string | Street/landmark-level location (Vietnamese) |
| `ward`, `district`, `province` | string | Administrative hierarchy at time of extraction |
| `full_address` | string | Concatenated address string |
| `geo_latitude`, `geo_longitude` | float | ≥4 decimal places |
| `event_date` | string (YYYY-MM-DD) | Date of the reported/sampled event |
| `label` | string | `"positive"` or `"negative"` — the ground-truth binary label |

## Positive-only fields

| Field | Type | Description |
|---|---|---|
| `confidence` | string | Extraction confidence tier (Low/Medium/High) |
| `severity` | string | Reported event severity |
| `cause` | string | Extracted cause description (Vietnamese) |
| `description` | string | Short extracted event description (Vietnamese) — a structured field produced by the extraction pipeline's schema, not the source article text |
| `source_url` | string | Link to the original news article (source text itself is not redistributed) |
| `geo_map_url` | string | Google Maps link for the coordinates |
| `flood_depth_cm` | int | Flood-only: reported flood depth in cm |
| `flood_type` | string | Flood-only: Urban / River / Coastal / etc. |
| `landslide_type` | string | Landslide-only: Mudslide / Rockfall / etc. |
| `affected_area_description` | string | Landslide-only: extracted description of the affected area |

## Negative-only fields

| Field | Type | Description |
|---|---|---|
| `is_negative` | bool | Always `true` |
| `batch_ratio` | string | Sampling ratio used to draw this negative (e.g. `"1:1"`) |
| `source_positive_id` | string (UUID) | The positive event whose coordinates this negative reuses. Populated for every negative — both tiers are drawn at a verified positive's location, only the date differs (see `CONSTRUCTION.md`) |

See `CONSTRUCTION.md` for how positives and negatives were sampled.
