#!/usr/bin/env node
// Contract tests for the Liquid views, run against TRMNL's own renderer.
//
// These assert behaviour, not pixels: that no view errors, that nothing leaks
// an unrendered tag, and — above everything else — that the screen never states
// something it does not know.
//
// That last one is the reason this file exists in its current form. An earlier
// version tested only that a sparse payload invents no *alarm*, which it does
// not: it renders six green ticks, 0% charge and a "Low charge" badge instead.
// A suite that passes while the dashboard lies is worse than no suite, so the
// assertions below check both directions — a missing sensor must produce
// neither a cross nor a tick.
//
//   node tools/test_views.mjs

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { loadSample, sampleNames, materialise } from './samples.mjs';

const MARKUP_API = 'https://trmnl.com/api/markup';
const ROOT = resolve(import.meta.dirname, '..');
const VIEWS = ['full', 'half_horizontal', 'half_vertical', 'quadrant'];

const CHECK = '&#10003;'; // ✓
const CROSS = '&#10007;'; // ✗
const QUERY = '?&nbsp;'; // the "did not report" marker on a check
const DASH = '&mdash;'; // the "did not report" marker on a figure

const shared = readFileSync(`${ROOT}/src/shared.liquid`, 'utf8');
const view = (name) => shared + '\n' + readFileSync(`${ROOT}/src/${name}.liquid`, 'utf8');

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

// The headline figure, whatever it happens to be.
function headline(html) {
  return html.match(/value--tnums"[^>]*>([^<]*)</)?.[1]?.trim() ?? '';
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

const samples = sampleNames();

// ---------------------------------------------------------------------------
// 1. Every view against every sample.
// ---------------------------------------------------------------------------
for (const v of VIEWS) {
  for (const s of samples) {
    universal(`${v}/${s}`, await render(view(v), loadSample(s)));
  }
}

// ---------------------------------------------------------------------------
// 2. The important one, in both directions.
//
//    A payload with nothing in it must read as "I do not know", which is
//    neither "everything is fine" nor "everything is broken". The zero-coercion
//    bug this suite now guards against rendered exactly the first of those.
// ---------------------------------------------------------------------------
for (const v of VIEWS) {
  const html = await render(view(v), {});
  universal(`${v}/empty`, html);

  check(`${v}/empty: invents no failing check`, !html.includes(CROSS),
    'a missing field rendered as a ✗ alarm');
  check(`${v}/empty: invents no PASSING check`, !html.includes(CHECK),
    'a missing field rendered as a ✓ — the dashboard is vouching for a sensor that never reported');
  check(`${v}/empty: says it does not know`, html.includes(QUERY) || html.includes(DASH),
    'nothing on screen marks the data as unknown');
  check(`${v}/empty: no "All good"`, !html.includes('All good'),
    'an empty payload reported a clean bill of health');
  check(`${v}/empty: no invented low-charge alarm`, !html.includes('Low charge'),
    'absent state of charge coerced to 0 and tripped the low-charge badge');
  check(`${v}/empty: charge is a dash, not a number`, headline(html) === DASH,
    `headline figure was ${JSON.stringify(headline(html))}`);
  check(`${v}/empty: does not claim the vehicle is parked`, !/>\s*Parked/.test(html),
    '"Parked" is a claim; with no data the status line must say so');
}

// A payload carrying only a state of charge is the realistic partial case: one
// sensor available, everything else absent.
for (const v of VIEWS) {
  const html = await render(view(v), { soc: 55, soc_limit: 80 });
  universal(`${v}/soc-only`, html);
  check(`${v}/soc-only: shows the charge`, headline(html) === '55');
  check(`${v}/soc-only: invents no failing check`, !html.includes(CROSS));
  check(`${v}/soc-only: invents no passing check`, !html.includes(CHECK));
  check(`${v}/soc-only: marks the rest unknown`, html.includes(QUERY) || html.includes(DASH));
}

// Explicit JSON nulls must behave exactly like absent keys. Home Assistant now
// sends null rather than omitting fields, so this is the shape that actually
// arrives in production.
for (const v of VIEWS) {
  const html = await render(view(v), loadSample('nodata'));
  universal(`${v}/nodata`, html);
  check(`${v}/nodata: explicit null behaves like absent`, !html.includes(CHECK) && !html.includes(CROSS));
  check(`${v}/nodata: charge is a dash`, headline(html) === DASH);
  check(`${v}/nodata: no low-charge alarm`, !html.includes('Low charge'));
  check(`${v}/nodata: announces the outage`, html.includes('No vehicle data') || html.includes('No data'),
    'a totally dark integration rendered without saying so');
}

// ---------------------------------------------------------------------------
// 3. Staleness. TRMNL holds the last image when a payload does not change, so
//    a screen that cannot age is indistinguishable from a live one.
// ---------------------------------------------------------------------------
{
  const full = view('full');

  const DATED = /Updated (Mon|Tue|Wed|Thu|Fri|Sat|Sun) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{1,2}:\d{2} (AM|PM)/;

  let html = await render(full, loadSample('charging'));
  check('fresh: no stale badge', !html.includes('No update') && !html.includes('No data'));

  // The one that matters most, and the least obvious. TRMNL drops an unchanged
  // payload before the render step, so if Home Assistant stops pushing the last
  // image stays on the wall untouched — it cannot age itself. A timestamp that
  // was relative when it was rendered stays relative forever. So even a
  // perfectly fresh render must be dated.
  check('fresh: timestamp is dated, so a frozen screen still says when', DATED.test(html),
    html.match(/Updated[^<]*/)?.[0]);
  check('fresh: never a bare clock time', !/Updated \d{1,2}:\d{2} (AM|PM)/.test(html),
    'a frozen copy of this screen would be indistinguishable from a live one');

  for (const v of ['full', 'half_horizontal']) {
    const h = await render(view(v), loadSample('charging'));
    check(`${v}: dated timestamp`, DATED.test(h), h.match(/Updated[^<]*/)?.[0]);
  }
  // The narrowest bar with a timestamp keeps the date and drops the weekday.
  const hv = await render(view('half_vertical'), loadSample('charging'));
  check('half_vertical: keeps a date in the narrow title bar',
    /(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{1,2}:\d{2} (AM|PM)/.test(hv));

  // Three days old: the reading itself may be true, but nothing on screen may
  // suggest it is current.
  html = await render(full, loadSample('stale'));
  check('stale: flags the age', html.includes('No update'), html.match(/No update[^<]*/)?.[0]);
  check('stale: timestamp still dated', DATED.test(html), html.match(/Updated[^<]*/)?.[0]);

  // Home Assistant is alive but the integration stopped reporting.
  html = await render(full, materialise({ ...loadSample('charging'), link_age_min: 180 }));
  check('dead feed: flags it even though the readings look recent', html.includes('No update 3h'),
    html.match(/No update[^<]*/)?.[0]);

  // No timestamp at all is not "just now".
  html = await render(full, materialise({ ...loadSample('charging'), updated_at: '' }));
  check('missing timestamp: does not render as fresh', html.includes('No data'));

  // Every view has somewhere to put it.
  for (const v of VIEWS) {
    const h = await render(view(v), loadSample('stale'));
    check(`${v}/stale: surfaces staleness`, h.includes('No update'));
  }
}

// ---------------------------------------------------------------------------
// 3a. A known state is not an unknown one. A vehicle can genuinely sit in a
//     service centre for days: "In service" is a fact the vehicle reported and
//     must keep its place at the top of the status line, while the age of the
//     readings is carried separately. Collapsing the two would be the same
//     mistake as collapsing unknown into zero.
// ---------------------------------------------------------------------------
{
  const inService = materialise({ ...loadSample('parked'), service_mode: true, _age_min: 1830 });
  for (const v of VIEWS) {
    const html = await render(view(v), inService);
    check(`${v}/in-service: keeps the reported state`, html.includes('In service'),
      'a real service-mode reading was suppressed or outranked');
    check(`${v}/in-service: still flags how old the readings are`, html.includes('No update'));
  }
  const html = await render(view('full'), inService);
  check('in-service: state and staleness are separate elements',
    /In service<\/span>[\s\S]{0,400}No update/.test(html));
  check('in-service: dates the reading rather than showing a bare clock time',
    /Updated (Mon|Tue|Wed|Thu|Fri|Sat|Sun) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2},/.test(html),
    html.match(/Updated[^<]*/)?.[0]);

  // Service mode outranks even a totally dark feed, because it is information.
  const darkButKnown = materialise({ ...loadSample('nodata'), service_mode: true });
  check('in-service: a reported state beats the no-data branch',
    (await render(view('full'), darkButKnown)).includes('In service'));
}

// ---------------------------------------------------------------------------
// 4. Partial data: the mixed case must show both, and neither may swallow the
//    other.
// ---------------------------------------------------------------------------
{
  const html = await render(view('full'), loadSample('partial'));
  check('partial: keeps the checks that did report', html.includes(`${CHECK}&nbsp;Locked`));
  check('partial: marks the checks that did not', html.includes(`${QUERY}12V`));
  check('partial: still raises a real fault', html.includes(`${CROSS}&nbsp;Closed`));
  check('partial: names the closure it does know about', html.includes('Tailgate'));
  check('partial: unknown cabin temperature is a dash, not 0',
    !/Cabin<\/span>[\s\S]{0,120}>0</.test(html));
  check('partial: draws the silhouette dashed', html.includes('stroke-dasharray="5 4"'),
    'the diagram asserted a closure state it does not have');

  // The smallest view has one line for health. A real fault wins that line, but
  // it must still admit how many checks it could not make.
  const q = await render(view('quadrant'), loadSample('partial'));
  check('quadrant/partial: reports the fault', q.includes('1 issue'));
  check('quadrant/partial: still admits the gaps', /1 issue[^<]*3\?/.test(q),
    q.match(/issue[^<]*/)?.[0]);
  check('quadrant/partial: never claims a clean bill', !q.includes('All good'));
}

// ---------------------------------------------------------------------------
// 5. The charging coordinator is dark upstream. Charge percentage, limit and
//    ETA come from vehicleState and survive; live kW does not. The screen must
//    drop the figure it lost instead of reporting it as zero.
// ---------------------------------------------------------------------------
{
  const html = await render(view('full'), loadSample('charging-degraded'));
  check('degraded charge: never prints 0 kW', !html.includes('0 kW'));
  check('degraded charge: keeps the ETA that still works', html.includes('1h 35m to limit'));
  check('degraded charge: still knows it is charging', html.includes('Charging'));
  check('degraded charge: no unknown-marker on the charge figure', headline(html) === '64');
}

// ---------------------------------------------------------------------------
// 6. Behaviour the design promises, on healthy data.
// ---------------------------------------------------------------------------
const full = (s) => render(view('full'), loadSample(s));

let html = await full('charging');
check('charging: status line names the place', html.includes('Charging at Home'));
check('charging: all checks pass', !html.includes(CROSS) && !html.includes(QUERY));
check('charging: no last-charge caliper while charging', !html.includes('class="charge-session"'));
check('charging: solid silhouette when everything reported', !html.includes('stroke-dasharray="5 4"'));

html = await full('after-charge');
check('after-charge: reports what the session added', html.includes('Last charge +40%'));
check('after-charge: draws the caliper', html.includes('class="charge-session"'));
check('after-charge: caliper starts at the session start', html.includes('left: 40%'));
check('after-charge: metered energy carries no tilde', html.includes('45 kWh') && !html.includes('~45'));

// An estimated figure must never be mistaken for a metered one.
html = await render(view('full'), materialise({
  ...loadSample('after-charge'), last_charge_kwh: 41.2, last_charge_kwh_est: true,
}));
check('estimated energy: marked with a tilde', html.includes('~41.2 kWh'));

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

// A driven-since payload must retire the last-charge panel even though the
// figures are still present.
html = await render(view('full'), materialise({ ...loadSample('after-charge'), moved_since_charge: true }));
check('driven since charge: retires the panel', !html.includes('class="charge-session"'));

// ---------------------------------------------------------------------------
// 7. Targeted regressions for each way the old build lied.
// ---------------------------------------------------------------------------
{
  const v = view('full');

  // A dead lock sensor used to read as "locked" — the most dangerous default
  // on the screen.
  let h = await render(v, materialise({ ...loadSample('parked'), locked: null }));
  check('regression: unknown lock is not "locked"', !h.includes(`${CHECK}&nbsp;Locked`));
  check('regression: unknown lock is not "unlocked" either', !h.includes(`${CROSS}&nbsp;Locked`));

  // Absent closures used to draw a sealed vehicle and tick "Closed".
  h = await render(v, materialise({
    ...loadSample('parked'),
    door_fl: null, door_fr: null, door_rl: null, door_rr: null,
    win_fl: null, win_fr: null, win_rl: null, win_rr: null,
    frunk: null, tonneau: null, tailgate: null, tunnel_l: null, tunnel_r: null,
  }));
  check('regression: unknown closures do not tick "Closed"', !h.includes(`${CHECK}&nbsp;Closed`));
  check('regression: unknown closures do not claim "All closed"', !h.includes('All closed'));

  // A 12V sensor reading nothing used to pass green forever because the entity
  // name was wrong; null must now be visible.
  h = await render(v, materialise({ ...loadSample('parked'), battery_12v_ok: null }));
  check('regression: unknown 12V shows as unknown', h.includes(`${QUERY}12V`));

  // Zero is a real, alarming reading and must survive as one.
  h = await render(v, materialise({ ...loadSample('parked'), soc: 0, charging: false }));
  check('regression: a genuine 0% still reads as 0%', headline(h) === '0');
  check('regression: a genuine 0% still warns', h.includes('Low charge'));

  // Tyres collapse worst-first: one flagged tyre outranks two silent ones.
  h = await render(v, materialise({ ...loadSample('parked'), tire_fl: false, tire_rr: null }));
  check('regression: a real flat outranks a silent sensor', h.includes(`${CROSS}&nbsp;Tires`));
}

// ---------------------------------------------------------------------------
// 8. Every sample must carry the documented contract and fit the webhook.
// ---------------------------------------------------------------------------
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
  'last_charge_kwh_est', 'last_charge_at', 'moved_since_charge',
  'updated_at', 'link_age_min',
];
for (const s of samples) {
  const data = loadSample(s);
  const missing = REQUIRED.filter((k) => !(k in data));
  check(`sample ${s}: complete contract`, missing.length === 0, `missing: ${missing.join(', ')}`);
  const size = JSON.stringify({ merge_variables: data }).length;
  check(`sample ${s}: fits the webhook limit`, size <= 2048, `${size} bytes`);
}

// At least one fixture must exercise each failure mode, or a future edit can
// delete the coverage without anything going red.
for (const required of ['nodata', 'partial', 'stale', 'charging-degraded']) {
  check(`fixture "${required}" exists`, samples.includes(required),
    'the failure-mode fixtures are the point of this suite');
}

console.log(`\n${assertions - failures}/${assertions} assertions passed`);
process.exit(failures ? 1 : 0);
