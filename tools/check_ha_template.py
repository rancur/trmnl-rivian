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
    "sensor.r1t_estimated_vehicle_range": ("200.4", {"unit_of_measurement": "mi"}),
    "sensor.r1t_cabin_temperature": ("20.0", {"unit_of_measurement": "°C"}),
    "sensor.r1t_odometer": ("12000.4", {"unit_of_measurement": "mi"}),
    "sensor.r1t_gear_selector": ("park", {}),
    "sensor.r1t_power_state": ("Ready", {}),
    "sensor.r1t_service_mode": ("false", {}),
    "sensor.r1t_power": ("11.24", {"unit_of_measurement": "kW"}),
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
}

DEVICE = {"name": "R1T", "name_by_user": "My Rivian", "model": "R1T"}


class State:
    def __init__(self, value, attrs):
        self.state = value
        self.attributes = attrs
        self.last_changed = datetime(2026, 7, 30, 14, 32, tzinfo=TZ)


def states(entity=None):
    if entity is None:
        return None
    return STATES.get(entity, ("unknown", {}))[0]


class StatesLookup:
    """Supports both states('x') and states['x'], like Home Assistant."""

    def __call__(self, entity):
        return states(entity)

    def __getitem__(self, entity):
        if entity not in STATES:
            return None
        return State(*STATES[entity])


def is_state(entity, value):
    return states(entity) == value


def state_attr(entity, attr):
    return STATES.get(entity, ("unknown", {}))[1].get(attr)


class LenientLoader(yaml.SafeLoader):
    """Home Assistant's !secret / !include tags are not valid stock YAML."""


LenientLoader.add_multi_constructor("!", lambda loader, suffix, node: f"<{suffix}>")


def main():
    path = ROOT / "homeassistant" / "trmnl_rivian.yaml"
    config = yaml.load(path.read_text(), Loader=LenientLoader)
    template = config["template"][0]["sensor"][0]["attributes"]["payload"]

    env = Environment()
    env.filters["to_json"] = json.dumps
    env.filters["as_local"] = lambda d: d.astimezone(TZ)
    rendered = env.from_string(template).render(
        states=StatesLookup(),
        is_state=is_state,
        state_attr=state_attr,
        device_id=lambda entity: "dev_1",
        device_attr=lambda dev, attr: DEVICE.get(attr),
        dict=dict,
    )

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

    required = [
        "vehicle", "model", "body_style", "soc", "soc_limit", "range",
        "distance_unit", "cabin_temp", "temp_unit", "odometer", "gear", "locked",
        "plugged_in", "charging", "charge_power", "charge_eta_min",
        "preconditioning", "pet_mode", "location", "driving", "service_mode",
        "door_fl", "door_fr", "door_rl", "door_rr",
        "win_fl", "win_fr", "win_rl", "win_rr",
        "frunk", "tonneau", "tailgate", "tunnel_l", "tunnel_r",
        "tire_fl", "tire_fr", "tire_rl", "tire_rr",
        "battery_12v_ok", "fluids_ok", "software_ok", "updated_at",
    ]
    if missing := [k for k in required if k not in merge]:
        print("missing keys:", ", ".join(missing))
        return 1

    # The stub above encodes a specific truck; if the template misreads any of
    # these, the screen would be confidently wrong rather than obviously broken.
    expected = {
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
    }
    failures = [
        f"  {k}: expected {v!r}, got {merge.get(k)!r}"
        for k, v in expected.items()
        if merge.get(k) != v
    ]
    if failures:
        print("payload does not match the stubbed vehicle:")
        print("\n".join(failures))
        return 1

    out = ROOT / "samples" / "from-ha.json"
    out.write_text(json.dumps(merge, indent=2) + "\n")
    print(json.dumps(merge, indent=2))
    print(f"\nall {len(expected)} assertions passed -> wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
