#!/usr/bin/env node
// Contract tests for the Liquid views, run against TRMNL's own renderer.
//
// These assert behaviour, not pixels: that no view errors, that nothing leaks
// an unrendered tag, and — most importantly — that a sparse payload never
// invents an alarm. Pixel review is what preview/ is for.
//
//   node tools/test_views.mjs

import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

const MARKUP_API = 'https://trmnl.com/api/markup';
const ROOT = resolve(import.meta.dirname, '..');
const VIEWS = ['full', 'half_horizontal', 'half_vertical', 'quadrant'];

const CHECK = '&#10003;'; // ✓
const CROSS = '&#10007;'; // ✗

const shared = readFileSync(`${ROOT}/src/shared.liquid`, 'utf8');
const view = (name) => shared + '\n' + readFileSync(`${ROOT}/src/${name}.liquid`, 'utf8');
const sample = (name) => JSON.parse(readFileSync(`${ROOT}/samples/${name}.json`, 'utf8'));

async function render(markup, variables) {
  const res = await fetch(MARKUP_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ markup, variables }),
  });
  if (!res.ok) throw new Error(`markup API ${res.status}: ${await res.text()}`);
  return (await res.json()).data;
}

let failures = 0;
let assertions = 0;

function check(label, condition, detail = '') {
  assertions++;
  if (!condition) {
    failures++;
    console.error(`  FAIL  ${label}${detail ? `\n        ${detail}` : ''}`);
  }
}

// Invariants that must hold for every view and every payload.
function universal(label, html) {
  check(`${label}: no Liquid error`, !/Liquid (error|syntax error)/i.test(html),
    html.match(/Liquid[^<]{0,120}/i)?.[0]);
  check(`${label}: no unrendered tag`, !html.includes('{{') && !html.includes('{%'));
  check(`${label}: no literal nil/undefined leaked`, !/>\s*(nil|undefined|null)\s*</.test(html));
  check(`${label}: renders a layout`, html.includes('class="layout'));
}

console.log('rendering contract tests...\n');

// 1. Every view against every sample.
const samples = readdirSync(`${ROOT}/samples`)
  .filter((f) => f.endsWith('.json'))
  .map((f) => f.replace(/\.json$/, ''))
  .sort();

for (const v of VIEWS) {
  for (const s of samples) {
    universal(`${v}/${s}`, await render(view(v), sample(s)));
  }
}

// 2. The important one: a payload with nothing in it must read as "nothing to
//    report", not as a truck with flat tires and the doors unlocked.
for (const v of VIEWS) {
  const html = await render(view(v), {});
  universal(`${v}/empty`, html);
  check(`${v}/empty: invents no failing check`, !html.includes(CROSS),
    'a missing field rendered as a ✗ alarm');
}

// A payload carrying only a state of charge is the realistic degraded case:
// one sensor available, everything else absent.
for (const v of VIEWS) {
  const html = await render(view(v), { soc: 55, soc_limit: 80 });
  universal(`${v}/soc-only`, html);
  check(`${v}/soc-only: invents no failing check`, !html.includes(CROSS));
  check(`${v}/soc-only: shows the charge`, html.includes('55'));
}

// 3. Behaviour that the design promises.
const full = (s) => render(view('full'), sample(s));

let html = await full('charging');
check('charging: status line names the place', html.includes('Charging at Home'));
check('charging: all checks pass', !html.includes(CROSS));
check('charging: no last-charge caliper while charging', !html.includes('class="charge-session"'));

html = await full('after-charge');
check('after-charge: reports what the session added', html.includes('Last charge +40%'));
check('after-charge: draws the caliper', html.includes('class="charge-session"'));
check('after-charge: caliper starts at the session start', html.includes('left: 40%'));

html = await full('everything');
check('everything: flags closures', html.includes(`${CROSS}&nbsp;Closed`));
check('everything: flags the lock', html.includes(`${CROSS}&nbsp;Locked`));
check('everything: names what is open', html.includes('Front left door'));
check('everything: labels read as phrases', html.includes('Right gear tunnel'));
check('everything: no last-charge panel when driven since', !html.includes('class="charge-session"'));

html = await full('low');
check('low: warns on charge', html.includes('Low charge'));
check('low: flags the tire', html.includes(`${CROSS}&nbsp;Tires`));

html = await full('suv');
check('suv: omits the gear tunnel', !html.includes('gear tunnel'));
check('suv: still draws a body', html.includes('<svg'));

// 4. A driven-since payload must retire the last-charge panel even though the
//    figures are still present.
html = await render(view('full'), { ...sample('after-charge'), moved_since_charge: true });
check('driven since charge: retires the panel', !html.includes('class="charge-session"'));

// 5. Every sample must carry the documented contract.
const REQUIRED = [
  'vehicle', 'model', 'body_style', 'soc', 'soc_limit', 'range', 'distance_unit',
  'cabin_temp', 'temp_unit', 'odometer', 'gear', 'locked', 'plugged_in',
  'charging', 'charge_power', 'charge_eta_min', 'preconditioning', 'pet_mode',
  'location', 'driving', 'service_mode',
  'door_fl', 'door_fr', 'door_rl', 'door_rr',
  'win_fl', 'win_fr', 'win_rl', 'win_rr',
  'frunk', 'tonneau', 'tailgate', 'tunnel_l', 'tunnel_r',
  'tire_fl', 'tire_fr', 'tire_rl', 'tire_rr',
  'battery_12v_ok', 'fluids_ok', 'software_ok',
  'last_charge_start_soc', 'last_charge_end_soc', 'last_charge_kwh',
  'last_charge_at', 'moved_since_charge', 'updated_at',
];
for (const s of samples) {
  const data = sample(s);
  const missing = REQUIRED.filter((k) => !(k in data));
  check(`sample ${s}: complete contract`, missing.length === 0, `missing: ${missing.join(', ')}`);
  const size = JSON.stringify({ merge_variables: data }).length;
  check(`sample ${s}: fits the webhook limit`, size <= 2048, `${size} bytes`);
}

console.log(`\n${assertions - failures}/${assertions} assertions passed`);
process.exit(failures ? 1 : 0);
