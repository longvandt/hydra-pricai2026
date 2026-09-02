# Optional: local elevation/slope cache

`get_elevation_slope` (`src/tools/geo_data.py`) checks a Supabase table called `elevation_slope_cache` before calling any elevation API, and writes a successful lookup back to it. This is a pure performance optimization for live execution — every tool in this release already has a fully working fallback chain without it (Open-Meteo Elevation → OpenTopoData SRTM-30m → OpenTopoData ASTER-30m), so **you do not need this to run anything in this repo, including live execution.** Skip it unless you're doing enough live runs that repeated elevation lookups start to matter.

Nothing about reproducing the paper's numbers touches this — `evaluate_metrics.py`, `render_traces.py`, and `compute_efficiency.py` never call any tool at all, let alone this cache.

## Schema

One table, keyed on rounded lat/lon:

```sql
create table if not exists elevation_slope_cache (
  lat         double precision not null,
  lon         double precision not null,
  elevation_m double precision,
  slope_deg   double precision,
  terrain     text,
  source      text,
  created_at  timestamptz default now(),
  primary key (lat, lon)
);
```

The `(lat, lon)` primary key is required — the code upserts on that exact conflict target (`on_conflict="lat,lon"`).

## Option A — fully local, no account (closest to a self-hosted setup)

Requires Docker running.

```bash
# 1. Install the Supabase CLI
brew install supabase/tap/supabase        # macOS
# or: npm install -g supabase

# 2. Spin up a local project (in its own directory, separate from this repo)
mkdir hydra-elevation-cache && cd hydra-elevation-cache
supabase init
supabase start
```

`supabase start` prints a local API URL and keys when it finishes, e.g.:

```
API URL: http://127.0.0.1:54321
anon key: eyJhbGciOi...
```

Create the table — either paste the SQL above into the local Studio SQL editor at `http://127.0.0.1:54323`, or save it as `supabase/migrations/0001_elevation_cache.sql` in that same directory and run `supabase db push`.

Set in your `.env` (back in the release repo):

```
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_KEY=<the anon key supabase start printed>
```

`supabase stop` pauses the containers; `supabase start` again brings back the same local database, including whatever the cache already learned.

## Option B — free Supabase Cloud project (no Docker)

1. Create a free project at [supabase.com](https://supabase.com).
2. Open the SQL Editor and run the `create table` statement above.
3. In Project Settings → API, copy the **Project URL** and the **anon public** key.
4. Set those as `SUPABASE_URL` / `SUPABASE_KEY` in your `.env`.

## Notes

- The cache only ever stores `(lat, lon, elevation_m, slope_deg, terrain, source)` — coordinates and terrain readings, nothing else. No event data, no API keys, no trace content ever goes through this table.
- A cache write failure is silent and non-fatal by design (`src/tools/geo_data.py`'s `_elev_cache_set`) — if `SUPABASE_URL`/`SUPABASE_KEY` are unset or wrong, `get_elevation_slope` just falls through to the API providers every time, with no error surfaced.
