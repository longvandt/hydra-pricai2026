# Hydra-Bench construction

## Positive event sampling

**Why local news, not global catalogs.** Global repositories such as DesInventar and the NASA Global Landslide Catalog contain few Vietnam events and are heavily biased toward catastrophic cases, so the 2024 corpus is built from local Vietnamese news instead.

**Extraction pipeline** (not part of this release — code lives outside `src/`, see the paper's methodology section):

1. Each province-month is queried with date-constrained Google Custom Search terms for "floods" and "landslides."
2. Matching articles are extracted with **Gemini 3 Flash**, enforced JSON output, temporal guards (preventing the model from conflating article publication date with event date), typed Pydantic schema validation, province-mismatch filtering (an event whose extracted province doesn't match the queried province is discarded), and same-date/co-located deduplication.
3. For each event, the pipeline extracts: province, district, street or landmark, event date, hazard type/subtype, a confidence tier, and impact severity.
4. Addresses are geocoded with Google Maps and cached by normalized address.

**Confidence tiers** capture extraction reliability, not event severity. In the 500-event positive samples released here: flood confidence is 40% High / 58% Medium / 2% Low; landslide confidence is 64% High / 36% Medium / 0% Low.

**Manual quality check.** An inspection of roughly 50 events confirmed correct date, location, and disaster-type extraction, and geocoding accurate to the street block in most cases — though no formal inter-annotator agreement study was conducted.

**Corpus size and stratified sampling.** The pipeline yielded 3,124 flood events and 1,007 landslide events for Vietnam in 2024. From this corpus, 500 flood events and 500 landslide events were drawn as a stratified sample, balanced by region, province, terrain, severity, and subtype (`flood_events.json`/`landslide_events.json` in this directory).

**Landslide scope.** The landslide sample includes only rainfall-triggered highland events on steep slopes. Riverbank erosion, coastal erosion, and human-induced slope failures are excluded, since they follow physical mechanisms distinct from the shallow rainfall-triggered model encoded in the system prompt.

**Geographic distribution reflects physical geography, not sampling artifacts.** Floods span all three regions, with the Northern region dominant due to its long monsoon season and dense river network. Landslides concentrate in the Northern region (83.2%), where the Northwest Highlands and northern karst ranges provide the slope angles and weathered lithology needed for shallow rainfall-triggered failure. No southern-province landslides are included, consistent with the flat Mekong Delta and the scope exclusions above. Event timing follows regional monsoon calendars, indicating genuine seasonal signal rather than uniform background noise.

See the paper's Table 1 for the full region / hazard-subtype / severity / peak-month breakdown of both 500-event samples.

## Negative sampling

Negative samples are location-date pairs with no recorded disaster. Because Hydra retrieves physical drivers at inference time rather than using learned feature vectors, negatives must represent physically meaningful non-event conditions rather than random coordinates. A two-tier stratified design is used, at a 1:1 positive-to-negative ratio for both hazards.

**Spatial constraint.** Every negative reuses the coordinates of a verified positive event, forcing evaluation at disaster-prone sites rather than geographically inert terrain.

**Tier 1 — Cross-season (easy).** The date is sampled from the core dry season of the source province. Candidates are rejected if any verified positive occurs in the same province within ±7 days; same-day provincial events are also excluded, guarding against anomalous dry-season flash floods. This tier tests whether the agent recognizes the *absence* of physical drivers, rather than merely memorizing geographic flood-proneness.

**Tier 2 — Temporal-proximity (hard).** The date is shifted ±4–6 weeks from the true event while remaining within the same rainy season. Candidates are rejected if any verified positive occurs in the same province within ±7 days. These negatives share similar soil-moisture and rainfall regimes with real events, testing whether the agent distinguishes a genuinely triggering physical state from an elevated-but-sub-threshold one.

The two-tier structure supports separate reporting on easy vs. hard negatives, alongside the aggregate F1 score, for a clearer operational error profile.

## Known limitations

- Labels are news-derived and therefore subject to reporting bias toward severe, populated events. A negative label means *no recorded report*, not *verified absence* of an event.
- `flood_events.json`/`landslide_events.json` carry the structured extracted fields and the source URL — not the article text itself, which remains with its publisher.
