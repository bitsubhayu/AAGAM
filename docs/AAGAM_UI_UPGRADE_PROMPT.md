# AAGAM — Front-End UI/UX Upgrade Prompt (paste this whole file into Antigravity, model: Claude Sonnet 4.6)

> **Before pasting:** also attach the reference screenshot (the cream/coral financial-dashboard mockup) to the Antigravity session. This document describes its palette and layout from memory/estimation — Sonnet needs the actual image to sample exact colors and replicate the card geometry precisely.

---

## 0. Role and scope
You are working inside the existing **AAGAM** repository (`https://github.com/bitsubhayu/AAGAM`, branch `phase-9/hardening`). The frontend lives in `web/` — Vite + React + TypeScript. This session's job is **visual and interaction design only**: restyle and enrich the existing dashboard. It is not a rebuild and not a new feature pass.

**Do not change:**
- Any API call, data-fetching hook, Supabase/Groq/FastAPI integration, routing logic, or business logic.
- The shape of any data contract (component props/types) — additive-only changes are fine (e.g. an optional `className`), changing what a hook returns is not.

**You may freely change:**
- All JSX layout/markup, Tailwind classes, component visual styling.
- Add new presentational-only components and small UI-only state (animation triggers, greeting text, open/closed toggles) that never touches data-fetching.
- Add new npm dependencies **only** after running `pick-ui-library` (Emil's skill, §1) to check nothing already in the project covers it.

**Before writing any code, do this audit (report back a short summary before touching styling):**
1. Read `PRODUCT.md` and `DESIGN.md` at the repo root, and `.impeccable/` if present — Impeccable has already been initialized in this repo, so these are the current source of truth for product/design intent. Treat them as a starting point to reconcile with, not something to blindly overwrite.
2. Inspect `web/src` (or wherever the app actually lives) to see the real current component structure, existing Tailwind config/theme tokens, and routing. Do not guess file paths or assume the token names used in this prompt already exist — check.
3. Check whether Taste-Skill and Emil's skills (§1) are already installed in this Antigravity environment. Impeccable clearly is (PRODUCT.md/DESIGN.md exist); the other two may not be — install if missing.
4. If `DESIGN.md` currently documents a dark palette (an earlier planning doc, `AAGAM_TECH_STACK.md` §10.5, specified a dark teal theme), note that explicitly: this prompt is a deliberate direction change toward a light, warm palette (§2). Update `DESIGN.md` to match once the new direction is applied — don't leave two conflicting palettes documented.

---

## 1. Skills and libraries to use

### Design-quality skills (agent-instruction packs — already-familiar workflow tools, not npm libraries)
| Pack | Status here | Use |
|---|---|---|
| **Impeccable** | Already initialized (`PRODUCT.md`/`DESIGN.md` exist) — verify config is intact, don't re-run `init` destructively | Per page/section you touch: `/impeccable shape <page>` → `/impeccable craft <page>`. Close out with `/impeccable critique` → `/impeccable audit` → `/impeccable polish` → `/impeccable harden`. End with `npx impeccable detect web/src` and fix what it flags (overused fonts, gray text on colored backgrounds, pure black/gray, cards-inside-cards, bounce/elastic easing, undersized touch targets) |
| **Taste-Skill** (`github.com/Leonxlnx/taste-skill`) | Install if missing: `npx skills add https://github.com/Leonxlnx/taste-skill --skill "design-taste-frontend"` | Set dials for this pass: **DESIGN_VARIANCE 3–4**, **MOTION_INTENSITY 3**, **VISUAL_DENSITY 7–8**. This is a data-dense operational dashboard, not a marketing site — density stays high, motion stays restrained |
| **Emil Kowalski's skills** (`github.com/emilkowalski/skills`) | Install if missing: `npx skills@latest add emilkowalski/skills` | `animate` / `review-animations` / `find-animation-opportunities` for every transition you add; `pick-ui-library` before any new dependency; `ask-sonner` if toasts are used |

### Component/animation reference — Motion Primitives
`github.com/ibelick/motion-primitives` (docs: motion-primitives.com/docs). **This is a copy-paste component library (Tailwind + the `motion` package), not an agent-instruction skill** — don't try to install it the way you installed the three above. Its docs/CLI scaffolding targets Next.js; the component source itself is plain React, so it should port into this Vite app, but confirm the exact CLI invocation and each component's current props against the live docs site before using it — the library is explicitly in beta and its API changes. Use it for:
- The typewriter/text-reveal greeting (§4.1) — likely its "Text Effect" component or equivalent; check current naming.
- General pattern reference for enter/exit and hover micro-interactions elsewhere — copy only the specific components you actually need, not the whole library.

If a Motion Primitives component doesn't port cleanly to Vite, reimplement the same interaction with the `motion` package directly (Emil's `animate` skill covers this) rather than fighting the Next-specific scaffolding.

---

## 2. Visual direction (from the reference image)
The reference is a warm, cream-and-coral fintech dashboard: soft rounded "bento grid" cards of varying sizes, a near-black pill-shaped nav/logo/icon treatment, one confident coral-orange accent used sparingly for the primary CTA and for small data highlights, circular progress rings and nested concentric bubbles for proportional data, a round profile photo, and — notably — the mockup's own chat prompt ("Hey, Need help?👋 |Just ask me anything!") already shows a blinking-cursor / typewriter pattern. That pattern is exactly what's wanted for §4.1 below; look at it closely.

**Adopt the visual/interaction language — the rounded bento cards, the pill shapes, the restrained single-accent-color discipline, the circular progress motif. Do not adopt the financial domain concepts** (no wallets, staking, buy/sell, tickers) — everything gets re-mapped to AAGAM's actual data per §3.

**Estimated token palette** (eyeballed from the image, not colour-picked — verify and adjust against the actual attached file before finalizing):
```css
:root {
  /* Light theme — this becomes the new default, superseding the dark tokens in
     AAGAM_TECH_STACK.md §10.5. A dark-mode toggle can be added later; not required now. */
  --bg-canvas:      #F5F1E9;   /* warm cream page background */
  --bg-surface:     #FFFFFF;   /* card fill */
  --bg-surface-2:   #EFEAE0;   /* inset / secondary tonal card */
  --ink-1:          #1A1712;   /* primary text — warm near-black, never pure #000 */
  --ink-2:          #6E685F;   /* secondary/label text */
  --ink-3:          #A79E92;   /* tertiary/placeholder — AA-check against --bg-surface before use on real text */
  --pill-dark:      #17140F;   /* near-black pills: logo badge, icon buttons, primary nav */
  --accent:         #E85C41;   /* single brand accent — primary CTA, "Alert" severity, key highlights */
  --accent-soft:    #F7DAD2;   /* light accent tint for badges/backgrounds */
  --line:           rgba(23,20,15,0.08);
  --radius-card:    20px;
  --shadow-card:    0 1px 2px rgba(23,20,15,0.04), 0 12px 24px -8px rgba(23,20,15,0.10);

  /* Severity — reuses --accent as the top tier so the brand color itself signals urgency,
     but ALWAYS pair with an icon + text label too, never color alone (existing NFR, unchanged) */
  --sev-advisory: #D9A441;  /* warm amber */
  --sev-watch:    #E07B2E;  /* deeper orange */
  --sev-alert:    var(--accent); /* full brand coral-red = highest severity */

  /* Model colors (GFS/IFS/ICON/AIFS) — keep distinct from severity hues; verify colorblind-safety */
  --m-gfs:  #4C7BD9;
  --m-ifs:  #8B6FD9;
  --m-icon: #4FA37A;
  --m-aifs: #C98A1E;
}
```
**Typography:** avoid Inter/Arial/system-default (Impeccable will flag these as overused). Pick one distinctive geometric/grotesk sans that matches the reference's premium, confident numeral style — e.g. **General Sans** or **Switzer** (both free via Fontshare) or **Instrument Sans** / **Sora** (Google Fonts) — self-host via `@fontsource` or Fontshare's own hosting, not a runtime Google Fonts call. Use `font-variant-numeric: tabular-nums` on all data figures.

**Card language:** large radius (~20px), soft multi-layer shadow (not a hard border), generous internal padding, a bento-style grid mixing 1×1, 2×1, and 1×2 card sizes rather than a uniform grid — matches the reference's KPI-tile-plus-hero layout.

---

## 3. Content mapping — reference layout → AAGAM data
Translate the mockup's card *shapes and interaction patterns* to AAGAM's actual content. Don't force every element 1:1; use judgment on what's genuinely useful.

| Reference element | AAGAM equivalent |
|---|---|
| Black pill logo badge, top-left | AAGAM logo/wordmark |
| "Hey, Need help?👋 Just ask me anything!" chat prompt + mic icon | The AI Assistant entry point (§4.2) |
| Date badge (day + "Tue, December") | Current date + "Last blended [time] · model v[x]" freshness stamp |
| "Show my Tasks" coral CTA pill | Primary CTA — e.g. **Get Alerts** on the home page, or **View Alerts** |
| Circular donut ("36% Growth rate") | A single KPI ring — e.g. blend skill gain vs. best single model, or overall model confidence for the selected view |
| "13 Days / 109 hours, 23 minutes" countdown card | Time until next scheduled retrain, or time since last pipeline cycle (freshness) |
| Small mini-chart card with year toggle | Small skill-trend sparkline, toggled by lead day or region |
| "$16,073.49 Main Stocks +9.3%" trend card with sparkline | A location's blended forecast trend for the selected variable |
| Nested concentric bubbles ("Annual profits" $14K/$9.3K/$6.8K/$4K) | Active alerts broken down by severity — outer ring = total, nested = advisory/watch/alert counts |
| "Activity manager" bar chart with filters (Team/Insights/Today) | Forecast Explorer preview or model-comparison mini chart, with the same filter-pill pattern |
| "Business plans" list (Bank loans/Accounting/HR) | Quick-links list — My Locations / Weight Maps / Skill / Extreme Weather |
| "Wallet Verification — Enable" card | The subscribe/OTP flow entry card — **Get Alerts**, matches the "verify then enable" pattern directly |
| "How is your business management going?" rating card | Lightweight feedback on an alert or an assistant answer ("Was this helpful?") |
| Top-right search bar | Global search — jump to a location, page, or alert |

---

## 4. The two required animations

### 4.1 Typewriter greeting
On landing (home/overview), show a time-of-day-aware, name-aware greeting that types itself out character-by-character, exactly matching the interaction pattern already visible in the reference mockup's chat prompt (text appears with a visible cursor, as if being typed).
- Logic: `Good morning` (before ~12:00 local), `Good afternoon` (~12:00–17:00), `Good evening` (after ~17:00) — use the browser's local time, not a server assumption.
- Name: if a subscriber is logged in, use their display name or email prefix ("Good evening, Subhayu"); if anonymous, a generic variant ("Good evening — here's what's active right now") — never invent a name for an anonymous visitor.
- Runs once per page load (don't re-type on every re-render); respects `prefers-reduced-motion` by showing the final text immediately with no animation when that's set.
- Build with Motion Primitives' text-effect component if it ports cleanly, otherwise hand-roll with the `motion` package per Emil's `animate` skill.

### 4.2 Animated assistant entry point
The control that opens the AI Assistant (chat drawer) needs a small, continuous, tasteful idle animation — a gentle "moving bot" presence, not a static icon — so it reads as alive/available without being distracting.
- Keep it subtle: a slow breathing/pulse scale, a soft glow, or a very small idle bob — pick one, not several at once. No bounce/elastic easing (Impeccable will flag it).
- Pause the idle animation while the assistant drawer is open (it's already got the user's attention; don't compete with it).
- Respect `prefers-reduced-motion` — fall back to a static icon with no motion.
- This is the single most decorative element allowed in this pass — keep everything else (§5) restrained by comparison, per the MOTION_INTENSITY 3 dial.

---

## 5. Motion principles for everything else
Subtle and purposeful only — this is an operational dashboard people use for minutes at a time, not a landing page. Beyond the two animations above:
- Panel open/close, tab switches, and chart data updates get short (~150–250ms) ease-out transitions. **Enter = ease-out**, never ease-in (a common agent mistake per Emil's notes).
- KPI numbers may count up once on first load — never re-trigger on every poll/refresh.
- No animation should hide or delay a number the user is trying to read (e.g. don't animate a severity badge's color in a way that's ambiguous mid-transition).
- Everything respects `prefers-reduced-motion: reduce` globally, not just the two named animations.
- Run `find-animation-opportunities` once per page (Emil's skill) — it also tells you what *not* to animate; don't add motion just because the tool ran.

---

## 6. Responsiveness (must hold after all of the above)
Deploying to **Vercel's free tier** — ship a fully static, client-rendered bundle; nothing here should require a server-only animation dependency.
- Desktop-first (≥1280px is the primary target — this is a control-room-style tool), but must degrade cleanly to tablet and to a reduced phone layout (Overview + Alerts + Assistant, per the existing PRD).
- The bento-grid card layout must reflow to a single column on narrow viewports without breaking card content or truncating numbers.
- Wide content (tables, charts) scrolls inside its own container — the page body itself never scrolls sideways.
- Touch targets ≥44px (Impeccable flags undersized ones).
- Test the two new animations specifically at phone width — a bot icon or typewriter line that looks fine at 1280px can crowd a small header; adjust size/position per breakpoint rather than just scaling down.
- WCAG 2.1 AA contrast still applies with the new light palette — check `--ink-2`/`--ink-3` against `--bg-surface` and `--bg-canvas` specifically, since warm grays on cream can quietly fail contrast where dark-on-dark didn't.

---

## 7. Execution order
1. **Audit** (§0) — read existing docs and code, report findings, install missing skills.
2. **Foundations** — add/replace the token set (§2) in the actual theme config you found in step 1 (don't assume Tailwind config location/shape — confirm it); pick and self-host the typeface; update `DESIGN.md` to match.
3. **Layout shell** — restyle the app shell/nav into the pill/bento language (§2) without touching routing.
4. **Page-by-page restyle**, one page at a time, each closed out with Impeccable's `critique` → `audit` → `polish` → `harden`: Overview (includes the content-mapping bento cards, §3), Forecast Explorer, Weight Maps, Skill, Extreme Weather Center, Assistant drawer/page, Data & Export, Pipeline Health, Auth/Settings.
5. **The two signature animations** (§4) — implement last, once the static layout is settled, so they're layered onto stable markup rather than fought while everything else is still moving.
6. **Responsive + motion QA pass** (§6) at 1280px, ~1024px, ~768px, and ~390px; verify `prefers-reduced-motion` at each.
7. **Final `npx impeccable detect web/src`** across the whole app; fix remaining flags.
8. Report back a short summary of what changed, what didn't port cleanly from Motion Primitives (if anything), and any token/contrast values you had to adjust from the estimates in §2.

## 8. Definition of done
- [ ] No data-fetching, routing, or business logic changed — visual/markup only.
- [ ] `DESIGN.md` updated to reflect the new light/warm palette (no leftover conflicting dark-theme doc).
- [ ] Typewriter greeting works, is time-of-day and login-aware, and respects reduced motion.
- [ ] Assistant entry point has a subtle idle animation that pauses when open and respects reduced motion.
- [ ] All severity indicators still carry icon + text label, not color alone, even with the new palette.
- [ ] Layout reflows cleanly at all four test widths in §7.6 with no horizontal page scroll.
- [ ] `npx impeccable detect web/src` run at the end with no unresolved flags (or each remaining flag has a stated reason).
