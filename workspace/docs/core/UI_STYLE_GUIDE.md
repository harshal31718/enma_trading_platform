# Enma UI Style Guide
> Derived from the AlgoTrading page redesign. Apply these principles to all pages for visual consistency.

---

## Philosophy

The UI targets a **professional trading terminal aesthetic** — dark, dense, and data-forward. Panels have visual depth through layered backgrounds rather than decorative elements. Color is used functionally (status, P&L direction, interactive state) not decoratively. Every element earns its place.

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
bg-[#0d1117] border border-slate-700/50 rounded-xl overflow-hidden shadow-2xl
hover:border-slate-600/70 transition-all duration-300
```

### Card header row (collapsible trigger)
```
px-5 py-4 flex items-center gap-4 cursor-pointer
bg-gradient-to-r from-slate-800/30 via-transparent to-transparent
hover:from-slate-800/40 transition-all
```
The left-fade gradient creates subtle depth without a visible border.

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

### Primary action (e.g., New Bot)
```
bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg px-4 py-2
```

### Destructive / Stop action
```
bg-red-600 hover:bg-red-700 text-white text-xs font-medium rounded-lg px-3 py-1.5
```

### Ghost / secondary (e.g., Clear stopped)
```
bg-transparent hover:bg-red-500/10 text-gray-500 hover:text-red-400
text-sm rounded-lg border border-gray-700 hover:border-red-500/30
```

### Icon-only danger (e.g., Delete session)
```
p-1.5 hover:bg-red-500/10 text-gray-600 hover:text-red-400
rounded-lg border border-transparent hover:border-red-500/20
```

### Expand/collapse toggle
```
p-1.5 bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white rounded-lg
```

**Rule**: Filled buttons (`bg-*-600`) for primary/destructive actions. Ghost buttons for secondary actions. Never use glass/translucent for a primary or destructive action.

---

## Status Badges (pill shaped)

```
text-[10px] px-2 py-0.5 rounded-full font-medium
```

Apply color from the status table above. Always include matching bg + text + border classes together.

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

- `bg-gray-900` / `bg-gray-800` as panel backgrounds — too warm, breaks the midnight-blue depth
- `text-gray-500` for labels — use `text-slate-400` for cooler tone
- `text-green-400` for profit — always `text-emerald-400`
- Glass/translucent buttons (`bg-red-500/10`) for primary or stop actions — use filled
- `opacity-50` to dim inactive rows — kills readability; use color tone instead
- `tracking-widest` on section titles — use `tracking-wider`
- Inline styles — Tailwind only
