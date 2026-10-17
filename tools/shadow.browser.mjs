// Dependency-free localhost Chromium check, following the existing overlay harness.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync, openSync, closeSync} from "node:fs";
import {join, resolve, sep} from "node:path";
import {setTimeout as delay} from "node:timers/promises";

const url = new URL(process.argv[2] || "http://127.0.0.1:8765/dev/shadow");
assert.equal(url.hostname, "127.0.0.1");
const dashboard = /^\/dashboard\/([A-Za-z0-9_]{1,25})$/.exec(url.pathname);
assert.ok(url.pathname === "/dev/shadow" || dashboard);
const endpoint = dashboard ? `/dev/api/streams/${dashboard[1]}/diagnostics` : '/dev/api/shadow';
const expected = await (await fetch(new URL(endpoint, url))).json();
assert.ok(expected.observations.length > 0, "Use an opt-in server with a completed shadow log");
const output = resolve(process.argv[3] || "artifacts/shadow-view");
assert.ok(["artifacts", "private"].some(root => output.startsWith(resolve(root) + sep)), "Screenshots must stay private/ or artifacts/");
mkdirSync(output, {recursive: true});
const browser = process.env.BROWSER_BIN || ["C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium"].find(existsSync);
assert.ok(browser, "Set BROWSER_BIN to an installed Chromium browser");
const profile = mkdtempSync(join(output, "browser-profile-"));
const log = openSync(join(output, "browser.log"), "w");
const child = spawn(browser, ["--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--user-data-dir=${profile}`, "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"],
  {stdio: ["ignore", "ignore", log], windowsHide: true});
let socket;
try {
  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; !existsSync(portFile) && i < 100; i++) { assert.equal(child.exitCode, null); await delay(150); }
  assert.ok(existsSync(portFile));
  const port = readFileSync(portFile, "utf8").split("\n")[0];
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(page => page.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  const pending = new Map(), failures = [], requests = [];
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) pending.get(message.id)?.(message);
    if (message.method === "Runtime.exceptionThrown") failures.push(message.params.exceptionDetails);
    if (message.method === "Log.entryAdded" && message.params.entry.level === "error") failures.push(message.params.entry);
    if (message.method === "Network.requestWillBeSent") requests.push(message.params.request.url);
  };
  function command(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timeout: ${method}`)); }, 8000);
      pending.set(id, message => { clearTimeout(timer); pending.delete(id);
        message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result); });
      socket.send(JSON.stringify({id, method, params}));
    });
  }
  async function evaluate(expression) {
    const result = await command("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true});
    assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  for (const domain of ["Page", "Runtime", "Network", "Log", "Performance"]) await command(`${domain}.enable`);
  await command("Emulation.setDeviceMetricsOverride", {width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await command("Page.navigate", {url:url.href});
  let loaded = false;
  for (let i = 0; i < 100 && !loaded; i++) {
    loaded = await evaluate(`document.querySelectorAll('#readings tr').length === ${expected.observations.length}`);
    if (!loaded) await delay(100);
  }
  assert.ok(loaded);
  if (dashboard) {
    assert.equal(await evaluate('document.getElementById("persisted").hidden'), false);
    assert.equal(await evaluate('document.getElementById("assignment").textContent'), expected.selected_character.label);
    assert.match(await evaluate('document.getElementById("trusted-summary").textContent'), /no trusted session observations|Separate trusted engine/);
  }
  const displayed = await evaluate(`[...document.querySelectorAll('#readings tr')].map(row => ({
    raw:row.children[2].querySelector('code').textContent,
    pair:row.children[2].querySelector('span').textContent,
    visual:row.children[3].firstChild.textContent,
    nearest:row.children[4].textContent, truncation:row.children[5].textContent}))`);
  expected.observations.forEach((row, index) => {
    assert.equal(displayed[index].raw, row.raw_text ?? "—");
    assert.equal(displayed[index].visual, String(row.visual_level ?? "—"));
    if (row.candidate) assert.equal(displayed[index].pair, `${new Intl.NumberFormat('en-US').format(BigInt(row.candidate.exp))} EXP [${row.candidate.percentage}%]`);
    if (row.percentage_only_candidate) assert.match(displayed[index].pair, /percentage only.*EXP unavailable/);
    assert.equal(displayed[index].nearest, `${row.hypotheses.nearest_half_up.status} · ${row.hypotheses.nearest_half_up.levels.join(', ') || 'no candidates'}`);
  });
  await delay(2300);
  assert.ok(await evaluate(`performance.getEntriesByType("resource").filter(r => r.name.includes(${JSON.stringify(endpoint)})).length >= 2`));
  const apiMilliseconds = await evaluate(`performance.getEntriesByType("resource").filter(r => r.name.includes(${JSON.stringify(endpoint)})).map(r => r.duration)`);
  const metrics = (await command("Performance.getMetrics")).metrics;
  await evaluate('globalThis.fetch = () => new Promise(() => {})');
  const measurements = [];
  async function screenshot(name, width, height) {
    await command("Emulation.setDeviceMetricsOverride", {width,height,deviceScaleFactor:1,mobile:width<650});
    const measured = await evaluate(`({pageWidth:document.documentElement.scrollWidth, width:innerWidth,
      rows:document.querySelectorAll('#readings tr').length,
      candidates:document.querySelectorAll('#timeline .sample').length,
      gaps:document.querySelectorAll('#timeline .gap').length,
      rejected:document.querySelectorAll('#timeline .rejected').length,
      stale:document.querySelectorAll('#timeline .stale').length,
      percentageCandidates:document.querySelectorAll('#percentage-timeline .sample').length,
      notice:document.getElementById('notice').textContent})`);
    assert.ok(measured.pageWidth <= width, `${name}: page overflow`);
    const shot = await command("Page.captureScreenshot", {format:"png", captureBeyondViewport:false});
    writeFileSync(join(output, `${name}.png`), Buffer.from(shot.data, "base64"));
    measurements.push({name, ...measured});
  }
  await screenshot("test-shadow-desktop", 1440, 2000);
  await screenshot("test-shadow-mobile", 390, 1200);
  await evaluate('globalThis.originalSnapshot = snapshot');
  await evaluate('snapshot = {...originalSnapshot,observations:[],log_status:"missing",age_seconds:null,stale:false,channel:null}; render()');
  await screenshot("missing-log", 1440, 900);
  await evaluate('snapshot = {...originalSnapshot,incomplete_tail:true}; render()');
  await screenshot("incomplete-tail", 1440, 1400);
  const rows = [1,2,5].map((index, position) => ({...expected.observations[0], index,
    channel:"synthetic_review", received_at:new Date(Date.UTC(2026,0,1)+index*15000).toISOString(),
    status:position===1?"capture_failed":position===2?"stale_local_frame":"diagnostic_pair",
    fresh_at_capture:position===0, candidate:position===1?null:{exp:"100",percentage:"25.00"}, raw_text:position===1?null:"100[25.00%]"}));
  await evaluate(`snapshot = {...originalSnapshot,channel:"synthetic_review",observations:${JSON.stringify(rows)},interval_seconds:15}; render()`);
  await screenshot("synthetic-gaps-failures-stale", 1440, 1000);
  const gaps = measurements.at(-1);
  assert.deepEqual([gaps.candidates,gaps.rejected,gaps.stale,gaps.gaps], [1,1,1,1]);
  await evaluate('snapshot=originalSnapshot; requestError=true; render()');
  await screenshot("cached-api-failure", 1440, 1400);
  assert.ok(requests.every(request => new URL(request).origin === url.origin));
  assert.deepEqual(failures, []);
  writeFileSync(join(output,"browser-measurements.json"),JSON.stringify({measurements,requests,
    observations:expected.observations.length,apiMilliseconds,
    jsHeapUsedBytes:metrics.find(metric => metric.name === 'JSHeapUsedSize')?.value},null,2));
  console.log(`Verified ${expected.observations.length} saved attempts, repeated polling and ${measurements.length} screenshots. ${output}`);
} finally {
  socket?.close(); child.kill(); closeSync(log);
}
