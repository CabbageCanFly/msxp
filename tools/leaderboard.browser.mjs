// Same dependency-free Chromium/CDP approach as overlay.browser.mjs; no security flags.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync, openSync, closeSync} from "node:fs";
import {join, resolve} from "node:path";
import {setTimeout as delay} from "node:timers/promises";

const url = new URL(process.argv[2] || "http://127.0.0.1:8765/demo/leaderboard");
assert.equal(url.hostname, "127.0.0.1");
assert.equal(url.pathname, "/demo/leaderboard");
const output = resolve("artifacts/leaderboard-preview");
mkdirSync(output, {recursive: true});
const browser = process.env.BROWSER_BIN || [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium", "/usr/bin/google-chrome",
].find(existsSync);
assert.ok(browser, "Set BROWSER_BIN to an installed Chrome/Edge/Chromium executable");
const profile = mkdtempSync(join(output, "browser-profile-"));
const log = openSync(join(output, "browser.log"), "w");
const child = spawn(browser, ["--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--user-data-dir=${profile}`, "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "about:blank"],
  {stdio: ["ignore", "ignore", log], windowsHide: true});
let socket;
try {
  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; !existsSync(portFile) && i < 100; i++) {
    assert.equal(child.exitCode, null, `Browser exited; see ${output}/browser.log`);
    await delay(150);
  }
  assert.ok(existsSync(portFile), "Browser debugging port did not start");
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
      pending.set(id, message => {
        clearTimeout(timer);
        pending.delete(id);
        message.error ? reject(new Error(JSON.stringify(message.error))) : resolve(message.result);
      });
      socket.send(JSON.stringify({id, method, params}));
    });
  }
  async function evaluate(expression) {
    const result = await command("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true});
    assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Network.enable");
  await command("Log.enable");
  await command("Emulation.setDeviceMetricsOverride", {width: 1440, height: 1150, deviceScaleFactor: 1, mobile: false});
  await command("Page.navigate", {url: url.href});
  let loaded = false;
  for (let i = 0; i < 100 && !loaded; i++) {
    loaded = await evaluate('document.querySelectorAll(".entry").length === 8');
    if (!loaded) await delay(100);
  }
  assert.ok(loaded, "Demo did not render");
  assert.equal(await evaluate('document.querySelector(".entry").dataset.id'), "fern");
  assert.equal(await evaluate(`document.querySelectorAll('.rank[data-medal="1"]').length`), 1);
  const measurements = [];
  async function screenshot(name, width, height) {
    await command("Emulation.setDeviceMetricsOverride", {width, height, deviceScaleFactor: 1, mobile: width < 650});
    const measured = await evaluate(`(() => ({
      width: innerWidth, pageWidth: document.documentElement.scrollWidth,
      count: document.querySelectorAll('.entry').length,
      notice: document.querySelector('.demo-notice').textContent,
      states: [...document.querySelectorAll('.entry')].map(e => e.dataset.state),
      bars: [...document.querySelectorAll('.entry progress')].map(e => ({hidden: e.hidden, value: e.getAttribute('value')})),
      fit: [...document.querySelectorAll('.score-value, .exp-label')].every(e => e.scrollWidth <= e.clientWidth + 1),
      clipping: [...document.querySelectorAll('.character, .channel')].every(e => getComputedStyle(e).textOverflow === 'ellipsis'),
    }))()`);
    assert.ok(measured.pageWidth <= width, `${name}: horizontal overflow`);
    assert.equal(measured.count, 8);
    assert.ok(measured.fit && measured.clipping, `${name}: text does not fit`);
    assert.match(measured.notice, /SIMULATED DEMO/);
    assert.deepEqual([...new Set(measured.states)].sort(), ["insufficient", "missing", "offline", "stale", "tracking", "unknown"]);
    assert.equal(measured.bars.filter(bar => bar.hidden && bar.value === null).length, 2);
    const image = await command("Page.captureScreenshot", {format: "png", captureBeyondViewport: false});
    writeFileSync(join(output, `${name}.png`), Buffer.from(image.data, "base64"));
    measurements.push({name, ...measured});
  }
  await screenshot("desktop-pace-30m", 1440, 1150);
  for (const minutes of [5, 10, 15, 30]) {
    await evaluate(`document.querySelector('[data-window="${minutes}"]').click()`);
    assert.ok(await evaluate(`[...document.querySelectorAll('.score-label')].every(e => e.textContent === 'EXP/h · ${minutes}m')`));
  }
  await evaluate(`document.querySelector('[data-window="5"]').click()`);
  assert.equal(await evaluate('document.querySelector(".entry").dataset.id'), "moss");
  await screenshot("desktop-pace-5m", 1440, 1150);
  for (const metric of ["today", "level"]) {
    await evaluate(`document.querySelector('[data-metric="${metric}"]').click()`);
    assert.ok(await evaluate('[...document.querySelectorAll("[data-window]")].every(e => e.disabled)'));
    assert.equal(await evaluate('document.querySelector(".entry").dataset.id'), "fern");
    await screenshot(`desktop-${metric}`, 1440, 1150);
  }
  await evaluate(`document.querySelector('[data-metric="pace"]').click()`);
  await screenshot("mobile-pace", 390, 1500);
  await screenshot("small-mobile-pace", 320, 1650);
  await evaluate('DEMO[0].character = "VeryLongSyntheticCharacterName".repeat(3); DEMO[0].channel = "very_long_demo_channel"; DEMO[0].exp = Number.MAX_SAFE_INTEGER; renderLeaderboard()');
  await screenshot("mobile-long-values", 390, 1500);
  assert.ok(requests.every(request => new URL(request).origin === url.origin), "Unexpected external request");
  assert.deepEqual(failures, [], "Browser/CSP errors");
  writeFileSync(join(output, "measurements.json"), JSON.stringify({browser, measurements, requests}, null, 2));
  console.log(`Passed controls and ${measurements.length} responsive screenshots. ${output}`);
} finally {
  socket?.close();
  child.kill();
  closeSync(log);
}
