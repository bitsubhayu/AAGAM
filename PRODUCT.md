# AAGAM — Product Definition & User Foundations

**Adaptive AI-Grid Assimilation Model** · SIH 2026 · Problem Statement 26081 (MoES / NCMRWF)  
*Hybrid AI–NWP Multi-Model Forecast Blending & Extreme Weather System*

---

## 1. Product Purpose & Value Proposition

AAGAM dynamically monitors recent multi-model forecast accuracy across Indian regions, lead times (0–7 days), and seasons, blending four premier forecast sources (**GFS, ECMWF IFS, DWD ICON, and ECMWF AIFS**) into an explainable, optimized forecast for rainfall, temperature, and wind.

### Key Differentiators
1. **Engineered for Operational Decision-Makers**: Built specifically for national forecasters and disaster managers, not consumer mobile weather apps.
2. **Transparent & Auditable**: Open weight maps show exactly why a model is trusted; forecasters can apply documented adjustments with full audit trails.
3. **India-Calibrated**: Evaluated against IMD gridded rainfall (0.25°) using official IMD thresholds and 08:30 IST accumulation conventions.
4. **Explainable AI**: The AAGAM Assistant translates model spread and telemetry into briefings without hallucinating numbers.

---

## 2. Target Users & Roles

| Persona | Real-World Role | Primary Needs in AAGAM | System Role |
|---|---|---|---|
| **Dr. Meera** | NCMRWF / IMD Duty Forecaster | Rapid model comparisons, lead-time weight inspection, audited weight overrides, alert acknowledgements, CSV export | `forecaster` |
| **Forecaster Coordinator** | Senior Duty Lead / Forecaster Coordinator | Full forecaster duties + designate/promote existing verified forecasters to coordinator | `coordinator` |
| **Mr. Rao** | State / District Disaster Duty Officer | Clear hazard alerts (heavy rain, heatwave, wind), multi-model agreement flags, alert subscriptions | `public` |
| **Sector Analyst** | Agriculture, Power, Aviation, Water | Parameter-specific forecasts, historical data comparisons, bulk downloads | `public` |
| **Researcher / Developer** | Academic Teams, Hackathon Judges | Model skill matrices (MAE/RMSE/bias), raw tables, pipeline telemetry | `public` |

---

## 3. Design Philosophy & Taste Dials

AAGAM is a **dense technical workstation** designed for operational situational awareness.

### Taste-Skill Dial Settings
- **`DESIGN_VARIANCE = 3`**: Highly structured, predictable, and scannable layouts. Consistent visual rhythm across pages.
- **`MOTION_INTENSITY = 3`**: Subtle, functional motion for enter/exit states, alert arrivals, and chart transitions. No distracting decorative animations.
- **`VISUAL_DENSITY = 8`**: Compact information density with high data-to-ink ratio. Modular card grids, tabular figures, and multi-model comparison matrices.

### Visual Foundations & Layout Reference
- **Theme**: Dark technical surface (`#0d1117` base, `#161b22` panels, `#30363d` borders).
- **Typography**: IBM Plex Sans (interface) + IBM Plex Mono (tabular figures, model numbers, timestamps).
- **Layout Architecture**: Fixed left sidebar navigation, top KPI overview tiles, modular card grid.
- **Strict Boundary**: Layout inspiration drawn from dense monitoring dashboards; **zero crypto/finance semantics** (strictly meteorological parameters: mm/24h, °C, km/h, lead days).

---

## 4. Skill Precedence Hierarchy
1. `PRD` + `PRODUCT.md` (Domain mission, operational guidelines, IMD thresholds)
2. `Impeccable` (Design system tokens, anti-pattern rules, accessibility)
3. `Taste-Skill` (Variance, density, and layout dials)
4. `Emil Kowalski skills` (Micro-motion, chart transitions, toast ergonomics)
