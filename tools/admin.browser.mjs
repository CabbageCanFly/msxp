// Real browser regression, no npm dependencies. Only a newly generated synthetic DB is opened.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {parseArgs} from 'node:util';
import {setTimeout as delay} from 'node:timers/promises';

const {values: args} = parseArgs({options: {python: {type: 'string', default: 'python'},
  chrome: {type: 'string', default: process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe'},
  output: {type: 'string', default: `private/admin-browser-${Date.now()}`}}});
const output = resolve(args.output); mkdirSync(output, {recursive: true});
assert.ok(!existsSync(join(output, 'synthetic.sqlite3')), 'Choose a new output directory; existing databases are never opened.');
const server = spawn(args.python, ['tools/admin_browser_fixture.py', '--output', output], {
  env: {...process.env, PYTHONPATH: resolve('src'), PYTHONDONTWRITEBYTECODE: '1'},
  windowsHide: true, stdio: ['ignore', 'pipe', 'inherit']});
let browser, info, port;
const sockets = [], errors = [], requests = [];
async function tab(origin, path, width = 1280, height = 1000) {
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, {method: 'PUT'})).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl); sockets.push(ws); await once(ws, 'open');
  let seq = 0; const pending = new Map();
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id) pending.get(m.id)?.(m);
    if (m.method === 'Runtime.exceptionThrown' || m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errors.push(m.params);
    if (m.method === 'Network.requestWillBeSent') requests.push(m.params.request.url);
  };
  function command(method, params = {}) {
    return new Promise((ok, no) => {
      const id = ++seq, timer = setTimeout(() => no(Error(method+' timeout')), 30000);
      pending.set(id, m => {clearTimeout(timer); pending.delete(id); m.error ? no(Error(JSON.stringify(m.error))) : ok(m.result);});
      ws.send(JSON.stringify({id, method, params}));
    });
  }
  async function evaluate(expression) {
    const r = await command('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
    assert.ok(!r.exceptionDetails, JSON.stringify(r.exceptionDetails)); return r.result.value;
  }
  async function wait(expression) {
    for (let i = 0; i < 200; i++) {if (await evaluate(expression)) return; await delay(100);}
    assert.fail('Timed out: '+expression+'; status: '+await evaluate('document.getElementById("status")?.textContent'));
  }
  async function fill(id, value) {
    await evaluate(`(() => {const n=document.getElementById(${JSON.stringify(id)}); n.value=${JSON.stringify(String(value))}; n.dispatchEvent(new Event('input',{bubbles:true})); n.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  }
  async function click(id) {await evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);}
  for (const name of ['Page', 'Runtime', 'Network', 'Log']) await command(name+'.enable');
  await command('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: width === 390});
  await command('Page.navigate', {url: origin+path});
  return {command, evaluate, wait, fill, click};
}
async function screenshot(page, name) {
  assert.ok(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'));
  const shot = await page.command('Page.captureScreenshot', {format: 'png', captureBeyondViewport: false});
  writeFileSync(join(output, name+'.png'), Buffer.from(shot.data, 'base64'));
}
try {
  info = await new Promise((ok, no) => {
    let text = ''; const timer = setTimeout(() => no(Error('fixture startup timeout')), 15000);
    server.on('error', no); server.once('exit', code => no(Error('fixture exited: '+code)));
    server.stdout.on('data', chunk => {text += chunk; if (text.includes('\n')) {clearTimeout(timer); ok(JSON.parse(text.split('\n')[0]));}});
  });
  const profile = mkdtempSync(join(output, 'chrome-'));
  browser = spawn(args.chrome, ['--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    `--user-data-dir=${profile}`, '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0', 'about:blank'],
    {windowsHide: true, stdio: 'ignore'});
  browser.on('error', e => errors.push(String(e)));
  for (let i = 0; i < 150 && !existsSync(join(profile, 'DevToolsActivePort')); i++) await delay(100);
  port = readFileSync(join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0];
  const admin = await tab(info.admin, '/');
  await admin.wait("typeof scope!=='undefined' && scope?.character?.label==='Tricia' && !loading");
  assert.equal(await admin.evaluate("document.getElementById('use-now').checked"), false);
  assert.equal(await admin.evaluate("document.getElementById('effective-at').value"), '');
  const board = await tab(info.public, '/'), detail = await tab(info.public, '/stream/alpha');
  const overlay = await tab(info.public, '/live/overlay/alpha', 500, 160);
  for (const p of [board, detail, overlay]) await p.wait("typeof data!=='undefined' && (data?.player?.reading || data?.players?.length)");
  const originalGain = await detail.evaluate('data.tracked_history.tracked_exp.approximate');
  async function inspect() {return admin.evaluate("api('/api/inspect?channel=alpha')");}
  async function preview() {
    await admin.click('preview-button');
    await admin.wait('previewId!==null && !busy');
    return admin.evaluate("JSON.parse(document.getElementById('preview-audit').textContent)");
  }
  async function save() {
    await admin.click('save'); await admin.wait("!busy && document.getElementById('status').textContent.startsWith('Saved ')");
    return admin.evaluate("JSON.parse(document.getElementById('saved-audit').textContent)");
  }
  async function historyAction(id, label) {
    await admin.evaluate(`(() => {const row=[...document.querySelectorAll('#history article')].find(n=>n.querySelector('h3')?.textContent.startsWith('#${id} ·')); [...row.querySelectorAll('button')].find(n=>n.textContent===${JSON.stringify(label)}).click();})()`);
  }
  // Historical correction uses the original identity/time in a closed session.
  await admin.fill('session', info.old_session); await admin.wait(`!loading && scope?.session?.id===${info.old_session}`);
  await admin.evaluate("(() => {const row=[...document.querySelectorAll('#readings article')].find(n=>n.querySelector('h3').textContent.startsWith('diagnostic old:2 ·')); row.querySelector('button').click();})()");
  assert.equal(await admin.evaluate("document.getElementById('target-id').value"), 'old:2');
  assert.equal(await admin.evaluate("document.getElementById('effective-at').value"), info.stamps.old[1]);
  await admin.fill('level', 49); await admin.fill('exp', '12345'); await admin.fill('percentage', '2.10'); await admin.fill('reason', 'Historical level correction');
  let p = await preview();
  assert.equal((await inspect()).corrections.length, 0);
  assert.equal(p.reading.level.value, 49); await screenshot(admin, 'historical-preview');
  const point = (await save()).event;
  await detail.wait(`data?.history?.some(p=>p.reading?.provenance?.id===${point.id})`);
  assert.equal(await detail.evaluate('data.player.display_level.value'), 50);
  assert.equal(await admin.evaluate("scope.readings.find(r=>r.identity==='old:2').original_level"), 50);
  assert.equal(await admin.evaluate("scope.readings.find(r=>r.identity==='old:2').presentation.level.value"), 49);
  await historyAction(point.id, 'Amend'); await admin.fill('level', 48); await admin.fill('reason', 'Fix my entry');
  await preview(); const amended = (await save()).event;
  assert.equal(amended.replaces_id, point.id);
  await historyAction(amended.id, 'Undo'); await admin.fill('reason', 'Restore original historical OCR'); await preview(); await save();
  assert.equal(await admin.evaluate("scope.readings.find(r=>r.identity==='old:2').presentation.evidence"), 'strict_full');
  // Browser validation and server errors, then create a numerical-only baseline.
  await admin.fill('session', ''); await admin.wait(`!loading && scope?.session?.id===${info.session}`);
  await admin.fill('action', 'set'); await admin.fill('level', 49); await admin.fill('exp', '1000'); await admin.fill('percentage', '');
  await admin.fill('effective-at', 'missing timezone'); await admin.click('preview-button');
  await admin.wait("!busy && document.getElementById('status').classList.contains('error')");
  assert.equal((await inspect()).corrections.length, 3);
  await admin.click('use-now');
  p = await preview(); assert.equal(p.reading.exp, '1000'); assert.ok(p.reading.estimated_percentage);
  const frozen = p.event.effective_at;
  // Editing a field cancels the existing preview and disables confirmation.
  await admin.fill('exp', '1001'); assert.equal(await admin.evaluate('previewId'), null);
  await admin.fill('exp', '1000'); p = await preview();
  const baseline = (await save()).event;
  assert.equal(baseline.effective_at, p.event.effective_at); assert.ok(frozen <= baseline.effective_at);
  for (const page of [detail, overlay]) await page.wait(`data?.player?.manual_correction?.id===${baseline.id}`);
  assert.equal(await overlay.evaluate('document.getElementById("level").textContent'), 'Lv. 49');
  assert.match(await overlay.evaluate('document.getElementById("percentage").textContent'), /^~/);
  await historyAction(baseline.id, 'Amend'); await admin.fill('level', 48); await admin.fill('reason', 'Wrong baseline level');
  await preview(); const baselineAmendment = (await save()).event;
  await overlay.wait(`data?.player?.manual_correction?.id===${baselineAmendment.id}`);
  await historyAction(baselineAmendment.id, 'Undo'); await admin.fill('reason', 'Remove seeded baseline'); await preview(); await save();
  await overlay.wait("data?.player?.reading?.evidence==='strict_full'");
  // Rename preview does not write; confirmation keeps identity, updates public caches.
  await admin.fill('action', 'rename'); await admin.fill('new-name', 'Tricia renamed'); await admin.fill('reason', 'Replace placeholder');
  await preview(); assert.equal((await inspect()).character.label, 'Tricia');
  const renamed = (await save()).event; assert.equal(renamed.character_id, info.cid);
  await board.wait("data?.players?.[0]?.character?.label==='Tricia renamed'");
  for (const page of [detail, overlay]) await page.wait("data?.player?.character?.label==='Tricia renamed'");
  // Clear is explicitly previewed and creates a time boundary, not a retraction.
  await admin.fill('action', 'clear'); await admin.click('use-now'); await admin.fill('reason', 'Wait for fresh OCR');
  await preview();
  // A failed read after a successful real write must preserve both receipt and error.
  await admin.evaluate(`(() => {const original=fetch; globalThis.fetch=(url,options)=> {
    if(String(url).startsWith('/api/inspect?')) {globalThis.fetch=original;
      return Promise.resolve(new Response(JSON.stringify({error:'Synthetic refresh outage'}),{status:503}));}
    return original(url,options);
  };})()`);
  const cleared = (await save()).event; assert.equal(cleared.action, 'clear');
  assert.match(await admin.evaluate("document.getElementById('status').textContent"), /Saved clear.*Refresh failed.*Synthetic refresh outage/);
  await admin.click('refresh'); await admin.wait('!loading && scope?.character');
  await overlay.wait(`data?.player?.manual_correction?.id===${cleared.id} && data.player.reading===null`);
  await detail.wait(`data?.player?.manual_correction?.id===${cleared.id}`);
  assert.equal(await detail.evaluate('data.tracked_history.tracked_exp.approximate'), originalGain);
  await admin.evaluate('window.scrollTo(0,0)'); await screenshot(admin, 'admin-desktop');
  await admin.command('Emulation.setDeviceMetricsOverride', {width: 390, height: 1100, deviceScaleFactor: 1, mobile: true});
  await screenshot(admin, 'admin-mobile');
  // Existing-character/channel selection is inspection only.
  await admin.fill('character', String(info.cid+1)); await admin.wait("!loading && scope?.character?.label==='Other'");
  assert.equal(await admin.evaluate('scope.corrections.length'), 0);
  await admin.fill('channel', 'beta'); await admin.wait("!loading && scope?.character?.label==='Beta'");
  assert.equal(await admin.evaluate('scope.corrections.length'), 0);
  for (const page of [board, detail, overlay]) assert.equal(await page.evaluate('performance.getEntriesByType("navigation").length'), 1);
  // Expected validation HTTP 400s are useful errors, not application script failures.
  const unexpected = errors.filter(e => !String(e.entry?.text).includes('400 (Bad Request)') &&
    !(e.entry?.url === info.public+'/favicon.ico' && e.entry.text.includes('404 (Not Found)')));
  assert.deepEqual(unexpected, []);
  assert.ok(requests.every(r => r.startsWith('data:') || [info.admin, info.public].includes(new URL(r).origin)));
  writeFileSync(join(output, 'verification.json'), JSON.stringify({syntheticOnly: true, point: point.id,
    amendment: amended.id, baseline: baseline.id, renameCharacterId: renamed.character_id, clear: cleared.id,
    workflows: ['preview', 'create', 'historical', 'amend', 'undo', 'rename', 'clear', 'validation', 'isolation', 'publisher'],
    scriptErrors: unexpected, networkRequests: requests.length}, null, 2));
  console.log('PASS: real-browser preview/create/historical/amend/undo/rename/clear, validation, exact preview time, isolation and public cache refresh.');
} finally {
  sockets.forEach(s => s.close()); browser?.kill(); server.kill();
}
