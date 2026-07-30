#!/usr/bin/env python3
"""Render the Home Assistant payload template against a stubbed entity table.

Catches Jinja mistakes, invalid JSON, wrong sensor polarity and payloads over
TRMNL's webhook size limit without needing a live Home Assistant. Writes the
result to samples/from-ha.json so the same payload can be rendered by
tools/render.mjs.
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

# A mid-charge R1T with the front-left window down, the tailgate up, a soft rear
# tyre and a pending software update. Values follow the polarity the
# bretterer/home-assistant-rivian integration actually uses — notably
# `locked_state` is a LOCK binary sensor, so "on" means UNLOCKED.
STATES = {
    "sensor.r1t_battery_state_of_charge": ("64", {"unit_of_measurement": "%"}),
    "sensor.r1t_battery_state_of_charge_limit": ("80", {"unit_of_measurement": "%"}),
    "sensor.r1t_estimated_vehicle_range": ("201.4", {"unit_of_measurement": "mi"}),
    "sensor.r1t_cabin_temperature": ("21.6", {"unit_of_measurement": "°C"}),
    "sensor.r1t_odometer": ("18432.7", {"unit_of_measurement": "mi"}),
    "sensor.r1t_gear_selector": ("park", {}),
    "sensor.r1t_power_state": ("Ready", {}),
    "sensor.r1t_service_mode": ("false", {}),
    "sensor.r1t_charging_speed": ("11.24", {"unit_of_measurement": "kW"}),
    "sensor.r1t_charging_energy_delivered": ("44.83", {"unit_of_measurement": "kWh"}),
    "sensor.r1t_charging_time_remaining": ("97", {"unit_of_measurement": "min"}),
    "sensor.r1t_tire_pressure_front_left_status": ("OK", {}),
    "sensor.r1t_tire_pressure_front_right_status": ("OK", {}),
    "sensor.r1t_tire_pressure_rear_left_status": ("Low", {}),
    "sensor.r1t_tire_pressure_rear_right_status": ("OK", {}),
    "sensor.r1t_twelve_volt_battery_health": ("good", {}),
    "sensor.r1t_brake_fluid_level_low": ("false", {}),
    "sensor.r1t_software_ota_current_version": ("2026.18.0", {}),
    "sensor.r1t_software_ota_available_version": ("2026.20.1", {}),
    "binary_sensor.r1t_locked_state": ("off", {}),  # off => locked
    "binary_sensor.r1t_wiper_fluid_level": ("off", {}),  # off => normal
    "binary_sensor.r1t_charger_connection": ("on", {}),
    "binary_sensor.r1t_charging_status": ("on", {}),
    "binary_sensor.r1t_cabin_climate_preconditioning": ("off", {}),
    "binary_sensor.r1t_pet_mode": ("off", {}),
    "binary_sensor.r1t_window_front_left": ("on", {}),
    "binary_sensor.r1t_tailgate": ("on", {}),
    "device_tracker.r1t_location": ("home", {}),
    # Frozen when the last session ended; the truck has not been driven since
    # (odometer matches), so the last-charge caliper should show.
    "sensor.rivian_last_charge": (
        "2026-07-30T04:20:00-0700",
        {"start_soc": 39, "end_soc": 80, "kwh": 44.8, "odometer": 18433},
    ),
}

DEVICE = {"name": "R1T", "name_by_user": "Gluten Free Grocery Getter", "model": "R1T"}


class State:
    def __init__(self, value, attrs):
        self.state = value
        self.attributes = attrs
        self.last_changed = datetime(2026, 7, 30, 14, 32, tzinfo=TZ)


ACTIVE = {}  # entity table for the scenario currently under test


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
        return State(*ACTIVE[entity])


def is_state(entity, value):
    return states(entity) == value


def state_attr(entity, attr):
    return ACTIVE.get(entity, ("unknown", {}))[1].get(attr)


class LenientLoader(yaml.SafeLoader):
    """Home Assistant's !secret / !include tags are not valid stock YAML."""


LenientLoader.add_multi_constructor("!", lambda loader, suffix, node: f"<{suffix}>")


def load_template():
    path = ROOT / "homeassistant" / "trmnl_rivian.yaml"
    config = yaml.load(path.read_text(), Loader=LenientLoader)
    # The package has several template blocks; find the one holding the payload
    # rather than depending on its position.
    template = next(
        (
            sensor["attributes"]["payload"]
            for block in config["template"]
            for sensor in block.get("sensor", [])
            if "payload" in sensor.get("attributes", {})
        ),
        None,
    )
    return template


def render(template, table):
    """Render the payload template against a given entity table."""
    global ACTIVE
    ACTIVE = table
    env = Environment()
    env.filters["to_json"] = json.dumps
    env.filters["as_local"] = lambda d: d.astimezone(TZ)
    rendered = env.from_string(template).render(
        states=StatesLookup(),
        is_state=is_state,
        state_attr=state_attr,
        # Returns none for an unknown entity, exactly as Home Assistant does,
        # so the guard around device_attr is exercised.
        device_id=lambda entity: "dev_1" if entity in ACTIVE else None,
        device_attr=lambda dev, attr: DEVICE.get(attr) if dev else None,
    )
    return rendered


def scenario(label, template, table, expected, required=()):
    print(f"\n--- {label} ---")
    try:
        rendered = render(template, table)
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

    contract = [
        "vehicle", "model", "body_style", "soc", "soc_limit", "range",
        "distance_unit", "cabin_temp", "temp_unit", "odometer", "gear", "locked",
        "plugged_in", "charging", "charge_power", "charge_eta_min",
        "preconditioning", "pet_mode", "location", "driving", "service_mode",
        "last_charge_start_soc", "last_charge_end_soc", "last_charge_kwh",
        "last_charge_at", "moved_since_charge",
        "door_fl", "door_fr", "door_rl", "door_rr",
        "win_fl", "win_fr", "win_rl", "win_rr",
        "frunk", "tonneau", "tailgate", "tunnel_l", "tunnel_r",
        "tire_fl", "tire_fr", "tire_rl", "tire_rr",
        "battery_12v_ok", "fluids_ok", "software_ok", "updated_at",
    ]
    if missing := [k for k in contract if k not in merge]:
        print("missing keys:", ", ".join(missing))
        return 1

    failures = [
        f"  {k}: expected {v!r}, got {merge.get(k)!r}"
        for k, v in expected.items()
        if merge.get(k) != v
    ]
    if failures:
        print(f"payload does not match the {label} scenario:")
        print("\n".join(failures))
        return 1

    print(f"{len(expected)} assertions passed")
    if required:
        (ROOT / "samples" / "from-ha.json").write_text(json.dumps(merge, indent=2) + "\n")
        print("wrote samples/from-ha.json")
    return 0


def main():
    template = load_template()
    if template is None:
        print("no template sensor exposes a `payload` attribute")
        return 1

    # A healthy truck: mid-charge, window down, tailgate up, soft rear tire,
    # pending software update, parked at home after a timed overnight session.
    healthy = {
        "vehicle": "Gluten Free Grocery Getter",
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
        "last_charge_start_soc": 39,
        "last_charge_end_soc": 80,
        "last_charge_kwh": 44.8,
        "moved_since_charge": False,  # odometer 18433 rounded == snapshot
    }

    # Integration installed but the vehicle has not reported yet: only the SOC
    # sensor exists. Nothing may crash, and nothing may invent an alarm.
    degraded = {
        "locked": True,          # no lock sensor is not "unlocked"
        "tire_fl": True, "tire_fr": True, "tire_rl": True, "tire_rr": True,
        "battery_12v_ok": True,
        "fluids_ok": True,
        "software_ok": True,     # no available version means nothing pending
        "charging": False,
        "plugged_in": False,
        "driving": False,
        "service_mode": False,
        "location": "",
        "moved_since_charge": True,   # no snapshot means nothing to report
    }

    # Nothing at all: the integration is not set up, or every entity is
    # unavailable. device_id() returns none, so the device-registry guard runs.
    empty = dict(degraded, soc=0, vehicle="Rivian", model="", updated_at="")

    rc = scenario("healthy vehicle", template, STATES, healthy, required=True)
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
    return scenario("no entities at all", template, {}, empty)
    out.write_text(json.dumps(merge, indent=2) + "\n")
    print(json.dumps(merge, indent=2))
    print(f"\nall {len(expected)} assertions passed -> wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
