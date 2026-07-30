# Changelog

## v1.0.0

First release. A TRMNL private plugin showing Rivian vehicle status, fed from
Home Assistant over a webhook.

### The screen

- State of charge as the headline figure, with a progress bar carrying a tick at
  the charge limit.
- A status line saying what the truck is doing and where — "Charging at Home",
  "Parked at Work", "Driving", "In service". Location comes from the
  integration's device tracker, so renaming a zone in Home Assistant renames it
  on screen.
- A top-down vehicle diagram drawn from the closure sensors. Panels open the way
  they actually open: doors swing out on their hinge, the frunk lifts past the
  nose, the tailgate drops past the tail, gear tunnels swing out the side, a
  lowered window leaves a gap in the door, and the tonneau's slats disappear.
  A flagged tire fills its wheel. R1T renders with a bed and gear tunnel;
  R1S/R3 without.
- A health row — Locked, Closed, Tires, 12V, Fluids, Software. Passing checks
  stay quiet; failing ones invert.
- Once a charge session ends, what it added: a caliper under the bar spanning
  the SOC it covered, plus the figure in percent and kWh. Shown only while it
  still describes the charge in the battery — one drive retires it.
- Range, cabin temperature and odometer.
- All four view sizes, light and dark.

### Data

- Home Assistant package that assembles a ~1 KB payload and pushes it when the
  truck's state changes rather than on a timer. Noisy values are quantised, and
  `updated_at` is the newest `last_changed` rather than the render time, so
  unchanged data deduplicates and the panel does not redraw.
- The last charge session is frozen as it finishes by two trigger-based template
  sensors, because the integration's session sensors describe the current charge
  and may go away once it ends.
- `tools/configure_ha.py --slug` writes a package wired to your vehicle, so the
  slug never has to be edited by hand in the several places Home Assistant
  requires literal entity ids.

### Tooling

- `tools/render.mjs` renders Liquid through TRMNL's own `/api/markup` and
  screenshots the result in Chromium at true device size against the real
  framework CSS.
- `tools/test_views.mjs` — 204 contract assertions across every view and sample.
- `tools/check_ha_template.py` — 52 assertions over three entity tables: a
  healthy vehicle, one reporting only a state of charge, and none at all.
- `npm run check` runs all of it and builds the importable archive.

### Known unverified

Nothing in this release has run against a live TRMNL account or a live Home
Assistant. [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) lists every value inferred
from source rather than observed, and how to confirm each one.
