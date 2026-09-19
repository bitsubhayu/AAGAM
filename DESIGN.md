# AAGAM — Design System & UI Specification

**AAGAM = Adaptive AI-Grid Assimilation Model** · SIH 2026 · PS 26081 (MoES / NCMRWF)  
*Dense Technical Weather & Disaster Management Workstation*

---

## 1. Design Tokens & Color Palette

### Surface & Elevation (Dark Technical Theme)
- **App Background**: `#0d1117` (Deep dark slate)
- **Card / Panel Surface**: `#161b22` (Raised container)
- **Nested Surface / Input**: `#21262d` (Controls, dropdowns, table headers)
- **Border Default**: `#30363d` (Subtle boundary definition)
- **Border Subtle**: `#21262d` (Inner cell dividers)

### Typography & Contrast
- **Text Primary**: `#f0f6fc` (Headers, key figures, active tab)
- **Text Secondary**: `#c9d1d9` (Body text, chart legends, table cells)
- **Text Muted**: `#8b949e` (Labels, units, timestamps, disabled states)

### Hazard & Semantic Accents
| Semantic Role | Hex Token | Use in AAGAM |
|---|---|---|
| **Advisory / Low Hazard** | `#d29922` (Amber/Yellow) | Rain 64.5mm advisory, moderate wind, waking state |
| **Watch / High Hazard** | `#db6d28` (Orange) | 2+ models >= 64.5mm, heatwave watch |
| **Alert / Severe Hazard** | `#f85149` (Red) | 3+ models >= 64.5mm, severe heatwave, strong gale |
| **Normal / Success** | `#2ea043` (Green) | Pipeline success, verified database connectivity |
| **Primary Brand / Action** | `#388bfd` (Blue) | Interactive controls, active tabs, blended forecast series |
| **AIFS (AI Model)** | `#a371f7` (Purple) | Dedicated line/badge color for ECMWF AIFS |
| **GFS (Physics Model)** | `#58a6ff` (Light Blue) | Dedicated color for GFS series |
| **ECMWF IFS (Physics)** | `#3fb950` (Emerald) | Dedicated color for ECMWF IFS 0.25° |
| **DWD ICON (Physics)** | `#f0883e` (Amber) | Dedicated color for DWD ICON |

---

## 2. Typography Rules

- **UI Headings & Body**: `IBM Plex Sans`, `-apple-system, BlinkMacSystemFont, sans-serif`.
- **Metrics, Model Values & Timestamps**: `IBM Plex Mono`, `monospace` (Tabular numerals enabled to ensure vertical alignment of numerical data).
- **Type Scale**:
  - H1 Page Title: `text-xl font-bold tracking-tight` (20px)
  - Card Header / Subheading: `text-sm font-semibold` (14px)
  - Body Text: `text-xs font-normal` (12px)
  - Fine Print / Units / Badges: `text-[11px]` or `text-[10px] font-mono`

---

## 3. Density & Layout Architecture

### Dials
- `VISUAL_DENSITY = 8`: Compact paddings (`p-3`, `p-4`), tight gap spacing (`gap-3`, `gap-4`).
- `DESIGN_VARIANCE = 3`: Strict modular grid layout across all dashboard screens.
- `MOTION_INTENSITY = 3`: Transitions capped at 150–200ms `ease-out`. No bouncy physics.

### Screen Hierarchy
1. **Top Header**: Organization branding, system status, active version, last refresh timestamp (IST).
2. **Top KPI Tiles**: Active alerts, dominant model this week, blend skill gain vs equal-mean, pipeline health.
3. **Primary Viewport**:
   - Split map / graph view (Leaflet + ECharts).
   - Multi-model comparison matrix with confidence band.
4. **Bottom Dock**: Status footer, data attribution notice (CC BY 4.0).

---

## 4. Accessibility & Non-Color Encoding (WCAG 2.1 AA)

- **Strict Non-Color Principle**: Color is **never** the sole indicator of hazard severity. Every alert card and table row carries:
  1. An explicit icon (`AlertCircle`, `CloudRain`, `Flame`, `Wind`).
  2. A clear text severity label (`Advisory`, `Watch`, `Alert`).
  3. The exact numerical value and unit (`78.4 mm/24h`).
- **Focus Rings**: All interactive elements provide visible high-contrast focus rings (`focus:ring-2 focus:ring-blue-500`).
