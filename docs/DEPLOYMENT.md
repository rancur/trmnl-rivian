# Deployment handoff

[`README.md`](../README.md) is the setup guide. This document is the deeper
version for whoever is deploying it for the first time — human or agent — and it
is mostly about **how to verify each step rather than assume it**.

The plugin was developed offline against the published TRMNL framework and the
entity definitions in
[bretterer/home-assistant-rivian](https://github.com/bretterer/home-assistant-rivian).
Everything renders, every test passes, and all 30 entity names are checked
against the integration's source — but a test suite proves the code does what it
was told, not that it was told the right thing.

---

## If you are an agent picking this up

**Ask for these first.** Nothing below works without them, and none are in the
repo:

| | |
|---|---|
| TRMNL account | with the Developer add-on ($20, per device) or a BYOD licence |
| TRMNL device access token | Devices → Edit → Developer Perks. Needed to read back what is actually on the screen |
| Home Assistant URL + long-lived token | or shell access to the HA config directory |
| The vehicle's entity slug | or enough HA access to look it up yourself |

**You can verify your own work end to end.** That is the point of the loop in
[Step 4a](#step-4a--check-what-is-actually-on-the-screen): TRMNL will hand you a
PNG of the live screen, and this repo can render the same payload locally, so
you can compare rather than guess. Use it after every change.

**Do not report success from a `200`.** A webhook can be accepted and still
render a screen full of dashes. Worse, on an earlier build it could render a
screen full of zeroes and green ticks, which looks like success. Look at the
image.

**Definition of done:**

1. `npm run check` passes.
2. A real payload from Home Assistant reaches TRMNL and the fetched screen
   matches the local render of the same data.
3. Every row in [Step 5](#step-5--confirm-the-guesses) has been checked against
   the real vehicle and the package corrected where it was wrong.
4. Anything you corrected is committed with a note on what the real value was —
   those are the repo's remaining unknowns and the next person needs them.

**Do not change the Liquid to make bad data look acceptable.** If a figure is
wrong, the entity mapping in `homeassistant/trmnl_rivian.yaml` is wrong; fix it
there. In particular, **do not add fallbacks that turn a missing sensor into a
plausible number.** That is the exact bug this plugin was rebuilt to remove, and
`npm test` will fail if you reintroduce it.

---

## Prerequisites

1. **TRMNL account with the Developer add-on or a BYOD licence.** Private
   plugins do not exist without one. The add-on is a one-time $20 and is linked
   to a *device*, not an account — a second TRMNL needs its own. Check at
   <https://trmnl.com/plugin_settings?keyname=private_plugin>.
2. **TRMNL account API key** — from <https://trmnl.com/account>, begins `user_`.
   Only needed for the API route; `trmnlp login` handles its own auth.
3. **Home Assistant** with the Rivian integration installed via HACS, **pinned to
   `1.5.3b0` with [PR #267](https://github.com/bretterer/home-assistant-rivian/pull/267)
   applied** — see the README's [Upstream status](../README.md#upstream-status).
   Without it, the whole `vehicleState` subscription fails and every entity reads
   `unavailable`.
4. **The vehicle's entity slug.** In HA go to **Developer Tools → States** and
   filter for `battery_state_of_charge`. If you see
   `sensor.r1t_battery_state_of_charge`, the slug is `r1t`. Write it down — it
   is the single value everything else keys off.

---

## Step 1 — Confirm the integration is actually reporting

Do this before anything else. The most common failure is upstream, not here.

In **Developer Tools → Template**, paste:

```jinja
{{ states('sensor.r1t_battery_state_of_charge') }}
{{ states('binary_sensor.r1t_locked_state') }}
{{ states('sensor.r1t_12v_battery_health') }}
```

You want three real values. `unknown` or `unavailable` means the integration is
down or the slug is wrong — fix that first. The plugin will faithfully render
"no data", which is correct behaviour and not the outcome you are after.

---

## Step 2 — Deploy the plugin to TRMNL

Two routes. Prefer `trmnlp`; it makes later edits a one-liner.

```bash
gem install trmnlp
trmnlp login
trmnlp lint          # fix anything it flags before pushing
trmnlp push
trmnlp pull          # writes the new plugin's id: back into src/settings.yml
```

Commit the `id:` that `trmnlp pull` adds. Without it every `push` creates a
*new* plugin instead of updating the existing one.

<details>
<summary>Fallback: ZIP import</summary>

```bash
python3 tools/build_plugin.py     # writes dist/trmnl-rivian.zip
```

**Plugins → Private Plugin → Import**, upload the zip.

</details>

**⚠ Known risk:** `src/settings.yml` pins `framework_version: '3.1'`. That value
is inferred from the published docs, not confirmed against the API, and TRMNL
does not publish an allow-list. If the push or import is rejected, change it to
`latest` and re-push, then note it here.

**Verify:** the plugin appears in your plugin list, and its settings page shows
a **Webhook URL** of the form
`https://trmnl.com/api/custom_plugins/<uuid>`. Copy it, and treat it as a
credential — anyone holding it can write to your screen.

At this point the screen renders as "No vehicle data" — dashes, `?` checks and a
dashed silhouette. That is the correct rendering of "nothing has been sent yet",
and it is worth looking at once so you know what a dead feed looks like.

---

## Step 3 — Send one payload by hand

Do this before touching Home Assistant. It isolates "is the plugin right" from
"is the HA template right".

```bash
curl -X POST "https://trmnl.com/api/custom_plugins/<uuid>" \
  -H "Content-Type: application/json" \
  -d "{\"merge_variables\": $(cat samples/charging.json)}"
```

`samples/charging.json` stores its age relatively, so if you want the timestamp
to look right, render it through the loader first:

```bash
node -e "import('./tools/samples.mjs').then(m=>console.log(JSON.stringify({merge_variables:m.loadSample('charging')})))" \
  | curl -X POST "https://trmnl.com/api/custom_plugins/<uuid>" -H "Content-Type: application/json" -d @-
```

**Verify:** open the plugin's markup editor, click **Force Refresh**, and
compare against `preview/full-charging.png`. They should be identical apart
from the title bar's instance name.

If they differ, the problem is in the markup or the framework version — not in
Home Assistant.

---

## Step 4 — Wire up Home Assistant

```yaml
# configuration.yaml
homeassistant:
  packages: !include_dir_named packages
```

```yaml
# secrets.yaml   (gitignored — never commit this)
trmnl_webhook_url: "https://trmnl.com/api/custom_plugins/<uuid>"
```

Home Assistant requires literal entity ids inside a trigger, so the slug appears
in several places. Do not edit them by hand — generate the package:

```bash
python3 tools/configure_ha.py --slug <your-slug> --out <config>/packages/trmnl_rivian.yaml
```

It refuses to write if any reference would be left behind. Restart Home
Assistant.

The package declares its own `input_datetime` helper for the push throttle, so
there is nothing to create in the UI.

**Verify, in order:**

1. **Developer Tools → Template**, paste this, and confirm it prints valid JSON:
   ```jinja
   {{ state_attr('sensor.rivian_trmnl_payload', 'payload') }}
   ```
   Read it carefully. **`null` means that entity is not reporting** — either the
   name is wrong for your vehicle or the integration is down. Fix the name in
   the package; do not fix it by changing the plugin. A field that reads `0`
   when the vehicle is not at 0 is a bug worth reporting, because the whole
   design is that it cannot happen.
2. **Developer Tools → Actions**, run `script.trmnl_rivian_push`. (This is the
   throttled entry point; `rest_command.trmnl_rivian_push` bypasses the rate
   limiter and should only be used when you know what you are doing.)
3. Force Refresh in TRMNL. The screen should now show your vehicle.
4. Open a door. The priority automation should fire within the rate-limit window
   on its own, and the door should appear open at the next device refresh.
5. **The last-charge panel needs one real charge session to appear.** It is
   populated by two trigger-based sensors that fire on the charging status going
   on and then off, so it stays empty until the vehicle has charged once with
   this package installed. After a session, check `sensor.rivian_last_charge`
   has `start_soc`, `end_soc`, `kwh`/`kwh_est` and `odometer` attributes, then
   confirm the caliper appears under the bar. Drive it and the panel disappears.
   Expect `kwh` to be `null` and the figure to show with a `~` while the
   live-session query is dark upstream.

---

## Step 4a — Check what is actually on the screen

Do not trust a `200`. TRMNL will give you the rendered image, so compare it
against what this repo produces for the same data.

Grab the device access token from **Devices → Edit → Developer Perks**, then:

```bash
# What the device is showing right now
curl -s https://trmnl.com/api/current_screen \
  --header "access-token: $TRMNL_DEVICE_TOKEN" | tee /tmp/screen.json

curl -s "$(python3 -c 'import json;print(json.load(open("/tmp/screen.json"))["image_url"])')" \
  -o /tmp/live.png
```

Then render the same payload locally and put them side by side:

```bash
# Capture exactly what Home Assistant sent. samples/live.json is gitignored
# because it contains your real odometer, zone names and vehicle name.
cp <the payload you posted>.json samples/live.json
npm run preview -- --view full --sample live --out preview/live-local.png
```

`/tmp/live.png` and `preview/live-local.png` are both 800×480 1-bit renders of
the same markup. They should be materially identical — small differences in the
title bar instance name are expected, anything else is a real discrepancy.

`GET /api/display` also works but **advances the playlist**, so prefer
`current_screen` when you only want to look.

If the live screen is blank or stale, click **Force Refresh** on the plugin
first: TRMNL discards a payload identical to the previous one *before* it
renders, so an unchanged screen usually means unchanged data rather than a bug.

---

## Step 5 — Confirm the guesses

Six values were inferred from source code, not observed on a real vehicle. Each
is written so that an unrecognised reading produces `?` rather than a false
tick or a false alarm — so a wrong guess is visible but quiet.
**Check each one and correct the package.**

| What | Where | How to check |
|---|---|---|
| Tire status vocabulary | `tyre_ok_values` in the package | Read `sensor.<slug>_tire_pressure_front_left_status`. If a healthy tyre says something other than `ok`/`normal`/`nominal`, add that value to the list — otherwise it will show `✗`. |
| 12V battery health | `batt12_ok` | Read `sensor.<slug>_12v_battery_health`. Note the entity is named after the *display name* `12V Battery Health`, not the integration's internal key `twelve_volt_battery_health` — reading the key spelling matched nothing and made this check pass green forever. Confirm a healthy vehicle reports something not in the bad-values list. |
| Brake fluid | `brake_low` | Read `sensor.<slug>_brake_fluid_level_low`. The template expects a truthy string (`true`/`on`/`yes`/`1`). |
| Service mode | `service_mode` | Read `sensor.<slug>_service_mode`. Same truthy-string assumption. This one is worth getting right: a vehicle at a service centre legitimately reports it for days. |
| Charge power | `charge_power` | Reads `sensor.<slug>_charging_speed`. **Expected to be unavailable** while Rivian's live-session query is dark — the screen drops the kW figure rather than showing `0 kW`. If it *does* report, confirm the figure is sane. |
| Charge energy | last-charge snapshot | Reads `sensor.<slug>_charging_energy_delivered`, with a SOC × `sensor.<slug>_battery_capacity` estimate as fallback. Confirm which one you are getting: an estimate is prefixed with `~`. |
| Zone names | `location` | Park at home and confirm `device_tracker.<slug>_location` reports `home`. Named zones flow straight through to the screen. Requires PR #267. |

---

## Step 6 — Tune the refresh

Defaults are deliberately conservative:

- A hard minimum gap of **330 s** between pushes, which admits at most
  `floor(3600/330) + 1 = 11` in any rolling hour against TRMNL's limit of 12.
  On TRMNL+ (30/hour) you can lower it to 130 s.
- Two automations: important transitions **queue** and wait out the window;
  cosmetic drift is dropped and rides along on the next push.
- A 30-minute heartbeat, which is also what lets a dead feed announce itself —
  `link_age_min` climbs, the payload genuinely changes, and TRMNL re-renders.
- Charge power is rounded to whole kW and time-to-limit to 5 minutes so a
  fluctuating charger does not count as new data.

If the panel redraws more often than expected, the cause is almost always a
payload field changing every push. Dump the payload twice a minute apart and
diff them — whatever differs is the culprit. Quantise it in the package.

Note that **you cannot make the device refresh faster from here.** TRMNL devices
pull; the server never pushes. Device refresh rate is set on the device, and 15
minutes is the floor without TRMNL+.

---

## Optional, once it works

- **Vehicle photo.** The Rivian integration exposes `image.<slug>_*` entities
  whose URLs point at Rivian's CDN. HA serves them behind a token'd local URL
  that TRMNL's renderer cannot reach. If the underlying CDN URL turns out to be
  publicly fetchable, put it in the payload as `vehicle_image_url` and it will
  replace the diagram. Trade-off: a photo cannot show which door is open, and it
  cannot go dashed when the closure sensors stop reporting.
- **Real Rivian logo.** The title bar mark is a custom glyph, not the trademark.
  Set the plugin's **Logo URL** custom field to an official asset.
- **Mashups.** All four sizes work; try the plugin as a half or quadrant
  alongside something else.

---

## Before publishing to the TRMNL recipe store

Not done, and not to be done without a decision. When it is:

1. Add `category:` to the `author_bio` field in `src/settings.yml`, picking up
   to two from TRMNL's own list in the publish UI. It is deliberately not
   guessed in the repo, because a wrong value fails the CHEF linter.
2. Re-read TRMNL's
   [publishing tips](https://trmnl.com/blog/plugin-recipe-publishing-tips)
   against the current markup.
3. Confirm the previews contain no real vehicle data. The samples use a
   placeholder vehicle name and invented odometer figures on purpose.
4. Consider publishing **unlisted** first — it skips moderation and produces a
   shareable link, which is a cheap way to test the install flow on someone
   else's account.

---

## Iterating on the design

Both need network access to `trmnl.com`: `npm run setup` mirrors the framework
bundle, and the tests render Liquid through TRMNL's public `/api/markup`.
Rendering needs a Chromium — the script uses Playwright's own unless
`PLAYWRIGHT_BROWSERS_PATH` or `CHROMIUM_PATH` points at one, so
`npx playwright install chromium` is the fix if it complains.

```bash
npm install && npm run setup
npm run preview -- --view full --sample everything
npm run check      # HA template assertions + all 48 renders + build
```

`samples/everything.json` opens every closure at once and is the best stress
test for the diagram. `samples/nodata.json`, `samples/partial.json`,
`samples/stale.json` and `samples/charging-degraded.json` are the failure modes
— check those after any change to `shared.liquid`, because they are the states
that are easiest to break without noticing.
