# Deployment handoff

Everything in this repo is built and rendering, but **nothing has ever run
against a live TRMNL account or a live Home Assistant.** It was developed
offline against the published TRMNL framework and the entity definitions in
[bretterer/home-assistant-rivian](https://github.com/bretterer/home-assistant-rivian).

This document is the list of what is left. It is written for someone — human or
agent — with access to the real accounts.

---

## What is already done

| | |
|---|---|
| Liquid markup for all four view sizes | ✅ verified by rendering against TRMNL's own `/api/markup` |
| Pixel-accurate previews at 800×480 | ✅ 32 renders, light and dark, in `preview/` |
| Home Assistant payload template | ✅ 20 assertions pass against a stubbed entity table |
| Plugin definition (`src/settings.yml`) | ✅ written, ❌ never uploaded |
| Importable archive (`dist/trmnl-rivian.zip`) | ✅ builds, ❌ never imported |
| Anything touching a real account | ❌ **all of this is unverified** |

---

## Prerequisites

Collect these before starting:

1. **TRMNL account with the Developer add-on or a BYOD licence.** Private
   plugins do not exist without it. Check at
   <https://trmnl.com/plugin_settings?keyname=private_plugin>.
2. **TRMNL account API key** — from <https://trmnl.com/account>, begins `user_`.
   Only needed for the API route; `trmnlp login` handles its own auth.
3. **Home Assistant** with the Rivian integration installed via HACS and a
   vehicle showing entities.
4. **The vehicle's entity slug.** In HA go to **Developer Tools → States** and
   filter for `battery_state_of_charge`. If you see
   `sensor.r1t_battery_state_of_charge`, the slug is `r1t`. Write it down — it
   is the single value everything else keys off.

---

## Step 1 — Deploy the plugin to TRMNL

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
is inferred from the published docs, not confirmed against the API. If the push
or import is rejected, change it to `latest` and re-push, then note it here.

**Verify:** the plugin appears in your plugin list, and its settings page shows
a **Webhook URL** of the form
`https://trmnl.com/api/custom_plugins/<uuid>`. Copy it.

At this point the screen will render empty — no data has been sent yet. That is
expected.

---

## Step 2 — Send one payload by hand

Do this before touching Home Assistant. It isolates "is the plugin right" from
"is the HA template right".

```bash
curl -X POST "https://trmnl.com/api/custom_plugins/<uuid>" \
  -H "Content-Type: application/json" \
  -d "{\"merge_variables\": $(cat samples/charging.json)}"
```

**Verify:** open the plugin's markup editor, click **Force Refresh**, and
compare against `preview/full-charging.png`. They should be identical apart
from the title bar's instance name.

If they differ, the problem is in the markup or the framework version — not in
Home Assistant. Iterate locally with `npm run preview -- --view full --sample charging`
and re-push.

---

## Step 3 — Wire up Home Assistant

```bash
cp homeassistant/trmnl_rivian.yaml <config>/packages/trmnl_rivian.yaml
```

```yaml
# configuration.yaml
homeassistant:
  packages: !include_dir_named packages
```

```yaml
# secrets.yaml
trmnl_webhook_url: "https://trmnl.com/api/custom_plugins/<uuid>"
```

Edit `packages/trmnl_rivian.yaml` and replace `r1t` with your slug. **It appears
9 times** — `grep -c r1t` to confirm you got them all. Most are inside the two
trigger-based sensors at the top, whose `entity_id:` fields must be literal and
so cannot use the `vehicle` variable. Restart Home Assistant.

**Verify, in order:**

1. **Developer Tools → Template**, paste this, and confirm it prints valid JSON
   with sane numbers:
   ```jinja
   {{ state_attr('sensor.rivian_trmnl_payload', 'payload') }}
   ```
   If any field is `0`, `unknown` or missing, that entity name is wrong for your
   vehicle. Fix the name in the package — do not fix it by changing the plugin.
2. **Developer Tools → Actions**, run `rest_command.trmnl_rivian_push` with:
   ```yaml
   body: "{{ state_attr('sensor.rivian_trmnl_payload','payload') }}"
   ```
3. Force Refresh in TRMNL. The screen should now show your truck.
4. Open a door. Within ~5 minutes the automation should fire on its own and the
   door should appear open on screen at the next device refresh.
5. **The last-charge panel needs one real charge session to appear.** It is
   populated by two trigger-based sensors that fire on the charging status
   going on and then off, so it stays empty until the truck has charged once
   with this package installed. After a session, check
   `sensor.rivian_last_charge` has `start_soc`, `end_soc`, `kwh` and `odometer`
   attributes, then confirm the caliper appears under the bar. Drive the truck
   and it should disappear.

---

## Step 4 — Confirm the guesses

Seven values were inferred from source code, not observed. Each is written to fail
safe — an unrecognised reading shows "healthy" rather than crying wolf — so a
wrong guess is quiet, not loud. **Check each one and correct the package.**

| What | Where | How to check |
|---|---|---|
| Tire status vocabulary | `tyre_ok_values` in the package | Read `sensor.<slug>_tire_pressure_front_left_status` in Developer Tools. If it says something other than `OK`, add that value to the list. |
| 12V battery health | `batt12_ok` | Read `sensor.<slug>_twelve_volt_battery_health`. Confirm a healthy truck reports something not in the bad-values list. |
| Brake fluid | `brake_low` | Read `sensor.<slug>_brake_fluid_level_low`. The template expects a truthy string (`true`/`on`/`yes`/`1`). |
| Service mode | `service_mode` | Read `sensor.<slug>_service_mode`. Same truthy-string assumption. |
| Charge power | `charge_power` | Reads `sensor.<slug>_charging_speed`, the session power sensor. (An earlier draft used `sensor.<slug>_power`, which belongs to the wallbox, not the vehicle.) If charge rate shows 0 while plugged in, this is the entity to check. |
| Charge energy | last-charge snapshot | Reads `sensor.<slug>_charging_energy_delivered`. Confirm it reports kWh during a session. |
| Zone names | `location` | Park at home and confirm `device_tracker.<slug>_location` reports `home`. Named zones flow straight through to the screen, so rename zones in HA to change what it says. |

---

## Step 5 — Tune the refresh

Defaults are deliberately conservative:

- Pushes are throttled to one per 5 minutes (TRMNL allows 12/hour, 30 on TRMNL+).
- A 30-minute heartbeat covers a dropped webhook.
- Charge power is rounded to whole kW and time-to-full to 5 minutes so a
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
  replace the diagram. Trade-off: a photo cannot show which door is open.
- **Real Rivian logo.** The title bar mark is a custom glyph, not the trademark.
  Set the plugin's **Logo URL** custom field to an official asset.
- **Mashups.** All four sizes work; try the plugin as a half or quadrant
  alongside something else.

---

## If something looks wrong

| Symptom | Cause |
|---|---|
| Screen never updates | TRMNL skips regeneration when merge variables are identical. Click Force Refresh. |
| Screen blank after import | No webhook received yet. Do Step 2. |
| Everything reads 0 / unknown | Wrong entity slug. Re-check Step 3 verification 1. |
| "Unlocked" while actually locked | `locked_state` is a LOCK sensor where `on` means unlocked. The package already inverts it — if it is wrong, it is inverted twice. |
| Layout reflowed oddly | Framework version drift. Pin `framework_version` in `src/settings.yml`. |
| `429` from the webhook | Rate limit. Raise the throttle in the automation's condition. |

## Iterating on the design

```bash
npm install && npm run setup
npm run preview -- --view full --sample everything
npm run check      # HA template assertions + all 28 renders + build
```

`samples/everything.json` opens every closure at once and is the best stress
test for the diagram. `tools/render.mjs` renders Liquid through TRMNL's real
`/api/markup`, so what you see locally is what the device gets.
