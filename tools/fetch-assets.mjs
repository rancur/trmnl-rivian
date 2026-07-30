#!/usr/bin/env node
// Mirrors the TRMNL framework bundle into vendor/ so previews render offline
// and deterministically. vendor/ is gitignored; run this once after cloning.
//
//   node tools/fetch-assets.mjs

import { mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const FRAMEWORK = process.env.TRMNL_FRAMEWORK || '3.1.8';
const ORIGIN = 'https://trmnl.com';
const root = resolve(import.meta.dirname, '..', 'vendor');

async function save(path, { optional = false } = {}) {
  const dest = resolve(root, path.replace(/^\//, ''));
  if (existsSync(dest)) return 'cached';
  const res = await fetch(ORIGIN + path);
  if (!res.ok) {
    if (optional) return `skip ${res.status}`;
    throw new Error(`${path} -> ${res.status}`);
  }
  mkdirSync(dirname(dest), { recursive: true });
  writeFileSync(dest, Buffer.from(await res.arrayBuffer()));
  return 'ok';
}

// The stylesheet is served from a versioned path but references its assets at
// the origin root, so mirror it to /css/plugins.css and keep asset paths as-is.
const cssRes = await fetch(`${ORIGIN}/css/${FRAMEWORK}/plugins.css`);
if (!cssRes.ok) throw new Error(`plugins.css -> ${cssRes.status}`);
const css = await cssRes.text();
mkdirSync(resolve(root, 'css'), { recursive: true });
writeFileSync(resolve(root, 'css/plugins.css'), css);

const jsRes = await fetch(`${ORIGIN}/js/${FRAMEWORK}/plugins.js`);
if (!jsRes.ok) throw new Error(`plugins.js -> ${jsRes.status}`);
mkdirSync(resolve(root, 'js'), { recursive: true });
writeFileSync(resolve(root, 'js/plugins.js'), await jsRes.text());

const assets = [...new Set([...css.matchAll(/url\("([^"]+)"\)/g)].map((m) => m[1]))]
  .filter((u) => u.startsWith('/'));

// The title bar icon is referenced from markup rather than the stylesheet.
assets.push('/images/plugins/trmnl--render.svg');

console.log(`framework ${FRAMEWORK}: ${assets.length} assets`);

let done = 0;
let failed = 0;
const queue = [...assets];
await Promise.all(
  Array.from({ length: 24 }, async () => {
    while (queue.length) {
      const path = queue.pop();
      try {
        const r = await save(path, { optional: true });
        if (String(r).startsWith('skip')) failed++;
      } catch {
        failed++;
      }
      if (++done % 250 === 0) console.log(`  ${done}/${assets.length}`);
    }
  }),
);

console.log(`done: ${done - failed} saved, ${failed} unavailable -> vendor/`);
