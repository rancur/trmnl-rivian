#!/usr/bin/env python3
"""Render the Home Assistant payload template against a stubbed entity table.

Catches Jinja mistakes, invalid JSON and payloads over TRMNL's webhook size
limit without needing a live Home Assistant. Writes the result to
samples/from-ha.json so the same payload can be rendered by tools/render.mjs.
"""

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import yaml
from jinja2 import Environment

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEBHOOK_LIMIT = 2048  # bytes, free tier

# A plausible mid-charge R1T with a window and the tailgate left open.
STATES = {
    "sensor.r1t_battery_state_of_charge": ("64", {"unit_of_measurement": "%"}),
    "sensor.r1t_battery_state_of_charge_limit": ("80", {"unit_of_measurement": "%"}),
    "sensor.r1t_estimated_vehicle_range": ("200.4", {"unit_of_measurement": "mi"}),
    "sensor.r1t_cabin_temperature": ("20.0", {"unit_of_measurement": "°C"}),
    "sensor.r1t_odometer": ("12000.4", {"unit_of_measurement": "mi"}),
    "sensor.r1t_gear_selector": ("park", {}),
    "sensor.r1t_power": ("11.24", {"unit_of_measurement": "kW"}),
    "sensor.r1t_charging_time_remaining": ("95", {"unit_of_measurement": "min"}),
    "sensor.r1t_tire_pressure_front_left_status": ("OK", {}),
    "sensor.r1t_tire_pressure_front_right_status": ("OK", {}),
    "sensor.r1t_tire_pressure_rear_left_status": ("OK", {}),
    "sensor.r1t_tire_pressure_rear_right_status": ("OK", {}),
    "binary_sensor.r1t_locked_state": ("on", {}),
    "binary_sensor.r1t_charger_connection": ("on", {}),
    "binary_sensor.r1t_charging_status": ("on", {}),
    "binary_sensor.r1t_cabin_climate_preconditioning": ("off", {}),
    "binary_sensor.r1t_pet_mode": ("off", {}),
    "binary_sensor.r1t_window_front_left": ("on", {}),
    "binary_sensor.r1t_tailgate": ("on", {}),
    "device_tracker.r1t": ("home", {"friendly_name": "R1T"}),
}


def states(entity):
    return STATES.get(entity, ("unknown", {}))[0]


def is_state(entity, value):
    return states(entity) == value


def state_attr(entity, attr):
    return STATES.get(entity, ("unknown", {}))[1].get(attr)


class LenientLoader(yaml.SafeLoader):
    """Home Assistant's !secret / !include tags are not valid stock YAML."""


LenientLoader.add_multi_constructor(
    "!", lambda loader, suffix, node: f"<{suffix}>"
)


def main():
    path = ROOT / "homeassistant" / "trmnl_rivian.yaml"
    config = yaml.load(path.read_text(), Loader=LenientLoader)
    template = config["rest_command"]["trmnl_rivian_push"]["payload"]

    env = Environment()
    env.filters["to_json"] = lambda v: json.dumps(v)
    rendered = env.from_string(template).render(
        states=states,
        is_state=is_state,
        state_attr=state_attr,
        now=lambda: datetime(2026, 7, 30, 14, 32, tzinfo=timezone(timedelta(hours=-7))),
    )

    try:
        payload = json.loads(rendered)
    except json.JSONDecodeError as exc:
        print("payload is not valid JSON:", exc)
        print(rendered[:600])
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
        "vehicle", "soc", "soc_limit", "range", "distance_unit", "cabin_temp",
        "temp_unit", "odometer", "gear", "locked", "plugged_in", "charging",
        "charge_power", "charge_eta_min", "preconditioning", "pet_mode",
        "tire_alert", "doors_open", "windows_open", "storage_open", "updated_at",
    ]
    missing = [k for k in required if k not in merge]
    if missing:
        print("missing keys:", ", ".join(missing))
        return 1

    out = ROOT / "samples" / "from-ha.json"
    out.write_text(json.dumps(merge, indent=2) + "\n")
    print(json.dumps(merge, indent=2))
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
