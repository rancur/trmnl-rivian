#!/usr/bin/env python3
"""Render the Home Assistant payload template against stubbed entity tables.

Catches Jinja mistakes, invalid JSON, wrong sensor polarity, wrong entity names
and payloads over TRMNL's webhook size limit without needing a live Home
Assistant. Writes the result to samples/from-ha.json so the same payload can be
rendered by tools/render.mjs.

The scenario that matters most is `no entities at all`. An earlier version of
this file asserted that an empty entity table produced `soc: 0` and every health
flag `True` — it did not merely miss the silent-zero bug, it certified it. A
missing sensor is now required to be JSON null, and the assertion is generic, so
adding a new field cannot quietly reintroduce the coercion.
"""

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import yaml
from jinja2 import Environment

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEBHOOK_LIMIT = 2048  # bytes, free tier
TZ = timezone(timedelta(hours=-7))

# A fixed clock, so link-age arithmetic is deterministic.
NOW = datetime(2026, 7, 30, 14, 35, tzinfo=TZ)
LAST_CHANGED = datetime(2026, 7, 30, 14, 32, tzinfo=TZ)

# Every field that describes the vehicle rather than the plugin. Each one must
# be null when its sensor did not report — never 0, never False, never "".
NULLABLE = [
    "soc", "soc_limit", "range", "cabin_temp", "odometer", "gear",
    "driving", "service_mode", "locked", "plugged_in", "charging",
    "charge_power", "charge_eta_min", "preconditioning", "pet_mode",
    "door_fl", "door_fr", "door_rl", "door_rr",
    "win_fl", "win_fr", "win_rl", "win_rr",
    "frunk", "tonneau", "tailgate", "tunnel_l", "tunnel_r",
    "tire_fl", "tire_fr", "tire_rl", "tire_rr",
    "battery_12v_ok", "fluids_ok", "software_ok",
    "last_charge_start_soc", "last_charge_end_soc", "last_charge_kwh",
]

CONTRACT = NULLABLE + [
    "vehicle", "model", "body_style", "distance_unit", "temp_unit",
    "location", "last_charge_at", "last_charge_kwh_est",
    "moved_since_charge", "updated_at", "link_age_min",
]

# A mid-charge R1T with the front-left window down, the tailgate up, a soft rear
# tyre and a pending software update. Values follow the polarity the
# bretterer/home-assistant-rivian integration actually uses — notably
# `locked_state` is a LOCK binary sensor, so "on" means UNLOCKED.
#
# Entity ids are built from each entity's *display name*, not the integration's
# internal key. That is why the 12V check reads `12v_battery_health`: the key is
# `twelve_volt_battery_health` but the name is "12V Battery Health", and reading
# the key spelling matched no entity at all, so the check passed green forever.
STATES = {
    "sensor.r1t_battery_state_of_charge": ("64", {"unit_of_measurement": "%"}),
    "sensor.r1t_battery_state_of_charge_limit": ("80", {"unit_of_measurement": "%"}),
    "sensor.r1t_battery_capacity": ("141.5", {"unit_of_measurement": "kWh"}),
    "sensor.r1t_estimated_vehicle_range": ("200.4", {"unit_of_measurement": "mi"}),
    "sensor.r1t_cabin_temperature": ("20.0", {"unit_of_measurement": "°C"}),
    "sensor.r1t_odometer": ("12000.4", {"unit_of_measurement": "mi"}),
    "sensor.r1t_gear_selector": ("park", {}),
    "sensor.r1t_power_state": ("Ready", {}),
    "sensor.r1t_service_mode": ("false", {}),
    "sensor.r1t_charging_speed": ("11.24", {"unit_of_measurement": "kW"}),
    "sensor.r1t_charging_energy_delivered": ("45.00", {"unit_of_measurement": "kWh"}),
    "sensor.r1t_charging_time_remaining": ("97", {"unit_of_measurement": "min"}),
    "sensor.r1t_tire_pressure_front_left_status": ("OK", {}),
    "sensor.r1t_tire_pressure_front_right_status": ("OK", {}),
    "sensor.r1t_tire_pressure_rear_left_status": ("Low", {}),
    "sensor.r1t_tire_pressure_rear_right_status": ("OK", {}),
    "sensor.r1t_12v_battery_health": ("good", {}),
    "sensor.r1t_brake_fluid_level_low": ("false", {}),
    "sensor.r1t_software_ota_current_version": ("2026.18.0", {}),
    "sensor.r1t_software_ota_available_version": ("2026.20.1", {}),
    "binary_sensor.r1t_locked_state": ("off", {}),  # off => locked
    "binary_sensor.r1t_wiper_fluid_level": ("off", {}),  # off => normal
    "binary_sensor.r1t_charger_connection": ("on", {}),
    "binary_sensor.r1t_charging_status": ("on", {}),
    "binary_sensor.r1t_cabin_climate_preconditioning": ("off", {}),
    "binary_sensor.r1t_pet_mode": ("off", {}),
    "binary_sensor.r1t_door_front_left": ("off", {}),
    "binary_sensor.r1t_door_front_right": ("off", {}),
    "binary_sensor.r1t_door_rear_left": ("off", {}),
    "binary_sensor.r1t_door_rear_right": ("off", {}),
    "binary_sensor.r1t_window_front_left": ("on", {}),
    "binary_sensor.r1t_window_front_right": ("off", {}),
    "binary_sensor.r1t_window_rear_left": ("off", {}),
    "binary_sensor.r1t_window_rear_right": ("off", {}),
    "binary_sensor.r1t_front_trunk": ("off", {}),
    "binary_sensor.r1t_tonneau": ("off", {}),
    "binary_sensor.r1t_tailgate": ("on", {}),
    "binary_sensor.r1t_gear_tunnel_left": ("off", {}),
    "binary_sensor.r1t_gear_tunnel_right": ("off", {}),
    "device_tracker.r1t_location": ("home", {}),
    # Frozen when the last session ended; the vehicle has not been driven since
    # (odometer matches), so the last-charge caliper should show.
    "sensor.rivian_last_charge": (
        "2026-07-30T04:20:00-0700",
        {"start_soc": 40, "end_soc": 80, "kwh": 45.0, "kwh_est": 58.0, "odometer": 12000},
    ),
}

DEVICE = {"name": "R1T", "name_by_user": "My Rivian", "model": "R1T"}


class State:
    def __init__(self, value, attrs, reported_ago_min=0):
        self.state = value
        self.attributes = attrs
        self.last_changed = LAST_CHANGED
        self.last_updated = LAST_CHANGED
        # `last_reported` advances on every poll even when the value is
        # unchanged, which is what makes it a liveness signal rather than a
        # change signal.
        self.last_reported = NOW - timedelta(minutes=reported_ago_min)


ACTIVE = {}  # entity table for the scenario currently under test
REPORTED_AGO = 0  # minutes since the integration last reported, for this scenario


def states(entity=None):
    if entity is None:
        return None
    return ACTIVE.get(entity, ("unknown", {}))[0]


class StatesLookup:
    """Supports both states('x') and states['x'], like Home Assistant."""

    def __call__(self, entity):
        return states(entity)

    def __getitem__(self, entity):
        if entity not in ACTIVE:
            return None
        return State(*ACTIVE[entity][:2], reported_ago_min=REPORTED_AGO)


def is_state(entity, value):
    return states(entity) == value


def state_attr(entity, attr):
    return ACTIVE.get(entity, ("unknown", {}))[1].get(attr)


class LenientLoader(yaml.SafeLoader):
    """Home Assistant's !secret / !include tags are not valid stock YAML."""


LenientLoader.add_multi_constructor("!", lambda loader, suffix, node: f"<{suffix}>")


def _sensors():
    path = ROOT / "homeassistant" / "trmnl_rivian.yaml"
    config = yaml.load(path.read_text(), Loader=LenientLoader)
    # The package has several template blocks; find sensors by what they expose
    # rather than by position.
    return [s for block in config["template"] for s in block.get("sensor", [])]


def load_template():
    return next(
        (s["attributes"]["payload"] for s in _sensors()
         if "payload" in s.get("attributes", {})),
        None,
    )


def load_alert_template():
    return next(
        (s["state"] for s in _sensors() if s.get("unique_id") == "rivian_trmnl_alert_key"),
        None,
    )


def render(template, table, reported_ago_min=0):
    """Render the payload template against a given entity table."""
    global ACTIVE, REPORTED_AGO
    ACTIVE = table
    REPORTED_AGO = reported_ago_min
    env = Environment()
    env.filters["to_json"] = json.dumps
    env.filters["as_local"] = lambda d: d.astimezone(TZ)
    return env.from_string(template).render(
        states=StatesLookup(),
        is_state=is_state,
        state_attr=state_attr,
        now=lambda: NOW,
        # Returns none for an unknown entity, exactly as Home Assistant does,
        # so the guard around device_attr is exercised.
        device_id=lambda entity: "dev_1" if entity in ACTIVE else None,
        device_attr=lambda dev, attr: DEVICE.get(attr) if dev else None,
    )


def alert_key(alert_template, merge):
    """Render the priority fingerprint for a given payload."""
    body = json.dumps({"merge_variables": merge})
    env = Environment()
    env.filters["from_json"] = json.loads
    global ACTIVE
    ACTIVE = {"sensor.rivian_trmnl_payload": ("ok", {"payload": body})}
    return env.from_string(alert_template).render(state_attr=state_attr).strip()


def check_alert_key(payload_template):
    """The fingerprint decides which changes are allowed to jump the rate-limit
    queue, so it has to be sensitive to exactly the right things: a tailgate
    opening must never be held back, and a state of charge ticking up must never
    spend a push.
    """
    print("\n--- priority fingerprint ---")
    alert = load_alert_template()
    if alert is None:
        print("no `rivian_trmnl_alert_key` sensor found")
        return 1

    # Start from a quiet, everything-fine vehicle so each mutation below is a
    # genuine transition rather than a no-op against the healthy fixture.
    base = json.loads(render(payload_template, STATES))["merge_variables"] | {
        "locked": True, "charging": False, "plugged_in": False,
        "service_mode": False, "tailgate": False, "door_fr": False,
        "tire_fr": True, "battery_12v_ok": True, "soc": 64, "link_age_min": 0,
    }
    key = alert_key(alert, base)

    cases = [
        # (label, mutation, must the fingerprint change?)
        ("state of charge drifts", {"soc": base["soc"] + 1}, False),
        ("range drifts", {"range": base["range"] - 3}, False),
        ("cabin warms up", {"cabin_temp": base["cabin_temp"] + 4}, False),
        ("odometer ticks", {"odometer": base["odometer"] + 1}, False),
        ("timestamp moves", {"updated_at": "2026-07-30T15:00:00-0700"}, False),
        ("tailgate opens", {"tailgate": True}, True),
        ("vehicle is unlocked", {"locked": False}, True),
        ("charging starts", {"charging": True}, True),
        ("a door opens", {"door_fr": True}, True),
        ("a tyre is flagged", {"tire_fr": False}, True),
        ("a sensor goes silent", {"battery_12v_ok": None}, True),
        ("the feed goes quiet", {"link_age_min": 180}, True),
        ("charge falls below 15%", {"soc": 12}, True),
        ("service mode engages", {"service_mode": True}, True),
    ]

    failures = 0
    for label, mutation, should_change in cases:
        # A mutation that does not actually change the payload would pass the
        # "must not change" cases for the wrong reason.
        if all(base.get(k) == v for k, v in mutation.items()):
            failures += 1
            print(f"  {label}: mutation is a no-op against the base payload")
            continue
        mutated = alert_key(alert, {**base, **mutation})
        changed = mutated != key
        if changed != should_change:
            failures += 1
            verb = "should have changed" if should_change else "should NOT have changed"
            print(f"  {label}: fingerprint {verb}")
    if failures:
        return 1

    # Home Assistant truncates a sensor state past 255 characters, which would
    # silently collapse distinct states into one.
    if len(key) > 255:
        print(f"fingerprint is {len(key)} characters; Home Assistant caps state at 255")
        return 1

    print(f"{len(cases) + 1} assertions passed (fingerprint is {len(key)} characters)")
    return 0


def scenario(label, template, table, expected, reported_ago_min=0,
             all_null=False, write_sample=False):
    print(f"\n--- {label} ---")
    try:
        rendered = render(template, table, reported_ago_min)
    except Exception as exc:  # noqa: BLE001 - any Jinja failure is a test failure
        print(f"template raised {type(exc).__name__}: {exc}")
        return 1

    try:
        payload = json.loads(rendered)
    except json.JSONDecodeError as exc:
        print("payload is not valid JSON:", exc)
        print(rendered[:800])
        return 1

    merge = payload.get("merge_variables")
    if merge is None:
        print("payload is missing the merge_variables node TRMNL expects")
        return 1

    size = len(rendered.encode())
    print(f"payload: {size} bytes (limit {WEBHOOK_LIMIT})")
    if size > WEBHOOK_LIMIT:
        print("payload exceeds the webhook size limit")
        return 1

    if missing := [k for k in CONTRACT if k not in merge]:
        print("missing keys:", ", ".join(missing))
        return 1

    checks = len(expected)

    # The generic guard. Any nullable field that came back as a number, a
    # boolean or an empty string when nothing reported is a silent-zero bug,
    # whether or not anyone remembered to write an assertion for it.
    if all_null:
        lying = {k: merge[k] for k in NULLABLE if merge[k] is not None}
        if lying:
            print("fields coerced a missing sensor into a value instead of null:")
            for key, value in sorted(lying.items()):
                print(f"  {key}: {value!r}")
            return 1
        checks += len(NULLABLE)
        print(f"all {len(NULLABLE)} vehicle fields are null")

    if failures := [
        f"  {k}: expected {v!r}, got {merge.get(k)!r}"
        for k, v in expected.items()
        if merge.get(k) != v
    ]:
        print(f"payload does not match the {label} scenario:")
        print("\n".join(failures))
        return 1

    print(f"{checks} assertions passed")

    if write_sample:
        out = dict(merge)
        # Relative ages so the fixture does not rot; see tools/samples.mjs.
        if out.get("updated_at"):
            age = (NOW - datetime.strptime(out["updated_at"], "%Y-%m-%dT%H:%M:%S%z"))
            out["_age_min"] = int(age.total_seconds() // 60)
            del out["updated_at"]
        if out.get("last_charge_at"):
            age = (NOW - datetime.strptime(out["last_charge_at"], "%Y-%m-%dT%H:%M:%S%z"))
            out["_last_charge_age_min"] = int(age.total_seconds() // 60)
            del out["last_charge_at"]
        (ROOT / "samples" / "from-ha.json").write_text(json.dumps(out, indent=2) + "\n")
        print("wrote samples/from-ha.json")
    return 0


def main():
    template = load_template()
    if template is None:
        print("no template sensor exposes a `payload` attribute")
        return 1

    # 1. A healthy vehicle: mid-charge, window down, tailgate up, soft rear tire,
    #    pending software update, parked at home after a timed overnight session.
    healthy = {
        "vehicle": "My Rivian",
        "body_style": "truck",
        "locked": True,       # locked_state 'off' means locked
        "win_fl": True,
        "tailgate": True,
        "door_fl": False,
        "tire_rl": False,     # 'Low' is not a known-good value
        "tire_fr": True,
        "fluids_ok": True,
        "software_ok": False,  # 2026.18.0 != 2026.20.1
        "battery_12v_ok": True,
        "charge_power": 11,    # quantised from 11.24
        "charge_eta_min": 95,  # quantised from 97 to the nearest 5
        "location": "Home",    # device_tracker 'home' zone
        "driving": False,      # power_state Ready, gear park
        "service_mode": False,
        "last_charge_start_soc": 40,
        "last_charge_end_soc": 80,
        "last_charge_kwh": 45.0,       # metered, so the estimate is not used
        "last_charge_kwh_est": False,
        "moved_since_charge": False,   # odometer 12000 rounded == snapshot
        "link_age_min": 0,             # everything reported just now
    }

    # 2. Integration installed but the vehicle has not reported yet: only the SOC
    #    sensor exists. Nothing may crash, and nothing may be invented.
    degraded = {
        "soc": 64,
        "locked": None,          # a silent lock sensor is NOT "locked"
        "tire_fl": None, "tire_fr": None, "tire_rl": None, "tire_rr": None,
        "battery_12v_ok": None,
        "fluids_ok": None,
        "software_ok": None,
        "charging": None,
        "plugged_in": None,
        "driving": None,
        "service_mode": None,
        "charge_power": None,
        "location": "",
        "moved_since_charge": True,   # no snapshot means nothing to report
    }

    # 3. The realistic total failure. One field removed upstream takes the whole
    #    vehicleState subscription down, so every entity reads `unavailable`
    #    rather than disappearing — and `unavailable` must not be a number.
    unavailable_table = {k: ("unavailable", {}) for k in STATES}

    # 4. Rivian's live-session query is retired, so charge rate and metered
    #    session energy go dark while everything from vehicleState keeps working.
    dark_session = {k: v for k, v in STATES.items()
                    if k not in ("sensor.r1t_charging_speed",
                                 "sensor.r1t_charging_energy_delivered")}
    dark_session["sensor.rivian_last_charge"] = (
        "2026-07-30T04:20:00-0700",
        {"start_soc": 40, "end_soc": 80, "kwh": None, "kwh_est": 58.0, "odometer": 12000},
    )

    rc = scenario("healthy vehicle", template, STATES, healthy, write_sample=True)
    if rc:
        return rc

    rc = scenario(
        "degraded: only a state of charge",
        template,
        {"sensor.r1t_battery_state_of_charge": ("64", {"unit_of_measurement": "%"})},
        degraded,
    )
    if rc:
        return rc

    rc = scenario(
        "no entities at all",
        template,
        {},
        {"vehicle": "Rivian", "model": "", "updated_at": "", "link_age_min": 2880},
        all_null=True,
    )
    if rc:
        return rc

    rc = scenario(
        "every entity unavailable (the vehicleState cascade)",
        template,
        unavailable_table,
        # Freshness must not count an entity that just changed *to* unavailable,
        # or a dying feed looks like it has only this second refreshed.
        {"updated_at": "", "link_age_min": 2880},
        all_null=True,
    )
    if rc:
        return rc

    rc = scenario(
        "live-session query retired: no charge rate, energy is an estimate",
        template,
        dark_session,
        {
            "soc": 64,                    # vehicleState, still fine
            "charging": True,             # vehicleState (chargerState)
            "plugged_in": True,           # vehicleState (chargerStatus)
            "charge_eta_min": 95,         # vehicleState (timeToEndOfCharge)
            "charge_power": None,         # live session only — must not be 0
            "last_charge_kwh": 58.0,      # falls back to the SOC estimate
            "last_charge_kwh_est": True,  # and says so
        },
    )
    if rc:
        return rc

    rc = scenario(
        "link gone quiet for three hours",
        template,
        STATES,
        {"soc": 64, "link_age_min": 180},
        reported_ago_min=185,
    )
    if rc:
        return rc

    # The bug that made the 12V check pass green forever: the entity is named
    # after its display name, not the integration's internal key.
    old_name = dict(STATES)
    del old_name["sensor.r1t_12v_battery_health"]
    old_name["sensor.r1t_twelve_volt_battery_health"] = ("poor", {})
    rc = scenario(
        "12V: the old key spelling matches nothing",
        template,
        old_name,
        {"battery_12v_ok": None},
    )
    if rc:
        return rc

    bad_12v = dict(STATES)
    bad_12v["sensor.r1t_12v_battery_health"] = ("poor", {})
    rc = scenario(
        "12V: a genuinely poor battery is flagged",
        template,
        bad_12v,
        {"battery_12v_ok": False},
    )
    if rc:
        return rc

    return check_alert_key(template)


if __name__ == "__main__":
    sys.exit(main())
