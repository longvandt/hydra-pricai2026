# Landslide assessment, Thôn Quyết Tiến, Huyện Hoàng Su Phì, Hà Giang

**Event** cebac2e4-9a78-4c08-b739-d4f0e6e2e9c4 | **Backbone** gemini-3.1-flash-lite | **Lead** T-3
**Ground truth** negative | **Predicted** LOW
**Tool calls** 10 | **Latency** 14.6s | **Tokens** 6780

---

### Final Assessment

### Final Risk Assessment
- **Terrain:** Steep mountain zone with an elevation of ~1692m. Slopes are significant, with an average of ~26° and localized sections up to ~47°. Several mountain roads exist within the 2km radius, indicating potential artificial cut-slopes (*taluy*) which are high-risk zones for instability.
- **Saturation:** Soil moisture is high at 0.498 m³/m³ (classified as "saturated"). However, the API (9.6) suggests that the cumulative rainfall over the preceding week was relatively low, implying the saturation might be locally persistent or related to factors other than intense recent regional precipitation.
- **Rainfall (ERA5 → corrected ×3):** Trigger-day 6.3mm → 18.9mm; 3-day 16.9mm → 50.7mm; 7-day 17mm → 51mm.
- **Do & Yin:** The calculated 3-day threshold is 30.6mm, against a trigger of 18.9mm. The threshold was not exceeded (margin -11.7mm); 0/3 windows were triggered.
- **Interpretation:** While the local soil is saturated and the terrain is inherently prone to landslides due to its steep topography and presence of cut-slopes, the precipitation levels on the event day and preceding days were insufficient to reach the established regional rainfall thresholds for triggering significant mass movements.
- **Risk Level:** **LOW**
- **Confidence:** **MEDIUM** — The soil saturation is concerning, but the lack of significant rainfall loading and the non-exceedance of the Do & Yin threshold suggest that the probability of a widespread landslide event is low. Confidence is medium due to the inherent uncertainty in applying satellite-based rainfall estimates and the potential for micro-scale hydro-geological conditions at this specific site.

**Risk Level: LOW**

---

### Tool Call Traces

**Call 1.** `get_elevation_slope(lat=22.6758, lon=104.7634)`

**Observation.**
```json
{
  "slope": 23.47,
  "cached": true,
  "source": "opentopodata_srtm30m",
  "terrain": "mountain",
  "elevation": 1692
}
```

---

**Call 2.** `get_terrain_profile(max_lat=22.6808, max_lon=104.7684, min_lat=22.6708, min_lon=104.7584)`

**Observation.**
```json
{
  "note": "Sampled 25 points. Max slope = steepest section.",
  "terrain": "mountain",
  "avg_slope": 25.9,
  "max_slope": 46.97,
  "sample_count": 25,
  "elevation_range": {
    "max": 1870.0,
    "min": 1480.0
  }
}
```

---

**Call 3.** `get_historical_rainfall(lat=22.6757954, lon=104.7634362, event_date='2024-01-03', days_before=3)`

**Observation.**
```json
{
  "days": 3,
  "period": "2023-12-31 to 2024-01-03",
  "total_mm": 16.9,
  "max_1h_mm": 1.5,
  "max_2h_mm": 2.7,
  "max_3h_mm": 3.8,
  "max_6h_mm": 5.5,
  "max_12h_mm": 6.5,
  "max_24h_mm": 7.8,
  "daily_breakdown": [
    {
      "date": "2023-12-31",
      "rain_mm": 1.5
    },
    {
      "date": "2024-01-01",
      "rain_mm": 4.3
    },
    {
      "date": "2024-01-02",
      "rain_mm": 4.8
    },
    {
      "date": "2024-01-03",
      "rain_mm": 6.3
    }
  ]
}
```

---

**Call 4.** `get_historical_rainfall(lat=22.6757954, lon=104.7634362, event_date='2024-01-03', days_before=5)`

**Observation.**
```json
{
  "days": 5,
  "period": "2023-12-29 to 2024-01-03",
  "total_mm": 17.0,
  "max_1h_mm": 1.5,
  "max_2h_mm": 2.7,
  "max_3h_mm": 3.8,
  "max_6h_mm": 5.5,
  "max_12h_mm": 6.5,
  "max_24h_mm": 7.8,
  "daily_breakdown": [
    {
      "date": "2023-12-29",
      "rain_mm": 0.0
    },
    {
      "date": "2023-12-30",
      "rain_mm": 0.1
    },
    {
      "date": "2023-12-31",
      "rain_mm": 1.5
    },
    {
      "date": "2024-01-01",
      "rain_mm": 4.3
    },
    {
      "date": "2024-01-02",
      "rain_mm": 4.8
    },
    {
      "date": "2024-01-03",
      "rain_mm": 6.3
    }
  ]
}
```

---

**Call 5.** `get_historical_rainfall(lat=22.6757954, lon=104.7634362, event_date='2024-01-03', days_before=7)`

**Observation.**
```json
{
  "days": 7,
  "period": "2023-12-27 to 2024-01-03",
  "total_mm": 17.0,
  "max_1h_mm": 1.5,
  "max_2h_mm": 2.7,
  "max_3h_mm": 3.8,
  "max_6h_mm": 5.5,
  "max_12h_mm": 6.5,
  "max_24h_mm": 7.8,
  "daily_breakdown": [
    {
      "date": "2023-12-27",
      "rain_mm": 0.0
    },
    {
      "date": "2023-12-28",
      "rain_mm": 0.0
    },
    {
      "date": "2023-12-29",
      "rain_mm": 0.0
    },
    {
      "date": "2023-12-30",
      "rain_mm": 0.1
    },
    {
      "date": "2023-12-31",
      "rain_mm": 1.5
    },
    {
      "date": "2024-01-01",
      "rain_mm": 4.3
    },
    {
      "date": "2024-01-02",
      "rain_mm": 4.8
    },
    {
      "date": "2024-01-03",
      "rain_mm": 6.3
    }
  ]
}
```

---

**Call 6.** `get_rainfall_after_event(lat=22.6757954, lon=104.7634362, hours=72, event_date='2024-01-03')`

**Observation.**
```json
{
  "note": "Actual recorded rainfall after event (simulates forecast for historical validation)",
  "total_mm": 6.3,
  "period_hours": 72
}
```

---

**Call 7.** `get_antecedent_precipitation_index(lat=22.6757954, lon=104.7634362, event_date='2024-01-03')`

**Observation.**
```json
{
  "api_value": 9.6,
  "period_days": 7,
  "decay_factor": 0.85,
  "interpretation": "low_saturation",
  "daily_breakdown": [
    {
      "date": "2023-12-27",
      "rain_mm": 0.0
    },
    {
      "date": "2023-12-28",
      "rain_mm": 0.0
    },
    {
      "date": "2023-12-29",
      "rain_mm": 0.0
    },
    {
      "date": "2023-12-30",
      "rain_mm": 0.1
    },
    {
      "date": "2023-12-31",
      "rain_mm": 1.5
    },
    {
      "date": "2024-01-01",
      "rain_mm": 4.3
    },
    {
      "date": "2024-01-02",
      "rain_mm": 4.8
    }
  ],
  "total_rainfall_mm": 10.7
}
```

---

**Call 8.** `get_soil_moisture(lat=22.6757954, lon=104.7634362, event_date='2024-01-03')`

**Observation.**
```json
{
  "date": "2024-01-03",
  "saturation": "saturated",
  "soil_moisture_m3_per_m3": 0.498
}
```

---

**Call 9.** `get_nearby_mountain_road(lat=22.6757954, lon=104.7634362)`

**Observation.**
```json
{
  "source": "OpenStreetMap_Overpass_2000m",
  "road_count": 6,
  "nearby_roads": [
    {
      "name": "unnamed",
      "type": "road_tertiary"
    },
    {
      "name": "unnamed",
      "type": "road_residential"
    },
    {
      "name": "unnamed",
      "type": "road_tertiary"
    },
    {
      "name": "unnamed",
      "type": "road_tertiary"
    },
    {
      "name": "unnamed",
      "type": "road_tertiary"
    },
    {
      "name": "unnamed",
      "type": "road_tertiary"
    }
  ],
  "cut_slope_warning": "CUT_SLOPE_RISK: Road detected on/near steep terrain. May have artificial cut-slopes (taluy) not visible in DEM.",
  "has_mountain_road": true
}
```

---

**Call 10.** `calculate_doyin_threshold(antecedent_3day_mm=50.7, antecedent_5day_mm=51, antecedent_7day_mm=51, trigger_day_rain_mm=18.9)`

**Observation.**
```json
{
  "formula_ref": "Do & Yin (2018), Open Journal of Geology, DOI:10.4236/ojg.2018.87040",
  "primary_result": {
    "formula": "RT = 40.8 − 0.201 × 50.7 = 30.6mm",
    "exceeded": false,
    "margin_mm": -11.7,
    "window_days": 3,
    "threshold_mm": 30.6,
    "antecedent_mm": 50.7,
    "trigger_day_rain_mm": 18.9
  },
  "window_results": [
    {
      "formula": "RT = 40.8 − 0.201 × 50.7 = 30.6mm",
      "exceeded": false,
      "margin_mm": -11.7,
      "window_days": 3,
      "threshold_mm": 30.6,
      "antecedent_mm": 50.7,
      "trigger_day_rain_mm": 18.9
    },
    {
      "formula": "RT = 44.7 − 0.087 × 51.0 = 40.3mm",
      "exceeded": false,
      "margin_mm": -21.4,
      "window_days": 5,
      "threshold_mm": 40.3,
      "antecedent_mm": 51.0,
      "trigger_day_rain_mm": 18.9
    },
    {
      "formula": "RT = 47.36 − 0.047 × 51.0 = 45.0mm",
      "exceeded": false,
      "margin_mm": -26.1,
      "window_days": 7,
      "threshold_mm": 45.0,
      "antecedent_mm": 51.0,
      "trigger_day_rain_mm": 18.9
    }
  ],
  "study_area_note": "Calibrated for Hà Giang province, NW Vietnam (37 events, 1990–2016). Agent should assess applicability to the target location.",
  "windows_exceeded": 0
}
```

---
