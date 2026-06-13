# DebugAI — Design System

A dark-mode-first component kit for the DebugAI web app: the dashboard where
developers read traces, failure diagnoses, signal breakdowns, and fix
suggestions. Personality: **deterministic, precise, trustworthy.** Core
metaphor: **signal → diagnosis.** Looks like a debugger/profiler, not a SaaS
dashboard.

## Principles
1. **Color is signal, never decoration.** One accent — amber `#EF9F27` — for
   warnings, active signals, and the primary action. Semantic green/red/cyan
   carry state. Everything else is the warm-dark neutral ramp.
2. **High density, high legibility.** Tight clinical radii (2–8px), generous
   data, monospace for anything machine-readable (values, ids, code).
3. **Two typefaces.** Hanken Grotesk for UI/prose, JetBrains Mono for data.
4. **Earned motion.** Animation communicates a signal firing or a state change,
   never ambient decoration. All motion respects `prefers-reduced-motion`.

## Foundations
- `styles.css` → imports `css/tokens.css`, `css/base.css`, `css/components.css`.
- Tokens: surfaces, text/border ramps, amber scale, semantic signals, a 1.25
  type scale, 4px spacing, tight radii, and glow elevation.

## Components (`window.DesignSystem_90c6f1`)
| Component | Role |
|---|---|
| `Button` | Action control. `primary` (amber) is the signal action; `secondary`/`ghost`/`danger`; `sm`/`md`/`lg`; `mono` for command-style. |
| `Badge` | Compact status token — `ok`/`warn`/`critical`/`trace`/`neutral`, optional glow `dot`, `solid`. |
| `SignalIndicator` | One telemetry signal: node, label, confidence fill, value. `pending` pulses, `fired` reveals. |
| `CodeBlock` | Terminal/editor readout — chrome bar, line numbers, highlight rail, copy. Accepts raw `code` or pre-tinted `tok-*` children. |
| `DiagnosticCard` | **Signature.** Severity rail, signal breakdown, confidence score, suggested fix, actions. |

## Templates
- `templates/landing/` — the DebugAI marketing landing page: animated
  signal-flow hero, "how it works" diagnosis sequence, features, CTA.

## Usage in a consuming project
Load React UMD, then this system's `styles.css` + `_ds_bundle.js`, then read
components off `window.DesignSystem_90c6f1`. Templates do this for you via their
local `ds-base.js`.
