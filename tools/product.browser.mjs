// Real localhost HTTP + SQLite + optional existing local-video capture. No API fixtures.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync,mkdirSync,mkdtempSync,readFileSync,writeFileSync,openSync,closeSync} from 'node:fs';
import {resolve,join,sep} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';

const [base='http://127.0.0.1:8765',directory,databaseArgument,channel='offline_window']=process.argv.slice(2);
const database=databaseArgument==='-'?null:databaseArgument;
const url=new URL(base);assert.equal(url.hostname,'127.0.0.1');assert.match(channel,/^[A-Za-z0-9_]{1,25}$/);
const output=resolve(directory);assert.ok(['private','artifacts'].some(root=>output.startsWith(resolve(root)+sep)));
mkdirSync(output,{recursive:false});
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
  if(recent.start)assert.ok(Date.parse(recent.end)-Date.parse(recent.start)<=300000);
  assert.equal(await detail.evaluate('document.getElementById("movement-label").textContent'),'Last 5 min');
  if(!original.player.windows['5'].eligible)assert.equal(await detail.evaluate('document.getElementById("rate").textContent'),'—');
  await screenshot(detail,'character-desktop',1440,1050);
  await screenshot(detail,'character-mobile',390,1200);
  await detail.evaluate('document.querySelectorAll("[data-window]")[2].click()');
  assert.equal(await detail.evaluate('document.getElementById("movement-label").textContent'),'Last 15 min');
  await screenshot(detail,'character-15-minute',1440,1050);
  await detail.evaluate('document.querySelectorAll("[data-window]")[0].click()');
  await detail.command('Page.bringToFront');await delay(2300);
  assert.ok(await detail.evaluate('performance.getEntriesByType("resource").filter(r=>r.name.includes("/api/players/")).length>=2'));
  assert.ok(await overlay.evaluate('performance.getEntriesByType("resource").filter(r=>r.name.includes("/api/players/")).length>=2'));
  const observed=[];
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
  writeFileSync(join(output,'verification.json'),JSON.stringify({before,observed,shots,failures,networkRequests:requests.length,actualCapture:!!database},null,2));
  console.log(`Verified ${before.players.length} real-data rows, detail and 500×160 transparent overlay; ${observed.length} distinct polled readings; ${shots.length} screenshots.`);
} finally {
  if(capture?.exitCode===null)capture.kill();
  sockets.forEach(ws=>ws.close());child.kill();closeSync(browserLog);if(captureLog!==null)closeSync(captureLog);
}
