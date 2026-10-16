// Optional Chromium check: start the local server, then run node tools/overlay.browser.mjs URL.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync, openSync, closeSync} from "node:fs";
import {join, resolve} from "node:path";
import {setTimeout as delay} from "node:timers/promises";

const url = new URL(process.argv[2] || "http://127.0.0.1:8765/overlay/demo");
assert.equal(url.hostname, "127.0.0.1", "Only the local overlay is tested");
assert.match(url.pathname, /^\/overlay\/[A-Za-z0-9_]{1,25}$/);
const output = resolve("artifacts/overlay-redesign");
mkdirSync(output, {recursive: true});
const browser = process.env.BROWSER_BIN || [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/chromium", "/usr/bin/google-chrome",
].find(existsSync);
assert.ok(browser, "Set BROWSER_BIN to an installed Chromium browser");
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
  const pending = new Map();
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.id) pending.get(message.id)?.(message);
  };
  function command(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`Timeout: ${method}`)); }, 8000);
      pending.set(id, message => {
        clearTimeout(timeout);
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
  await command("Emulation.setDeviceMetricsOverride", {width: 500, height: 160, deviceScaleFactor: 1, mobile: false});
  await command("Emulation.setDefaultBackgroundColorOverride", {color: {r: 0, g: 0, b: 0, a: 0}});
  await command("Page.navigate", {url: url.href});
  let loaded = false;
  for (let i = 0; i < 100 && !loaded; i++) {
    loaded = await evaluate('typeof snapshot !== "undefined" && !!snapshot?.last_trusted');
    if (!loaded) await delay(100);
  }
  assert.ok(loaded, "Use a database/channel containing a trusted reading");
  const actual = await (await fetch(new URL(`/api/streams/${url.pathname.split("/")[2]}/state`, url))).json();
  assert.equal(await evaluate('document.getElementById("exp").textContent'), new Intl.NumberFormat("en-US").format(actual.last_trusted.current_exp));
  await delay(2300);
  assert.ok(await evaluate('performance.getEntriesByType("resource").filter(r => r.name.includes("/api/streams/")).length >= 2'), "Real two-second polling did not run");
  // Freeze requests for controlled presentation cases; the database is never changed.
  await evaluate('globalThis.fetch = () => new Promise(() => {}); globalThis.setTimeout = () => 0');
  const base = {...actual, status: "tracking", reason: "same_level_gain", age_seconds: 5, stale: false, continuity_broken: false};
  const cases = [
    ["tracking", base, null, ""],
    ["brief-ocr", {...base, status: "paused", reason: "cannot_parse_exp"}, null, ""],
    ["stale", {...base, status: "paused", reason: "stale", stale: true, age_seconds: 121}, null, "Updates delayed"],
    ["offline", {...base, status: "offline"}, null, "Offline"],
    ["offline-empty", {...base, status: "offline", last_trusted: null}, null, "Offline"],
    ["paused", {...base, status: "paused", reason: "explicit_pause", continuity_broken: true}, null, "Paused"],
    ["review", {...base, status: "ambiguous"}, null, "Updates delayed"],
    ["api-failure", base, "api_unavailable", "Updates delayed"],
    ["unconfigured", {...base, selected_character: null, session: null, last_trusted: null}, null, "Waiting for EXP"],
    ["waiting", {...base, status: "waiting", last_trusted: null}, null, "Waiting for EXP"],
    ["previous-session", {...base, status: "waiting", session: {...base.session, id: -1}}, null, "Waiting for EXP"],
    ["long-values", {...base, selected_character: {...base.selected_character, label: "WhimsicalVeryLongCharacterName".repeat(4)},
      last_trusted: {...base.last_trusted, current_exp: Number.MAX_SAFE_INTEGER, percentage_bp: 9999},
      observed_session_exp: Number.MAX_SAFE_INTEGER}, null, ""],
    ["zero", {...base, last_trusted: {...base.last_trusted, current_exp: 0, percentage_bp: 0}}, null, ""],
  ];
  const measurements = [];
  for (const [name, state, error, label] of cases) {
    await evaluate(`snapshot = ${JSON.stringify(state)}; receivedAt = performance.now(); requestError = ${JSON.stringify(error)}; render()`);
    const measured = await evaluate(`(() => {
      const card = document.getElementById("card"), rect = card.getBoundingClientRect(), style = getComputedStyle(card);
      return {width: rect.width, height: rect.height, x: rect.x, y: rect.y,
        pageWidth: document.documentElement.scrollWidth, pageHeight: document.documentElement.scrollHeight,
        background: style.backgroundImage, border: style.borderColor,
        transparent: [document.body, document.documentElement].every(e => getComputedStyle(e).backgroundColor === "rgba(0, 0, 0, 0)"),
        status: document.getElementById("status").textContent,
        fits: ["exp", "percentage", "session-exp", "status", "age"].every(id => {const e = document.getElementById(id); return e.scrollWidth <= e.clientWidth + 1;}),
        nameEllipsis: getComputedStyle(document.getElementById("character")).textOverflow};
    })()`);
    assert.deepEqual([measured.width, measured.height, measured.x, measured.y], [490, 150, 5, 5], name);
    assert.ok(measured.pageWidth <= 500 && measured.pageHeight <= 160, `${name}: page overflow`);
    assert.equal(measured.status, label, name);
    assert.ok(measured.fits && measured.transparent, `${name}: text overflow or opaque page`);
    assert.equal(measured.nameEllipsis, "ellipsis", name);
    if (measurements.length) {
      assert.equal(measured.background, measurements[0].background, name);
      assert.equal(measured.border, measurements[0].border, name);
    }
    const screenshot = await command("Page.captureScreenshot", {format: "png", captureBeyondViewport: false});
    writeFileSync(join(output, `${name}.png`), Buffer.from(screenshot.data, "base64"));
    measurements.push({name, ...measured});
  }
  writeFileSync(join(output, "measurements.json"), JSON.stringify(measurements, null, 2));
  console.log(`Verified real API polling and ${measurements.length} fixed-size states. Screenshots: ${output}`);
} finally {
  socket?.close();
  child.kill();
  closeSync(log);
}
