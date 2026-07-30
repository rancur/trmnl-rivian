#!/usr/bin/env python3
"""Write a Home Assistant package wired to your vehicle's entity slug.

The slug appears in several places — Home Assistant requires literal entity ids
in trigger definitions, so they cannot read it from a variable. Editing by hand
and missing one leaves a package that half works, which is worse than one that
fails outright. This does the substitution for you.

    python3 tools/configure_ha.py --slug my_r1t
    python3 tools/configure_ha.py --slug my_r1t --out ~/ha/packages/trmnl_rivian.yaml

With --check it verifies the shipped package uses one slug consistently, which
is what the test suite calls.
"""

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "homeassistant" / "trmnl_rivian.yaml"
DEFAULT_SLUG = "r1t"

# Entity domains the Rivian integration creates, used to find slug references.
DOMAINS = ("sensor", "binary_sensor", "device_tracker")


def occurrences(text, slug):
    """Every entity id and Jinja assignment that names the vehicle."""
    entity = re.compile(rf"\b({'|'.join(DOMAINS)})\.{re.escape(slug)}_")
    assign = re.compile(rf"set vehicle = '{re.escape(slug)}'")
    return len(entity.findall(text)) + len(assign.findall(text))


def substitute(text, old, new):
    for domain in DOMAINS:
        text = text.replace(f"{domain}.{old}_", f"{domain}.{new}_")
    return text.replace(f"set vehicle = '{old}'", f"set vehicle = '{new}'")


def check():
    text = SOURCE.read_text()
    found = occurrences(text, DEFAULT_SLUG)
    if found == 0:
        print(f"no references to the default slug '{DEFAULT_SLUG}' — did it get renamed?")
        return 1

    # Any other slug in an entity id means a half-finished rename.
    others = {
        m.group(2)
        for m in re.finditer(rf"\b({'|'.join(DOMAINS)})\.([a-z0-9_]+?)_(battery_state_of_charge|charging_status|odometer|location)\b", text)
        if m.group(2) != DEFAULT_SLUG
    }
    # The package's own helper sensors are not vehicle entities.
    others -= {"rivian"}
    if others:
        print(f"package mixes slugs: {DEFAULT_SLUG} and {', '.join(sorted(others))}")
        return 1

    print(f"package references '{DEFAULT_SLUG}' consistently in {found} places")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", help="your vehicle's entity slug, e.g. r1t")
    ap.add_argument("--out", help="where to write (default: stdout)")
    ap.add_argument("--check", action="store_true", help="verify the shipped package")
    args = ap.parse_args()

    if args.check:
        return check()
    if not args.slug:
        ap.error("--slug is required unless --check is given")

    if not re.fullmatch(r"[a-z0-9_]+", args.slug):
        print("slug must be lowercase letters, digits and underscores", file=sys.stderr)
        return 1

    text = SOURCE.read_text()
    count = occurrences(text, DEFAULT_SLUG)
    result = substitute(text, DEFAULT_SLUG, args.slug)

    if occurrences(result, DEFAULT_SLUG) and args.slug != DEFAULT_SLUG:
        print("substitution left references behind — refusing to write", file=sys.stderr)
        return 1

    if args.out:
        out = pathlib.Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result)
        print(f"wrote {out} ({count} references set to '{args.slug}')")
    else:
        sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
