# AAGAM — Design System & UI Specification

**AAGAM = Adaptive AI-Grid Assimilation Model** · SIH 2026 · PS 26081 (MoES / NCMRWF)  
*Dense Technical Weather & Disaster Management Workstation*

> **Direction note (updated 2026-09-22):** This document supersedes the earlier dark-teal palette documented in `AAGAM_TECH_STACK.md §10.5`. The dashboard now uses a light, warm cream-and-coral palette as detailed below.

---

## 1. Design Tokens & Color Palette

### Surfaces & Elevation (Light Warm Theme)

| Token | Value | Usage |
|---|---|---|
| `--bg-canvas` | `#F5F1E9` | Warm cream — page/app background |
| `--bg-surface` | `#FFFFFF` | Card fill |
| `--bg-surface-2` | `#EFEAE0` | Inset / secondary tonal card, filter controls |
| `--line` | `rgba(23,20,15,0.08)` | Dividers, subtle card borders |

### Ink / Typography Colors

| Token | Value | Usage |
|---|---|---|
| `--ink-1` | `#1A1712` | Primary text — warm near-black (never pure `#000`) |
| `--ink-2` | `#6E685F` | Secondary / label text |
| `--ink-3` | `#A79E92` | Tertiary / placeholder — AA-checked against `--bg-surface` |

### Brand Accent (single)

| Token | Value | Usage |
|---|---|---|
| `--accent` | `#E85C41` | Coral-red — primary CTA, Alert severity, key data highlights |
| `--accent-soft` | `#F7DAD2` | Light accent tint for badges and chip backgrounds |
| `--pill-dark` | `#17140F` | Near-black pills: logo badge, icon buttons, primary nav |

### Hazard & Semantic Accents

| Semantic Role | Token | Value | Use in AAGAM |
|---|---|---|---|
| **Advisory / Low Hazard** | `--sev-advisory` | `#D9A441` | Rain 64.5mm advisory, moderate wind |
| **Watch / High Hazard** | `--sev-watch` | `#E07B2E` | 2+ models ≥ 64.5mm, heatwave watch |
| **Alert / Severe** | `--sev-alert` | `#E85C41` (= `--accent`) | 3+ models ≥ 64.5mm, strong gale |
| **Normal / Success** | — | `#3D9970` | Pipeline OK, verified connectivity |

> WCAG rule: Color is **never** the sole indicator of severity. Every alert carries icon + text label + numerical value.

### Model Colors (colorblind-safe, distinct from severity hues)

| Model | Token | Value |
|---|---|---|
| GFS (Physics) | `--m-gfs` | `#4C7BD9` — blue |
| ECMWF IFS (Physics) | `--m-ifs` | `#8B6FD9` — purple |
| DWD ICON (Physics) | `--m-icon` | `#4FA37A` — teal-green |
| ECMWF AIFS (AI) | `--m-aifs` | `#C98A1E` — warm gold |

---

## 2. Typography Rules

- **UI Headings & Body**: `Instrument Sans`, system-ui, sans-serif — self-hosted via `@fontsource/instrument-sans`
- **Metrics, Model Values & Timestamps**: `IBM Plex Mono`, monospace — self-hosted via `@fontsource/ibm-plex-mono`
- **Numeric rendering**: `font-variant-numeric: tabular-nums` applied to all data figures
- **Type Scale**:
  - H1 Page Title: `text-xl font-bold tracking-tight` (20px)
  - Card Header / Subheading: `text-sm font-semibold` (14px)
  - Body Text: `text-xs font-normal` (12px)
  - Fine Print / Units / Badges: `text-[11px]` or `text-[10px] font-mono`

---

## 3. Card & Geometry Language

```css
--radius-card:  20px;      /* all main cards */
--shadow-card:  0 1px 2px rgba(23,20,15,0.04), 0 12px 24px -8px rgba(23,20,15,0.10);
```

- **Large radius** (~20px), soft multi-layer shadow, no hard border ring (border is only a subtle `--line` rgba)
- **Bento grid**: mixes 1×1, 2×1, and 1×2 card sizes rather than uniform grid
- **Generous internal padding** (`p-5` or `p-6`) for primary cards; `p-4` for compact tiles
- **Pill shapes** for badges, CTAs, nav elements, logo badge

---

## 4. Density & Layout Architecture

### Dials
- `VISUAL_DENSITY = 7–8`: Compact paddings for data elements, generous padding inside cards
- `DESIGN_VARIANCE = 3–4`: Bento grid layout with controlled variance in card sizes
- `MOTION_INTENSITY = 3`: Transitions capped at 150–250ms `ease-out`. No bounce/elastic easing.

### Screen Hierarchy
1. **Top Header**: AAGAM pill logo, variable/lead controls (pill-shaped), freshness stamp, role switcher, animated assistant entry
2. **Left Sidebar**: Nav items with coral active state, collapsible 56px/224px
3. **Main Content**: Bento-grid cards — KPI tiles row + map + alerts on Overview; page-specific layouts elsewhere
4. **Slide-out Drawer**: AAGAM Assistant (right side, warm surface)

---

## 5. Signature Animations (§4 from upgrade prompt)

### 5.1 Typewriter Greeting
- Time-of-day aware (morning/afternoon/evening) using browser local time
- Login-aware (subscriber name from email prefix, or generic fallback)
- Runs once per page load; `prefers-reduced-motion: reduce` → final text immediately, no animation

### 5.2 Animated Assistant Entry Point
- Slow breathing scale pulse (~2.5s loop, scale 1 → 1.08 → 1, no bounce easing)
- Pauses while assistant drawer is open
- `prefers-reduced-motion: reduce` → static icon

---

## 6. Accessibility & Non-Color Encoding (WCAG 2.1 AA)

- **Strict Non-Color Principle**: Color is **never** the sole indicator of hazard severity. Every alert card and table row carries:
  1. An explicit icon (`AlertCircle`, `CloudRain`, `Flame`, `Wind`)
  2. A clear text severity label (`Advisory`, `Watch`, `Alert`)
  3. The exact numerical value and unit (`78.4 mm/24h`)
- **Contrast**: `--ink-2` (#6E685F) on `--bg-surface` (#FFF) = 5.5:1 ✓ AA. `--ink-3` (#A79E92) on `--bg-surface` = 2.7:1 — use only for decorative/non-essential text (placeholder, timestamp hint), not standalone data labels
- **Focus Rings**: All interactive elements provide visible high-contrast focus rings (`focus:ring-2 focus:ring-accent/50`)
- **Touch Targets**: ≥ 44px for all interactive controls on mobile viewports
