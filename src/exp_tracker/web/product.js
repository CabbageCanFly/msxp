"use strict";

const view=document.body.dataset.view;
const channel=view==='overlay'?location.pathname.split('/')[3]:view==='player'?location.pathname.split('/')[2]:null;
const endpoint=channel?`/api/players/${encodeURIComponent(channel)}`:'/api/players';
const numbers=new Intl.NumberFormat('en-US'),shortNumber=new Intl.NumberFormat('en-US',{maximumSignificantDigits:3});
const sorts={exp_hour:'Estimated pace over the selected window; community requirements are provisional.',
  level:'Latest supported character levels. Hover for the reading time.',
  movement:'Displayed change within the selected window. Incomplete or interrupted coverage is not ranked.'};
let data=null,receivedAt=0,failed=false,sort='level',windowMinutes=5,chartMode='exp',bucketSeconds=60,pollTimer=null,activeController=null;
const el=id=>document.getElementById(id);
function node(tag,className,text) { const n=document.createElement(tag);if(className)n.className=className;if(text!=null)n.textContent=text;return n; }
function ageText(seconds) { if(seconds==null)return 'No reading yet';if(seconds<60)return `${Math.floor(seconds)}s ago`;if(seconds<3600)return `${Math.floor(seconds/60)}m ago`;if(seconds<86400)return `${Math.floor(seconds/3600)}h ago`;return `${Math.floor(seconds/86400)}d ago`; }
function expText(value) { if(value==null)return '—';const n=Number(value),scale=n>=1e9?1e9:n>=1e6?1e6:n>=1e3?1e3:1;return (scale===1?numbers:shortNumber).format(n/scale)+({1:'',1000:'K',1000000:'M',1000000000:'B'}[scale]); }
function movementText(summary) { return summary?.estimated_exp?`+${expText(summary.estimated_exp.value.approximate)} EXP`:summary?.difference_percentage_points!=null?`+${summary.difference_percentage_points}%`:'—'; }
function displayedExp(r) {
  return r?.exp!=null?(r.evidence==='grammar_recovered'?'≈ ':'')+expText(r.exp):
    r?.estimated_exp?`≈${expText(r.estimated_exp.value.approximate)}`:'—';
}
function expTitle(r) {
  if(r?.estimated_exp) {
    const e=r.estimated_exp;
    return `Estimated from observed percentage and provisional level ${e.level_evidence.value} requirement, not read directly by OCR. ${Object.entries(e.hypotheses).map(([rule,b])=>`${rule}: ${b.count?`${numbers.format(b.min)}–${numbers.format(b.max)} EXP`:'no compatible within-level integer'}`).join('; ')}. Community table ${e.requirement.version}; bounds exclude OCR/table errors.${r.exp_validity?.status==='invalid'?' Contradictory OCR integer withheld.':''}`;
  }
  return r?.exp_validity?.status==='invalid'?'Absolute EXP withheld: inconsistent with level and percentage under both display hypotheses':r?.exp==null?'Absolute EXP unavailable; level or requirement unresolved':`${numbers.format(BigInt(r.exp))} current EXP; ${r.evidence==='grammar_recovered'?'unverified grammar-recovered proposal':'original strict OCR candidate; unverified'}`;
}
function sourceText(p) { return `${p.source_kind==='file'?'Video · ':p.source_kind==='twitch'?'ttv/':''}${p.channel}`; }
function displayLevel(p) { return p.display_level?.evidence ?? p.reading?.level; }
function lastKnown(p) { const l=p.display_level;return !!l && (l.last_known || l.age_seconds+(performance.now()-receivedAt)/1000>p.stale_after_seconds); }
function levelText(p) { const level=displayLevel(p);return level?.value==null?'—':String(level.value); }
function levelTitle(p) {
  const l=displayLevel(p),saved=p.display_level;
  if(saved)return `${lastKnown(p)?'Last-known':'Recently supported'} level; ${ageText(saved.age_seconds+(performance.now()-receivedAt)/1000)}; ${saved.evidence.reason}; ${saved.timestamp}. Display only, not evidence for calculations; OCR remains unverified.`;
  return l?.status==='conflict'?`Level readers disagree: ${l.visual} / ${l.neural}`:l?.value!=null?'Provisional OCR level; unverified':'Waiting for supported level evidence';
}
function earlyText(p) {
  if(p.responsive_pace) {
    const pace=publicPace(p),e=pace.estimates;
    const rate=e.exp_per_hour?`~${expText(e.exp_per_hour.value.approximate)} EXP/hour`:`~${e.percentage_per_hour.value.approximate.toFixed(2)}% / hour`;
    return `${rate} · ${pace.label}`;
  }
  const early=p.early_pace;
  if(!early?.active || current(p).stale || failed)return null;
  const e=early.estimates,segment=early.segment;
  const rate=e.exp_per_hour?`~${expText(e.exp_per_hour.value.approximate)} EXP/hour`:e.percentage_per_hour?`~${e.percentage_per_hour.value.approximate.toFixed(2)}% / hour`:null;
  return rate?`${rate} · early estimate · ${segment.readings} readings / ${Math.round(segment.span_seconds.approximate)}s`:null;
}
function publicPace(p) {
  const pace=p.responsive_pace;if(!pace)return null;
  const age=pace.age_seconds+(performance.now()-receivedAt)/1000;
  const active=pace.active && !current(p).stale && !failed;
  return {active,age,label:active?(pace.tentative?'first estimate':'recent trend'):`last estimated ${ageText(age)}`,
    estimates:active?pace.estimates:{...pace.estimates,eta:null},source:pace};
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
function observedWindow(p) { const o=selectedWindow(p)?.observed;return o?.available?o:null; }
function spanText(seconds) { const s=Math.floor(seconds);return s<60?`${s}s`:`${Math.floor(s/60)}m ${s%60}s`; }
function windowNote(p) {
  const w=selectedWindow(p);
  const o=observedWindow(p);
  if(o) {
    const age=o.age_seconds+(performance.now()-receivedAt)/1000;
    const old=current(p).stale || failed || o.paused;
    return `${spanText(o.span_seconds.approximate)} · ${o.readings} readings${o.interruptions?` · ${o.interruptions} short gap${o.interruptions===1?'':'s'}`:''}${old?` · last updated ${ageText(age)}`:w.eligible?' · complete window':' · partial history'}`;
  }
  if(current(p).stale || failed)return 'Waiting for fresh readings';
  if(w?.eligible)return `Last ${windowMinutes} min · ${Math.round(w.coverage_seconds.approximate)}s observed · ${w.readings} readings`;
  if(w?.state==='unavailable')return 'Gathering a fresh comparison';
  return `Building ${windowMinutes}m history`;
}
function statusText(p) {
  const s=current(p),state=p.activity?.state;
  if(failed)return 'Updates delayed';
  if(!p.reading)return p.latest_attempt_status==='capture_failed'?'Capture unavailable':'Waiting for EXP';
  if(s.stale)return 'Updates delayed';
  if(p.percentage_state?.public_eligible===false && p.percentage_state?.pending_since)return 'Verifying EXP change';
  if(p.latest_attempt_status==='capture_failed')return 'Waiting for the next reading';
  if(state==='stopped' && p.activity.completion)return ({completed:'Capture complete',interrupted:'Capture interrupted',failed:'Capture stopped'})[p.activity.completion] ?? 'Capture paused';
  return ({running:'Updating',waiting:'Tracking',capture_delayed:'Updates running behind',capture_failing:'Capture interrupted',
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
  const level=node('span','level');level.append(node('small','','LV.'),node('strong','',levelText(p)));level.title=levelTitle(p);
  const identity=node('div','identity'),name=node('a','character',p.character?.label ?? 'Character not selected');name.href=`/stream/${p.channel}`;name.title=name.textContent;
  identity.append(name,node('span','channel',sourceText(p)),node('span','status',statusText(p)));
  const section=node('div','exp-section'),bar=node('div','exp-bar'),progress=node('progress');progress.max=100;progress.value=r?r.bp/100:0;progress.hidden=!r;progress.setAttribute('aria-label',`${p.character?.label ?? p.channel} observed EXP percentage`);
  bar.dataset.missing=String(!r);bar.dataset.recovered=String(r?.evidence==='grammar_recovered');
  const label=node('span','exp-label');label.title=expTitle(r);label.append(node('small','','EXP'),node('span','exp-number',displayedExp(r)),node('span','percentage',r?`[${r.percentage}%]`:'Waiting for EXP'));
  bar.append(progress,label);
  section.append(bar,node('div','exp-detail',`${observedWindow(p)?`${movementText(observedWindow(p))} · ${windowNote(p)}`:!selectedWindow(p)?.eligible && earlyText(p) || windowNote(p)} · ${r?'Updated '+ageText(s.age):'No reading yet'}`));
  const score=node('div','score');score.append(node('strong','score-value',value==null?'—':sort==='level'?String(value):sort==='movement'?`+${value.toFixed(2)}%`:`~${expText(value)}`),
    node('small','score-label',sort==='level'?'level':sort==='movement'?'level progress':'EXP / hour'));
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
  el('ranking-note').textContent=sort==='level'?'Your party, by level':`Comparing complete ${windowMinutes}-minute windows`;
  el('ranking-note').title=sorts[sort]+(sort==='level'?'':` ${windowMinutes}-minute window; ≥90% contiguous coverage, no interpolation.`);
  el('connection').textContent=failed?'Connection interrupted · showing older readings':'Updates automatically · local tracker';
  document.querySelectorAll('[data-sort]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.sort===sort)));
  document.querySelectorAll('[data-window]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.window)===windowMinutes)));
}
function renderPlayer() {
  const p=data?.player,r=p?.reading;
  if(!p) { el('status').textContent=failed?'Tracker unavailable':'Waiting for EXP';return; }
  const s=current(p),pace=publicPace(p),m=pace?.estimates ?? s.metrics;
  if(view==='overlay') { el('streamer').textContent=sourceText(p);el('character').textContent=p.character?.label ?? p.channel;el('character').title=el('character').textContent;el('streamer').title=sourceText(p);el('card').dataset.stale=String(s.stale||failed);el('card').dataset.recovered=String(r?.evidence==='grammar_recovered'); }
  else { el('player-name').textContent=p.character?.label ?? p.channel;el('player-source').textContent=sourceText(p); }
  el('level').textContent=`Lv. ${levelText(p)}`;el('level').title=levelTitle(p);
  el('level').dataset.lastKnown=String(lastKnown(p));
  el('progress').value=r?r.bp/100:0;
  el('progress').hidden=!r;
  el('exp').textContent=displayedExp(r);el('exp').title=expTitle(r);
  el('percentage').textContent=r?`${r.percentage}%`:'—';
  el('status').textContent=statusText(p);
  el('age').textContent=r?`Updated ${ageText(s.age)}`:'';el('age').title=r?.timestamp ?? '';
  const observed=view==='player'?observedWindow(p):null;
  const movement=view==='overlay'?(p.segment?.readings>=2?p.segment.difference_percentage_points:null):observed?.difference_percentage_points ?? (selectedWindow(p)?.eligible?selectedWindow(p).difference_percentage_points:null);
  const summary=observed ?? (movement!=null?{difference_percentage_points:movement}:null);
  el('movement').textContent=(observed || !s.stale && !failed) && movement!=null?movementText(summary):'—';
  el('movement').dataset.paused=String(!!observed && (observed.paused || s.stale || failed));
  el('movement').title=observed?`${observed.start} – ${observed.end}; +${movement} percentage points. ${observed.estimated_exp?'Approximate net EXP from percentage and community requirement '+observed.estimated_exp.requirement.version+'. ':''}${observed.unavailable_attempts} unavailable and ${observed.missing_attempts} missing attempts; not exact earned EXP, no progress allocated inside gaps. Not used for ranking.`:'';
  el('rate').textContent=m?.exp_per_hour?`~${expText(m.exp_per_hour.value.approximate)}`:'—';el('rate').title=(view==='overlay' && earlyText(p)?earlyText(p)+'. ':'')+rateTitle(m?.exp_per_hour);
  el('pp-rate').textContent=m?.percentage_per_hour?`~${m.percentage_per_hour.value.approximate.toFixed(2)}`:'—';
  el('pp-rate').title='Experimental displayed percentage points/hour; zero displayed change does not prove zero actual EXP.';
  el('eta').textContent=etaText(m?.eta);el('eta').title=m?.eta?'Provisional same-level percentage estimate at the last reading, not a countdown. Both quantization hypotheses require positive pace.':'Building positive, comparable history';
  if(view==='overlay') for(const id of ['exp','movement','rate','pp-rate','eta']) el(id).dataset.size=el(id).textContent.length>(id==='exp'?16:8)?'long':'normal';
  el('rate').dataset.paused=String(!!pace && !pace.active);
  if(view==='overlay') {
    if(pace && !pace.active && !failed && !p.percentage_state?.pending_since)el('status').textContent=`Last estimate ${ageText(pace.age)}`;
    el('rate-label').textContent=pace && !pace.active?'Last EXP / hour':'EXP / hour';
    el('rate').title=pace?`${pace.label}; ${pace.source.readings} readings / ${Math.round(pace.source.span_seconds.approximate)}s. ${rateTitle(m?.exp_per_hour)}`:el('rate').title;
  }
  if(view==='player') {
    const early=p.early_pace,text=earlyText(p);
    el('early-value').textContent=pace?`${pace.label} · ${pace.source.readings} readings / ${Math.round(pace.source.span_seconds.approximate)}s`:text ?? (early?.segment?'Estimate paused':'Building comparable history');
    el('early-note').textContent=text?'Experimental current segment · separate from completed-window comparisons.':early?.segment?'Last eligible estimate retained for inspection; waiting for fresh, connected readings.':'Needs 3 supported same-level readings over 30s; interruptions restart the segment.';
    el('early-value').title=pace?`${pace.source.start} – ${pace.source.end}; ${(pace.source.coverage_seconds ?? pace.source.span_seconds).approximate}s of comparable captured intervals. Missing intervals supply neither gain nor elapsed time. ${rateTitle(m?.exp_per_hour)}`:early?.segment?`${early.segment.start} – ${early.segment.end}; ${early.segment.readings} readings. ${rateTitle(early.estimates?.exp_per_hour)} Historical value: ${early.estimates?.exp_per_hour?.value.approximate ?? early.estimates?.percentage_per_hour?.value.approximate} ${early.estimates?.exp_per_hour?'EXP/h':'pp/h'}. Bounds exclude OCR errors.`:'';
    el('rate-label').textContent=m?.exp_per_hour?'EXP / hour':'% / hour';
    if(!m?.exp_per_hour && m?.percentage_per_hour)el('rate').textContent=`~${m.percentage_per_hour.value.approximate.toFixed(2)}%`;
    el('early-note').textContent=pace?.active?(pace.source.interruptions?'Short gaps excluded':'') :pace?'Waiting for the next reading':'Building history';
    el('early-note').hidden=!el('early-note').textContent;
    el('level-note').textContent=lastKnown(p)?`Level last seen ${ageText(p.display_level.age_seconds+(performance.now()-receivedAt)/1000)}`:'';
    el('level-note').hidden=!lastKnown(p);
    el('level-note').title=levelTitle(p);
    el('movement-label').textContent=`Last ${windowMinutes} min`;
    el('segment-note').textContent=windowNote(p);
    el('segment-note').title='Observed progress compares supported same-level endpoints across only short, disclosed gaps; it is not a complete-window measurement. Complete comparisons still need ≥90% uninterrupted coverage.';
    el('window-rate').textContent=selectedWindow(p)?.eligible && s.metrics?.exp_per_hour?`~${expText(s.metrics.exp_per_hour.value.approximate)}`:observed?(s.stale || failed || observed.paused?'Paused':'Not complete yet'):'Building history';
    el('window-rate-label').textContent=`${windowMinutes} min EXP / hour`;
    el('pp-stat').hidden=!!m?.exp_per_hour || !m?.percentage_per_hour;
    el('eta-stat').hidden=!m?.eta;
    document.querySelectorAll('[data-window]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.window)===windowMinutes)));
  }
}
function bucketHistory(history,anchor,seconds) {
  const range=({60:1800,300:7200,1800:21600})[seconds];
  if(!range || !Number.isFinite(anchor))return null;
  const step=seconds*1000,end=Math.ceil(anchor/step)*step,start=end-range*1000;
  const bins=Array.from({length:range/seconds},(_,i)=>({start:start+i*step,end:start+(i+1)*step,value:null,covered:0,intervals:0}));
  let previousEnd=-Infinity;
  for(const row of history) {
    const g=row.gain,a=Date.parse(g?.start),b=Date.parse(g?.end),amount=g?.value?.approximate;
    if(!row.connect_previous || !Number.isFinite(a) || !Number.isFinite(b) || b<=a || a<previousEnd || !Number.isFinite(amount) || amount<0)continue;
    previousEnd=b;
    for(const bin of bins) {
      const overlap=Math.max(0,Math.min(b,bin.end,anchor)-Math.max(a,bin.start));
      if(!overlap)continue;
      // Visualization only: uniform allocation within an eligible captured interval.
      // Intervals crossing missing samples never arrive here from the server.
      bin.value=(bin.value ?? 0)+amount*overlap/(b-a);
      bin.covered+=overlap/1000;bin.intervals++;
    }
  }
  for(const bin of bins)bin.state=bin.value==null?'missing':bin.covered<seconds-.01?'partial':'covered';
  return {start,end,bins,range,seconds};
}
function drawExpHistory() {
  const svg=el('history-chart');svg.replaceChildren();
  delete svg.dataset.start;delete svg.dataset.end;
  const rows=data?.history ?? [],anchor=Date.parse(data?.player?.latest_attempt_at ?? rows.at(-1)?.timestamp);
  const chart=bucketHistory(rows,anchor,bucketSeconds);
  if(!chart){el('history-note').textContent='Your next adventure starts here.';return;}
  const width=Math.max(300,Math.min(960,svg.clientWidth||960)),plotWidth=width-76;
  svg.setAttribute('viewBox',`0 0 ${width} 250`);svg.setAttribute('aria-label','EXP history in fixed time buckets; gaps are missing data, faded bars have partial coverage');
  svg.dataset.start=new Date(chart.start).toISOString();svg.dataset.end=new Date(chart.end).toISOString();
  const max=Math.max(1,...chart.bins.map(b=>b.value ?? 0)),scale=10**Math.floor(Math.log10(max)),top=Math.ceil(max/scale)*scale;
  const x=t=>54+(t-chart.start)/(chart.end-chart.start)*plotWidth;
  function shape(tag,attrs,title){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(title)n.append(node('title','',title));svg.append(n);return n;}
  for(let i=0;i<=4;i++){
    const y=200-i*40;
    shape('line',{x1:54,x2:width-22,y1:y,y2:y,class:'chart-grid'});
    shape('text',{x:44,y:y+4,'text-anchor':'end'}).textContent=expText(top*i/4);
  }
  for(const bin of chart.bins){
    const left=x(bin.start)+2,w=Math.max(2,x(bin.end)-x(bin.start)-4),height=bin.value==null?0:Math.max(2,bin.value/top*160);
    const time=new Date(bin.start).toISOString();
    const title=`${time} UTC · ${bin.state==='missing'?'No comparable readings':`${expText(bin.value)} EXP; ${Math.round(bin.covered)}s sampled / ${chart.seconds}s; ${bin.state} coverage. Allocation within intervals is a visualization estimate.`}`;
    shape('rect',{x:left,y:bin.state==='missing'?205:200-height,width:w,height:bin.state==='missing'?2:height,rx:2,
      class:`exp-column ${bin.state}`,tabindex:0,role:'img','aria-label':title},title);
  }
  const ticks=width<600?3:5;
  for(let i=0;i<ticks;i++)shape('text',{x:54+plotWidth*i/(ticks-1),y:235,'text-anchor':i===0?'start':i===ticks-1?'end':'middle'})
    .textContent=new Date(chart.start+(chart.end-chart.start)*i/(ticks-1)).toISOString().slice(11,16);
  const count=chart.bins.filter(b=>b.value!=null).length;
  el('history-note').textContent=`${chart.seconds/60} min per bar · last ${chart.range<3600?'30 min':chart.range/3600+' hours'} · UTC${current(data.player).stale?' · saved history':''}${count?'':' · building history'}`;
  el('history-note').title='Only comparable same-level captured intervals contribute. Gains are spread uniformly within each such interval for visualization only, never across gaps. Faded bars have partial coverage; baseline dashes are unknown, not zero. At most 640 saved attempts are loaded; older coverage may be absent.';
}
function drawHistory() {
  document.querySelectorAll('[data-chart]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.chart===chartMode)));
  document.querySelectorAll('[data-bucket]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.bucket)===bucketSeconds)));
  el('bucket-controls').hidden=chartMode!=='exp';
  if(chartMode==='exp')drawExpHistory();else drawPercentageHistory();
  const all=data?.history ?? [],anchor=Date.parse(data?.player?.latest_attempt_at ?? all.at(-1)?.timestamp);
  const event=(data?.player?.level_events ?? []).filter(e=>Date.parse(e.timestamp)>=anchor-windowMinutes*60000).at(-1);
  const label=event?`Level ${event.level} reached!`:'';
  if(el('level-event').textContent!==label)el('level-event').textContent=label;
  el('level-event').hidden=!event;
  el('level-event').title=event?`Confirmed at ${event.timestamp}; first seen ${event.first_observed_at}. Cross-level EXP is not counted.`:'';
}
function drawPercentageHistory() {
  const svg=el('history-chart');svg.replaceChildren();
  svg.setAttribute('aria-label','Same-level percentage trend; gaps remain open');
  delete svg.dataset.start;delete svg.dataset.end;
  const width=Math.max(300,Math.min(960,svg.clientWidth||960)),plotWidth=width-100;
  svg.setAttribute('viewBox',`0 0 ${width} 230`);
  const all=(data?.history ?? []).map(r=>({...r,time:Date.parse(r.timestamp)})).filter(r=>Number.isFinite(r.time));
  const anchor=all.length?Math.max(...all.map(p=>p.time)):0;
  const windowPoints=all.filter(p=>p.time>=anchor-windowMinutes*60000);
  const level=displayLevel(data?.player ?? {})?.value;
  const firstLevel=windowPoints.find(p=>p.reading && p.level.value===level);
  const points=firstLevel?windowPoints.filter(p=>p.time>=firstLevel.time):windowPoints;
  // Unknown level points are retained as gaps, never assigned to the displayed level.
  const visible=p=>p.reading && (level==null || p.level.value===level);
  const values=points.filter(visible).map(p=>p.reading.bp/100),min=values.length?Math.min(...values):0,max=values.length?Math.max(...values):100;
  const padding=Math.max(.01,(max-min)*.1),low=Math.max(0,min-padding),high=Math.min(100,max+padding);
  function shape(tag,attrs,title) { const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(title)n.append(node('title','',title));svg.append(n);return n; }
  if(!points.length) { shape('text',{x:30,y:100}).textContent='Your next adventure starts here.';return; }
  const first=Math.min(...points.map(p=>p.time)),last=Math.max(...points.map(p=>p.time));
  const x=t=>60+(t-first)/Math.max(1,last-first)*plotWidth,y=v=>175-(v-low)/Math.max(.01,high-low)*140;
  let gaps=0;
  points.forEach((p,i)=>{
    const previous=points[i-1];
    if(previous && p.time-previous.time>previous.interval_seconds*1500) { gaps++;shape('rect',{x:x(previous.time),y:20,width:x(p.time)-x(previous.time),height:160,class:'gap'}); }
    if(previous && p.connect_previous && visible(p) && visible(previous) && p.level.value===previous.level.value)shape('line',{
      x1:x(previous.time),y1:y(previous.reading.bp/100),x2:x(p.time),y2:y(p.reading.bp/100),class:'trend'},'Trend between comparable captured endpoints; intermediate gains were not observed');
    if(visible(p)) shape('circle',{cx:x(p.time),cy:y(p.reading.bp/100),r:3,class:p.reading.evidence==='grammar_recovered'?'recovered':'sample'},`${p.timestamp} · ${p.reading.percentage}% · ${p.reading.evidence}`);
    else shape('path',{d:`M${x(p.time)-3} 185l6 6m0-6-6 6`,class:'missing'},`${p.timestamp} · reading unavailable`);
  });
  shape('text',{x:10,y:32}).textContent=high.toFixed(2)+'%';shape('text',{x:10,y:180}).textContent=low.toFixed(2)+'%';
  const ticks=width<600?3:5;
  for(let i=0;i<ticks;i++) {
    const time=first+(last-first)*i/(ticks-1);
    shape('text',{x:60+plotWidth*i/(ticks-1),y:218,'text-anchor':i===0?'start':i===ticks-1?'end':'middle'}).textContent=new Date(time).toISOString().slice(11,19);
  }
  svg.dataset.start=new Date(first).toISOString();svg.dataset.end=new Date(last).toISOString();
  el('history-note').textContent=`${level!=null?'Lv. '+level+' · ':''}${points.length} readings · ${Math.round((last-first)/1000)}s displayed · UTC${current(data.player).stale?' · saved history':''}`;
  el('history-note').title=`Last ${windowMinutes} min. Lines join only comparable same-level endpoints, not observed intermediate activity. Other levels and full history remain in Advanced.`;
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
  document.querySelectorAll('[data-chart]').forEach(b=>b.addEventListener('click',()=>{if(!['exp','percentage'].includes(b.dataset.chart))return;chartMode=b.dataset.chart;drawHistory();}));
  document.querySelectorAll('[data-bucket]').forEach(b=>b.addEventListener('click',()=>{if(![60,300,1800].includes(Number(b.dataset.bucket)))return;bucketSeconds=Number(b.dataset.bucket);drawHistory();}));
  globalThis.addEventListener?.('resize',drawHistory);
  const url=`${location.origin}/live/overlay/${encodeURIComponent(channel)}`;
  el('overlay-link').href=url;el('diagnostics').href=`/dashboard/${channel}`;el('history-link').href=`/dashboard/${channel}`;
  el('copy-overlay').addEventListener('click',async()=>{try {await navigator.clipboard.writeText(url);el('copy-status').textContent='Copied · use a 500 × 160 Browser Source';}catch{el('copy-status').textContent='Copy the Open OBS overlay link · 500 × 160';}});
}
poll();setInterval(()=>{if(view==='board')renderBoard();else renderPlayer();},1000);
