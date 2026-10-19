"use strict";

const view=document.body.dataset.view;
const channel=view==='overlay'?location.pathname.split('/')[3]:view==='player'?location.pathname.split('/')[2]:null;
const endpoint=channel?`/api/players/${encodeURIComponent(channel)}`:'/api/players';
// The server lowercases logins; an empty path keeps the static HTML title.
if(view==='player' && channel)document.title=`${channel.toLowerCase()} · EXP Tracker`;
const numbers=new Intl.NumberFormat('en-US'),shortNumber=new Intl.NumberFormat('en-US',{maximumSignificantDigits:3});
const wholeNumbers=new Intl.NumberFormat('en-US',{maximumFractionDigits:0}),localDates=new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'long'});
const sorts={exp_hour:'Estimated pace over the selected window; community requirements are provisional.',
  level:'Latest supported character levels. Hover for the reading time.',
  movement:'Displayed change within the selected window. Incomplete or interrupted coverage is not ranked.'};
let data=null,receivedAt=0,failed=false,sort='level',windowMinutes=5,chartMode='exp',bucketSeconds=60,pollTimer=null,activeController=null;
let rollingData=null,rollingReceived=0,rollingRevision=null,rollingFailed=false,rollingController=null,rollingTimer=null;
let tip=null,tipKey=null,tipPosition=null,tipDismissed=false,lastPointer=null;
let currentLevelOnly=false;
const el=id=>document.getElementById(id);
function node(tag,className,text) { const n=document.createElement(tag);if(className)n.className=className;if(text!=null)n.textContent=text;return n; }
function hideTip() { if(tip)tip.hidden=true;tipKey=null;tipPosition=null; }
function showTip(target,position=null) {
  if(tipDismissed)return;
  if(!tip){tip=node('div','chart-tooltip');tip.id='chart-tooltip';tip.setAttribute('role','tooltip');document.body.append(tip);}
  tipKey=target.dataset.tipKey;tipPosition=position;tip.textContent=target.dataset.tipText;tip.hidden=false;
  target.setAttribute('aria-describedby','chart-tooltip');
  const box=target.getBoundingClientRect(),size=tip.getBoundingClientRect();
  const x=position?.x ?? box.left+box.width/2,y=position?.y ?? box.top;
  tip.style.left=Math.max(8,Math.min(innerWidth-size.width-8,x-size.width/2))+'px';
  tip.style.top=Math.max(8,Math.min(innerHeight-size.height-8,y-size.height-12>=8?y-size.height-12:box.bottom+10))+'px';
}
function inspect(target,key,text) {
  target.dataset.tipKey=key;target.dataset.tipText=text;target.setAttribute('tabindex','0');target.setAttribute('role','img');target.setAttribute('aria-label',text);
  target.addEventListener('pointerenter',e=>{if(e.pointerType!=='touch')showTip(target,{x:e.clientX,y:e.clientY});});
  target.addEventListener('pointerleave',()=>{if(document.activeElement!==target)hideTip();});
  target.addEventListener('focus',()=>showTip(target));target.addEventListener('blur',hideTip);
  target.addEventListener('pointerdown',e=>{tipDismissed=false;if(e.pointerType==='touch'){if(tipKey===key)hideTip();else showTip(target);}});
  return target;
}
function localTime(stamp) { return localDates.format(new Date(stamp)); }
function ageText(seconds) { if(seconds==null)return 'No reading yet';if(seconds<60)return `${Math.floor(seconds)}s ago`;if(seconds<3600)return `${Math.floor(seconds/60)}m ago`;if(seconds<86400)return `${Math.floor(seconds/3600)}h ago`;return `${Math.floor(seconds/86400)}d ago`; }
function expText(value,full=false) { if(value==null)return '—';if(full)return wholeNumbers.format(typeof value==='string'?BigInt(value):value);const n=Number(value),scale=n>=1e9?1e9:n>=1e6?1e6:n>=1e3?1e3:1;return (scale===1?numbers:shortNumber).format(n/scale)+({1:'',1000:'K',1000000:'M',1000000000:'B'}[scale]); }
function amount(id,full,compact) {
  const target=el(id);target.dataset.fullNumber=full;target.dataset.compactNumber=compact;
  target.textContent=view==='player'?full:compact;
}
function fitAmounts() {
  const targets=['exp','movement','rate','tracked-exp','window-rate','eta'].map(el).filter(n=>n.dataset.fullNumber!=null);
  const narrow=targets.filter(n=>n.clientWidth>0 && n.scrollWidth>n.clientWidth+1);
  narrow.forEach(n=>{n.textContent=n.dataset.compactNumber;});
}
function movementText(summary) { return summary?.estimated_exp?`+${expText(summary.estimated_exp.value.approximate)} EXP`:summary?.difference_percentage_points!=null?`+${summary.difference_percentage_points}%`:'—'; }
function displayedExp(r,full=false) {
  return r?.exp!=null?(['grammar_recovered','conditional_symbol'].includes(r.evidence)?'~ ':'')+expText(r.exp,full):
    r?.estimated_exp?`~${expText(r.estimated_exp.value.approximate,full)}`:'—';
}
function expTitle(r) {
  if(r?.estimated_exp) {
    const e=r.estimated_exp;
    return `Estimated from observed percentage and provisional level ${e.level_evidence.value} requirement, not read directly by OCR. ${Object.entries(e.hypotheses).map(([rule,b])=>`${rule}: ${b.count?`${numbers.format(b.min)}–${numbers.format(b.max)} EXP`:'no compatible within-level integer'}`).join('; ')}. Community table ${e.requirement.version}; bounds exclude OCR/table errors.${r.exp_validity?.status==='invalid'?' Contradictory OCR integer withheld.':''}`;
  }
  return r?.exp_validity?.status==='invalid'?'Absolute EXP withheld: inconsistent with level and percentage under both display hypotheses':r?.exp==null?'Absolute EXP unavailable; level or requirement unresolved':`${numbers.format(BigInt(r.exp))} current EXP; ${r.evidence==='conditional_symbol'?'conditional X-to-% recovery; unverified':r.evidence==='grammar_recovered'?'unverified grammar-recovered proposal':'original strict OCR candidate; unverified'}`;
}
function sourceText(p) { return `${p.source_kind==='file'?'Video · ':p.source_kind==='twitch'?'ttv/':''}${p.channel}`; }
function displayLevel(p) { return p.display_level?.evidence ?? p.reading?.level; }
function lastKnown(p) { const l=p.display_level;return !!l && (l.last_known || l.age_seconds+(performance.now()-receivedAt)/1000>p.stale_after_seconds); }
// Public labels show the proposed level; provenance and uncertainty stay in hover text.
const LEVEL_SOURCES={exp_derived:'Inferred from EXP and percentage with the provisional community table; not read from the level HUD.',
  retained_level:'Last supported level, retained across percentage-only readings; not re-verified since then.',
  provisional_level_up:'Provisional level-up inferred from a percentage wrap and forward progress; awaiting EXP or level-reader corroboration.'};
function levelTransition(p) { const t=p.level_context?.transition;return t?.phase==='possible'?t:null; }
function levelText(p) {
  const level=displayLevel(p),t=levelTransition(p);
  if(t)return String(t.to_level);
  return level?.value==null?'—':String(level.value);
}
function levelTitle(p) {
  const l=displayLevel(p),saved=p.display_level,t=levelTransition(p),context=p.level_context;
  if(t)return `Possible level-up: percentage went from ${t.before_bp/100}% to ${t.after_bp/100}% at ${t.detected_at}. Lv. ${t.from_level} is the last supported level; Lv. ${t.to_level} needs more forward progress, EXP or a level reading.`;
  if(saved && LEVEL_SOURCES[saved.evidence.status])return `${LEVEL_SOURCES[saved.evidence.status]}${context?.supported_at?` Last supported ${context.supported_at} (${context.source}).`:''} ${saved.timestamp}. Experimental; never trusted accounting.`;
  if(saved)return `${lastKnown(p)?'Last-known':'Recently supported'} level; ${ageText(saved.age_seconds+(performance.now()-receivedAt)/1000)}; ${saved.evidence.reason}; ${saved.timestamp}. Display only, not evidence for calculations; OCR remains unverified.`;
  return l?.status==='conflict'?`Level readers disagree: ${l.visual} / ${l.neural}`:l?.value!=null?'Provisional OCR level; unverified':'Waiting for supported level evidence';
}
function earlyText(p) {
  if(p.responsive_pace) {
    const pace=publicPace(p);if(!pace)return null;const e=pace.estimates;
    const rate=e.exp_per_hour?`~${expText(e.exp_per_hour.value.approximate)} EXP/hour`:e.percentage_per_hour?`~${e.percentage_per_hour.value.approximate.toFixed(2)}% / hour`:'Pace paused';
    return `${rate} · ${pace.label}`;
  }
  const early=p.early_pace;
  if(!early?.active || current(p).stale || failed)return null;
  const e=early.estimates,segment=early.segment;
  const rate=e.exp_per_hour?`~${expText(e.exp_per_hour.value.approximate)} EXP/hour`:e.percentage_per_hour?`~${e.percentage_per_hour.value.approximate.toFixed(2)}% / hour`:null;
  return rate?`${rate} · early estimate · ${segment.readings} readings / ${Math.round(segment.span_seconds.approximate)}s`:null;
}
function paceSample(pace) {
  const covered=(pace.coverage_seconds ?? pace.span_seconds).approximate,sequences=(pace.interruptions ?? 0)+1;
  if(pace.interval_counts)return `${pace.readings} readings / ${Math.round(covered)}s elapsed${pace.missing_attempts?` · ${pace.missing_attempts} missing reading${pace.missing_attempts===1?'':'s'}`:''}${sequences>1?` · ${sequences} sequences`:''}`;
  return `${pace.readings} readings / ${Math.round(covered)}s sampled · ${sequences} sequence${sequences===1?'':'s'}`;
}
function publicPace(p) {
  const recent=recentWindow(p);
  if(view==='player' && recent?.status==='history_limit')return null;
  const compatible=p.responsive_pace?.level==null || p.responsive_pace.level===(p.reading?.level?.value ?? p.display_level?.value);
  const pace=view==='player' && recent?(recent.pace ?? recent.last_observed_pace ?? (windowMinutes===5 && compatible?p.responsive_pace:null)):p.responsive_pace;
  if(!pace)return null;
  const age=pace.age_seconds+(performance.now()-receivedAt)/1000;
  const policy=pace.presentation;
  const active=pace.active && !(view==='player' && recent && !recent.pace) && !current(p).stale && !failed && (!policy || policy.state==='observed');
  let estimates=active?pace.estimates:{...pace.estimates,eta:null};
  const expired=policy?.state==='paused' || policy?.running && age>=(policy.expire_after_seconds ?? policy.pause_after_seconds);
  if(expired)estimates={exp_per_hour:null,percentage_per_hour:null,eta:null};
  return {active,age,label:expired?'Pace paused':failed?`last observed ${ageText(age)}`:active?(pace.tentative?'first estimate':'recent trend'):`last observed ${ageText(age)}`,
    estimates,source:pace};
}
function publicETA(p) {
  if(view!=='player')return null;
  const saved=recentWindow(p)?.eta;
  if(!saved)return null;
  const age=saved.age_seconds+(performance.now()-receivedAt)/1000;
  const pace=recentWindow(p)?.pace;
  return {...saved,age,historical:saved.historical || failed || current(p).stale || !pace?.active || (pace.presentation && pace.presentation.state!=='observed')};
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
function recentWindow(p) { return (view==='player' && currentLevelOnly?p.current_level_windows:p.recent_windows)?.[String(windowMinutes)]; }
function observedWindow(p) {
  const windows=view==='player' && currentLevelOnly?p.tracked_current_level_windows:p.tracked_windows;
  if(p.tracked_status)return windows?.[String(windowMinutes)]?.observed?.available?windows[String(windowMinutes)].observed:null;
  const o=recentWindow(p)?.observed ?? selectedWindow(p)?.observed;return o?.available?o:null;
}
function spanText(seconds) { const s=Math.floor(seconds);return s<60?`${s}s`:`${Math.floor(s/60)}m ${s%60}s`; }
function windowNote(p) {
  if(p.tracked_status && p.tracked_status!=='ready')return 'Tracked history unavailable';
  if(recentWindow(p)?.status==='history_limit')return 'Recent history unavailable';
  const w=selectedWindow(p);
  const o=observedWindow(p);
  if(o) {
    const age=o.age_seconds+(performance.now()-receivedAt)/1000;
    const old=current(p).stale || failed || o.paused;
    return `${spanText((o.coverage_seconds ?? o.span_seconds).approximate)} · ${o.readings} readings${o.interruptions?` · ${o.interruptions+1} sequences`:''}${old?` · last updated ${ageText(age)}`:w?.eligible?' · complete window':' · partial history'}`;
  }
  if(current(p).stale || failed)return 'Waiting for fresh readings';
  if(w?.eligible)return `Last ${windowMinutes} min · ${Math.round(w.coverage_seconds.approximate)}s observed · ${w.readings} readings`;
  if(w?.state==='unavailable')return 'Gathering a fresh comparison';
  return `Building ${windowMinutes}m history`;
}
function captureText(p) {
  const s=current(p),state=p.activity?.state;
  if(failed)return 'Updates delayed';
  if(state==='capture_finished' || state==='stopped' && p.activity.completion==='completed')return 'Capture finished';
  if(state==='capture_interrupted')return 'Capture stopped';
  if(['coordinator_stopped','previous_unfinished_run','historical_session'].includes(state) && s.stale)return p.reading?`Last tracked ${ageText(s.age)}`:'Capture paused';
  if(!p.reading)return p.latest_attempt_status==='capture_failed'?'Capture unavailable':'Waiting for EXP';
  const attemptAge=p.latest_attempt_age_seconds==null?null:p.latest_attempt_age_seconds+(performance.now()-receivedAt)/1000;
  if(attemptAge!=null && attemptAge>=0 && attemptAge<=p.stale_after_seconds && p.latest_attempt_at!==p.reading.timestamp &&
      ['malformed_or_unavailable','unavailable'].includes(p.latest_attempt_status) && ['waiting','running'].includes(state))return 'HUD unreadable';
  if(s.stale)return 'Updates delayed';
  if(p.percentage_state?.public_eligible===false && p.percentage_state?.pending_since)return 'Verifying EXP change';
  if(p.latest_attempt_status==='capture_failed')return 'Waiting for the next reading';
  if(state==='stopped' && p.activity.completion)return ({completed:'Capture complete',interrupted:'Capture interrupted',failed:'Capture stopped'})[p.activity.completion] ?? 'Capture paused';
  return ({running:'Updating',waiting:'Tracking',capture_delayed:'Updates running behind',capture_failing:'Capture interrupted',
    stopped:'Capture paused',coordinator_stopped:'Capture paused',previous_unfinished_run:'Capture stopped'})[state] ?? 'Capture paused';
}
function statusText(p) {
  let status=p.twitch?.status;
  const now=Date.parse(data?.served_at ?? data?.player?.latest_attempt_at)+(performance.now()-receivedAt);
  if(p.twitch?.valid_until && now>Date.parse(p.twitch.valid_until))status='unknown';
  const capture=captureText(p);
  if(status==='live')return `Twitch live · ${p.latest_attempt_status==='capture_failed'?'Capture unavailable':capture}`;
  if(status==='offline')return `Twitch offline · ${p.twitch.capture_disagreement?'Recent capture differs':capture}`;
  if(status==='unknown' && p.latest_attempt_status==='capture_failed')return `Live status unknown · Capture unavailable`;
  return capture;
}
function etaText(value,compact=false) {
  const seconds=value?.seconds?.approximate;
  if(!Number.isFinite(seconds) || seconds<0)return '—';
  const minutes=Math.round(seconds/60);
  if(!minutes)return seconds>0?'~<1m':'~0m';
  const days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60),rest=minutes%60;
  const parts=[];if(days)parts.push(`${days}d`);if(hours)parts.push(`${hours}h`);
  if(rest && !(compact && days))parts.push(`${rest}m`);
  return '~'+parts.join(' ');
}
function rateTitle(rate) {
  if(!rate)return 'Needs two supported readings and a positive, comparable elapsed interval. Recent pace includes time between valid endpoints; complete-window rankings remain separate.';
  return `Experimental estimate, not earned EXP. ${Object.entries(rate.hypotheses).map(([rule,b])=>`${rule}: ${numbers.format(Math.round(b.lower.approximate))}–${numbers.format(Math.round(b.upper.approximate))} EXP/h`).join('; ')}. Community requirement ${rate.requirement.version}; quantization bounds exclude OCR errors.`;
}
function metricValue(p,key) {
  if(key==='level')return levelTransition(p)?.to_level ?? displayLevel(p)?.value ?? null;
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
  bar.dataset.missing=String(!r);bar.dataset.recovered=String(['grammar_recovered','conditional_symbol'].includes(r?.evidence));
  const label=node('span','exp-label'),integer=node('span','exp-number',displayedExp(r,true));
  integer.dataset.compactNumber=displayedExp(r);label.title=expTitle(r);label.append(node('small','','EXP'),integer,node('span','percentage',r?`[${r.percentage}%]`:'Waiting for EXP'));
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
  [...el('entries').querySelectorAll('.exp-number')].filter(n=>n.clientWidth>0 && n.scrollWidth>n.clientWidth+1).forEach(n=>{n.textContent=n.dataset.compactNumber;});
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
  const s=current(p),pace=publicPace(p),m=pace?.estimates ?? (view==='player' && p.recent_windows?null:s.metrics);
  if(view==='overlay') { el('streamer').textContent=sourceText(p);el('character').textContent=p.character?.label ?? p.channel;el('character').title=el('character').textContent;el('streamer').title=sourceText(p);el('card').dataset.stale=String(s.stale||failed);el('card').dataset.recovered=String(['grammar_recovered','conditional_symbol'].includes(r?.evidence)); }
  else { el('player-name').textContent=p.character?.label ?? p.channel;el('player-source').textContent=sourceText(p); }
  el('level').textContent=`Lv. ${levelText(p)}`;el('level').title=levelTitle(p);
  el('level').dataset.lastKnown=String(lastKnown(p));
  el('level').dataset.inferred=String(!!levelTransition(p) || !!LEVEL_SOURCES[displayLevel(p)?.status]);
  el('progress').value=r?r.bp/100:0;
  el('progress').hidden=!r;
  const absolute=displayedExp(r,true);
  amount('exp',absolute==='—'?'—':absolute+' EXP',displayedExp(r));el('exp').title=expTitle(r);
  el('percentage').textContent=r?`${r.percentage}%`:'—';
  el('status').textContent=statusText(p);
  el('age').textContent=r?`Updated ${ageText(s.age)}`:'';el('age').title=r?.timestamp ?? '';
  const observed=view==='player'?observedWindow(p):null;
  const movement=view==='overlay'?(p.segment?.readings>=2?p.segment.difference_percentage_points:null):observed?.difference_percentage_points ?? (!p.recent_windows && selectedWindow(p)?.eligible?selectedWindow(p).difference_percentage_points:null);
  const summary=observed ?? (movement!=null?{difference_percentage_points:movement}:null);
  el('movement').textContent=(observed || !s.stale && !failed) && (summary?.estimated_exp || movement!=null)?movementText(summary):'—';
  amount('movement',el('movement').textContent==='—'?'—':summary?.estimated_exp?`+${expText(summary.estimated_exp.value.approximate,true)} EXP`:el('movement').textContent,el('movement').textContent);
  el('movement').dataset.paused=String(!!observed && (observed.paused || s.stale || failed));
  el('movement').title=observed?`${observed.start} – ${observed.end}; ${movement!=null?'+'+movement+' percentage points. ':''}${observed.estimated_exp?'Supported EXP intervals; each level uses its own community requirement. ':''}${observed.unavailable_attempts} unavailable and ${observed.missing_attempts} missing attempts; not exact earned EXP, no progress allocated inside gaps or level transitions. Not used for ranking.`:'';
  if(observed)el('movement').title=el('movement').dataset.fullNumber+'; '+el('movement').title;
  amount('rate',m?.exp_per_hour?`~${expText(m.exp_per_hour.value.approximate,true)}`:'—',m?.exp_per_hour?`~${expText(m.exp_per_hour.value.approximate)}`:'—');el('rate').title=(view==='overlay' && earlyText(p)?earlyText(p)+'. ':'')+rateTitle(m?.exp_per_hour);
  el('pp-rate').textContent=m?.percentage_per_hour?`~${m.percentage_per_hour.value.approximate.toFixed(2)}`:'—';
  el('pp-rate').title='Experimental displayed percentage points/hour; zero displayed change does not prove zero actual EXP.';
  const savedETA=publicETA(p),eta=view==='player' && p.recent_windows?savedETA?.estimate:m?.eta;
  amount('eta',etaText(eta),etaText(eta,true));el('eta').title=eta?`${etaText(eta)}. Static duration at the last supported reading, not a countdown.${savedETA?` ${savedETA.window_minutes} min basis · ${savedETA.readings} readings · ${new Date(savedETA.estimated_at).toLocaleString()}${savedETA.rate_observed_at?`; rate last observed ${new Date(savedETA.rate_observed_at).toLocaleString()}; current level ${savedETA.level} remaining EXP`:''}`:''}`:'Building positive, comparable history';
  if(view==='overlay')el('eta').textContent=etaText(eta);
  if(view==='overlay') for(const id of ['exp','movement','rate','pp-rate','eta']) el(id).dataset.size=el(id).textContent.length>(id==='exp'?16:8)?'long':'normal';
  el('rate').dataset.paused=String(!!pace && !pace.active);
  if(pace)el('rate').title=`${pace.label}; ${paceSample(pace.source)}. ${rateTitle(m?.exp_per_hour)}`;
  if(view==='overlay') {
    if(el('eta').clientWidth>0 && el('eta').scrollWidth>el('eta').clientWidth+1)el('eta').textContent=etaText(eta,true);
    if(pace && !pace.active && !failed && !p.twitch && !p.percentage_state?.pending_since && !['capture_finished','capture_interrupted','historical_session','stopped','coordinator_stopped'].includes(p.activity?.state))el('status').textContent=`Last estimate ${ageText(pace.age)}`;
    el('rate-label').textContent=pace && !pace.active?'Last EXP / hour':'EXP / hour';
  }
  if(view==='player') {
    const rolling=rollingData?.character_id===p.character?.id?rollingData:null;
    amount('tracked-exp',rolling?.tracked_exp?`~${expText(rolling.tracked_exp.approximate,true)}`:'—',rolling?.tracked_exp?`~${expText(rolling.tracked_exp.approximate)}`:'—');
    el('tracked-exp').title=rolling?`${el('tracked-exp').dataset.fullNumber} EXP; ${rolling.start} – ${rolling.end}; selected character only. ${rolling.intervals} comparable intervals; ${Math.round(rolling.coverage_seconds.approximate)} captured seconds. Both direct OCR and percentage-based EXP estimates can contribute. Missing periods, losses and level transitions contribute no inferred gain. Not exact EXP earned today.`:'';
    const rollingAge=(performance.now()-rollingReceived)/1000;
    el('tracked-note').textContent=rollingFailed?(rolling?`Saved · updated ${ageText(rollingAge)}`:'History unavailable'):rolling?.status==='history_limit'?'History unavailable':rolling?(rolling.tracked_exp?`${spanText(rolling.coverage_seconds.approximate)} tracked`:'No comparable readings'):'Loading history';
    const early=p.early_pace,text=earlyText(p);
    el('early-value').textContent=pace?`${pace.label} · ${paceSample(pace.source)}`:text ?? (early?.segment?'Estimate paused':'Building comparable history');
    el('early-note').textContent=text?'Experimental current segment · separate from completed-window comparisons.':early?.segment?'Last eligible estimate retained for inspection; waiting for fresh, connected readings.':'Needs 3 supported same-level readings over 30s; interruptions restart the segment.';
    el('early-value').title=pace?`${pace.source.start} – ${pace.source.end}; ${(pace.source.coverage_seconds ?? pace.source.span_seconds).approximate}s of eligible elapsed intervals. ${pace.source.interval_counts?`${pace.source.interval_counts.direct} direct and ${pace.source.interval_counts.endpoint_supported} endpoint-supported intervals; gap time is included, with no intermediate values invented.`:'Missing intervals supply neither gain nor elapsed time.'} ${rateTitle(m?.exp_per_hour)}`:early?.segment?`${early.segment.start} – ${early.segment.end}; ${early.segment.readings} readings. ${rateTitle(early.estimates?.exp_per_hour)} Historical value: ${early.estimates?.exp_per_hour?.value.approximate ?? early.estimates?.percentage_per_hour?.value.approximate} ${early.estimates?.exp_per_hour?'EXP/h':'pp/h'}. Bounds exclude OCR errors.`:'';
    el('rate-label').textContent=m?.exp_per_hour?'EXP / hour':'% / hour';
    if(!m?.exp_per_hour && m?.percentage_per_hour)amount('rate',`~${m.percentage_per_hour.value.approximate.toFixed(2)}%`,`~${m.percentage_per_hour.value.approximate.toFixed(2)}%`);
    el('early-note').textContent=pace?.active?(pace.source.interruptions?'Unsafe intervals excluded':'') :pace?(['capture_finished','capture_interrupted','historical_session','coordinator_stopped'].includes(p.activity?.state)?'Saved trend':'Waiting for the next reading'):'Building history';
    el('early-note').hidden=!el('early-note').textContent;
    el('movement-label').textContent=`${observed?.historical || s.stale && ['completed','interrupted'].includes(p.capture_lifecycle)?'Saved':'Last'} ${windowMinutes} min`;
    el('segment-note').textContent=windowNote(p);
    el('segment-note').title='Sums supported same-level endpoint intervals inside this real time window, including elapsed unreadable captures. Separate runs contribute independent intervals, never a difference across restart. Complete comparisons still need ≥90% uninterrupted coverage.';
    el('window-rate').textContent=selectedWindow(p)?.eligible && s.metrics?.exp_per_hour?`~${expText(s.metrics.exp_per_hour.value.approximate)}`:observed?(s.stale || failed || observed.paused?'Paused':'Not complete yet'):'Building history';
    if(selectedWindow(p)?.eligible && s.metrics?.exp_per_hour)amount('window-rate',`~${expText(s.metrics.exp_per_hour.value.approximate,true)}`,el('window-rate').textContent);
    else {delete el('window-rate').dataset.fullNumber;delete el('window-rate').dataset.compactNumber;}
    el('window-rate-label').textContent=`${windowMinutes} min EXP / hour`;
    el('pp-stat').hidden=!!m?.exp_per_hour || !m?.percentage_per_hour;
    el('eta-stat').hidden=false;
    el('eta-note').textContent=savedETA?(savedETA.historical?`Last estimated ${ageText(savedETA.age)} · ${savedETA.window_minutes} min basis`:savedETA.tentative?`Early estimate · ${savedETA.readings} readings`:`At your ${savedETA.window_minutes} min pace`):eta?`At your ${windowMinutes} min pace`:'Building positive history';
    document.querySelectorAll('[data-window]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.window)===windowMinutes)));
    fitAmounts();
  }
}
function bucketHistory(history,anchor,seconds,rangeSeconds=null) {
  const range=rangeSeconds ?? ({60:1800,300:7200,1800:86400})[seconds];
  if(!range || !Number.isFinite(anchor))return null;
  const step=seconds*1000,end=rangeSeconds==null?Math.ceil(anchor/step)*step:anchor,start=end-range*1000;
  const bins=Array.from({length:range/seconds},(_,i)=>({start:start+i*step,end:start+(i+1)*step,value:null,covered:0,intervals:0}));
  let previousEnd=-Infinity;
  for(const row of history) {
    const g=row.gain,a=Date.parse(g?.start),b=Date.parse(g?.end),amount=g?.value?.approximate;
    if(!row.connect_previous || !Number.isFinite(a) || !Number.isFinite(b) || b<=a || a<previousEnd || a<start || b>anchor || !Number.isFinite(amount) || amount<0)continue;
    previousEnd=b;
    for(const bin of bins) {
      const overlap=Math.max(0,Math.min(b,bin.end,anchor)-Math.max(a,bin.start));
      if(!overlap)continue;
      // Visualization only: uniform allocation within an eligible captured interval.
      // Intervals crossing missing samples never arrive here from the server.
      bin.value=(bin.value ?? 0)+amount*overlap/(b-a);
      bin.covered+=overlap/1000;bin.intervals++;
      bin.gap ||= g.kind==='endpoint_supported';
    }
  }
  for(const bin of bins)bin.state=bin.value==null?'missing':bin.covered<seconds-.01 || bin.gap?'partial':'covered';
  return {start,end,bins,range,seconds};
}
function drawExpHistory() {
  const svg=el('history-chart');svg.replaceChildren();
  delete svg.dataset.start;delete svg.dataset.end;
  const rolling=rollingData?.character_id===data?.player?.character?.id?rollingData:null;
  const history=rolling?.chart_intervals?rolling.chart_intervals.map(g=>({gain:g,connect_previous:true,level:{value:g.level}})):data?.history ?? [],level=rolling?.current_level ?? displayLevel(data?.player ?? {})?.value;
  const rows=currentLevelOnly?history.filter(p=>p.level.value===level):history,anchor=Date.parse(rolling?.as_of ?? data?.player?.recent_windows?.[String(windowMinutes)]?.end ?? data?.player?.latest_attempt_at ?? history.at(-1)?.timestamp);
  const chart=bucketSeconds===1800 && rolling?{
    start:Date.parse(rolling.start),end:Date.parse(rolling.end),seconds:1800,range:86400,
    bins:rolling.buckets.map(b=>({...b,start:Date.parse(b.start),end:Date.parse(b.end),value:b.value?.approximate ?? null,covered:b.covered.approximate}))
  }:bucketHistory(bucketSeconds===1800?[]:rows,bucketSeconds===1800?Date.parse(data?.served_at):anchor,bucketSeconds,bucketSeconds===1800?null:windowMinutes*60);
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
      class:`exp-column ${bin.state}`},title);
    inspect(shape('rect',{x:left,y:25,width:w,height:183,fill:'transparent',class:'bar-hit'}),`bar:${bin.start}:${bin.end}`,
      `${localTime(bin.start)}\n${bin.value==null?'No reading':`~${expText(bin.value,true)} EXP`}\n${chart.seconds/60} min bucket · ${bin.state==='missing'?'No coverage':bin.state==='partial'?`Partial coverage · ${spanText(bin.covered)} captured`:'Complete coverage'}`);
  }
  const ticks=width<600?3:5;
  for(let i=0;i<ticks;i++){
    const tick=new Date(chart.start+(chart.end-chart.start)*i/(ticks-1)).toISOString();
    const attrs={x:54+plotWidth*i/(ticks-1),'text-anchor':i===0?'start':i===ticks-1?'end':'middle'};
    shape('text',{...attrs,y:232}).textContent=tick.slice(11,16);
    if(chart.range===86400)shape('text',{...attrs,y:248}).textContent=tick.slice(5,10);
  }
  const count=chart.bins.filter(b=>b.value!=null).length;
  el('history-note').textContent=`${chart.seconds/60} min per bar · last ${chart.range<3600?chart.range/60+' min':chart.range/3600+' hours'} · UTC${current(data.player).stale || rollingFailed && bucketSeconds===1800?' · saved history':''}${count?'':' · building history'}`;
  el('history-note').title='Supported same-level endpoint intervals contribute, each with its own level requirement. Their net gains are spread uniformly inside each interval for visualization only; unreadable intermediate captures are not observations. Unsafe gaps and level changes remain unknown. Faded bars have partial coverage; dashes are unknown, not zero. The 24h view always includes all levels.';
}
function drawHistory() {
  const focus=document.activeElement?.dataset?.tipKey,openKey=tipKey,position=tipPosition;
  document.querySelectorAll('[data-chart]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.chart===chartMode)));
  document.querySelectorAll('[data-bucket]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.bucket)===bucketSeconds)));
  el('bucket-controls').hidden=chartMode!=='exp';
  if(chartMode==='exp')drawExpHistory();else drawPercentageHistory();
  const all=data?.history ?? [],anchor=Date.parse(data?.tracked_history?.as_of ?? data?.player?.recent_windows?.[String(windowMinutes)]?.end ?? data?.player?.latest_attempt_at ?? all.at(-1)?.timestamp);
  const event=(data?.player?.level_events ?? []).filter(e=>Date.parse(e.timestamp)>=anchor-windowMinutes*60000).at(-1);
  const label=!event?'':event.inferred?(event.status==='corroborated'?`Level ${event.level} reached (inferred)`:`Level ${event.level} reached`):`Level ${event.level} reached!`;
  if(el('level-event').textContent!==label)el('level-event').textContent=label;
  el('level-event').hidden=!event;
  el('level-event').title=!event?'':event.inferred?`Inferred from a percentage wrap after Lv. ${event.previous_level} at ${event.first_observed_at}; ${event.status==='corroborated'?`corroborated by ${event.evidence}`:'not yet corroborated by EXP or a level reading'}. Cross-level EXP is not counted.`:`Confirmed at ${event.timestamp}; first seen ${event.first_observed_at}. Cross-level EXP is not counted.`;
  const targets=[...document.querySelectorAll('#history-chart [data-tip-key]')];
  if(focus){targets.find(n=>n.dataset.tipKey===focus)?.focus({preventScroll:true});if(!openKey)hideTip();}
  if(openKey){const target=targets.find(n=>n.dataset.tipKey===openKey);if(target)showTip(target,position);else hideTip();}
}
function drawPercentageHistory() {
  const svg=el('history-chart');svg.replaceChildren();
  svg.setAttribute('aria-label','Level percentage history; level changes are marked and gaps remain open');
  delete svg.dataset.start;delete svg.dataset.end;
  const width=Math.max(300,Math.min(960,svg.clientWidth||960)),plotWidth=width-100;
  svg.setAttribute('viewBox',`0 0 ${width} 230`);
  const all=(data?.history ?? []).map(r=>({...r,time:Date.parse(r.timestamp)})).filter(r=>Number.isFinite(r.time));
  const anchor=Date.parse(data?.tracked_history?.as_of ?? data?.player?.recent_windows?.[String(windowMinutes)]?.end) || (all.length?Math.max(...all.map(p=>p.time)):0);
  const first=anchor-windowMinutes*60000,last=anchor;
  const windowPoints=all.filter(p=>p.time>=first && p.time<=last);
  const level=displayLevel(data?.player ?? {})?.value;
  const points=currentLevelOnly?windowPoints.filter(p=>!p.reading || p.level.value===level):windowPoints;
  // Unknown level points are retained as gaps, never assigned to the displayed level.
  const visible=p=>p.reading && p.level.value!=null && (!currentLevelOnly || p.level.value===level);
  const values=points.filter(visible).map(p=>p.reading.bp/100),min=values.length?Math.min(...values):0,max=values.length?Math.max(...values):100;
  const padding=Math.max(.01,(max-min)*.1),low=Math.max(0,min-padding),high=Math.min(100,max+padding);
  function shape(tag,attrs,title) { const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(title)n.append(node('title','',title));svg.append(n);return n; }
  if(!points.length)shape('text',{x:60,y:100}).textContent='Your next adventure starts here.';
  const x=t=>60+(t-first)/Math.max(1,last-first)*plotWidth,y=v=>175-(v-low)/Math.max(.01,high-low)*140;
  let gaps=0;
  points.forEach((p,i)=>{
    const previous=points[i-1];
    if(previous && p.time-previous.time>previous.interval_seconds*1500) { gaps++;shape('rect',{x:x(previous.time),y:20,width:x(p.time)-x(previous.time),height:160,class:'gap'}); }
    if(previous && p.connect_previous && visible(p) && visible(previous) && p.level.value===previous.level.value)shape('line',{
      x1:x(previous.time),y1:y(previous.reading.bp/100),x2:x(p.time),y2:y(p.reading.bp/100),class:'trend'},'Trend between comparable captured endpoints; intermediate gains were not observed');
    if(visible(p))inspect(shape('circle',{cx:x(p.time),cy:y(p.reading.bp/100),r:4,class:p.reading.evidence==='grammar_recovered'?'recovered':'sample'},`${p.timestamp} · ${p.reading.percentage}% · ${p.reading.evidence}`),
      `point:${p.event_id}`,`${localTime(p.timestamp)}\n${p.level.value!=null?'Lv. '+p.level.value+' · ':''}${p.reading.percentage}%\n${p.reading.exp!=null || p.reading.estimated_exp?displayedExp(p.reading,true)+' EXP':'EXP unavailable'}`);
    else inspect(shape('path',{d:`M${x(p.time)-3} 185l6 6m0-6-6 6`,class:'missing'},`${p.timestamp} · reading unavailable`),`point:${p.event_id}`,`${localTime(p.timestamp)}\nReading unavailable`);
  });
  let previousLevel=null;
  for(const p of windowPoints.filter(p=>p.reading && p.level.value!=null)) {
    if(previousLevel!=null && p.level.value!==previousLevel) {
      const event=(data.player.level_events ?? []).find(e=>e.level===p.level.value && Date.parse(e.first_observed_at)<=p.time);
      shape('line',{x1:x(p.time),x2:x(p.time),y1:20,y2:180,class:'level-transition'});
      shape('text',{x:Math.min(width-75,x(p.time)+4),y:16,class:'level-transition-label'},'Level boundary; EXP across the transition is not counted').textContent=
        !event?`Lv. ${p.level.value} seen`:event.inferred && event.status!=='corroborated'?`Lv. ${p.level.value}`:`Level ${p.level.value}!`;
    }
    previousLevel=p.level.value;
  }
  shape('text',{x:10,y:32}).textContent=high.toFixed(2)+'%';shape('text',{x:10,y:180}).textContent=low.toFixed(2)+'%';
  const ticks=width<600?3:5;
  for(let i=0;i<ticks;i++) {
    const time=first+(last-first)*i/(ticks-1);
    shape('text',{x:60+plotWidth*i/(ticks-1),y:218,'text-anchor':i===0?'start':i===ticks-1?'end':'middle'}).textContent=new Date(time).toISOString().slice(11,19);
  }
  svg.dataset.start=new Date(first).toISOString();svg.dataset.end=new Date(last).toISOString();
  const readable=points.filter(visible).length,unavailable=points.length-readable;
  el('history-note').textContent=`${currentLevelOnly && level!=null?'Lv. '+level+' · ':''}${readable} readings${unavailable?` · ${unavailable} unavailable`:''} · last ${windowMinutes} min · UTC${current(data.player).stale?' · saved history':''}`;
  el('history-note').title='Lines join only comparable same-level endpoints. Level resets are marked; unknown transition gains and missing captures are not connected.';
}
async function poll() {
  if(activeController)return;
  clearTimeout(pollTimer);
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),5000),requested=performance.now();
  activeController=controller;
  try {
    const response=await fetch(endpoint,{cache:'no-store',signal:controller.signal});if(!response.ok)throw new Error();
    data=await response.json();receivedAt=requested;failed=false;
    if(view==='player' && data.tracked_history){rollingData=data.tracked_history;rollingReceived=performance.now();rollingFailed=false;}
    if(view==='board')renderBoard();else { renderPlayer();if(view==='player'){drawHistory();if(Array.isArray(data.history))pollRolling();} }
  } catch { failed=true;if(view==='board')renderBoard();else renderPlayer(); }
  finally { clearTimeout(timeout);activeController=null;pollTimer=setTimeout(poll,2000); }
}

async function pollRolling(force=false) {
  if(data?.tracked_history)return;
  if(view!=='player' || rollingController)return;
  const revision=JSON.stringify([data?.player?.character?.id,data?.player?.latest_attempt_at]);
  if(!force && rollingRevision===revision && performance.now()-rollingReceived<30000)return;
  clearTimeout(rollingTimer);
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),30000);
  rollingController=controller;
  try {
    const response=await fetch(`/api/players/${encodeURIComponent(channel)}/history`,{cache:'no-store',signal:controller.signal});
    if(!response.ok)throw new Error('History unavailable');
    const result=await response.json();
    if(!Array.isArray(result.buckets) || result.buckets.length!==48)throw new Error('Invalid history');
    if(result.character_id!==data?.player?.character?.id)return;
    rollingData=result;rollingReceived=performance.now();rollingRevision=revision;rollingFailed=false;
  } catch { rollingFailed=true; }
  finally { clearTimeout(timeout);rollingController=null;renderPlayer();drawHistory();rollingTimer=setTimeout(()=>pollRolling(true),30000); }
}
document.addEventListener?.('visibilitychange',()=>{if(!document.hidden)poll();});
globalThis.addEventListener?.('pageshow',poll);
if(view==='board')globalThis.addEventListener?.('resize',renderBoard);
if(view==='board') document.querySelectorAll('[data-sort]').forEach(button=>button.addEventListener('click',()=>{sort=button.dataset.sort;if(sort in sorts)renderBoard();}));
document.querySelectorAll('[data-window]').forEach(button=>button.addEventListener('click',()=>{
  const minutes=Number(button.dataset.window);if(![5,10,15,30,60].includes(minutes))return;windowMinutes=minutes;
  if(view==='board')renderBoard();else if(data?.player){renderPlayer();drawHistory();}
}));
if(view==='player') {
  el('current-level-only').addEventListener('change',e=>{currentLevelOnly=e.target.checked;if(data?.player){renderPlayer();drawHistory();}});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){tipDismissed=true;hideTip();}else if(e.key==='Tab')tipDismissed=false;});
  document.addEventListener('pointermove',e=>{if(!lastPointer || lastPointer.x!==e.clientX || lastPointer.y!==e.clientY)tipDismissed=false;lastPointer={x:e.clientX,y:e.clientY};});
  document.addEventListener('pointerdown',e=>{if(!e.target.closest?.('[data-tip-key]'))hideTip();});
  globalThis.addEventListener?.('scroll',hideTip,true);
  document.querySelectorAll('[data-chart]').forEach(b=>b.addEventListener('click',()=>{if(!['exp','percentage'].includes(b.dataset.chart))return;chartMode=b.dataset.chart;drawHistory();}));
  document.querySelectorAll('[data-bucket]').forEach(b=>b.addEventListener('click',()=>{if(![60,300,1800].includes(Number(b.dataset.bucket)))return;bucketSeconds=Number(b.dataset.bucket);drawHistory();}));
  globalThis.addEventListener?.('resize',()=>{renderPlayer();drawHistory();});
  const url=`${location.origin}/live/overlay/${encodeURIComponent(channel)}`;
  el('overlay-link').href=url;el('diagnostics').href=`/dashboard/${channel}`;el('history-link').href=`/dashboard/${channel}`;
  el('copy-overlay').addEventListener('click',async()=>{try {await navigator.clipboard.writeText(url);el('copy-status').textContent='Copied · use a 500 × 160 Browser Source';}catch{el('copy-status').textContent='Copy the Open OBS overlay link · 500 × 160';}});
}
poll();setInterval(()=>{if(view==='board')renderBoard();else renderPlayer();},1000);
