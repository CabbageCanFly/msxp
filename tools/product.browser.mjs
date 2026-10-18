// Real localhost HTTP + SQLite + optional existing local-video capture. No API fixtures.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync,mkdirSync,mkdtempSync,readFileSync,writeFileSync,openSync,closeSync} from 'node:fs';
import {resolve,join,sep} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

const [base='http://127.0.0.1:8765',directory,databaseArgument,channel='offline_window']=process.argv.slice(2);
const verifyQuarantine=databaseArgument==='--verify-quarantine';
const verifyUsability=databaseArgument==='--verify-usability';
const verifyLevelUp=databaseArgument==='--verify-level-up';
const verifyWindows=databaseArgument==='--verify-windows';
const verifyRolling=databaseArgument==='--verify-rolling';
const verifyHistorical=databaseArgument==='--verify-historical';
const verifyUpdates=databaseArgument==='--verify-updates' || verifyQuarantine;
const database=databaseArgument==='-' || verifyUpdates || verifyUsability || verifyLevelUp || verifyWindows || verifyRolling || verifyHistorical?null:databaseArgument;
const url=new URL(base);assert.equal(url.hostname,'127.0.0.1');assert.match(channel,/^[A-Za-z0-9_]{1,25}$/);
const output=resolve(directory);assert.ok(['private','artifacts'].some(root=>output.startsWith(resolve(root)+sep)));
mkdirSync(output,{recursive:false});
let fixture=null,fixtureCommand=null;
if(verifyUpdates || verifyUsability || verifyLevelUp || verifyWindows || verifyRolling || verifyHistorical){
  const python=resolve(process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
  fixture=spawn(python,['tools/product_updates_fixture.py','--directory',output,'--port',url.port||'80',...(verifyHistorical?['--historical']:verifyRolling?['--rolling']:verifyWindows?['--windows']:verifyUsability?['--usability']:verifyLevelUp?['--level-up']:[])],{windowsHide:true,stdio:['pipe','pipe','inherit']});
  let buffer='',waiting=null;const messages=[];
  fixture.stdout.on('data',chunk=>{buffer+=chunk;let end;while((end=buffer.indexOf('\n'))>=0){const message=JSON.parse(buffer.slice(0,end));buffer=buffer.slice(end+1);if(waiting){waiting(message);waiting=null;}else messages.push(message);}});
  const next=()=>new Promise((ok,no)=>{if(messages.length){ok(messages.shift());return;}const timer=setTimeout(()=>no(new Error('SQLite fixture timeout')),10000);waiting=m=>{clearTimeout(timer);ok(m);};});
  fixtureCommand=async command=>{fixture.stdin.write(command+'\n');return next();};
  assert.ok((await next()).ready);
}
if(database)assert.ok(['private','artifacts'].some(root=>resolve(database).startsWith(resolve(root)+sep)));
const browser=process.env.BROWSER_BIN || ['C:/Program Files/Google/Chrome/Application/chrome.exe','/usr/bin/chromium'].find(existsSync);
assert.ok(browser,'Set BROWSER_BIN to Chrome/Chromium');
const profile=mkdtempSync(join(output,'chrome-')),browserLog=openSync(join(output,'browser.log'),'wx');
const child=spawn(browser,['--headless','--disable-gpu','--no-first-run','--no-default-browser-check',`--user-data-dir=${profile}`,'--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','about:blank'],{stdio:['ignore','ignore',browserLog],windowsHide:true});
const sockets=[],failures=[],requests=[],shots=[];let capture=null,captureDone=null,captureLog=null,port;
const api=async path=>{const r=await fetch(new URL(path,url));assert.ok(r.ok);return r.json();};
async function tab(path,width,height){
  const target=await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`,{method:'PUT'})).json();
  const ws=new WebSocket(target.webSocketDebuggerUrl);sockets.push(ws);
  await new Promise((ok,no)=>{ws.onopen=ok;ws.onerror=no;});
  let sequence=0;const pending=new Map();
  ws.onmessage=event=>{const m=JSON.parse(event.data);if(m.id)pending.get(m.id)?.(m);if(m.method==='Runtime.exceptionThrown')failures.push(m.params.exceptionDetails);if(m.method==='Network.requestWillBeSent')requests.push(m.params.request.url);};
  function command(method,params={}){return new Promise((ok,no)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);no(new Error('CDP timeout '+method));},10000);pending.set(id,m=>{clearTimeout(timer);pending.delete(id);m.error?no(new Error(JSON.stringify(m.error))):ok(m.result);});ws.send(JSON.stringify({id,method,params}));});}
  async function evaluate(expression){const r=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});assert.ok(!r.exceptionDetails,JSON.stringify(r.exceptionDetails));return r.result.value;}
  async function wait(expression,seconds=15){for(let i=0;i<seconds*10;i++){if(await evaluate(expression))return;await delay(100);}assert.fail('Timed out: '+expression);}
  for(const name of ['Page','Runtime','Network'])await command(name+'.enable');
  await command('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width<650 && width!==500});
  await command('Emulation.setDefaultBackgroundColorOverride',{color:{r:0,g:0,b:0,a:0}});
  await command('Page.navigate',{url:new URL(path,url).href});
  return {command,evaluate,wait};
}
async function screenshot(page,name,width,height){
  await page.command('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width<650 && width!==500});
  await page.evaluate('if(document.body.dataset.view==="player")drawHistory()');
  assert.ok(await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),name+': horizontal overflow');
  if(name.startsWith('character'))assert.ok(await page.evaluate('document.getElementById("history-chart").parentElement.scrollWidth<=document.getElementById("history-chart").parentElement.clientWidth'),name+': chart horizontal overflow');
  const image=await page.command('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});writeFileSync(join(output,name+'.png'),Buffer.from(image.data,'base64'));shots.push(name);
}
try {
  const file=join(profile,'DevToolsActivePort');for(let i=0;!existsSync(file)&&i<100;i++){assert.equal(child.exitCode,null);await delay(100);}assert.ok(existsSync(file));port=readFileSync(file,'utf8').split('\n')[0];
  const before=await api('/api/players');assert.ok(before.players.length>=1);assert.ok(before.players.some(p=>p.channel===channel));
  const board=await tab('/',1440,1050);await board.wait(`typeof data!=='undefined' && data?.players?.length===${before.players.length}`);
  assert.deepEqual(await board.evaluate('[...document.querySelectorAll(".entry")].map(r=>r.dataset.channel).sort()'),before.players.map(p=>p.channel).sort());
  for(const p of before.players)if(p.reading)assert.equal(await board.evaluate(`document.querySelector('.entry[data-channel="${p.channel}"] progress').value`),p.reading.bp/100);
  assert.equal(await board.evaluate('document.querySelectorAll("[data-window]").length'),4);
  await board.evaluate('document.querySelector("[data-sort=movement]").click();document.querySelectorAll("[data-window]")[1].click()');
  assert.match(await board.evaluate('document.getElementById("ranking-note").textContent'),/10-minute window/);
  await board.evaluate('document.querySelectorAll("[data-window]")[0].click()');
  await screenshot(board,'homepage-desktop',1440,1050);await screenshot(board,'homepage-mobile',390,1200);
  const overlay=await tab('/live/overlay/'+channel,500,160);await overlay.wait("typeof data!=='undefined' && !!data?.player");
  const original=await api('/api/players/'+channel);
  assert.equal(await overlay.evaluate('document.getElementById("percentage").textContent'),original.player.reading.percentage+'%');
  assert.equal(await overlay.evaluate('document.getElementById("card").getBoundingClientRect().height'),150);
  assert.equal(await overlay.evaluate('getComputedStyle(document.body).backgroundColor'),'rgba(0, 0, 0, 0)');
  await screenshot(overlay,'overlay-before-stale',500,160);
  const detail=await tab('/stream/'+channel,1440,1050);await detail.wait("typeof data!=='undefined' && !!data?.player");
  const recent=await detail.evaluate('({start:document.getElementById("history-chart").dataset.start,end:document.getElementById("history-chart").dataset.end,note:document.getElementById("history-note").textContent})');
  if(recent.start)assert.equal(Date.parse(recent.end)-Date.parse(recent.start),1800000);
  assert.equal(await detail.evaluate('document.getElementById("movement-label").textContent'),'Last 5 min');
  if(!original.player.windows['5'].eligible)assert.equal(await detail.evaluate('document.getElementById("window-rate").textContent'),original.player.windows['5'].observed?.available?'Not complete yet':'Building history');
  await screenshot(detail,'character-desktop',1440,1050);
  await screenshot(detail,'character-mobile',390,1200);
  await detail.evaluate('document.querySelectorAll("[data-window]")[2].click()');
  assert.equal(await detail.evaluate('document.getElementById("movement-label").textContent'),'Last 15 min');
  await screenshot(detail,'character-15-minute',1440,1050);
  await detail.evaluate('document.querySelectorAll("[data-window]")[0].click()');
  await detail.command('Page.bringToFront');
  await detail.wait('performance.getEntriesByType("resource").filter(r=>r.name.includes("/api/players/")).length>=2');
  await overlay.wait('performance.getEntriesByType("resource").filter(r=>r.name.includes("/api/players/")).length>=2');
  const observed=[];
  if(verifyHistorical){
    const stages=[];
    await detail.evaluate('[...document.querySelectorAll(".bar-hit")].at(-1).focus()');
    await detail.wait('tip && !tip.hidden');
    const oldTip=await detail.evaluate('({key:tipKey,text:tip.textContent})');
    for(const action of ['finish','age']){
      await fixtureCommand(action);
      const actual=await api('/api/players/'+channel);stages.push(actual);
      await detail.wait(`data?.served_at===${JSON.stringify(actual.served_at)}`);
      await board.wait(`data?.served_at===${JSON.stringify(actual.served_at)}`);
      await overlay.wait(`data?.served_at===${JSON.stringify(actual.served_at)}`);
      if(action==='finish'){
        await detail.wait(`tipKey===${JSON.stringify(oldTip.key)} && tip.textContent!==${JSON.stringify(oldTip.text)}`);
        assert.equal(await detail.evaluate('tip.hidden'),false);
      }
      await board.wait(`data?.players.find(p=>p.channel===${JSON.stringify(channel)})?.capture_lifecycle==='completed'`);
      assert.equal(await detail.evaluate('document.getElementById("status").textContent'),'Capture finished');
      if(action==='age')assert.equal(await board.evaluate('data.players.every(p=>p.stale && p.age_seconds>4600)'),true);
      assert.equal(actual.player.responsive_pace.active,false);
      for(const minutes of [5,10,15,30]){
        await detail.evaluate(`document.querySelector('[data-window="${minutes}"]').click()`);
        assert.ok(actual.player.windows[String(minutes)].observed.available);
        assert.equal(actual.player.windows[String(minutes)].eligible,false);
        assert.notEqual(await detail.evaluate('document.getElementById("movement").textContent'),'—');
        assert.match(await detail.evaluate('document.getElementById("segment-note").textContent'),/readings.*last updated/);
      }
    }
    await detail.wait('rollingData?.buckets?.length===48');
    await screenshot(detail,'historical-desktop',1440,1200);await screenshot(board,'historical-homepage',1440,1000);
    async function tooltip(selector,touch=false){
      await detail.evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'})`);await delay(100);
      const bounds=await detail.evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
      if(touch){
        await detail.command('Emulation.setTouchEmulationEnabled',{enabled:true});
        await detail.command('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[bounds]});
        await detail.command('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
      }else {await detail.command('Input.dispatchMouseEvent',{type:'mouseMoved',x:0,y:0});await detail.command('Input.dispatchMouseEvent',{type:'mouseMoved',...bounds});}
      try {await detail.wait('tip && !tip.hidden');}catch(error){
        writeFileSync(join(output,'tooltip-failure.json'),JSON.stringify(await detail.evaluate(`({bounds:${JSON.stringify(bounds)},target:document.elementFromPoint(${bounds.x},${bounds.y})?.outerHTML,tip:tip?.textContent,hidden:tip?.hidden})`),null,2));throw error;
      }
      assert.ok(await detail.evaluate('(()=>{const r=tip.getBoundingClientRect();return r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight})()'));
      return detail.evaluate('tip.textContent');
    }
    assert.match(await tooltip('.bar-hit[data-tip-text*="Partial coverage"]'),/EXP\n1 min bucket/);
    assert.match(await tooltip('.bar-hit[data-tip-text*="Complete coverage"]'),/Complete coverage/);
    await screenshot(detail,'bar-tooltip-desktop',1440,1100);
    const key=await detail.evaluate('tipKey');await delay(2500);
    assert.equal(await detail.evaluate('tipKey'),key);assert.equal(await detail.evaluate('tip.hidden'),false);
    await detail.evaluate('document.querySelector(".bar-hit").focus()');
    await detail.wait('tip && !tip.hidden');
    await detail.command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
    assert.equal(await detail.evaluate('tip.hidden'),true);
    await delay(2500);assert.equal(await detail.evaluate('tip.hidden'),true);
    await detail.evaluate('document.querySelector("[data-bucket=\\"1800\\"]").click()');
    assert.match(await tooltip('.bar-hit[data-tip-text*="No reading"]'),/No reading/);
    await detail.evaluate('document.querySelector("[data-chart=percentage]").click()');
    assert.match(await tooltip('circle[data-tip-key]'),/Lv\. 57 · \d+\.\d{2}%\n[\d,]+ EXP/);
    await screenshot(detail,'point-tooltip-desktop',1440,1100);
    assert.match(await tooltip('path[data-tip-key]'),/Reading unavailable/);
    await screenshot(detail,'historical-mobile',390,1200);
    await detail.evaluate('document.querySelector("[data-chart=exp]").click();document.querySelector("[data-bucket=\\"60\\"]").click()');
    assert.match(await tooltip('.bar-hit[data-tip-text*="Partial coverage"]',true),/Partial coverage/);
    await screenshot(detail,'bar-tooltip-mobile',390,1200);
    const other=await tab('/stream/telfer1',1440,1100);await other.wait("typeof data!=='undefined' && data?.player?.capture_lifecycle==='completed'");
    assert.match(await other.evaluate('document.getElementById("exp").textContent'),/EXP|K/);
    await screenshot(other,'telfer-historical-desktop',1440,1100);
    await overlay.wait("data?.player?.capture_lifecycle==='completed'");await screenshot(overlay,'historical-overlay',500,160);
    for(const page of [board,detail,overlay])assert.equal(await page.evaluate('performance.getEntriesByType("navigation").length'),1);
    writeFileSync(join(output,'historical-stages.json'),JSON.stringify(stages,null,2));observed.push(...stages);
    writeFileSync(join(output,'chart-cost.json'),JSON.stringify(await detail.evaluate('Array.from({length:10},()=>{const start=performance.now();drawHistory();return performance.now()-start})')));
  }else if(verifyRolling){
    const stages=[];
    for(const action of [null,'advance','expire']){
      if(action)await fixtureCommand(action);
      const actual=await api('/api/players/'+channel),rolling=await api('/api/players/'+channel+'/history');
      await detail.wait(`data?.served_at===${JSON.stringify(actual.served_at)}`);
      await detail.wait(`rollingData?.as_of===${JSON.stringify(rolling.as_of)}`,45);
      assert.equal(rolling.buckets.length,48);
      await detail.evaluate('document.querySelector("[data-bucket=\\"1800\\"]").click()');
      const bounds=await detail.evaluate('({a:document.getElementById("history-chart").dataset.start,b:document.getElementById("history-chart").dataset.end})');
      assert.equal(Date.parse(bounds.b)-Date.parse(bounds.a),86400000);
      assert.ok(await detail.evaluate('document.querySelectorAll(".exp-column.missing").length>0'));
      if(action==='expire'){
        assert.equal(rolling.tracked_exp,null);
        assert.equal(await detail.evaluate('document.getElementById("tracked-exp").textContent'),'—');
        assert.equal(await detail.evaluate('document.querySelectorAll(".exp-column:not(.missing)").length'),0);
      }else{
        assert.ok(rolling.tracked_exp.approximate>0);
        assert.equal(await detail.evaluate('document.getElementById("tracked-exp").textContent'),await detail.evaluate(`'~'+expText(${rolling.tracked_exp.approximate})`));
        assert.ok(await detail.evaluate('document.querySelectorAll(".exp-column:not(.missing)").length>0'));
      }
      if(action==='advance'){
        assert.ok(rolling.tracked_exp.approximate>stages[0].tracked_exp.approximate);
        await screenshot(detail,'rolling-24h-desktop',1440,1200);await screenshot(detail,'rolling-24h-mobile',390,1400);
        await overlay.wait(`data?.player?.latest_attempt_at===${JSON.stringify(actual.player.latest_attempt_at)}`);
        await board.wait(`data?.players.find(p=>p.channel===${JSON.stringify(channel)})?.latest_attempt_at===${JSON.stringify(actual.player.latest_attempt_at)}`);
        await screenshot(overlay,'rolling-overlay',500,160);
      }
      stages.push(rolling);
    }
    await screenshot(detail,'rolling-expired',1100,1100);
    for(const seconds of [60,300]){
      await detail.evaluate(`document.querySelector('[data-bucket="${seconds}"]').click()`);
      const span=await detail.evaluate('Date.parse(document.getElementById("history-chart").dataset.end)-Date.parse(document.getElementById("history-chart").dataset.start)');
      assert.equal(span,seconds===60?1800000:7200000);
    }
    for(const page of [detail,board,overlay])assert.equal(await page.evaluate('performance.getEntriesByType("navigation").length'),1);
    writeFileSync(join(output,'rolling-stages.json'),JSON.stringify(stages,null,2));observed.push(...stages);
  }else if(verifyWindows){
    const batches=[];
    for(const action of [null,'advance','finish']){
      if(action)await fixtureCommand(action);
      const actual=await api('/api/players/'+channel);batches.push(actual);
      await detail.wait(`data?.player?.latest_attempt_at===${JSON.stringify(actual.player.latest_attempt_at)}`);
      await overlay.wait(`data?.player?.latest_attempt_at===${JSON.stringify(actual.player.latest_attempt_at)}`);
      await board.wait(`data?.players.find(p=>p.channel===${JSON.stringify(channel)})?.latest_attempt_at===${JSON.stringify(actual.player.latest_attempt_at)}`);
      for(const minutes of [5,10,15,30]){
        const o=actual.player.windows[String(minutes)].observed;assert.ok(o.available);
        assert.equal(actual.player.windows[String(minutes)].eligible,false);
        await detail.evaluate(`document.querySelector('[data-window="${minutes}"]').click()`);
        assert.equal(await detail.evaluate('document.getElementById("movement").textContent'),await detail.evaluate(`movementText(data.player.windows[${JSON.stringify(String(minutes))}].observed)`));
        assert.match(await detail.evaluate('document.getElementById("movement").textContent'),/EXP$|%$/);
        assert.match(await detail.evaluate('document.getElementById("segment-note").textContent'),/readings.*partial history/);
        assert.equal(await detail.evaluate('document.getElementById("window-rate").textContent'),'Not complete yet');
        await board.evaluate(`document.querySelector('[data-window="${minutes}"]').click();document.querySelector('[data-sort="movement"]').click()`);
        assert.equal(await board.evaluate(`document.querySelector('.entry[data-channel="${channel}"]').dataset.rank`),'');
      }
      if(action==='advance')await screenshot(detail,'observed-after-rotation',1100,1050);
    }
    assert.notEqual(batches[0].player.reading.event_id.split(':')[0],batches[1].player.reading.event_id.split(':')[0]);
    for(const minutes of [5,30]){
      await detail.evaluate(`document.querySelector('[data-window="${minutes}"]').click()`);
      await screenshot(detail,`observed-${minutes}-minute-desktop`,1100,1050);
      await screenshot(detail,`observed-${minutes}-minute-mobile`,390,1100);
    }
    await screenshot(board,'observed-homepage',1440,1050);
    await screenshot(overlay,'observed-overlay',500,160);
    await detail.wait('rollingData?.buckets?.length===48');
    for(const [seconds,span] of [[60,1800000],[300,7200000],[1800,86400000]]){
      await detail.evaluate(`document.querySelector('[data-bucket="${seconds}"]').click()`);
      const bounds=await detail.evaluate('({a:document.getElementById("history-chart").dataset.start,b:document.getElementById("history-chart").dataset.end})');
      assert.equal(Date.parse(bounds.b)-Date.parse(bounds.a),span);
      assert.ok(await detail.evaluate('document.querySelectorAll(".exp-column:not(.missing)").length>0'));
      assert.ok(await detail.evaluate('document.querySelectorAll(".exp-column.missing").length>0'));
    }
    await detail.evaluate('document.querySelector("[data-bucket=\\"60\\"]").click()');
    await screenshot(detail,'exp-bars-desktop',1100,1250);await screenshot(detail,'exp-bars-mobile',390,1400);
    await detail.evaluate('document.querySelector("[data-chart=percentage]").click()');
    assert.ok(await detail.evaluate('document.querySelectorAll("#history-chart .trend").length>0'));
    await screenshot(detail,'secondary-level-chart',1100,1050);
    await detail.evaluate('document.querySelector("[data-chart=exp]").click()');
    await fixtureCommand('stale');
    const stale=await api('/api/players/'+channel);assert.ok(stale.player.stale);
    await detail.wait('data?.player?.stale===true');
    await overlay.wait('data?.player?.stale===true');
    for(const minutes of [5,10,15,30]){
      await detail.evaluate(`document.querySelector('[data-window="${minutes}"]').click()`);
      assert.match(await detail.evaluate('document.getElementById("segment-note").textContent'),/last updated/);
      assert.equal(await detail.evaluate('document.getElementById("movement").dataset.paused'),'true');
      assert.equal(await detail.evaluate('document.getElementById("window-rate").textContent'),'Paused');
    }
    await screenshot(detail,'observed-stale',1100,1050);
    for(const page of [detail,board,overlay])assert.equal(await page.evaluate('performance.getEntriesByType("navigation").length'),1);
    observed.push(...batches.map(batch=>({reading:batch.player.reading,windows:batch.player.windows})));
  }else if(verifyLevelUp){
    assert.equal(original.player.display_level.value,65);assert.equal(original.player.level_events.length,0);
    assert.equal((await fixtureCommand('levelup')).stage,'levelup');
    await detail.wait('data?.player?.display_level?.value===66');
    assert.equal(await detail.evaluate('data.player.level_events.length'),0);
    assert.equal((await fixtureCommand('advance')).stage,'advance');
    const after=await api('/api/players/'+channel);
    assert.equal(after.player.responsive_pace.active,true);assert.equal(after.player.responsive_pace.readings,2);
    assert.equal(after.player.responsive_pace.estimates.eta,null);assert.equal(after.player.windows['5'].eligible,false);
    await detail.wait('document.getElementById("level-event").textContent==="Level 66 reached!"');
    await overlay.wait(`data?.player?.reading?.event_id===${JSON.stringify(after.player.reading.event_id)}`);
    await board.wait(`data?.players.find(p=>p.channel===${JSON.stringify(channel)})?.reading?.event_id===${JSON.stringify(after.player.reading.event_id)}`);
    assert.match(await detail.evaluate('document.getElementById("early-value").textContent'),/first estimate.*2 readings/);
    assert.equal(await overlay.evaluate('document.getElementById("level").textContent'),'Lv. 66');
    assert.equal(await detail.evaluate('document.getElementById("history-chart").textContent.includes("99.97%")'),false);
    await screenshot(detail,'level-up-first-estimate',1100,1050);await screenshot(overlay,'level-up-overlay',500,160);
    assert.equal((await fixtureCommand('finish')).stage,'finish');
    const final=await api('/api/players/'+channel);
    await detail.wait(`data?.player?.latest_attempt_at===${JSON.stringify(final.player.latest_attempt_at)}`);
    await overlay.wait(`data?.player?.latest_attempt_at===${JSON.stringify(final.player.latest_attempt_at)}`);
    await board.wait(`data?.players.find(p=>p.channel===${JSON.stringify(channel)})?.latest_attempt_at===${JSON.stringify(final.player.latest_attempt_at)}`);
    assert.match(await detail.evaluate('document.getElementById("early-value").textContent'),/last estimated/);
    assert.equal(final.player.responsive_pace.active,false);
    for(const page of [board,detail,overlay])assert.equal(await page.evaluate('performance.getEntriesByType("navigation").length'),1);
    await screenshot(board,'recent-trend-homepage',1440,1050);await screenshot(board,'recent-trend-homepage-mobile',390,1200);
    await screenshot(detail,'current-level-history',1100,1050);await screenshot(detail,'current-level-history-mobile',390,1200);
    await screenshot(overlay,'paused-recent-overlay',500,160);
    observed.push({asOfReplay:true,after:after.player,final:final.player});
  }
  if(verifyUsability){
    assert.equal(original.player.early_pace.active,false);
    assert.equal((await fixtureCommand('advance')).stage,'advance');
    const after=await api('/api/players/'+channel);
    assert.equal(after.player.early_pace.active,true);assert.equal(after.player.windows['5'].eligible,false);
    await detail.wait('document.getElementById("early-value").textContent.includes("early estimate")');
    await overlay.wait(`data?.player?.reading?.event_id===${JSON.stringify(after.player.reading.event_id)}`);
    await board.wait(`data?.players.find(p=>p.channel===${JSON.stringify(channel)})?.reading?.event_id===${JSON.stringify(after.player.reading.event_id)}`);
    assert.equal(await detail.evaluate('document.getElementById("window-rate").textContent'),after.player.windows['5'].observed?.available?'Not complete yet':'Building history');
    await screenshot(detail,'early-pace-saved-trial',1100,1050);
    await screenshot(overlay,'early-pace-overlay',500,160);
    assert.equal((await fixtureCommand('finish')).stage,'finish');
    await detail.wait('data?.player?.latest_attempt_status!=="diagnostic_percentage_only" && data?.player?.display_level?.last_known');
    const final=await api('/api/players/'+channel);
    assert.equal(final.player.display_level.value,65);assert.equal(final.player.reading.level.value,null);
    assert.equal(final.player.early_pace.active,false);assert.equal(final.player.estimates.exp_per_hour,null);
    await overlay.wait(`data?.player?.latest_attempt_at===${JSON.stringify(final.player.latest_attempt_at)}`);
    await board.wait(`data?.players.find(p=>p.channel===${JSON.stringify(channel)})?.latest_attempt_at===${JSON.stringify(final.player.latest_attempt_at)}`);
    assert.equal(await overlay.evaluate('document.getElementById("level").textContent'),'Lv. 65');
    for(const page of [board,detail,overlay])assert.equal(await page.evaluate('performance.getEntriesByType("navigation").length'),1);
    await screenshot(detail,'last-known-saved-trial',1100,1050);await screenshot(detail,'last-known-mobile',390,1200);
    await screenshot(overlay,'last-known-overlay',500,160);await screenshot(board,'completed-two-stream-trial',1440,1050);
    assert.ok(await board.evaluate('[...document.querySelectorAll(".level-note")].every(n=>n.getBoundingClientRect().right<=n.closest(".entry").querySelector(".identity").getBoundingClientRect().left)'), 'Last-known label overlaps character identity');
    observed.push({asOfReplay:true,after:after.player,final:final.player});
  }
  if(verifyUpdates){
    const initialWindow=before.players.find(p=>p.channel==='synthetic_window');assert.equal(initialWindow.windows['5'].eligible,false);
    const windowPage=await tab('/stream/synthetic_window',1100,1050);await windowPage.wait('typeof data!=="undefined" && !!data?.player');
    assert.equal(await windowPage.evaluate('document.getElementById("window-rate").textContent'),'Not complete yet');
    const advanceStarted=performance.now();assert.ok((await fixtureCommand('advance')).advanced);
    const after=await api('/api/players/'+channel),all=await api('/api/players');
    assert.notEqual(after.player.reading.event_id,original.player.reading.event_id);
    assert.equal(after.player.reading.exp,null);assert.equal(after.player.reading.estimated_exp,null); // Unresolved saved level evidence must stay unresolved.
    // Keep other tabs hidden: background updates are part of the regression.
    await overlay.wait(`data?.player?.reading?.event_id===${JSON.stringify(after.player.reading.event_id)}`);
    await board.wait(`data?.players.find(p=>p.channel===${JSON.stringify(channel)})?.reading?.event_id===${JSON.stringify(after.player.reading.event_id)}`);
    await detail.wait(`data?.player?.reading?.event_id===${JSON.stringify(after.player.reading.event_id)}`);
    const control=all.players.find(p=>p.channel==='synthetic_window');assert.equal(control.windows['5'].eligible,true);
    assert.equal(control.windows['5'].coverage_seconds.approximate,300);
    await windowPage.wait('data?.player?.windows["5"].eligible===true');
    const updateMilliseconds=performance.now()-advanceStarted;
    assert.match(await windowPage.evaluate('document.getElementById("rate").textContent'),/^~/);
    await board.evaluate('document.querySelector("[data-sort=exp_hour]").click()');
    await board.wait('document.querySelector(".entry[data-channel=synthetic_window]").dataset.rank==="1"');
    for(const page of [board,detail,overlay,windowPage])assert.equal(await page.evaluate('performance.getEntriesByType("navigation").length'),1);
    assert.equal(await detail.evaluate('document.getElementById("exp").textContent'),'—');
    assert.equal(await overlay.evaluate('document.getElementById("percentage").textContent'),'67.72%');
    assert.equal(await windowPage.evaluate('document.getElementById("exp").textContent'),'~1.07M');
    const estimatedOverlay=await tab('/live/overlay/synthetic_window',500,160);await estimatedOverlay.wait('typeof data!=="undefined" && !!data?.player');
    assert.equal(await estimatedOverlay.evaluate('document.getElementById("exp").textContent'),'~1.07M');
    await screenshot(board,'homepage-updated',1440,1050);await screenshot(estimatedOverlay,'overlay-million-estimate-synthetic',500,160);
    await screenshot(windowPage,'eligible-five-minute-control',1100,1050);
    if(verifyQuarantine){
      const stages=[];
      for(const [command,percentage,state] of [['decrease','67.71','pending_exp_decrease'],['confirm','67.55','corroborated_lower_baseline'],['recover','67.60','accepted_observation']]){
        assert.equal((await fixtureCommand(command)).stage,command);
        const actual=await api('/api/players/synthetic_window');stages.push(actual);
        assert.equal(actual.player.reading.percentage,percentage);assert.equal(actual.player.percentage_state.status,state);
        assert.equal(actual.player.windows['5'].eligible,false);assert.equal(actual.player.estimates.exp_per_hour,null);
        await windowPage.wait(`data?.player?.percentage_state?.status===${JSON.stringify(state)} && data?.player?.reading?.percentage===${JSON.stringify(percentage)}`);
        await estimatedOverlay.wait(`data?.player?.percentage_state?.status===${JSON.stringify(state)} && data?.player?.reading?.percentage===${JSON.stringify(percentage)}`);
        await board.wait(`data?.players.find(p=>p.channel==='synthetic_window')?.percentage_state?.status===${JSON.stringify(state)}`);
        if(command==='decrease'){
          assert.equal(await estimatedOverlay.evaluate('document.getElementById("status").textContent'),'Verifying EXP change');
          const advanced=await api('/dev/api/streams/synthetic_window/diagnostics');
          assert.equal(advanced.observations.at(-1).raw_text,'[67.50%]');
          assert.equal(advanced.observations.at(-1).percentage_review.public_eligible,false);
          await screenshot(estimatedOverlay,'pending-decrease-overlay',500,160);
        }
      }
      assert.equal(stages.at(-1).player.segment.difference_percentage_points,'0.05');
      for(const page of [board,windowPage,estimatedOverlay])assert.equal(await page.evaluate('performance.getEntriesByType("navigation").length'),1);
      await screenshot(windowPage,'confirmed-lower-baseline',1100,1050);
      writeFileSync(join(output,'quarantine-stages.json'),JSON.stringify(stages,null,2));
    }
    observed.push({before:original.player.reading,after:after.player.reading,syntheticWindow:control.windows['5'],updateMilliseconds});
    writeFileSync(join(output,'after.json'),JSON.stringify(all,null,2));
  }
  if(database){
    await board.command('Page.bringToFront');
    captureLog=openSync(join(output,'capture-terminal.txt'),'wx');
    const python=resolve(process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
    capture=spawn(python,['tools/shadow_capture.py','--db',resolve(database),'--tracking-channel',channel,'--file','samples/sample-stream3.mp4','--start','1186','--interval','16','--count','3','--experimental-neural-level','--output',join(output,'capture.jsonl')],{windowsHide:true,stdio:['ignore',captureLog,captureLog]});
    captureDone=new Promise((ok,no)=>{capture.on('error',no);capture.on('exit',code=>code===0?ok():no(new Error('Offline capture exit '+code)));});
    const started=Date.now();
    while(capture.exitCode===null && Date.now()-started<150000){
      const reading=await overlay.evaluate('data?.player?.reading');
      if(reading && observed.at(-1)?.event_id!==reading.event_id)observed.push({...reading,board:await board.evaluate('data?.players.find(p=>p.channel==='+JSON.stringify(channel)+')?.reading')});
      await delay(500);
    }
    assert.notEqual(capture.exitCode,null,'Existing bounded capture exceeded 150s');await captureDone;
    const after=await api('/api/players/'+channel);assert.notEqual(after.player.reading.event_id,original.player.reading.event_id);
    await overlay.wait(`data?.player?.reading?.event_id===${JSON.stringify(after.player.reading.event_id)}`);
    await board.wait(`data?.players.find(p=>p.channel===${JSON.stringify(channel)})?.reading?.event_id===${JSON.stringify(after.player.reading.event_id)}`);
    await detail.command('Page.bringToFront');
    await detail.wait(`data?.player?.reading?.event_id===${JSON.stringify(after.player.reading.event_id)}`);
    assert.equal(await overlay.evaluate('document.getElementById("progress").value'),after.player.reading.bp/100);
    assert.equal(await board.evaluate(`document.querySelector('.entry[data-channel="${channel}"] progress').value`),after.player.reading.bp/100);
    assert.equal(await overlay.evaluate('performance.getEntriesByType("navigation").length'),1);
    if(after.player.estimates.exp_per_hour){assert.match(await overlay.evaluate('document.getElementById("rate").textContent'),/^~/);}
    await board.evaluate('document.querySelector("[data-sort=exp_hour]").click()');
    await screenshot(board,'homepage-after-capture',1440,1050);await screenshot(overlay,'overlay-after-capture',500,160);
    await screenshot(detail,'character-after-capture',1440,1050);
    writeFileSync(join(output,'after.json'),JSON.stringify(after,null,2));
    assert.ok(observed.some(r=>r.event_id!==original.player.reading.event_id),'No polled observation update recorded');
  }
  assert.deepEqual(failures,[]);
  assert.ok(requests.every(request=>new URL(request).origin===url.origin || new URL(request).protocol==='data:'));
  writeFileSync(join(output,'verification.json'),JSON.stringify({before,observed,shots,failures,networkRequests:requests.length,actualCapture:!!database,
    syntheticWindowControl:verifyUpdates},null,2));
  console.log(`Verified ${before.players.length} SQLite rows${verifyUpdates?' (two saved streams + one synthetic window control)':''}, detail and 500×160 transparent overlay; ${observed.length} ${verifyUpdates?'verified update batches':'distinct polled readings'}; ${shots.length} screenshots.`);
} finally {
  if(capture?.exitCode===null)capture.kill();
  if(fixture){fixture.stdin.end();await new Promise(ok=>{if(fixture.exitCode!==null)return ok();fixture.once('exit',ok);setTimeout(()=>{fixture.kill();ok();},3000).unref();});}
  sockets.forEach(ws=>ws.close());child.kill();closeSync(browserLog);if(captureLog!==null)closeSync(captureLog);
}
