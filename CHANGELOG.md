# Changelog

## v2.0.0

The first release to have run against a live TRMNL device and a live Home
Assistant — and the release that stops the screen lying when it has nothing to
say.

Major rather than minor because **the payload contract changed in a breaking
way**: any field may now be JSON `null`, and anything consuming this data has to
handle that. If you are running the v1.0.0 package, replace
`homeassistant/trmnl_rivian.yaml` as well as the plugin markup. The two halves
are versioned together.

### Fixed — the screen no longer reports things it does not know

- **Unknown is no longer zero.** The Home Assistant template coerced every
  unavailable sensor through `| float(0)`. A dead integration therefore rendered
  as a confident dashboard: **0% charge, a "Low charge" warning, and all six
  health checks ticked green**, with nothing on screen to suggest anything was
  wrong. The Liquid layer's nil-defaults never fired, because Home Assistant was
  sending zeros rather than nulls. Every read now tests for
  `unknown`/`unavailable` first and emits `null`, which survives all the way to
  the pixels: figures render as `—`, checks render as an outlined `?`, and the
  vehicle silhouette goes dashed rather than drawing a sealed vehicle it cannot
  vouch for. A genuine `0%` still reads as `0%` and still warns.
- **A dead lock sensor no longer reads as "locked".** It was previously treated
  as locked so a dropped connection would not raise a false alarm — which
  replaced a false alarm with a false reassurance on the single most
  consequential check on the screen.
- **The 12V check could never fail.** It read
  `sensor.<slug>_twelve_volt_battery_health`, which is the integration's internal
  key. Home Assistant builds entity ids from the *display name*, so the entity is
  actually `sensor.<slug>_12v_battery_health`. The old name matched nothing, and
  a check that matches nothing passes forever. All 30 entity names are now
  verified against the integration's source; this was the only one wrong.
- **Missing OTA sensors no longer report a healthy software state** from no data
  at all. A readable current version with no available version still correctly
  means "nothing pending"; both silent now means unknown.
- **Absent closures no longer tick "Closed"** or claim "All closed". Something
  known-open still outranks the gaps — the screen will say the tailgate is up
  even if three other sensors are quiet — but "all closed" now requires all
  thirteen to have actually said so.

### Fixed — the screen can now age

- **The timestamp always carries a date.** It used to render a bare clock time,
  so `Updated 10:01 AM` could be sitting on thirty-hour-old values. TRMNL
  deduplicates *at the data layer* — an unchanged payload is dropped before the
  render step — so if Home Assistant stops pushing, the last image stays on the
  wall exactly as rendered and no amount of clever Liquid can age it. The only
  defence is to never render an ambiguous timestamp in the first place.
- **A dead feed now announces itself.** Home Assistant measures minutes since the
  integration last *reported* (not last changed) and sends it as a coarse,
  saturating bucket. Healthy it is always `0`, so the payload does not churn and
  the e-ink does not redraw; when the feed dies the bucket steps up, which makes
  the payload genuinely different, which is the only thing that survives
  deduplication. A filled `No update 3h` badge appears.
- **Freshness no longer counts entities that just went unavailable**, which
  previously made a dying feed look like it had refreshed a second ago.
- Staleness is kept deliberately separate from state. A vehicle can sit at a
  service centre for a week: `In service` is a fact it reported and keeps its
  place on the status line, while the age of the reading is carried by its own
  badge.

### Fixed — rate limiting

- **The throttle was over the limit.** 290 s allows 13 pushes in a rolling hour
  against TRMNL's 12/hour, which earns `429`s. It is now 330 s, admitting at most
  `floor(3600/330) + 1 = 11`.
- **Important changes queue instead of being dropped.** Previously a meaningful
  transition arriving inside the throttle window was discarded and could go
  unshown for up to half an hour. Pushes are now split: anything you would act on
  (unlocked, something opened, charging started, the feed went dark) waits out
  the window and is always sent; cosmetic drift is dropped and rides along on the
  next push. Both feed one queued script that reads the payload *after* its
  delay, so rapid changes coalesce into one accurate screen rather than a backlog
  of stale ones.

### Changed — upstream reality

Rivian changed their API in 2026 and the integration has not fully caught up.
The plugin now degrades honestly rather than depending on a fix landing.

- **Location.** `gnssLocation` was removed. Because the integration requests the
  whole vehicle state as one GraphQL subscription, a single dead field fails the
  entire subscription — so the real-world symptom is *every entity going
  unavailable at once*, not a missing map. That is the failure the no-data
  rendering above is built around. Users need `1.5.3b0` plus community pull
  request [#267](https://github.com/bretterer/home-assistant-rivian/pull/267) by
  [@cellmechanic](https://github.com/cellmechanic) — someone else's patch, linked
  rather than vendored. The recommendation is to pin and patch, not fork.
- **Charging telemetry is not recoverable.** Rivian moved live telemetry to
  protobuf over a GraphQL WebSocket ("Parallax") with no public schema. This is a
  transport and encoding change, not a field rename, and the workaround
  circulating in issue #254 does not restore the sensors.
- **But charging still works**, because it now reads from `vehicleState`:
  charge percentage (`batteryLevel`), charge limit (`batteryLimit`), charger
  state (`chargerState`), connection (`chargerStatus`) and time to limit
  (`timeToEndOfCharge`) are all unaffected. Only two values are lost: live charge
  rate in kW, which is now simply omitted rather than printed as `0 kW`, and
  metered session energy, which falls back to a SOC × pack-capacity estimate
  marked with a `~` so it is never mistaken for a meter reading.
- The package comments say which subsystem each value comes from, so the next
  upstream change is traceable.

### Added

- `LICENSE` — MIT.
- An `author_bio` custom field, as TRMNL's recipe publishing guidance requires,
  stating the setup burden up front: Home Assistant, the community Rivian
  integration, and TRMNL's **$20 Developer add-on, which is per device**, not per
  account.
- A README rewritten for someone who is not the author: prerequisites and cost
  before anything else, the integration set up first, verification at each step,
  and a troubleshooting table.
- Four failure-mode fixtures — `nodata`, `partial`, `stale`, `charging-degraded`
  — and previews of each.
- `.gitignore` coverage for secrets and personal data, including
  `samples/live.json`, which the deployment guide asks you to create from a real
  payload.

### Tests

The suite was part of the problem: it asserted only that a sparse payload
invents no *alarm*, and the "no entities" fixture positively asserted `soc: 0`
with every health flag `True`. It did not merely miss the bug, it certified it.

- View assertions now check **both directions**: an empty payload must produce
  neither a `✗` nor a `✓`. Targeted regressions cover each specific way the old
  build lied.
- The Home Assistant harness gained a **generic** assertion: with no entities,
  every vehicle field must be `null`, so a newly added field cannot quietly
  reintroduce the coercion. Eight entity tables now, including "every entity
  `unavailable`" and both 12V entity spellings.
- 393 view assertions and 146 template assertions, up from 204 and 52.
- Fixtures store ages relatively, so the repo's previews do not rot into showing
  `No update 400d`.

---

## v1.0.0

Never tagged, never released, and never run against live data — kept here
because the v2.0.0 notes refer back to it.

A TRMNL private plugin showing Rivian vehicle status, fed from Home Assistant
over a webhook. Its design survives into v2.0.0 essentially intact:

- State of charge as the headline figure, with a progress bar carrying a tick at
  the charge limit.
- A status line saying what the vehicle is doing and where — "Charging at Home",
  "Parked at Work", "Driving", "In service". Location comes from the
  integration's device tracker, so renaming a zone in Home Assistant renames it
  on screen.
- A top-down vehicle diagram drawn from the closure sensors. Panels open the way
  they actually open: doors swing out on their hinge, the frunk lifts past the
  nose, the tailgate drops past the tail, gear tunnels swing out the side, a
  lowered window leaves a gap in the door, and the tonneau's slats disappear.
  A flagged tire fills its wheel. R1T renders with a bed and gear tunnel;
  R1S/R3 without.
- A health row — Locked, Closed, Tires, 12V, Fluids, Software.
- Once a charge session ends, what it added: a caliper under the bar spanning
  the SOC it covered, plus the figure in percent and kWh.
- Range, cabin temperature and odometer. All four view sizes, light and dark.
- A Home Assistant package that assembles a ~1 KB payload and pushes it when the
  vehicle's state changes rather than on a timer.
- `tools/configure_ha.py --slug` to wire the package to your vehicle.

What did not survive was its handling of missing data.
