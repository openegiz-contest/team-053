// Screenshots of the live Stand / Grafana through the Chrome DevTools Protocol.
// Usage: node capture.mjs job.json
// job = { "url": "...", "width": 1920, "height": 1600, "scale": 2, "wait": 12000,
//         "steps": [ { "click": "css selector" | "eval": "js", "wait": 2000 } ],
//         "shots": [ { "out": "img/x.png", "selector": "#advisor" | "clip": [x, y, w, h], "pad": 0 } ] }
// Needs Node 22+ (global WebSocket and fetch) and Google Chrome. Does not change the Stand.
import { spawn } from 'node:child_process';
import { readFileSync, mkdtempSync, rmSync } from 'node:fs';
import { writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME = process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9300 + Math.floor(Math.random() * 500);
const job = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(join(tmpdir(), 'cdp-'));
const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--enable-unsafe-swiftshader', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  `--window-size=${job.width || 1920},${job.height || 1080}`, 'about:blank',
], { stdio: 'ignore' });

let ws; let seq = 0; const pending = new Map();
function send(method, params = {}) {
  const id = ++seq;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject, method }));
}
async function evaluate(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.exceptionDetails) throw new Error(`eval failed: ${expr}: ${JSON.stringify(r.exceptionDetails).slice(0, 300)}`);
  return r.result.value;
}

try {
  let targets = [];
  for (let i = 0; i < 50 && !targets.length; i++) {
    await sleep(200);
    try { targets = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).filter((t) => t.type === 'page'); } catch { /* not up yet */ }
  }
  if (!targets.length) throw new Error('Chrome did not start');
  ws = new WebSocket(targets[0].webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      if (m.error) p.reject(new Error(`${p.method}: ${m.error.message}`)); else p.resolve(m.result);
    }
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {
    width: job.width || 1920, height: job.height || 1080, deviceScaleFactor: job.scale || 1, mobile: false,
  });
  await send('Page.navigate', { url: job.url });
  await sleep(job.wait ?? 10000);
  for (const step of job.steps || []) {
    if (step.click) await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(step.click)}); if (!e) throw new Error('no ' + ${JSON.stringify(step.click)}); e.click(); return true; })()`);
    if (step.eval) await evaluate(step.eval);
    await sleep(step.wait ?? 1500);
  }
  for (const shot of job.shots) {
    let clip;
    if (shot.selector) {
      const r = await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(shot.selector)}); if (!e) return null; const b = e.getBoundingClientRect(); return [b.left + scrollX, b.top + scrollY, b.width, b.height]; })()`);
      if (!r) throw new Error(`selector not found: ${shot.selector}`);
      clip = r;
    } else if (shot.clip) {
      clip = shot.clip;
    } else {
      clip = [0, 0, job.width || 1920, job.height || 1080];
    }
    const pad = shot.pad || 0;
    const [x, y, w, h] = [Math.max(0, clip[0] - pad), Math.max(0, clip[1] - pad), clip[2] + 2 * pad, clip[3] + 2 * pad];
    const shotRes = await send('Page.captureScreenshot', {
      format: 'png', clip: { x, y, width: w, height: h, scale: 1 }, captureBeyondViewport: false,
    });
    await writeFile(shot.out, Buffer.from(shotRes.data, 'base64'));
    console.log(`${shot.out} ${Math.round(w)}x${Math.round(h)} css px at (${Math.round(x)}, ${Math.round(y)})`);
  }
} finally {
  try { ws && ws.close(); } catch { /* ignore */ }
  chrome.kill();
  await sleep(500);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* Chrome may still hold files */ }
}
