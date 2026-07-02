# Enma UI Style Guide
> Derived from the AlgoTrading page redesign. Apply these principles to all pages for visual consistency.

---

## Philosophy

The UI targets a **professional trading terminal aesthetic** — dark, dense, and data-forward. Panels have visual depth through layered backgrounds rather than decorative elements. Color is used functionally (status, P&L direction, interactive state) not decoratively. Every element earns its place.

---

## Global Layout Rules (Non-Negotiable)

### Rule 1 — No Rounded Corners
All `borderRadius` values are overridden to `0px` in `tailwind.config.js` (theme-level, not extend). The CSS variable `--radius` is also `0px`. **Never add `rounded-*` classes.** Every div, panel, button, input, badge, and card renders as a sharp rectangle.

### Rule 2 — Connected Panels (No Inter-Section Gaps)
Panels and sections must be **flush against each other** — no margins or gaps between major layout blocks. Reference: the Trade page, where TickerBar, Chart, BottomPanel, OrderBook, and OrderForm touch each other with only a shared `border-*` separating them.

- Panel grids: always `gap-0` (not `gap-4` or `gap-6`)
- Section stacks: always `space-y-0` (not `space-y-6` or `space-y-4` at panel level)
- No `mt-6` between content sections
- `PageWrapper` has no padding — pages are edge-to-edge
- `PageHeader` is a full-width bar with `border-b border-slate-700/50` and `title-fade`
- Use `border-r` / `border-b` / `divide-*` utilities for visual separation between connected panels

Small inline gaps (`gap-2`, `gap-3`) inside component internals (icon+text, form field grids) are still allowed.

---

## Color Palette

### Backgrounds (darkest → lightest, use in layers)

| Token | Hex | Usage |
|---|---|---|
| `bg-[#060a0f]` | #060a0f | Terminal/log inner boxes — deepest layer |
| `bg-[#080b10]` | #080b10 | Primary expanded panel rows (row 1) |
| `bg-[#0a0d13]` | #0a0d13 | Secondary expanded panel rows (row 2) |
| `bg-[#0d1117]` | #0d1117 | Card base, StatTiles, inner tiles |
| `bg-slate-900/70` | — | Avoid — reads warmer than midnight blue |
| `bg-gray-900` | — | Avoid on new components — too neutral/warm |

### Borders

| Usage | Class |
|---|---|
| Card outer border | `border-slate-700/50` |
| Panel dividers (between sections) | `divide-slate-700/40` |
| Row separator borders | `border-slate-700/50` |
| Inner tiles / StatTiles | `border-slate-700/40` |
| Table header underline | `border-slate-700/50` |
| Table row dividers | `border-slate-700/30` |
| Terminal/log box border | `border-slate-700/30` |

### Text

| Role | Class |
|---|---|
| Primary data / values | `text-gray-100` |
| Secondary labels / metadata | `text-slate-400` |
| Section titles | `text-gray-300` |
| Table column headers | `text-gray-400` |
| Muted / supporting info | `text-slate-500` |
| Positive P&L / profit | `text-emerald-400` — **never `text-green-400`** |
| Negative P&L / loss | `text-red-400` |
| Warning / caution | `text-amber-400` |

### Interactive / Status Colors

| State | Background | Text | Border |
|---|---|---|---|
| Running / active | `bg-emerald-400/10` | `text-emerald-400` | `border-emerald-400/20` |
| Stopped / inactive | `bg-gray-700/50` | `text-gray-400` | `border-gray-600/20` |
| Error | `bg-red-400/10` | `text-red-400` | `border-red-400/20` |
| Starting | `bg-yellow-400/10` | `text-yellow-400` | `border-yellow-400/20` |
| Stopping | `bg-orange-400/10` | `text-orange-400` | `border-orange-400/20` |
| Watching (positions) | `bg-yellow-400/10` | `text-yellow-400` | — |
| Long | `bg-emerald-400/10` | `text-emerald-400` | — |
| Short | `bg-red-400/10` | `text-red-400` | — |
| Closed | `bg-gray-700/50` | `text-gray-400` | — |

---

## Typography

- **Font**: system sans-serif (Tailwind default) — no custom font imports
- **Section titles**: `text-[11px] font-semibold text-gray-300 uppercase tracking-wider`
- **Table column headers**: `text-[10px] font-semibold text-gray-400 uppercase tracking-wider`
- **Card header — strategy/page name**: `text-base font-semibold text-gray-100 tracking-tight`
- **Inline stat labels** (above values in header bar): `text-xs text-slate-400`
- **Inline stat values**: `text-sm font-semibold text-gray-100`
- **Monospaced data** (prices, quantities, timestamps): `font-mono tabular-nums`
- **Status/type badges**: `text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded`
- **Large P&L figure** (card header): `text-lg font-bold tracking-tight`
- **Small supporting label** under P&L: `text-[10px] text-slate-400 uppercase tracking-wider`

---

## Card / Panel Pattern

### Outer card wrapper
```
bg-[#0d1117] border border-slate-700/50 overflow-hidden shadow-2xl
hover:border-slate-600/70 transition-all duration-300
```
No `rounded-*` — all border-radius is globally zeroed to 0.

### Card header row (collapsible trigger)
```
px-5 py-4 flex items-center gap-4 cursor-pointer
bg-gradient-to-r from-slate-800/30 via-transparent to-transparent
hover:from-slate-800/40 transition-all
```
The left-fade gradient creates subtle depth without a visible border.

### Title-row fade (general)
The same left-fade is applied to **title rows only** across the app — panel/card headers,
section title bars, and the nav bar — never to descriptions, data rows, content, tabs, or stat tiles.

It is a **single global class** — do not hand-roll `bg-gradient-*` utilities per element. Add the
`title-fade` class; interactive title rows (collapsible triggers) also add `title-fade-hover`:
```jsx
<div className="… title-fade">…</div>                 {/* static title row */}
<div className="… title-fade title-fade-hover transition-all">…</div>  {/* interactive */}
```
Defined once in `client/src/index.css` (`@layer components`) and driven by CSS variables in `:root`
— tune these to restyle every title bar app-wide, no per-file edits:
```css
--title-fade-rgb: 30 41 59;          /* slate-800 */
--title-fade-strength: 0.50;         /* left-edge opacity (current: 50%) */
--title-fade-strength-hover: 0.60;   /* interactive hover */
--title-fade-reach: 55%;             /* fades to transparent by ~55% across */
```
`title-fade` sets `background-image` only, so any existing `bg-*` color underneath is preserved.
Application notes:
- The shared `CardHeader` (`components/ui/card.jsx`) carries `title-fade` (with `rounded-t-xl` to
  keep the card's top corners clean), so every `Card`-based panel title inherits it automatically.
- On a plain panel `<div>`, bleed the title bar to the panel edges with matched
  negative-margin + padding (e.g. `-mx-5 -mt-5 px-5 pt-5 pb-3`) and add `overflow-hidden`
  to the panel so the gradient respects rounded corners.
- On a solid bar (e.g. nav) keep the base color class and add `title-fade`: `bg-[#0a0d13] title-fade`.

### Expanded body — top border
```
border-t border-slate-700/50
```

### Panel rows inside expanded body
- Row 1 (primary): `bg-[#080b10]`
- Row 2 (secondary): `bg-[#0a0d13]`
- Column dividers: `divide-slate-700/40`
- Row separator: `border-t border-slate-700/50`

### Panel padding
All panels: `p-5`

### Section title inside a panel
```jsx
<div className="flex items-center gap-2 text-[11px] font-semibold text-gray-300 uppercase tracking-wider mb-4">
  <Icon size={13} className="text-gray-400" /> Section Name
</div>
```

---

## StatTile (small metric tile)

Used in dense stat grids (e.g., Session Stats).

```jsx
<div className="bg-[#0d1117] border border-slate-700/40 rounded-lg px-2.5 py-2">
  <div className="text-[10px] text-slate-400 mb-0.5 truncate">{label}</div>
  <div className={`text-sm font-bold tabular-nums ${color}`}>{value}</div>
</div>
```

- Default value color: `text-gray-100`
- Positive value: `text-emerald-400`
- Negative value: `text-red-400`

---

## Table Pattern (Positions-style)

```jsx
<table className="w-full text-xs border-collapse">
  <thead>
    <tr className="border-b border-slate-700/50">
      <th className="text-left pb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Col</th>
      {/* right-aligned numeric cols */}
      <th className="text-right pb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Value</th>
    </tr>
  </thead>
  <tbody>
    <tr className="border-b border-slate-700/30 hover:bg-slate-800/20">
      <td className="py-2.5 pr-3 font-semibold text-gray-100">{value}</td>
      <td className="py-2.5 text-right font-mono text-gray-100">{value}</td>
    </tr>
  </tbody>
</table>
```

- Row padding: `py-2.5`
- Column gap: `pr-3` on all but last column
- Numeric data: `font-mono tabular-nums text-gray-100`
- P&L columns: override color with `text-emerald-400` / `text-red-400`
- Hover: `hover:bg-slate-800/20`

---

## Terminal / Log Box

```
bg-[#060a0f] border border-slate-700/30 rounded-lg p-3
overflow-y-auto max-h-52
[&::-webkit-scrollbar]:hidden [scrollbar-width:none]
```

Log row structure:
- Timestamp: `text-slate-500 font-mono text-xs tabular-nums`
- Icon: colored by type (emerald for long, red for short, gray for info)
- Message: `text-gray-300 font-mono text-xs break-words leading-relaxed`
- P&L in message: inline `<span>` with `text-emerald-400` or `text-red-400`

---

## Buttons

> **Note:** `rounded-*` classes are omitted from all samples below per Rule 1 — the theme's
> border-radius scale is zeroed globally, so `rounded-lg`/`rounded-full` render as sharp rectangles
> regardless. Earlier versions of this doc included `rounded-lg` in these samples, which contradicted
> Rule 1; ~130 call sites in `client/src` still carry it as dead-but-harmless noise (see "What to
> Avoid"). Don't copy `rounded-*` into new code even though it currently has no visual effect.

### Primary action (e.g., New Bot)
```
bg-emerald-600 hover:bg-emerald-700 text-white text-sm px-4 py-2
```

### Destructive / Stop action
```
bg-red-600 hover:bg-red-700 text-white text-xs font-medium px-3 py-1.5
```

### Ghost / secondary (e.g., Clear stopped)
```
bg-transparent hover:bg-red-500/10 text-gray-500 hover:text-red-400
text-sm border border-gray-700 hover:border-red-500/30
```

### Icon-only danger (e.g., Delete session)
```
p-1.5 hover:bg-red-500/10 text-gray-600 hover:text-red-400
border border-transparent hover:border-red-500/20
```

### Expand/collapse toggle
```
p-1.5 bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white
```

**Rule**: Filled buttons (`bg-*-600`) for primary/destructive actions. Ghost buttons for secondary actions. Never use glass/translucent for a primary or destructive action.

---

## Status Badges (sharp rectangle, not a pill)

```
text-[10px] px-2 py-0.5 font-medium
```

Apply color from the status table above. Always include matching bg + text + border classes together.
Do not add `rounded-full` — the global radius override renders it as a sharp rectangle, not a pill;
adding it is dead-but-harmless noise, same as the button samples above.

### Exception: genuinely circular elements (spinners, status-pulse dots)
`rounded-full` is a global no-op, so any element that structurally needs to be a circle (loading
spinners, live-status pulse dots) must use the arbitrary-value escape hatch instead:
```
[border-radius:50%]
```
This bypasses the theme's zeroed radius scale. See `client/CLAUDE.md`'s Navbar section for the
existing example (avatar button). Current spinners/dots still built with the broken `rounded-full`
(render as squares, not circles) and due for this fix: `client/src/App.jsx`,
`client/src/pages/Trade.jsx`, `client/src/pages/AlgoTrading.jsx`,
`client/src/components/algo/ChaosWizard.jsx`, `client/src/pages/Settings.jsx`.

---

## Scrollable containers

All scrollable panels hide the native scrollbar:
```
[&::-webkit-scrollbar]:hidden [scrollbar-width:none]
```

---

## Chart Axis Styling (Recharts)

```js
tick={{ fill: '#94a3b8', fontSize: 10 }}  // slate-400
stroke="#1e293b"                           // slate-800 — grid/axis line
```

Reference line (baseline): `stroke="#4B5563" strokeDasharray="3 3"`

Equity line color: `#34d399` (emerald-400) when positive, `#f87171` (red-400) when negative.
`EquityCurve.jsx` and `EquitySparkline.jsx` both follow this now (fixed 2026-07-02 — `EquityCurve.jsx`
was on `#10b981`/emerald-500). `EquityCurve.jsx`'s grid/axis strokes (`#1f2937`/`#4b5563`, gray-scale)
still don't match the `#1e293b` (slate-800) specified above — known minor drift, not yet reconciled.

---

## Spacing Conventions

| Context | Value |
|---|---|
| Panel internal padding | `p-5` |
| Section title bottom margin | `mb-4` |
| StatTile grid gap | `gap-2` |
| Table row vertical padding | `py-2.5` |
| Table column right gap | `pr-3` |
| Log entry spacing | `space-y-2` |
| Card list spacing (page level) | `space-y-3` |

---

## What to Avoid

- `rounded-*` classes — all border-radius is globally zeroed; these are dead no-ops and add noise
- `gap-4`, `gap-6`, `space-y-6` at panel/section level — use `gap-0`, `space-y-0`; separation is via borders
- `mb-6` or `mt-6` between major content sections — sections are flush
- `p-6` in `PageWrapper` — the wrapper has no padding; pages are edge-to-edge
- `bg-gray-900` / `bg-gray-800` as panel backgrounds — too warm, breaks the midnight-blue depth
- `text-gray-500` for labels — use `text-slate-400` for cooler tone
- `text-green-400` for profit — always `text-emerald-400`
- Glass/translucent buttons (`bg-red-500/10`) for primary or stop actions — use filled
- `opacity-50` to dim inactive rows — kills readability; use color tone instead
- `tracking-widest` on section titles — use `tracking-wider`
- Inline styles — Tailwind only
