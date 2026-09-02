# Landslide assessment, Tỉnh lộ 677 (Km16+015 - Km23+500), Huyện Kon Rẫy, Kon Tum

**Event** 51e98c7c-39ae-4ddb-97b3-bbe1a25ab32c | **Backbone** ministral-3-14b | **Lead** T-3
**Ground truth** negative | **Predicted** HIGH
**Tool calls** 9 | **Latency** 29.39s | **Tokens** 7517

---

### Final Assessment

### Data Summary
- **Terrain**: Slope at point = **13.36° (hilly)**, but max slope within 500m = **39.69° (mountainous)**. Elevation range: 660–891m.
- **Rainfall (ERA5, uncorrected)**:
  - Antecedent 3-day: **26.6mm** (July 17–19)
  - Antecedent 5-day: **37.2mm** (July 15–19)
  - Antecedent 7-day: **60.6mm** (July 13–19)
  - Trigger-day (next 72h): **10.1mm** (July 20–23 forecast)
- **Soil Moisture**: **0.5 m³/m³ (saturated)**; API = **31.63 (high saturation)**.
- **Roads**: **31 roads detected within 2km (cut-slope risk)**.

---

### ERA5 Correction
- **API = 31.63 (high saturation)** → **Apply ×3 scaling** to rainfall (soil already pre-loaded).
- **Corrected Rainfall**:
  - Antecedent 3-day: **26.6 × 3 = 79.8mm**
  - Antecedent 5-day: **37.2 × 3 = 111.6mm**
  - Antecedent 7-day: **60.6 × 3 = 181.8mm**
  - Trigger-day: **10.1 × 3 = 30.3mm**

---

### Do & Yin Threshold Check
Calculating thresholds for **Hà Giang calibration** (adjustments may apply for geographic differences):
- **3-day window**: \( RT = 40.8 - 0.201 \times 79.8 = 24.8 \)
  → Trigger (30.3mm) **exceeds** threshold by **+5.5mm**.
- **5-day window**: \( RT = 44.7 - 0.087 \times 111.6 = 34.9 \)
  → Trigger (30.3mm) **does not exceed** (margin: **-4.6mm**).
- **7-day window**: \( RT = 47.36 - 0.047 \times 181.8 = 38.7 \)
  → Trigger (30.3mm) **does not exceed** (margin: **-8.4mm**).

**Result**: **1/3 windows triggered** (3-day).

---

### Interpretation
1. **Terrain**: Steep mountainous terrain (max 39.69°) with **cut-slope risk from roads** (artificial taluy). Highly susceptible to shallow translational slips or debris flows.
2. **Saturation**: Soil is **saturated (SM = 0.5 m³/m³, API = 31.63)** → **multi-day pre-loading** from prior rainfall (e.g., 14.7mm on July 14, 13.8mm on July 18).
3. **Triggering Rainfall**: Corrected 72h forecast = **30.3mm** (ERA5 underestimates real mountain rainfall; true value likely **higher**).
   - **3-day window exceeded** (+5.5mm), but 5/7-day windows did not. This suggests **short-term intensity matters more** than long-term accumulation.
4. **Mechanism**: Likely **shallow translational slips** on road cuts or **debris flows** in gullies, given:
   - Steep slopes + saturated soil + road-induced weaknesses.
   - High-intensity rainfall (e.g., 11.3mm in 3h on July 18) primes slopes for rapid failure.

---

### Risk Assessment
- **Confidence**: **HIGH** (Do & Yin threshold exceeded in 3-day window, saturated soil, steep terrain, and road cuts).
- **Geographic Applicability**: Hà Giang calibration is conservative for **Central Vietnam** (higher rainfall intensity). True risk may be **higher** than modeled.
- **ERA5 Note**: Scaling factor ×3 applied due to saturation; real rainfall likely **underestimated**.

### Final Risk Assessment
- **Terrain**: slope **13.36° (hilly)**, max **39.69° (steep mountain zone)** within 500m; **mountain road present (cut-slope risk)**.
- **Saturation**: SM **0.5 m³/m³ (saturated)**; API **31.63 (high — multi-day pre-loading)**.
- **Rainfall (ERA5 → corrected ×3)**:
  Trigger-day **10.1mm → 30.3mm**; 3-day **26.6mm → 79.8mm**; 7-day **60.6mm → 181.8mm**.
- **Do & Yin**: 3-day threshold **24.8mm**, trigger **30.3mm** — **exceeded by +5.5mm**; **1/3 windows triggered**.
- **Interpretation**: **Steep, road-cut terrain with saturated soil and short-term rainfall intensity exceeding thresholds** → **high risk of shallow translational slips or debris flows**.
- **Risk Level**: **HIGH**
- **Confidence**: **HIGH** (Do & Yin threshold exceeded, saturation confirmed, and road cuts amplify risk). ERA5 scaling ×3 applied; true rainfall likely higher.

**Risk Level: HIGH**

---

### Tool Call Traces

**Call 1.** `get_elevation_slope(lat=14.636716, lon=108.134931)`

**Observation.**
```json
{
  "slope": 13.36,
  "cached": true,
  "source": "opentopodata_srtm30m",
  "terrain": "hilly",
  "elevation": 679
}
```

---

**Call 2.** `get_terrain_profile(max_lat=14.641716, max_lon=108.139931, min_lat=14.631716, min_lon=108.129931)`

**Observation.**
```json
{
  "note": "Sampled 25 points. Max slope = steepest section.",
  "terrain": "mountain",
  "avg_slope": 17.42,
  "max_slope": 39.69,
  "sample_count": 25,
  "elevation_range": {
    "max": 891.0,
    "min": 660.0
  }
}
```

---

**Call 3.** `get_historical_rainfall(lat=14.636716, lon=108.134931, event_date='2024-07-20', days_before=3)`

**Observation.**
```json
{
  "days": 3,
  "period": "2024-07-17 to 2024-07-20",
  "total_mm": 26.6,
  "max_1h_mm": 5.0,
  "max_2h_mm": 9.1,
  "max_3h_mm": 11.3,
  "max_6h_mm": 12.5,
  "max_12h_mm": 13.2,
  "max_24h_mm": 15.8,
  "daily_breakdown": [
    {
      "date": "2024-07-17",
      "rain_mm": 4.0
    },
    {
      "date": "2024-07-18",
      "rain_mm": 13.8
    },
    {
      "date": "2024-07-19",
      "rain_mm": 1.3
    },
    {
      "date": "2024-07-20",
      "rain_mm": 7.5
    }
  ]
}
```

---

**Call 4.** `get_historical_rainfall(lat=14.636716, lon=108.134931, event_date='2024-07-20', days_before=5)`

**Observation.**
```json
{
  "days": 5,
  "period": "2024-07-15 to 2024-07-20",
  "total_mm": 37.2,
  "max_1h_mm": 5.0,
  "max_2h_mm": 9.1,
  "max_3h_mm": 11.3,
  "max_6h_mm": 12.5,
  "max_12h_mm": 13.2,
  "max_24h_mm": 15.8,
  "daily_breakdown": [
    {
      "date": "2024-07-15",
      "rain_mm": 6.5
    },
    {
      "date": "2024-07-16",
      "rain_mm": 4.1
    },
    {
      "date": "2024-07-17",
      "rain_mm": 4.0
    },
    {
      "date": "2024-07-18",
      "rain_mm": 13.8
    },
    {
      "date": "2024-07-19",
      "rain_mm": 1.3
    },
    {
      "date": "2024-07-20",
      "rain_mm": 7.5
    }
  ]
}
```

---

**Call 5.** `get_historical_rainfall(lat=14.636716, lon=108.134931, event_date='2024-07-20', days_before=7)`

**Observation.**
```json
{
  "days": 7,
  "period": "2024-07-13 to 2024-07-20",
  "total_mm": 60.6,
  "max_1h_mm": 5.0,
  "max_2h_mm": 9.1,
  "max_3h_mm": 11.3,
  "max_6h_mm": 12.5,
  "max_12h_mm": 13.2,
  "max_24h_mm": 18.3,
  "daily_breakdown": [
    {
      "date": "2024-07-13",
      "rain_mm": 8.7
    },
    {
      "date": "2024-07-14",
      "rain_mm": 14.7
    },
    {
      "date": "2024-07-15",
      "rain_mm": 6.5
    },
    {
      "date": "2024-07-16",
      "rain_mm": 4.1
    },
    {
      "date": "2024-07-17",
      "rain_mm": 4.0
    },
    {
      "date": "2024-07-18",
      "rain_mm": 13.8
    },
    {
      "date": "2024-07-19",
      "rain_mm": 1.3
    },
    {
      "date": "2024-07-20",
      "rain_mm": 7.5
    }
  ]
}
```

---

**Call 6.** `get_rainfall_after_event(lat=14.636716, lon=108.134931, hours=72, event_date='2024-07-20')`

**Observation.**
```json
{
  "note": "Actual recorded rainfall after event (simulates forecast for historical validation)",
  "total_mm": 10.1,
  "period_hours": 72
}
```

---

**Call 7.** `get_antecedent_precipitation_index(lat=14.636716, lon=108.134931, event_date='2024-07-20')`

**Observation.**
```json
{
  "api_value": 31.63,
  "period_days": 7,
  "decay_factor": 0.85,
  "interpretation": "high_saturation",
  "daily_breakdown": [
    {
      "date": "2024-07-13",
      "rain_mm": 8.7
    },
    {
      "date": "2024-07-14",
      "rain_mm": 14.7
    },
    {
      "date": "2024-07-15",
      "rain_mm": 6.5
    },
    {
      "date": "2024-07-16",
      "rain_mm": 4.1
    },
    {
      "date": "2024-07-17",
      "rain_mm": 4.0
    },
    {
      "date": "2024-07-18",
      "rain_mm": 13.8
    },
    {
      "date": "2024-07-19",
      "rain_mm": 1.3
    }
  ],
  "total_rainfall_mm": 53.1
}
```

---

**Call 8.** `get_soil_moisture(lat=14.636716, lon=108.134931, event_date='2024-07-20')`

**Observation.**
```json
{
  "date": "2024-07-20",
  "saturation": "saturated",
  "soil_moisture_m3_per_m3": 0.5
}
```

---

**Call 9.** `get_nearby_mountain_road(lat=14.636716, lon=108.134931)`

**Observation.**
```json
{
  "source": "OpenStreetMap_Overpass_2000m",
  "road_count": 31,
  "nearby_roads": [
    {
      "name": "unnamed",
      "type": "road_unclassified"
    },
    {
      "name": "unnamed",
      "type": "road_residential"
    },
    {
      "name": "unnamed",
      "type": "road_residential"
    },
    {
      "name": "unnamed",
      "type": "road_residential"
    },
    {
      "name": "unnamed",
      "type": "road_unclassified"
    },
    {
      "name": "unnamed",
      "type": "road_unclassified"
    },
    {
      "name": "unnamed",
      "type": "road_residential"
    },
    {
      "name": "unnamed",
      "type": "road_unclassified"
    },
    {
      "name": "unnamed",
      "type": "road_unclassified"
    },
    {
      "name": "unnamed",
      "type": "road_residential"
    }
  ],
  "cut_slope_warning": "CUT_SLOPE_RISK: Road detected on/near steep terrain. May have artificial cut-slopes (taluy) not visible in DEM.",
  "has_mountain_road": true
}
```

---
