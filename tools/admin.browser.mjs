// Actual Chrome forms and protected writes, using only a new synthetic database.
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
async function tab(origin, path, width = 1360, height = 1000) {
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
      const id = ++seq, timer = setTimeout(() => no(Error(method+' timeout: '+String(params.expression ?? '').slice(0,180))), 30000);
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
  async function key(key, code) {
    await command('Input.dispatchKeyEvent', {type:'keyDown', key, code:key, windowsVirtualKeyCode:code,
      ...(key === 'Enter' ? {text:'\r', unmodifiedText:'\r'} : {})});
    await command('Input.dispatchKeyEvent', {type:'keyUp', key, code:key, windowsVirtualKeyCode:code});
  }
  for (const name of ['Page', 'Runtime', 'Network', 'Log']) await command(name+'.enable');
  await command('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: width === 390});
  await command('Emulation.setTimezoneOverride', {timezoneId:'America/Toronto'});
  await command('Emulation.setLocaleOverride', {locale:'en-US'});
  await command('Page.navigate', {url: origin+path});
  return {command, evaluate, wait, fill, click, key};
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
  const idle = "document.getElementById('app')?.getAttribute('aria-busy')==='false'";
  await admin.wait(idle+" && document.getElementById('character')?.selectedOptions[0]?.text==='Tricia'");
  const get = id => admin.evaluate(`document.getElementById(${JSON.stringify(id)}).value`);
  async function api(path = '/api/inspect?channel=alpha') {
    return admin.evaluate(`fetch(${JSON.stringify(path)},{headers:{'X-Admin-Token':document.querySelector('meta[name="admin-token"]').content}}).then(r=>r.json())`);
  }
  async function preview(rename = false) {
    if (rename) await admin.evaluate("document.getElementById('rename-form').requestSubmit()");
    else await admin.click('preview-button');
    await admin.wait(idle+" && !document.getElementById('preview').hidden");
    return admin.evaluate("JSON.parse(document.getElementById('preview-audit').textContent)");
  }
  async function save() {
    await admin.click('save'); await admin.wait(idle+" && document.getElementById('status').textContent.startsWith('Saved')");
    return admin.evaluate("JSON.parse(document.getElementById('saved-audit').textContent)");
  }
  async function historyAction(id, label) {
    await admin.evaluate(`(() => {document.getElementById('history-section').open=true; const row=document.querySelector('[data-correction-id="${id}"]'); [...row.querySelectorAll('button')].find(n=>n.textContent===${JSON.stringify(label)}).click();})()`);
  }
  async function undo(event) {await historyAction(event.id,'Undo'); await admin.fill('reason','Synthetic review: undo this correction'); await preview(); await save();}
  async function localTime(stamp) {
    const parts = await admin.evaluate(`(() => {const d=new Date(${JSON.stringify(stamp)}), p=n=>String(n).padStart(2,'0'); return {date:[d.getFullYear(),p(d.getMonth()+1),p(d.getDate())].join('-'),time:[p(d.getHours()),p(d.getMinutes()),p(d.getSeconds())].join(':')};})()`);
    await admin.fill('date',parts.date); await admin.fill('time',parts.time);
  }
  assert.equal(await get('date'),''); assert.equal(await get('time'),'');
  assert.equal(await admin.evaluate("document.getElementById('use-now').checked"),false);
  assert.match(await admin.evaluate("document.getElementById('timezone').textContent"), /America\/Toronto/);
  assert.equal(await admin.evaluate("document.getElementById('action')"),null);
  assert.equal(await admin.evaluate("document.getElementById('form-advanced').open"),false);
  await screenshot(admin,'default-desktop');
  const board = await tab(info.public,'/'), detail = await tab(info.public,'/stream/alpha');
  const overlay = await tab(info.public,'/live/overlay/alpha',500,160);
  for (const p of [board,detail,overlay]) await p.wait("typeof data!=='undefined' && (data?.player?.reading || data?.players?.length)");
  const originalGain = await detail.evaluate('data.tracked_history.tracked_exp.approximate');
  console.log('Checking reading invalidation, restoration and complete-history batches…');
  async function readingAction(identity,label) {
    await admin.evaluate(`(() => {document.getElementById('past-section').open=true;const row=document.querySelector('[data-reading-id="${identity}"]');[...row.querySelectorAll('button')].find(b=>b.textContent===${JSON.stringify(label)}).click();})()`);
  }
  async function invalidReview() {
    await admin.wait("!document.getElementById('invalidation-review').hidden && !document.getElementById('confirm-invalidation').disabled");
    return admin.evaluate("JSON.parse(document.getElementById('invalidation-audit').textContent)");
  }
  async function invalidSave(prefix) {
    await admin.click('confirm-invalidation');
    await admin.wait(idle+` && document.getElementById('invalidation-review').hidden && document.getElementById('invalidation-status').textContent.startsWith(${JSON.stringify(prefix)})`);
    return admin.evaluate("JSON.parse(document.getElementById('invalidation-saved-audit').textContent)");
  }
  async function restoreExcluded(identity) {
    await admin.evaluate(`(() => {document.getElementById('invalidated-section').open=true;document.querySelector('[data-invalidated-identity="${identity}"] button').click();})()`);
    await invalidReview();await invalidSave('Restored');
  }
  await admin.fill('session',info.old_session);await admin.wait(idle+" && !!document.querySelector('[data-reading-id=\"old:2\"]')");
  await readingAction('old:2','Invalidate');let invalid=await invalidReview();
  assert.equal(invalid.count,1);assert.equal(invalid.readings[0].original.level,50);
  await screenshot(admin,'invalidate-one');await invalidSave('Invalidated');
  assert.equal((await api()).corrections.length,0);
  assert.match(await admin.evaluate("document.querySelector('[data-reading-id=\"old:2\"]').textContent"),/Invalidated/);
  await readingAction('old:2','Restore');await invalidReview();await invalidSave('Restored');
  // Latest values and the public publisher change without another frame.
  await admin.fill('session','');await admin.wait(idle+" && !!document.querySelector('[data-reading-id=\"live:4\"]')");
  await readingAction('live:4','Invalidate');await invalidReview();await invalidSave('Invalidated');
  await overlay.wait("data?.player?.reading?.event_id==='live:3'");
  await restoreExcluded('live:4');await overlay.wait("data?.player?.reading?.event_id==='live:4'");
  // One pre-existing exclusion is shown but not silently added to the new batch.
  await admin.fill('session',info.old_session);await admin.wait(idle+" && !!document.querySelector('[data-reading-id=\"old:2\"]')");
  await readingAction('old:2','Invalidate');await invalidReview();await invalidSave('Invalidated');
  await admin.evaluate("document.getElementById('invalidate-section').open=true");
  async function rangeTime(prefix,stamp) {
    const parts=await admin.evaluate(`(() => {const d=new Date(${JSON.stringify(stamp)}),p=n=>String(n).padStart(2,'0');return{date:[d.getFullYear(),p(d.getMonth()+1),p(d.getDate())].join('-'),time:[p(d.getHours()),p(d.getMinutes()),p(d.getSeconds())].join(':')};})()`);
    await admin.fill(prefix+'-date',parts.date);await admin.fill(prefix+'-time',parts.time);
  }
  await admin.fill('invalidate-start-date','2026-03-08');await admin.fill('invalidate-start-time','02:30:00');
  await rangeTime('invalidate-end',info.boundary);await admin.click('review-readings');
  await admin.wait("document.getElementById('invalidation-status').textContent.includes('does not exist')");
  await admin.fill('invalidate-start-date','2025-11-02');await admin.fill('invalidate-start-time','01:30:00');
  assert.equal(await admin.evaluate("document.getElementById('invalidate-start-fold').hidden"),false);
  assert.equal(await get('invalidate-start-choice'),'');
  await admin.fill('invalidate-start-choice','2025-11-02T06:30:00.000Z');
  await admin.fill('invalidate-end-date','2025-11-02');await admin.fill('invalidate-end-time','01:45:00');
  assert.equal(await admin.evaluate("document.getElementById('invalidate-end-fold').hidden"),false);
  await admin.fill('invalidate-end-choice','2025-11-02T06:45:00.000Z');await admin.click('review-readings');
  await admin.wait("document.getElementById('invalidation-status').textContent.includes('no readings')");
  await rangeTime('invalidate-start',info.stamps.old[0]);await rangeTime('invalidate-end',info.boundary);
  await admin.fill('invalidate-reason','Incorrect OCR in the selected interval');await admin.click('review-readings');
  invalid=await invalidReview();assert.equal(invalid.total,113);assert.equal(invalid.count,112);assert.equal(invalid.already_invalidated,1);
  assert.equal(await admin.evaluate("document.querySelectorAll('#invalidation-list article').length"),50);
  assert.match(await admin.evaluate("document.getElementById('invalidation-list').textContent"),/Already invalidated/);
  await admin.click('invalidation-next');await admin.wait("document.getElementById('invalidation-page').textContent==='Page 2 of 3'");
  await admin.click('invalidation-next');await admin.wait("document.getElementById('invalidation-page').textContent==='Page 3 of 3'");
  assert.equal(await admin.evaluate("document.querySelectorAll('#invalidation-list article').length"),13);
  await screenshot(admin,'invalidate-batch');const invalidBatch=(await invalidSave('Invalidated')).event;
  const state=(await api()).invalidated;assert.ok(state.next_before);assert.equal(state.readings.length,50);
  const restoredMember=state.readings[0].identity;await restoreExcluded(restoredMember);
  await admin.evaluate(`(() => {document.getElementById('invalidated-section').open=true;document.querySelector('[data-invalidation-batch="${invalidBatch.id}"] button').click();})()`);
  invalid=await invalidReview();assert.equal(invalid.count,111);assert.equal(invalid.total,112);
  await invalidSave('Restored');assert.equal((await api()).invalidated.readings.length,1);
  await restoreExcluded('old:2');assert.equal((await api()).invalidated.readings.length,0);
  assert.equal((await api()).corrections.length,0);
  await admin.fill('session','');await admin.wait(idle+" && !!document.querySelector('[data-reading-id=\"live:4\"]')");
  console.log('Checking native keyboard navigation and ordinary corrections…');
  // Native keyboard navigation through date, time and EXP controls.
  await localTime(info.stamps.live[2]);
  await admin.evaluate("document.getElementById('date').focus()");
  const visited = [];
  for (let n=0;n<12;n++) {visited.push(await admin.evaluate('document.activeElement.id')); await admin.key('Tab',9);}
  assert.ok(visited.includes('date') && visited.includes('time') && visited.includes('use-now'), JSON.stringify(visited));
  await admin.evaluate("document.getElementById('level').focus()"); await admin.key('Tab',9);
  assert.equal(await admin.evaluate('document.activeElement.id'),'exp'); await admin.key('Tab',9);
  assert.equal(await admin.evaluate('document.activeElement.id'),'percentage');
  await admin.fill('level','50'); await admin.click('preview-button');
  await admin.wait("document.getElementById('status').textContent.includes('Enter numerical EXP')");
  assert.equal((await api()).corrections.length,0);
  // Ordinary correction using native local date/time and percentage only.
  await admin.fill('percentage','0.45');
  let p = await preview(); assert.equal(p.event.current_exp,null); assert.ok(p.reading.estimated_exp);
  assert.match(await admin.evaluate("document.getElementById('preview-summary').textContent"), /setting Tricia to level 50 at 0.45%/);
  assert.equal(p.event.effective_at,info.stamps.live[2].replace('.123456','.000000'));
  assert.equal((await api()).corrections.length,0);
  await screenshot(admin,'review-percentage');
  // Back returns the form with its values; editing invalidates confirmation.
  await admin.click('cancel'); assert.equal(await get('percentage'),'0.45');
  p = await preview(); const percent = (await save()).event; await undo(percent);
  // Numerical-only correction with explicit current time and exact large integer transport.
  await admin.fill('level','49'); await admin.fill('exp','1000'); await admin.click('use-now');
  p = await preview(); assert.ok(p.reading.estimated_percentage); assert.equal(p.reading.exp,'1000');
  const numeric = (await save()).event; assert.equal(numeric.effective_at,p.event.effective_at);
  await overlay.wait(`data?.player?.manual_correction?.id===${numeric.id}`);
  assert.equal(await overlay.evaluate('document.getElementById("level").textContent'),'Lv. 49');
  await historyAction(numeric.id,'Edit'); assert.equal(await get('exp'),'1000'); assert.equal(await get('percentage'),'');
  assert.equal(await admin.evaluate("document.getElementById('reason').required"),true);
  await admin.fill('level','48'); await admin.fill('reason','Correct the entered level');
  await preview(); const revised = (await save()).event; assert.equal(revised.replaces_id,numeric.id); await undo(revised);
  await overlay.wait("data?.player?.reading?.evidence==='strict_full'");
  console.log('Checking historical Fix, Edit and Undo…');
  // Historical Fix keeps identity, character, all entered coordinates and six-digit source time.
  await admin.evaluate("document.getElementById('past-section').open=true");
  await admin.fill('session',info.old_session); await admin.wait(idle+" && !!document.querySelector('[data-reading-id="+'"old:2"'+"]')");
  await admin.evaluate("document.querySelector('[data-reading-id=\"old:2\"] button').click()");
  assert.equal(await get('target-id'),'old:2'); assert.equal(await get('effective-at'),info.stamps.old[1]);
  assert.notEqual(await get('exp'),''); assert.notEqual(await get('percentage'),'');
  await admin.fill('level','49'); await admin.fill('exp','12345'); await admin.fill('percentage','2.10');
  p = await preview(); assert.equal(p.event.effective_at,info.stamps.old[1]);
  assert.equal(p.event.target_event_id,'old:2'); assert.equal(p.event.character_id,info.cid);
  assert.equal(await admin.evaluate("document.getElementById('preview-warning').hidden"),false);
  const point = (await save()).event;
  await detail.wait(`data?.history?.some(p=>p.reading?.provenance?.id===${point.id})`);
  assert.equal(await detail.evaluate('data.player.display_level.value'),50);
  const archived = await api(`/api/inspect?channel=alpha&character_id=${info.cid}&session_id=${info.old_session}`);
  assert.equal(archived.readings.find(r=>r.identity==='old:2').original_level,50);
  await historyAction(point.id,'Edit'); await admin.fill('level','48'); await admin.fill('reason','Edit the past correction');
  p = await preview(); assert.equal(p.event.effective_at,info.stamps.old[1]); const revisedPoint = (await save()).event; await undo(revisedPoint);
  // Only a genuinely ambiguous recording boundary asks the operator to pick a period.
  await admin.fill('level','50'); await admin.fill('percentage','33.00');
  await admin.evaluate("document.getElementById('form-advanced').open=true"); await admin.click('use-iso'); await admin.fill('effective-at',info.boundary);
  await admin.click('preview-button'); await admin.wait(idle+" && !document.getElementById('session-choice').hidden");
  const periodLabels = await admin.evaluate("[...document.getElementById('recording-choice').options].map(o=>o.text)");
  assert.ok(periodLabels.slice(1).every(s=>!s.includes('#') && s.includes('2026')));
  const afterBoundary = new Date(new Date(info.boundary).getTime()+1000).toISOString();
  await admin.fill('effective-at',afterBoundary);
  assert.equal(await admin.evaluate("document.getElementById('session-choice').hidden"),true);
  p = await preview(); assert.equal(p.event.session_id,info.session); await admin.click('cancel');
  await admin.fill('effective-at',info.boundary); await admin.click('preview-button');
  await admin.wait(idle+" && !document.getElementById('session-choice').hidden");
  await admin.fill('recording-choice',info.old_session); p = await preview(); assert.equal(p.event.session_id,info.old_session);
  const boundary = (await save()).event; await undo(boundary);
  // Gap and fold handling in Chrome. Never silently choose or normalize a local time.
  await admin.fill('level','43'); await admin.fill('percentage','0.45');
  await admin.fill('date','2026-03-08'); await admin.fill('time','02:30:00');
  await admin.click('preview-button'); await admin.wait(idle+" && document.getElementById('status').textContent.includes('does not exist')");
  await admin.fill('date','2025-11-02'); await admin.fill('time','01:30:00');
  assert.equal(await admin.evaluate("document.getElementById('clock-choice').hidden"),false);
  assert.equal(await get('clock-time'),'');
  await admin.evaluate("document.getElementById('form-advanced').open=true"); await admin.fill('target-session','none');
  await admin.fill('clock-time','2025-11-02T06:30:00.000Z'); p = await preview();
  assert.equal(p.event.effective_at,'2025-11-02T06:30:00.000000+00:00'); await admin.click('cancel');
  // Advanced ISO input preserves microseconds and an explicit non-UTC offset exactly.
  await admin.click('use-iso'); await admin.fill('effective-at','2025-11-02T01:30:00.123456-05:00');
  p = await preview(); assert.equal(p.event.effective_at,'2025-11-02T06:30:00.123456+00:00'); await admin.click('cancel');
  await admin.click('new-correction');
  // Rename is a separate small action, with a review that does not write.
  await admin.click('rename'); await admin.fill('new-name','Tricia renamed'); p = await preview(true);
  assert.equal((await api()).character.label,'Tricia'); const renamed = (await save()).event; assert.equal(renamed.character_id,info.cid);
  await board.wait("data?.players?.[0]?.character?.label==='Tricia renamed'");
  for (const page of [detail,overlay]) await page.wait("data?.player?.character?.label==='Tricia renamed'");
  // Clear stays available in Advanced and still requires an explicit time and confirmation.
  await admin.evaluate("document.getElementById('form-advanced').open=true"); await admin.click('clear'); await admin.click('use-now');
  await preview();
  // Keep a successful save receipt if its follow-up read fails.
  await admin.evaluate(`(() => {const original=fetch; globalThis.fetch=(url,options)=> {
    if(String(url).startsWith('/api/inspect?')) {globalThis.fetch=original; return Promise.resolve(new Response(JSON.stringify({error:'Synthetic refresh outage'}),{status:503}));}
    return original(url,options);
  };})()`);
  const cleared = (await save()).event; assert.equal(cleared.action,'clear');
  assert.match(await admin.evaluate("document.getElementById('status').textContent"), /Saved.*Refresh failed.*Synthetic refresh outage/);
  assert.match(await admin.evaluate("document.getElementById('latest').textContent"),/Could not load/);
  assert.equal(await admin.evaluate("document.querySelectorAll('#history [data-correction-id]').length"),0);
  await admin.click('refresh'); await admin.wait(idle);
  await detail.wait(`data?.player?.manual_correction?.id===${cleared.id}`);
  assert.equal(await detail.evaluate('data.tracked_history.tracked_exp.approximate'),originalGain);
  // Empty states use one message; selecting a different character/channel cannot carry edits.
  await admin.fill('character',info.cid+1); await admin.wait(idle+" && document.getElementById('character').selectedOptions[0].text==='Other'");
  assert.match(await admin.evaluate("document.getElementById('latest').textContent"),/No recorded level or EXP/);
  assert.equal(await get('date'),''); assert.equal(await get('level'),'');
  await screenshot(admin,'empty-state');
  await admin.fill('channel','beta'); await admin.wait(idle+" && document.getElementById('character').selectedOptions[0].text==='Beta'");
  await admin.fill('channel','alpha'); await admin.wait(idle+" && document.getElementById('character').selectedOptions[0].text==='Tricia renamed'");
  await undo(cleared); await overlay.wait("data?.player?.reading?.evidence==='strict_full'");
  await admin.evaluate("document.getElementById('past-section').open=false;document.getElementById('history-section').open=false;window.scrollTo(0,0)");
  await screenshot(admin,'admin-desktop');
  await admin.command('Emulation.setDeviceMetricsOverride',{width:390,height:1100,deviceScaleFactor:1,mobile:true});
  await screenshot(admin,'admin-mobile');
  await admin.evaluate("document.getElementById('past-section').open=true;document.getElementById('readings').querySelector('article').querySelectorAll('button')[1].click()");
  await invalidReview();await screenshot(admin,'invalidate-mobile');await admin.click('cancel-invalidation');
  await admin.evaluate("document.getElementById('invalidate-section').open=true;document.getElementById('invalidate-form').scrollIntoView()");
  await screenshot(admin,'invalidate-form-mobile');
  await admin.evaluate("document.getElementById('past-section').open=false;document.getElementById('invalidate-section').open=false;window.scrollTo(0,0)");
  // Mobile keyboard editing and review still work at normal scale.
  await admin.fill('level','43'); await admin.fill('percentage','0.45'); await admin.click('use-now');
  assert.equal(await admin.evaluate("document.getElementById('editor').checkValidity()"),true,
    await admin.evaluate("[...document.querySelectorAll('#editor input,#editor select')].filter(n=>!n.checkValidity()).map(n=>n.id+': '+n.validationMessage).join(', ')") );
  await admin.evaluate("document.getElementById('reason').focus()"); await admin.key('Enter',13);
  await admin.wait(idle+" && !document.getElementById('preview').hidden"); await screenshot(admin,'review-mobile');
  await admin.click('cancel');
  for (const page of [board,detail,overlay]) assert.equal(await page.evaluate('performance.getEntriesByType("navigation").length'),1);
  const unexpected = errors.filter(e => !String(e.entry?.text).includes('400 (Bad Request)') &&
    !(e.entry?.url === info.public+'/favicon.ico' && e.entry.text.includes('404 (Not Found)')));
  assert.deepEqual(unexpected,[]);
  assert.ok(requests.every(r=>r.startsWith('data:') || [info.admin,info.public].includes(new URL(r).origin)));
  writeFileSync(join(output,'verification.json'), JSON.stringify({syntheticOnly:true, keyboardVisited:visited,
    workflows:['single invalidation','single restore','complete-history range','batch pagination','individual batch restore','batch restore','invalidated latest','native local time','percentage only','numeric only','exact microseconds','historical fix','edit','undo','rename','empty states','DST gap/fold','recording ambiguity','clear','refresh failure','publisher'],
    point:point.id, renamedCharacterId:renamed.character_id, scriptErrors:unexpected, networkRequests:requests.length},null,2));
  console.log('PASS: redesigned admin workflows, native date/time, DST, exact historical times, keyboard, desktop/mobile, protected writes and public publication.');
} finally {sockets.forEach(s=>s.close()); browser?.kill(); server.kill();}
