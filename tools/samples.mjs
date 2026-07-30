// Loading a sample payload.
//
// Samples that describe freshness do it in relative terms — `_age_min` rather
// than a literal `updated_at` — and this module turns that into a real
// timestamp at load time. Without it every fixture in the repo would drift into
// looking stale as the months passed, and the previews would slowly fill up
// with "No update 412d" badges that say nothing about the plugin.
//
// Keys beginning with an underscore are directives for this loader and are
// stripped before anything reaches Liquid.

import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '..');
const SAMPLES = `${ROOT}/samples`;

// The format Home Assistant emits: ISO 8601 with a numeric offset, no colon.
function isoWithOffset(date) {
  const pad = (n, w = 2) => String(Math.abs(n)).padStart(w, '0');
  const off = -date.getTimezoneOffset();
  const sign = off < 0 ? '-' : '+';
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
    `${sign}${pad(Math.floor(Math.abs(off) / 60))}${pad(Math.abs(off) % 60)}`
  );
}

const ago = (now, minutes) => isoWithOffset(new Date(now.getTime() - minutes * 60_000));

export function materialise(raw, now = new Date()) {
  const out = { ...raw };
  if ('_age_min' in out) out.updated_at = ago(now, out._age_min);
  if ('_last_charge_age_min' in out) out.last_charge_at = ago(now, out._last_charge_age_min);
  for (const key of Object.keys(out)) if (key.startsWith('_')) delete out[key];
  return out;
}

export function sampleNames() {
  return readdirSync(SAMPLES)
    .filter((f) => f.endsWith('.json'))
    .map((f) => f.replace(/\.json$/, ''))
    .sort();
}

export function loadSample(name, now = new Date()) {
  return materialise(JSON.parse(readFileSync(`${SAMPLES}/${name}.json`, 'utf8')), now);
}
