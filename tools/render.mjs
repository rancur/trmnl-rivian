#!/usr/bin/env node
// Renders a TRMNL plugin view locally at true device size.
//
// Liquid is rendered by TRMNL's own public /api/markup endpoint, so the output
// matches what the real markup editor produces (custom filters included).
// The page is then screenshotted in Chromium against the real plugins.css.

import { readFileSync, writeFileSync, mkdirSync, existsSync, createReadStream } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, resolve, extname, normalize } from 'node:path';
import { chromium } from 'playwright';

const MARKUP_API = 'https://trmnl.com/api/markup';

// Device dimensions as published by TRMNL's /api/models.
const DEVICES = {
  og: { w: 800, h: 480, cls: 'screen--og screen--1bit' },
  v2: { w: 1040, h: 780, cls: 'screen--v2 screen--4bit' },
};

// A view's wrapper markup. Anything smaller than full must sit inside a mashup.
const VIEWS = {
  full: (inner) => `<div class="view view--full">${inner}</div>`,
  half_horizontal: (inner) => `
    <div class="mashup mashup--1Tx1B">
      <div class="view view--half_horizontal">${inner}</div>
      <div class="view view--half_horizontal"><div class="layout"></div></div>
    </div>`,
  half_vertical: (inner) => `
    <div class="mashup mashup--1Lx1R">
      <div class="view view--half_vertical">${inner}</div>
      <div class="view view--half_vertical"><div class="layout"></div></div>
    </div>`,
  quadrant: (inner) => `
    <div class="mashup mashup--2x2">
      <div class="view view--quadrant">${inner}</div>
      <div class="view view--quadrant"><div class="layout"></div></div>
      <div class="view view--quadrant"><div class="layout"></div></div>
      <div class="view view--quadrant"><div class="layout"></div></div>
    </div>`,
};

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
}

async function renderLiquid(markup, variables) {
  const res = await fetch(MARKUP_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ markup, variables }),
  });
  if (!res.ok) {
    throw new Error(`markup API ${res.status}: ${await res.text()}`);
  }
  const { data } = await res.json();
  return data;
}

// Serves vendor/ at the document root so the stylesheet's absolute /fonts and
// /images references resolve exactly as they do on trmnl.com.
const MIME = {
  '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.ttf': 'font/ttf', '.woff': 'font/woff',
  '.woff2': 'font/woff2', '.html': 'text/html',
};

function serve(dir) {
  const server = createServer((req, res) => {
    const path = normalize(decodeURIComponent(req.url.split('?')[0])).replace(/^(\.\.[/\\])+/, '');
    const file = resolve(dir, '.' + path);
    if (!file.startsWith(dir) || !existsSync(file)) {
      res.writeHead(404).end('not found');
      return;
    }
    res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream' });
    createReadStream(file).pipe(res);
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok(server)));
}

function page({ body, device, dark }) {
  const d = DEVICES[device];
  return `<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <link rel="stylesheet" href="/css/plugins.css">
    <script src="/js/plugins.js"></script>
    <style>html,body{margin:0;padding:0;background:#fff}</style>
  </head>
  <body class="environment trmnl">
    <div class="screen ${d.cls}${dark ? ' screen--dark-mode' : ''}">
      ${body}
    </div>
  </body>
</html>`;
}

const view = arg('view', 'full');
const sample = arg('sample', 'charging');
const device = arg('device', 'og');
const dark = process.argv.includes('--dark');
const out = arg('out', `preview/${view}-${sample}.png`);

if (!VIEWS[view]) throw new Error(`unknown view: ${view}`);
if (!DEVICES[device]) throw new Error(`unknown device: ${device}`);

const root = resolve(import.meta.dirname, '..');
const shared = readFileSync(`${root}/plugin/shared.liquid`, 'utf8');
const template = readFileSync(`${root}/plugin/${view}.liquid`, 'utf8');
const variables = JSON.parse(readFileSync(`${root}/samples/${sample}.json`, 'utf8'));

const rendered = await renderLiquid(shared + '\n' + template, variables);

// Surface Liquid errors instead of silently screenshotting a broken screen.
const liquidError = rendered.match(/Liquid (error|syntax error)[^<]*/i);
if (liquidError) {
  console.error(`\n  Liquid error in ${view}.liquid:\n  ${liquidError[0]}\n`);
  process.exit(1);
}

const vendor = resolve(root, 'vendor');
if (!existsSync(vendor)) {
  console.error('vendor/ is missing — run: node tools/fetch-assets.mjs');
  process.exit(1);
}

const html = page({ body: VIEWS[view](rendered), device, dark });
mkdirSync(dirname(resolve(root, out)), { recursive: true });
writeFileSync(resolve(vendor, '_preview.html'), html);

const server = await serve(vendor);
const origin = `http://127.0.0.1:${server.address().port}`;

// The image ships its own Chromium build; don't depend on the version the
// installed playwright package happens to expect. Everything is served from
// loopback, so no proxy is involved.
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
});
const ctx = await browser.newContext({
  viewport: { width: DEVICES[device].w, height: DEVICES[device].h },
  deviceScaleFactor: 1,
});
const p = await ctx.newPage();
const errors = [];
p.on('pageerror', (e) => errors.push(e.message));
p.on('requestfailed', (r) => errors.push(`${r.failure()?.errorText} ${r.url()}`));
await p.goto(`${origin}/_preview.html`, { waitUntil: 'networkidle' });
await p.evaluate(() => document.fonts.ready);
await p.waitForTimeout(400); // let the framework runtime finish fit/clamp passes
await p.screenshot({ path: resolve(root, out) });
await browser.close();
server.close();

if (errors.length) console.error('page errors:', errors);
console.log(`${out}  (${view} / ${sample} / ${device}${dark ? ' / dark' : ''})`);
