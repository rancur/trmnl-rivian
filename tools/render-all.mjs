#!/usr/bin/env node
// Renders every view against every sample, so a change can't quietly break a
// size or a state you weren't looking at.

import { spawn } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const VIEWS = ['full', 'half_horizontal', 'half_vertical', 'quadrant'];
const samples = readdirSync(`${root}/samples`)
  .filter((f) => f.endsWith('.json'))
  .map((f) => f.replace(/\.json$/, ''))
  .sort();

const run = (args) =>
  new Promise((ok, fail) => {
    const p = spawn('node', [`${root}/tools/render.mjs`, ...args], { stdio: 'inherit' });
    p.on('exit', (code) => (code === 0 ? ok() : fail(new Error(`exit ${code}: ${args.join(' ')}`))));
  });

let failures = 0;
for (const view of VIEWS) {
  for (const sample of samples) {
    try {
      await run(['--view', view, '--sample', sample]);
    } catch (e) {
      console.error(e.message);
      failures++;
    }
  }
}

console.log(`\n${VIEWS.length * samples.length - failures} rendered, ${failures} failed`);
process.exit(failures ? 1 : 0);
