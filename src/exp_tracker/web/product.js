"use strict";

const view=document.body.dataset.view;
const channel=view==='overlay'?location.pathname.split('/')[3]:view==='player'?location.pathname.split('/')[2]:null;
const endpoint=channel?`/api/players/${encodeURIComponent(channel)}`:'/api/players';
const numbers=new Intl.NumberFormat('en-US'),compact=new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1});
const sorts={exp_hour:'Estimated pace from each eligible recent segment; community requirements are provisional.',
  level:'Last observed levels, including old readings. A * marks evidence from one OCR reader.',
  movement:'Displayed change in each uninterrupted recent segment. Durations differ; this is not a fixed-window comparison.'};
let data=null,receivedAt=0,failed=false,sort='level';
const el=id=>document.getElementById(id);
function node(tag,className,text) { const n=document.createElement(tag);if(className)n.className=className;if(text!=null)n.textContent=text;return n; }
function ageText(seconds) { if(seconds==null)return 'No reading yet';if(seconds<60)return `${Math.floor(seconds)}s ago`;if(seconds<3600)return `${Math.floor(seconds/60)}m ago`;if(seconds<86400)return `${Math.floor(seconds/3600)}h ago`;return `${Math.floor(seconds/86400)}d ago`; }
function expText(value) { return value==null?'—':numbers.format(BigInt(value)); }
function sourceText(p) { return `${p.source_kind==='file'?'Video · ':p.source_kind==='twitch'?'ttv/':''}${p.channel}`; }
function levelText(p) { const level=p.reading?.level;return level?.value==null?'—':`${level.value}${level.status==='single_reader'?'*':''}`; }
function levelTitle(p) { const l=p.reading?.level;return l?.status==='conflict'?`Level readers disagree: ${l.visual} / ${l.neural}`:l?.status==='single_reader'?'One OCR reader; unverified level':'OCR level evidence; unverified'; }
function current(p) {
  const age=p.age_seconds==null?null:p.age_seconds+(performance.now()-receivedAt)/1000;
  const stale=p.stale || age==null || age>p.stale_after_seconds;
  const metrics=!stale && !failed?p.estimates:null;
  return {age,stale,metrics};
}
function statusText(p) {
  const s=current(p),state=p.activity?.state;
  if(failed)return 'Updates delayed';
  if(!p.reading)return p.latest_attempt_status==='capture_failed'?'Capture unavailable':'Waiting for EXP';
  if(s.stale)return 'Updates delayed';
  if(p.latest_attempt_status==='capture_failed')return 'Capture interrupted';
  return ({running:'Capturing',waiting:'Waiting for next capture',capture_delayed:'Capture delayed',capture_failing:'Capture interrupted',
    stopped:'Capture paused',coordinator_stopped:'Capture paused',previous_unfinished_run:'Capture stopped'})[state] ?? 'Capture paused';
}
function etaText(value) { if(!value)return '—';const m=Math.max(5,Math.ceil(value.seconds.approximate/300)*5);if(m<60)return `~${m}m`;if(m<1440)return `~${Math.floor(m/60)}h ${m%60}m`;return `~${Math.floor(m/1440)}d ${Math.floor(m%1440/60)}h`; }
function rateTitle(rate) {
  if(!rate)return 'Building comparable history; estimates require three readings across at least 30 seconds.';
  return `Experimental estimate, not earned EXP. ${Object.entries(rate.hypotheses).map(([rule,b])=>`${rule}: ${numbers.format(Math.round(b.lower.approximate))}–${numbers.format(Math.round(b.upper.approximate))} EXP/h`).join('; ')}. Community requirement ${rate.requirement.version}; quantization bounds exclude OCR errors.`;
}
function metricValue(p,key) {
  if(key==='level')return p.reading?.level?.value ?? null;
  if(current(p).stale || failed)return null;
  if(key==='exp_hour')return current(p).metrics?.exp_per_hour?.value.approximate ?? null;
  return p.segment && p.segment.readings>=2?Number(p.segment.difference_percentage_points):null;
}
function ranked(players,key) {
  const rows=players.map(player=>({player,value:metricValue(player,key)})).sort((a,b)=>(a.value==null)-(b.value==null)||(b.value??0)-(a.value??0)||a.player.channel.localeCompare(b.player.channel));
  let rank=null,previous=null;
  return rows.map((entry,i)=>{if(entry.value!=null && entry.value!==previous)rank=i+1;previous=entry.value;return {...entry,rank:entry.value==null?null:rank};});
}
function entry({player:p,value,rank}) {
  const r=p.reading,s=current(p),row=node('li','entry');row.dataset.channel=p.channel;row.dataset.rank=rank??'';row.dataset.stale=String(s.stale);row.dataset.state=s.stale || failed?'stale':['running','waiting'].includes(p.activity?.state)?'tracking':'paused';
  const badge=node('span','rank',rank??'—');badge.dataset.medal=rank!=null && rank<=3?rank:'';badge.setAttribute('aria-label',rank==null?'Unranked: insufficient data':`Experimental local rank ${rank}`);
  const level=node('span','level');level.append(node('small','','LV.'),node('strong','',levelText(p)));level.title=levelTitle(p);
  const identity=node('div','identity'),name=node('a','character',p.character?.label ?? 'Character not selected');name.href=`/stream/${p.channel}`;name.title=name.textContent;
  identity.append(name,node('span','channel',sourceText(p)),node('span','status',statusText(p)));
  const section=node('div','exp-section'),bar=node('div','exp-bar'),progress=node('progress');progress.max=100;progress.value=r?r.bp/100:0;progress.hidden=!r;progress.setAttribute('aria-label',`${p.character?.label ?? p.channel} observed EXP percentage`);
  bar.dataset.missing=String(!r);bar.dataset.recovered=String(r?.evidence==='grammar_recovered');
  const label=node('span','exp-label');label.append(node('small','',r?.evidence==='grammar_recovered'?'≈ EXP':'EXP'),node('span','exp-number',expText(r?.exp)),node('span','percentage',r?`[${r.percentage}%]`:'Waiting for EXP'));
  bar.append(progress,label);
  const movement=!s.stale && p.segment && p.segment.readings>=2?`+${p.segment.difference_percentage_points} pp · ${Math.round(p.segment.span_seconds.approximate)}s segment`:'Building recent history';
  section.append(bar,node('div','exp-detail',`${movement} · ${r?'Updated '+ageText(s.age):'No reading yet'}`));
  const score=node('div','score');score.append(node('strong','score-value',value==null?'—':sort==='level'?String(value):sort==='movement'?`+${value.toFixed(2)}`:`~${compact.format(value)}`),
    node('small','score-label',sort==='level'?'last observed level':sort==='movement'?'percentage points':'estimated EXP / hour'));
  score.title=sort==='exp_hour'?rateTitle(s.metrics?.exp_per_hour):sort==='level'?levelTitle(p):'Displayed percentage change only; no exact earned EXP is inferred.';
  row.append(badge,level,identity,section,score);return row;
}
function renderBoard() {
  const rows=ranked(data?.players ?? [],sort);
  const focus=document.activeElement?.closest?.('#entries a')?.getAttribute('href');
  el('entries').replaceChildren(...rows.map(entry));
  if(focus) [...el('entries').querySelectorAll('a')].find(a=>a.getAttribute('href')===focus)?.focus({preventScroll:true});
  el('empty').hidden=rows.length>0 || !data;
  el('board-count').textContent=data?`${rows.length} character${rows.length===1?'':'s'} · saved stream readings`:failed?'Tracker unavailable':'Loading your party…';
  el('ranking-count').textContent=`${rows.filter(r=>r.rank!=null).length} eligible · ${rows.length} shown`;
  el('ranking-note').textContent=sorts[sort];
  el('connection').textContent=failed?'Connection interrupted · showing older readings':'Updates automatically · local tracker';
  document.querySelectorAll('[data-sort]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.sort===sort)));
}
function renderPlayer() {
  const p=data?.player,r=p?.reading;
  if(!p) { el('status').textContent=failed?'Tracker unavailable':'Waiting for EXP';return; }
  const s=current(p),m=s.metrics;
  if(view==='overlay') { el('streamer').textContent=sourceText(p);el('character').textContent=p.character?.label ?? p.channel;el('character').title=el('character').textContent;el('streamer').title=sourceText(p);el('card').dataset.stale=String(s.stale||failed);el('card').dataset.recovered=String(r?.evidence==='grammar_recovered'); }
  else { el('player-name').textContent=p.character?.label ?? p.channel;el('player-source').textContent=sourceText(p); }
  el('level').textContent=`Lv. ${levelText(p)}`;el('level').title=levelTitle(p);
  el('progress').value=r?r.bp/100:0;
  el('progress').hidden=!r;
  el('exp').textContent=(r?.evidence==='grammar_recovered'?'≈ ':'')+expText(r?.exp);
  el('exp').title=r?.exp==null?'Absolute EXP unavailable; percentage does not reconstruct EXP':r.evidence==='grammar_recovered'?'Unverified grammar-recovered proposal':'Original strict OCR candidate; unverified';
  el('percentage').textContent=r?`${r.percentage}%`:'—';
  el('status').textContent=statusText(p);
  el('age').textContent=r?`Updated ${ageText(s.age)}`:'';el('age').title=r?.timestamp ?? '';
  el('movement').textContent=!s.stale && !failed && p.segment?.readings>=2?`+${p.segment.difference_percentage_points} pp`:'—';
  el('rate').textContent=m?.exp_per_hour?`~${compact.format(m.exp_per_hour.value.approximate)}`:'—';el('rate').title=rateTitle(m?.exp_per_hour);
  el('pp-rate').textContent=m?.percentage_per_hour?`~${m.percentage_per_hour.value.approximate.toFixed(2)}`:'—';
  el('pp-rate').title='Experimental displayed percentage points/hour; zero displayed change does not prove zero actual EXP.';
  el('eta').textContent=etaText(m?.eta);el('eta').title=m?.eta?'Provisional same-level percentage estimate at the last reading, not a countdown. Both quantization hypotheses require positive pace.':'Building positive, comparable history';
  if(view==='overlay') for(const id of ['exp','movement','rate','pp-rate','eta']) el(id).dataset.size=el(id).textContent.length>(id==='exp'?16:8)?'long':'normal';
  if(view==='player') {
    el('segment-note').textContent=p.segment?`Recent segment · ${p.segment.readings} readings across ${Math.round(p.segment.span_seconds.approximate)}s · ${p.segment.evidence_counts.grammar_recovered} recovered. Estimates use displayed percentages and local capture time; gaps and level changes start a new segment.`:'Building comparable history. Missing readings and uncertain levels interrupt pace; no session earnings are invented.';
  }
}
function drawHistory() {
  const svg=el('history-chart');svg.replaceChildren();
  const points=(data?.history ?? []).map(r=>({...r,time:Date.parse(r.timestamp)})).filter(r=>Number.isFinite(r.time));
  const values=points.filter(p=>p.reading).map(p=>p.reading.bp/100),min=values.length?Math.min(...values):0,max=values.length?Math.max(...values):100;
  function shape(tag,attrs,title) { const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(title)n.append(node('title','',title));svg.append(n);return n; }
  if(!points.length) { shape('text',{x:30,y:100}).textContent='Your next adventure starts here.';return; }
  const first=Math.min(...points.map(p=>p.time)),last=Math.max(...points.map(p=>p.time));
  const x=t=>70+(t-first)/Math.max(1,last-first)*850,y=v=>175-(v-min)/Math.max(.02,max-min)*140;
  let gaps=0;
  points.forEach((p,i)=>{
    const previous=points[i-1];
    if(previous && p.time-previous.time>previous.interval_seconds*1500) { gaps++;shape('rect',{x:x(previous.time),y:20,width:x(p.time)-x(previous.time),height:160,class:'gap'}); }
    if(previous && (p.level.value==null || previous.level.value==null || p.level.value!==previous.level.value)) shape('line',{x1:x(p.time),x2:x(p.time),y1:20,y2:180,class:'boundary'},'Level context changed or unavailable');
    if(p.reading) shape('circle',{cx:x(p.time),cy:y(p.reading.bp/100),r:4,class:p.reading.evidence==='grammar_recovered'?'recovered':'sample'},`${p.timestamp} · ${p.reading.percentage}% · ${p.reading.evidence}`);
    else shape('path',{d:`M${x(p.time)-3} 185l6 6m0-6-6 6`,class:'missing'},`${p.timestamp} · reading unavailable`);
  });
  shape('text',{x:10,y:32}).textContent=max.toFixed(2)+'%';shape('text',{x:10,y:180}).textContent=min.toFixed(2)+'%';
  shape('text',{x:70,y:218}).textContent=new Date(first).toISOString().slice(11,19)+' UTC';shape('text',{x:920,y:218,'text-anchor':'end'}).textContent=new Date(last).toISOString().slice(11,19)+' UTC';
  el('history-note').textContent=`${points.length} saved attempts · ${gaps} sampling gaps${data.truncated?' · earlier history available in Advanced':''}. Points only; no progress is assigned between missing observations.`;
}
async function poll() {
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),5000),requested=performance.now();
  try {
    if(document.hidden && view!=='overlay')return;
    const response=await fetch(endpoint,{cache:'no-store',signal:controller.signal});if(!response.ok)throw new Error();
    data=await response.json();receivedAt=requested;failed=false;
    if(view==='board')renderBoard();else { renderPlayer();if(view==='player')drawHistory(); }
  } catch { failed=true;if(view==='board')renderBoard();else renderPlayer(); }
  finally { clearTimeout(timeout);setTimeout(poll,document.hidden && view!=='overlay'?10000:2000); }
}
if(view==='board') document.querySelectorAll('[data-sort]').forEach(button=>button.addEventListener('click',()=>{sort=button.dataset.sort;if(sort in sorts)renderBoard();}));
if(view==='player') {
  const url=`${location.origin}/live/overlay/${encodeURIComponent(channel)}`;
  el('overlay-link').href=url;el('diagnostics').href=`/dashboard/${channel}`;el('history-link').href=`/dashboard/${channel}`;
  el('copy-overlay').addEventListener('click',async()=>{try {await navigator.clipboard.writeText(url);el('copy-status').textContent='Copied · use a 500 × 160 Browser Source';}catch{el('copy-status').textContent='Copy the Open OBS overlay link · 500 × 160';}});
}
poll();setInterval(()=>{if(view==='board')renderBoard();else renderPlayer();},1000);
