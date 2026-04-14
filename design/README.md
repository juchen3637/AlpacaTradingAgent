# AlpacaTradingAgent UI Redesign

## Visual Concept
Selected **Concept 4** from Nano Banana 2 generation — full-width chart hero with clean bottom card row.
- `concept-4-selected.jpg` — the visual direction reference

## Design System (Google Stitch)
- **Project ID:** `736262051520308158`
- **Design System:** "AlpacaTrader Dark" (`assets/289791172305819754`)
- **Colors:** Background #0F172A, Cards #1E293B, Primary #3B82F6, Success #22C55E, Danger #EF4444
- **Fonts:** Space Grotesk (headlines), Inter (body)
- **Roundness:** 8px
- **Cards:** Frosted glass (rgba backdrop-blur)

## Screens

| # | Screen | File | Stitch ID |
|---|--------|------|-----------|
| 1 | Dashboard | `screens/01-dashboard.png` | `92796a5b68d6483581b8c0a0b03c5c14` |
| 2 | Analysis Config | `screens/02-config.png` | `ef8b5fe4f40748799bdf0770a9f4fdb2` |
| 3 | Analysis Results | `screens/03-analysis-results.png` | `f8e627bfbc3a45c095fd4a5db9db558e` |
| 4 | Portfolio/Account | `screens/04-portfolio.png` | `5509dcd62761443086b5213cd34bab63` |
| 5 | Debug/System Logs | `screens/05-debug.png` | `fb4a7cc2abaf4fa39d995c5e5d249c84` |

## Variants

### Dashboard Variants
| Variant | Description | File |
|---------|-------------|------|
| V1 | Top nav (no sidebar) | `variants/01-dashboard-v1-topnav.png` |
| V2 | Larger info cards, smaller chart | `variants/01-dashboard-v2-larger-cards.png` |
| V3 | Two-column (chart + positions side by side) | `variants/01-dashboard-v3-two-column.png` |

### Config Variants
| Variant | Description | File |
|---------|-------------|------|
| V1 | Single-column scrollable | `variants/02-config-v1-single-column.png` |
| V2 | Tabbed interface | `variants/02-config-v2-tabbed.png` |
| V3 | Compact all-on-screen | `variants/02-config-v3-compact.png` |

### Analysis Results Variants
| Variant | Description | File |
|---------|-------------|------|
| V1 | Hero decision banner | `variants/03-results-v1-hero-decision.png` |
| V2 | Card grid for analysts | `variants/03-results-v2-card-grid.png` |
| V3 | Pipeline flow visualization | `variants/03-results-v3-pipeline-flow.png` |

## HTML/CSS Reference Code
Stitch-generated HTML with Tailwind CSS in `code/`:
- `code/01-dashboard.html`
- `code/02-config.html`
- `code/03-analysis-results.html`
- `code/04-portfolio.html`
- `code/05-debug.html`

## Implementation Target
**Framework:** Python Dash (staying with existing stack)

**Files to modify:**
- `webui/config/constants.py` — design tokens
- `webui/assets/custom.css` — all custom styles
- `webui/components/*.py` — Dash component files
- `webui/layout.py` — page structure

**Translation approach:** Extract design tokens and CSS from Stitch HTML → update constants.py + custom.css → translate HTML structure to Dash components (dbc.Card, dbc.Row, html.Div, etc.)
