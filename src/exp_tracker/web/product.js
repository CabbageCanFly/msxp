"use strict";

const view=document.body.dataset.view;
const channel=view==='overlay'?location.pathname.split('/')[3]:view==='player'?location.pathname.split('/')[2]:null;
const endpoint=channel?`/api/players/${encodeURIComponent(channel)}`:'/api/players';
const numbers=new Intl.NumberFormat('en-US'),compact=new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1});
const compactExp=new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:2});
const sorts={exp_hour:'Estimated pace over the selected window; community requirements are provisional.',
  level:'Last observed levels, including old readings. A * marks provisional level evidence.',
  movement:'Displayed change within the selected window. Incomplete or interrupted coverage is not ranked.'};
let data=null,receivedAt=0,failed=false,sort='level',windowMinutes=5,pollTimer=null,activeController=null;
const el=id=>document.getElementById(id);
function node(tag,className,text) { const n=document.createElement(tag);if(className)n.className=className;if(text!=null)n.textContent=text;return n; }
function ageText(seconds) { if(seconds==null)return 'No reading yet';if(seconds<60)return `${Math.floor(seconds)}s ago`;if(seconds<3600)return `${Math.floor(seconds/60)}m ago`;if(seconds<86400)return `${Math.floor(seconds/3600)}h ago`;return `${Math.floor(seconds/86400)}d ago`; }
function expText(value) { return value==null?'—':numbers.format(BigInt(value)); }
function displayedExp(r) {
  return r?.exp!=null?(r.evidence==='grammar_recovered'?'≈ ':'')+expText(r.exp):
    r?.estimated_exp?`≈${compactExp.format(r.estimated_exp.value.approximate)}`:'—';
}
function expTitle(r) {
  if(r?.estimated_exp) {
    const e=r.estimated_exp;
    return `Estimated from observed percentage and provisional level ${e.level_evidence.value} requirement, not read directly by OCR. ${Object.entries(e.hypotheses).map(([rule,b])=>`${rule}: ${b.count?`${numbers.format(b.min)}–${numbers.format(b.max)} EXP`:'no compatible within-level integer'}`).join('; ')}. Community table ${e.requirement.version}; bounds exclude OCR/table errors.${r.exp_validity?.status==='invalid'?' Contradictory OCR integer withheld.':''}`;
  }
  return r?.exp_validity?.status==='invalid'?'Absolute EXP withheld: inconsistent with level and percentage under both display hypotheses':r?.exp==null?'Absolute EXP unavailable; level or requirement unresolved':r.evidence==='grammar_recovered'?'Unverified grammar-recovered proposal':'Original strict OCR candidate; unverified';
}
function sourceText(p) { return `${p.source_kind==='file'?'Video · ':p.source_kind==='twitch'?'ttv/':''}${p.channel}`; }
function displayLevel(p) { return p.display_level?.evidence ?? p.reading?.level; }
function lastKnown(p) { const l=p.display_level;return !!l && (l.last_known || l.age_seconds+(performance.now()-receivedAt)/1000>p.stale_after_seconds); }
function levelText(p) { const level=displayLevel(p);return level?.value==null?'—':`${level.value}${lastKnown(p)?'†':['single_reader','provisional_neural','recent_context'].includes(level.status)?'*':''}`; }
function levelTitle(p) {
  const l=displayLevel(p),saved=p.display_level;
  if(saved)return `${lastKnown(p)?'Last-known':'Recently supported'} level; ${ageText(saved.age_seconds+(performance.now()-receivedAt)/1000)}; ${saved.evidence.reason}; ${saved.timestamp}. Display only, not evidence for calculations; OCR remains unverified.`;
  return l?.status==='conflict'?`Level readers disagree: ${l.visual} / ${l.neural}`:l?.value!=null?'Provisional OCR level; unverified':'Waiting for supported level evidence';
}
function earlyText(p) {
  const early=p.early_pace;
  if(!early?.active || current(p).stale || failed)return null;
  const e=early.estimates,segment=early.segment;
  const rate=e.exp_per_hour?`~${compact.format(e.exp_per_hour.value.approximate)} EXP/hour`:e.percentage_per_hour?`~${e.percentage_per_hour.value.approximate.toFixed(2)} pp/hour`:null;
  return rate?`${rate} · early estimate · ${segment.readings} readings / ${Math.round(segment.span_seconds.approximate)}s`:null;
}
function current(p) {
  const age=p.age_seconds==null?null:p.age_seconds+(performance.now()-receivedAt)/1000;
  const review=p.percentage_state;
  const deadline=review?.verification_deadline || review?.confirmation_deadline;
  const expired=review?.public_eligible===false && deadline && p.reading?.timestamp && age>(Date.parse(deadline)-Date.parse(p.reading.timestamp))/1000;
  const stale=p.stale || expired || age==null || age>p.stale_after_seconds;
  const metrics=!stale && !failed?(view==='overlay'?p.estimates:selectedWindow(p)?.eligible?selectedWindow(p).estimates:null):null;
  return {age,stale,metrics};
}
function selectedWindow(p) { return p.windows?.[String(windowMinutes)]; }
function windowNote(p) {
  const w=selectedWindow(p);
  if(current(p).stale || failed)return 'Waiting for fresh readings';
  if(w?.eligible)return `Last ${windowMinutes} min · ${Math.round(w.coverage_seconds.approximate)}s observed · ${w.readings} readings`;
  if(w?.state==='unavailable')return 'History interrupted · waiting for comparable readings';
  return `Building ${windowMinutes}m history${p.segment?.readings>=2?` · recent +${p.segment.difference_percentage_points} pp / ${Math.round(p.segment.span_seconds.approximate)}s`:''}`;
}
function statusText(p) {
  const s=current(p),state=p.activity?.state;
  if(failed)return 'Updates delayed';
  if(!p.reading)return p.latest_attempt_status==='capture_failed'?'Capture unavailable':'Waiting for EXP';
  if(s.stale)return 'Updates delayed';
  if(p.percentage_state?.public_eligible===false && p.percentage_state?.pending_since)return 'Verifying EXP change';
  if(p.latest_attempt_status==='capture_failed')return 'Capture interrupted';
  if(state==='stopped' && p.activity.completion)return ({completed:'Capture complete',interrupted:'Capture interrupted',failed:'Capture stopped'})[p.activity.completion] ?? 'Capture paused';
  return ({running:'Capturing',waiting:'Waiting for next capture',capture_delayed:'Capture delayed',capture_failing:'Capture interrupted',
    stopped:'Capture paused',coordinator_stopped:'Capture paused',previous_unfinished_run:'Capture stopped'})[state] ?? 'Capture paused';
}
function etaText(value) { if(!value)return '—';const m=Math.max(5,Math.ceil(value.seconds.approximate/300)*5);if(m<60)return `~${m}m`;if(m<1440)return `~${Math.floor(m/60)}h ${m%60}m`;return `~${Math.floor(m/1440)}d ${Math.floor(m%1440/60)}h`; }
function rateTitle(rate) {
  if(!rate)return view==='overlay'?'Building comparable history; estimates require three readings across at least 30 seconds.':`Building ${windowMinutes}-minute history; at least 90% contiguous coverage, with no interpolation.`;
  return `Experimental estimate, not earned EXP. ${Object.entries(rate.hypotheses).map(([rule,b])=>`${rule}: ${numbers.format(Math.round(b.lower.approximate))}–${numbers.format(Math.round(b.upper.approximate))} EXP/h`).join('; ')}. Community requirement ${rate.requirement.version}; quantization bounds exclude OCR errors.`;
}
function metricValue(p,key) {
  if(key==='level')return displayLevel(p)?.value ?? null;
  if(current(p).stale || failed)return null;
  if(key==='exp_hour')return current(p).metrics?.exp_per_hour?.value.approximate ?? null;
  return selectedWindow(p)?.eligible?Number(selectedWindow(p).difference_percentage_points):null;
}
function ranked(players,key) {
  const rows=players.map(player=>({player,value:metricValue(player,key)})).sort((a,b)=>(a.value==null)-(b.value==null)||(b.value??0)-(a.value??0)||a.player.channel.localeCompare(b.player.channel));
  let rank=null,previous=null;
  return rows.map((entry,i)=>{if(entry.value!=null && entry.value!==previous)rank=i+1;previous=entry.value;return {...entry,rank:entry.value==null?null:rank};});
}
function entry({player:p,value,rank}) {
  const r=p.reading,s=current(p),row=node('li','entry');row.dataset.channel=p.channel;row.dataset.rank=rank??'';row.dataset.stale=String(s.stale);row.dataset.state=s.stale || failed?'stale':['running','waiting'].includes(p.activity?.state)?'tracking':'paused';
  const badge=node('span','rank',rank??'—');badge.dataset.medal=rank!=null && rank<=3?rank:'';badge.setAttribute('aria-label',rank==null?'Unranked: insufficient data':`Experimental local rank ${rank}`);
  const level=node('span','level');level.append(node('small','','LV.'),node('strong','',levelText(p)));level.title=levelTitle(p);if(lastKnown(p))level.append(node('small','level-note','last known'));
  const identity=node('div','identity'),name=node('a','character',p.character?.label ?? 'Character not selected');name.href=`/stream/${p.channel}`;name.title=name.textContent;
  identity.append(name,node('span','channel',sourceText(p)),node('span','status',statusText(p)));
  const section=node('div','exp-section'),bar=node('div','exp-bar'),progress=node('progress');progress.max=100;progress.value=r?r.bp/100:0;progress.hidden=!r;progress.setAttribute('aria-label',`${p.character?.label ?? p.channel} observed EXP percentage`);
  bar.dataset.missing=String(!r);bar.dataset.recovered=String(r?.evidence==='grammar_recovered');
  const label=node('span','exp-label');label.title=expTitle(r);label.append(node('small','','EXP'),node('span','exp-number',displayedExp(r)),node('span','percentage',r?`[${r.percentage}%]`:'Waiting for EXP'));
  bar.append(progress,label);
  section.append(bar,node('div','exp-detail',`${!selectedWindow(p)?.eligible && earlyText(p) || windowNote(p)} · ${r?'Updated '+ageText(s.age):'No reading yet'}`));
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
  el('ranking-note').textContent=sorts[sort]+(sort==='level'?'':` ${windowMinutes}-minute window ending at each latest capture; ≥90% contiguous coverage, no interpolation.`);
  el('connection').textContent=failed?'Connection interrupted · showing older readings':'Updates automatically · local tracker';
  document.querySelectorAll('[data-sort]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.sort===sort)));
  document.querySelectorAll('[data-window]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.window)===windowMinutes)));
}
function renderPlayer() {
  const p=data?.player,r=p?.reading;
  if(!p) { el('status').textContent=failed?'Tracker unavailable':'Waiting for EXP';return; }
  const s=current(p),m=s.metrics;
  if(view==='overlay') { el('streamer').textContent=sourceText(p);el('character').textContent=p.character?.label ?? p.channel;el('character').title=el('character').textContent;el('streamer').title=sourceText(p);el('card').dataset.stale=String(s.stale||failed);el('card').dataset.recovered=String(r?.evidence==='grammar_recovered'); }
  else { el('player-name').textContent=p.character?.label ?? p.channel;el('player-source').textContent=sourceText(p); }
  el('level').textContent=`Lv. ${levelText(p)}`;el('level').title=levelTitle(p);
  el('level').dataset.lastKnown=String(lastKnown(p));
  el('progress').value=r?r.bp/100:0;
  el('progress').hidden=!r;
  el('exp').textContent=displayedExp(r);el('exp').title=expTitle(r);
  el('percentage').textContent=r?`${r.percentage}%`:'—';
  el('status').textContent=statusText(p)+(view==='overlay' && lastKnown(p)?' · † last-known Lv':'');
  el('age').textContent=r?`Updated ${ageText(s.age)}`:'';el('age').title=r?.timestamp ?? '';
  const movement=view==='overlay'?(p.segment?.readings>=2?p.segment.difference_percentage_points:null):selectedWindow(p)?.eligible?selectedWindow(p).difference_percentage_points:null;
  el('movement').textContent=!s.stale && !failed && movement!=null?`+${movement} pp`:'—';
  el('rate').textContent=m?.exp_per_hour?`~${compact.format(m.exp_per_hour.value.approximate)}`:'—';el('rate').title=(view==='overlay' && earlyText(p)?earlyText(p)+'. ':'')+rateTitle(m?.exp_per_hour);
  el('pp-rate').textContent=m?.percentage_per_hour?`~${m.percentage_per_hour.value.approximate.toFixed(2)}`:'—';
  el('pp-rate').title='Experimental displayed percentage points/hour; zero displayed change does not prove zero actual EXP.';
  el('eta').textContent=etaText(m?.eta);el('eta').title=m?.eta?'Provisional same-level percentage estimate at the last reading, not a countdown. Both quantization hypotheses require positive pace.':'Building positive, comparable history';
  if(view==='overlay') for(const id of ['exp','movement','rate','pp-rate','eta']) el(id).dataset.size=el(id).textContent.length>(id==='exp'?16:8)?'long':'normal';
  if(view==='player') {
    const early=p.early_pace,text=earlyText(p);
    el('early-value').textContent=text ?? (early?.segment?'Estimate paused':'Building comparable history');
    el('early-note').textContent=text?'Experimental current segment · separate from completed-window comparisons.':early?.segment?'Last eligible estimate retained for inspection; waiting for fresh, connected readings.':'Needs 3 supported same-level readings over 30s; interruptions restart the segment.';
    el('early-value').title=early?.segment?`${early.segment.start} – ${early.segment.end}; ${early.segment.readings} readings. ${rateTitle(early.estimates?.exp_per_hour)} Historical value: ${early.estimates?.exp_per_hour?.value.approximate ?? early.estimates?.percentage_per_hour?.value.approximate} ${early.estimates?.exp_per_hour?'EXP/h':'pp/h'}. Bounds exclude OCR errors.`:'';
    el('level-note').textContent=lastKnown(p)?`Last-known level · ${ageText(p.display_level.age_seconds+(performance.now()-receivedAt)/1000)}`:'Provisional visual level';
    el('level-note').title=levelTitle(p);
    el('movement-label').textContent=`Last ${windowMinutes} min`;
    el('segment-note').textContent=windowNote(p)+'. Window estimates need ≥90% uninterrupted same-level coverage and a first reading within one capture interval of the boundary. Local capture time; no missing progress is filled in.';
    document.querySelectorAll('[data-window]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.window)===windowMinutes)));
  }
}
function drawHistory() {
  const svg=el('history-chart');svg.replaceChildren();
  delete svg.dataset.start;delete svg.dataset.end;
  const width=Math.max(300,Math.min(960,svg.clientWidth||960)),plotWidth=width-100;
  svg.setAttribute('viewBox',`0 0 ${width} 230`);
  const all=(data?.history ?? []).map(r=>({...r,time:Date.parse(r.timestamp)})).filter(r=>Number.isFinite(r.time));
  const anchor=all.length?Math.max(...all.map(p=>p.time)):0;
  const points=all.filter(p=>p.time>=anchor-windowMinutes*60000);
  const values=points.filter(p=>p.reading).map(p=>p.reading.bp/100),min=values.length?Math.min(...values):0,max=values.length?Math.max(...values):100;
  function shape(tag,attrs,title) { const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(title)n.append(node('title','',title));svg.append(n);return n; }
  if(!points.length) { shape('text',{x:30,y:100}).textContent='Your next adventure starts here.';return; }
  const first=Math.min(...points.map(p=>p.time)),last=Math.max(...points.map(p=>p.time));
  const x=t=>60+(t-first)/Math.max(1,last-first)*plotWidth,y=v=>175-(v-min)/Math.max(.02,max-min)*140;
  let gaps=0;
  points.forEach((p,i)=>{
    const previous=points[i-1];
    if(previous && p.time-previous.time>previous.interval_seconds*1500) { gaps++;shape('rect',{x:x(previous.time),y:20,width:x(p.time)-x(previous.time),height:160,class:'gap'}); }
    if(previous && p.level.value!==previous.level.value) shape('line',{x1:x(p.time),x2:x(p.time),y1:p.level.value==null || previous.level.value==null?170:20,y2:180,class:'boundary'},'Level context changed or unavailable');
    if(p.reading) shape('circle',{cx:x(p.time),cy:y(p.reading.bp/100),r:4,class:p.reading.evidence==='grammar_recovered'?'recovered':'sample'},`${p.timestamp} · ${p.reading.percentage}% · ${p.reading.evidence}`);
    else shape('path',{d:`M${x(p.time)-3} 185l6 6m0-6-6 6`,class:'missing'},`${p.timestamp} · reading unavailable`);
  });
  shape('text',{x:10,y:32}).textContent=max.toFixed(2)+'%';shape('text',{x:10,y:180}).textContent=min.toFixed(2)+'%';
  const ticks=width<600?3:5;
  for(let i=0;i<ticks;i++) {
    const time=first+(last-first)*i/(ticks-1);
    shape('text',{x:60+plotWidth*i/(ticks-1),y:218,'text-anchor':i===0?'start':i===ticks-1?'end':'middle'}).textContent=new Date(time).toISOString().slice(11,19);
  }
  svg.dataset.start=new Date(first).toISOString();svg.dataset.end=new Date(last).toISOString();
  el('history-note').textContent=`${points.length} attempts in the ${windowMinutes} min ending at the last capture · ${Math.round((last-first)/1000)}s displayed · UTC · ${gaps} sampling gaps${current(data.player).stale?' · archived/stale readings':''}${data.truncated?' · earlier history available in Advanced':''}. Points only; no interpolation.`;
}
async function poll() {
  if(activeController)return;
  clearTimeout(pollTimer);
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),5000),requested=performance.now();
  activeController=controller;
  try {
    const response=await fetch(endpoint,{cache:'no-store',signal:controller.signal});if(!response.ok)throw new Error();
    data=await response.json();receivedAt=requested;failed=false;
    if(view==='board')renderBoard();else { renderPlayer();if(view==='player')drawHistory(); }
  } catch { failed=true;if(view==='board')renderBoard();else renderPlayer(); }
  finally { clearTimeout(timeout);activeController=null;pollTimer=setTimeout(poll,2000); }
}
document.addEventListener?.('visibilitychange',()=>{if(!document.hidden)poll();});
globalThis.addEventListener?.('pageshow',poll);
if(view==='board') document.querySelectorAll('[data-sort]').forEach(button=>button.addEventListener('click',()=>{sort=button.dataset.sort;if(sort in sorts)renderBoard();}));
document.querySelectorAll('[data-window]').forEach(button=>button.addEventListener('click',()=>{
  const minutes=Number(button.dataset.window);if(![5,10,15,30].includes(minutes))return;windowMinutes=minutes;
  if(view==='board')renderBoard();else if(data?.player){renderPlayer();drawHistory();}
}));
if(view==='player') {
  globalThis.addEventListener?.('resize',drawHistory);
  const url=`${location.origin}/live/overlay/${encodeURIComponent(channel)}`;
  el('overlay-link').href=url;el('diagnostics').href=`/dashboard/${channel}`;el('history-link').href=`/dashboard/${channel}`;
  el('copy-overlay').addEventListener('click',async()=>{try {await navigator.clipboard.writeText(url);el('copy-status').textContent='Copied · use a 500 × 160 Browser Source';}catch{el('copy-status').textContent='Copy the Open OBS overlay link · 500 × 160';}});
}
poll();setInterval(()=>{if(view==='board')renderBoard();else renderPlayer();},1000);
