"use strict";

const view=document.body.dataset.view;
const channel=view==='overlay'?location.pathname.split('/')[3]:view==='player'?location.pathname.split('/')[2]:null;
const endpoint=channel?`/api/players/${encodeURIComponent(channel)}`:'/api/players';
// The server lowercases logins; an empty path keeps the static HTML title.
if(view==='player' && channel)document.title=`${channel.toLowerCase()} · EXP Tracker`;
const numbers=new Intl.NumberFormat('en-US'),shortNumber=new Intl.NumberFormat('en-US',{maximumSignificantDigits:3});
const wholeNumbers=new Intl.NumberFormat('en-US',{maximumFractionDigits:0}),localDates=new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'long'});
const sorts={exp_hour:'Estimated from recent stream updates.',
  level:'Latest known level for each character.',
  movement:'Level % gained in the selected time.'};
let data=null,receivedAt=0,failed=false,sort='level',windowMinutes=5,chartMode='exp',bucketSeconds=60,pollTimer=null,activeController=null;
let rollingData=null,rollingReceived=0,rollingRevision=null,rollingFailed=false,rollingController=null,rollingTimer=null;
let tip=null,tipKey=null,tipPosition=null,tipDismissed=false,lastPointer=null;
let currentLevelOnly=false,warming=false;
// View-only character choice (?character=ID); null follows whichever character is being tracked.
const characterParam=()=>{const id=new URLSearchParams(location.search).get('character');return view==='player' && /^[1-9][0-9]{0,17}$/.test(id ?? '')?id:null;};
let viewCharacter=characterParam(),roster=[],rosterKey='',rosterViewing=null;
const boardParam=()=>new URLSearchParams(location.search).get('mode')==='characters'?'characters':'streamers';
let boardMode=boardParam();
const inactiveView=()=>view==='player' && data?.view?.current===false;
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
// Public hover text stays short; the evidence behind each value is in the local Advanced pages.
function expTitle(r) {
  if(r?.evidence==='manual_admin')return `Entered manually by the tracker operator.${r.estimated_exp?' EXP is estimated from the entered %.':''}${r.estimated_percentage?' % is estimated from the entered EXP.':''}${r.exp_validity?.status==='invalid'?' The entered EXP and % don\'t fully match.':''}`;
  if(r?.estimated_exp)return 'Estimated from the level %; the exact EXP isn\'t shown on stream.';
  return r?.exp_validity?.status==='invalid'?'EXP hidden: it didn\'t match the level and %':r?.exp==null?'EXP not available yet':`${numbers.format(BigInt(r.exp))} EXP${['grammar_recovered','conditional_symbol'].includes(r.evidence)?' · partly unclear on stream, may be slightly off':''}`;
}
function percentageText(r) { return r?.percentage!=null?`${r.estimated_percentage?'~':''}${r.percentage}%`:'—'; }
function sourceText(p) { return `${p.source_kind==='file'?'Video · ':p.source_kind==='twitch'?'ttv/':''}${p.channel}`; }
function displayLevel(p) { return p.display_level?.evidence ?? p.reading?.level; }
function lastKnown(p) { const l=p.display_level;return !!l && (l.last_known || l.age_seconds+(performance.now()-receivedAt)/1000>p.stale_after_seconds); }
// Public labels follow accepted display evidence; possible wraps stay in the status and hover text.
const LEVEL_SOURCES={exp_derived:'Level worked out from EXP; not read from the screen.',
  retained_level:'Last confirmed level.',
  provisional_level_up:'Likely level-up; waiting for confirmation.',
  validated_level_floor:'Last confirmed level for this character.'};
function levelTransition(p) { const t=p.level_context?.transition;return t?.phase==='possible'?t:null; }
function levelText(p) {
  const level=displayLevel(p);
  return level?.value==null?'—':String(level.value);
}
function levelTitle(p) {
  const l=displayLevel(p),saved=p.display_level,t=levelTransition(p);
  if(l?.status==='manual_admin')return 'Level entered manually by the tracker operator.';
  if(t)return `Possible level-up to Lv. ${t.to_level}; waiting for confirmation.`;
  if(saved && LEVEL_SOURCES[saved.evidence.status])return LEVEL_SOURCES[saved.evidence.status];
  if(saved)return `${lastKnown(p)?'Last known level':'Level'} · read ${ageText(saved.age_seconds+(performance.now()-receivedAt)/1000)}`;
  return l?.status==='conflict'?'Level unclear':l?.value!=null?'Level read from the stream':'Waiting for level';
}
function earlyText(p) {
  if(p.responsive_pace) {
    const pace=publicPace(p);if(!pace)return null;const e=pace.estimates;
    const rate=e.exp_per_hour?`~${expText(e.exp_per_hour.value.approximate)} EXP/hour`:e.percentage_per_hour?`~${e.percentage_per_hour.value.approximate.toFixed(2)}% / hour`:null;
    return rate?`${rate} · ${pace.label}`:'Paused';
  }
  const early=p.early_pace;
  if(!early?.active || current(p).stale || failed)return null;
  const e=early.estimates;
  const rate=e.exp_per_hour?`~${expText(e.exp_per_hour.value.approximate)} EXP/hour`:e.percentage_per_hour?`~${e.percentage_per_hour.value.approximate.toFixed(2)}% / hour`:null;
  return rate?`${rate} · Early estimate`:null;
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
  return {active,age,label:expired?'Paused':failed?`As of ${ageText(age)}`:active?(pace.tentative?'Early estimate':'Recent pace'):`As of ${ageText(age)}`,
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
  if(p.tracked_status && p.tracked_status!=='ready' || recentWindow(p)?.status==='history_limit')return 'History unavailable';
  const limitation={level_transition_requirement_unavailable:'Can\'t total EXP across the level-up',
    percentage_requirement_unavailable:'EXP needed for this level isn\'t known yet',
    observed_exp_decrease:'EXP went down',observed_level_decrease:'Level went down',level_unavailable:'Level unknown'}[recentWindow(p)?.reason];
  if(limitation)return limitation;
  const w=selectedWindow(p);
  const o=observedWindow(p);
  if(o) {
    const age=o.age_seconds+(performance.now()-receivedAt)/1000;
    const old=current(p).stale || failed || o.paused;
    return `${o.span_seconds.approximate>=windowMinutes*60?`Based on the full ${windowMinutes} min`:`Based on ${spanText((o.coverage_seconds ?? o.span_seconds).approximate)} tracked`}${old?` · last updated ${ageText(age)}`:''}`;
  }
  if(inactiveView())return 'Saved history';
  if(current(p).stale || failed)return 'Waiting for an update';
  if(w?.eligible)return `Based on the full ${windowMinutes} min`;
  return 'Calculating…';
}
function captureText(p) {
  const s=current(p),state=p.activity?.state;
  if(failed)return 'Updates delayed';
  if(state==='capture_finished' || state==='stopped' && p.activity.completion==='completed')return 'Tracking ended';
  if(state==='capture_interrupted')return 'Tracking stopped';
  if(['coordinator_stopped','previous_unfinished_run','historical_session'].includes(state) && s.stale)return p.reading?`Last tracked ${ageText(s.age)}`:'Tracking paused';
  if(!p.reading)return p.latest_attempt_status==='capture_failed'?'Can\'t read the stream':'Waiting for EXP';
  const attemptAge=p.latest_attempt_age_seconds==null?null:p.latest_attempt_age_seconds+(performance.now()-receivedAt)/1000;
  if(attemptAge!=null && attemptAge>=0 && attemptAge<=p.stale_after_seconds && p.latest_attempt_at!==p.reading.timestamp &&
      ['malformed_or_unavailable','unavailable'].includes(p.latest_attempt_status) && ['waiting','running'].includes(state))return 'EXP bar not visible';
  if(s.stale)return 'Updates delayed';
  if(p.percentage_state?.public_eligible===false && p.percentage_state?.pending_since)return 'Verifying EXP change';
  if(p.latest_attempt_status==='capture_failed')return 'Waiting for an update';
  if(state==='stopped' && p.activity.completion)return ({completed:'Tracking ended',interrupted:'Tracking stopped',failed:'Tracking stopped'})[p.activity.completion] ?? 'Tracking paused';
  return ({running:'Updating',waiting:'Tracking',capture_delayed:'Updates running behind',capture_failing:'Trouble reading the stream',
    stopped:'Tracking paused',coordinator_stopped:'Tracking paused',previous_unfinished_run:'Tracking stopped'})[state] ?? 'Tracking paused';
}
function statusText(p) {
  // Another character's saved state: never the tracked character's capture or Twitch status.
  if(inactiveView())return `Not currently tracked · ${p.reading?'last seen '+ageText(current(p).age):'nothing saved yet'}`;
  let status=p.twitch?.status;
  const now=Date.parse(data?.served_at ?? data?.player?.latest_attempt_at)+(performance.now()-receivedAt);
  if(p.twitch?.valid_until && now>Date.parse(p.twitch.valid_until))status='unknown';
  const capture=captureText(p);
  const pending=levelTransition(p)?' · Possible level-up (confirming)':'';
  if(status==='live')return `Live on Twitch · ${p.latest_attempt_status==='capture_failed'?'Can\'t read the stream':capture}${pending}`;
  if(status==='offline')return `Offline on Twitch · ${p.twitch.capture_disagreement?'Tracker still updating':capture}${pending}`;
  // Unknown Twitch status is never shown as live or offline.
  if(status==='unknown' && p.latest_attempt_status==='capture_failed')return `Can't read the stream${pending}`;
  return capture+pending;
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
function rateTitle(rate) { return rate?'Estimated from recent stream updates.':'Not enough recent updates yet.'; }
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
  const badge=node('span','rank',rank??'—');badge.dataset.medal=rank!=null && rank<=3?rank:'';badge.setAttribute('aria-label',rank==null?'Not ranked yet':`Rank ${rank}`);
  const level=node('span','level');level.append(node('small','','LV.'),node('strong','',levelText(p)));level.title=levelTitle(p);
  const identity=node('div','identity'),name=node('a','character',p.character?.label ?? 'Character not selected');name.href=`/stream/${p.channel}`;name.title=name.textContent;
  identity.append(name,node('span','channel',sourceText(p)),node('span','status',statusText(p)));
  const section=node('div','exp-section'),bar=node('div','exp-bar'),progress=node('progress');progress.max=100;progress.value=r?.bp!=null?r.bp/100:0;progress.hidden=r?.bp==null;progress.setAttribute('aria-label',`${p.character?.label ?? p.channel} EXP progress`);
  bar.dataset.missing=String(!r);bar.dataset.recovered=String(['grammar_recovered','conditional_symbol'].includes(r?.evidence));
  const label=node('span','exp-label'),integer=node('span','exp-number',displayedExp(r,true));
  integer.dataset.compactNumber=displayedExp(r);label.title=expTitle(r);label.append(node('small','','EXP'),integer,node('span','percentage',r?.percentage!=null?`[${percentageText(r)}]`:'Waiting for EXP'));
  bar.append(progress,label);
  const o=observedWindow(p),old=s.stale || failed || o?.paused;
  section.append(bar,node('div','exp-detail',`${o?`${movementText(o)} · last ${windowMinutes} min${old?' tracked':''}`:!selectedWindow(p)?.eligible && earlyText(p) || windowNote(p)} · ${r?'Updated '+ageText(s.age):'No reading yet'}`));
  const score=node('div','score');score.append(node('strong','score-value',value==null?'—':sort==='level'?String(value):sort==='movement'?`+${value.toFixed(2)}%`:`~${expText(value)}`),
    node('small','score-label',sort==='level'?'level':sort==='movement'?'level progress':'EXP / hour'));
  score.title=sort==='exp_hour'?rateTitle(s.metrics?.exp_per_hour):sort==='level'?levelTitle(p):sorts.movement;
  row.append(badge,level,identity,section,score);return row;
}
function renderBoard() {
  const characters=boardMode==='characters';
  document.querySelectorAll('[data-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.mode===boardMode)));
  el('streamer-metrics').hidden=characters;el('streamer-windows').hidden=characters;el('character-controls').hidden=!characters;
  el('connection').textContent=failed?'Reconnecting · showing last known numbers':'Updates automatically';
  if(characters){renderCharacters();return;}
  const rows=ranked(data?.players ?? [],sort);
  const focus=document.activeElement?.closest?.('#entries a')?.getAttribute('href');
  el('entries').replaceChildren(...rows.map(entry));
  [...el('entries').querySelectorAll('.exp-number')].filter(n=>n.clientWidth>0 && n.scrollWidth>n.clientWidth+1).forEach(n=>{n.textContent=n.dataset.compactNumber;});
  if(focus) [...el('entries').querySelectorAll('a')].find(a=>a.getAttribute('href')===focus)?.focus({preventScroll:true});
  el('empty').hidden=rows.length>0 || !data;
  el('empty').textContent='No players are being tracked yet.';
  el('board-count').textContent=data?`${rows.length} player${rows.length===1?'':'s'}${data.warming?.length?` · ${data.warming.length} more loading`:''}`:failed?'Tracker unavailable':'Loading players…';
  el('ranking-count').textContent='';
  el('ranking-note').textContent=sort==='level'?'Sorted by level':sort==='exp_hour'?`EXP per hour · last ${windowMinutes} min`:`Level % gained · last ${windowMinutes} min`;
  el('ranking-note').title=sorts[sort]+(sort==='level'?'':` Players need ${windowMinutes} minutes of steady updates to be ranked.`);
  document.querySelectorAll('[data-sort]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.sort===sort)));
  document.querySelectorAll('[data-window]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.window)===windowMinutes)));
}
function renderCharacters() {
  const search=el('character-filter').value.trim().toLowerCase(),order=el('character-sort').value || 'recent';
  const all=data?.characters ?? [],rows=all.filter(r=>`${r.label} ${r.channel}`.toLowerCase().includes(search));
  rows.sort((a,b)=>(order==='level'?(b.level ?? -1)-(a.level ?? -1):order==='name'?a.label.localeCompare(b.label):
    (Date.parse(b.last_seen_at) || 0)-(Date.parse(a.last_seen_at) || 0)) || a.channel.localeCompare(b.channel) || a.id-b.id);
  const focus=document.activeElement?.closest?.('#entries a')?.getAttribute('href');
  const now=data?.served_at?Date.parse(data.served_at)+(performance.now()-receivedAt):Date.now();
  el('entries').replaceChildren(...rows.map(r=>{
    const row=node('li','entry character-entry');row.dataset.channel=r.channel;row.dataset.character=r.id;
    const level=node('span','level');level.append(node('small','','LV.'),node('strong','',r.level ?? '—'));
    const identity=node('div','identity'),link=node('a','character',r.label);link.href=`/stream/${encodeURIComponent(r.channel)}?character=${r.id}`;
    const status=node('span','status',r.current?'Currently tracked':'Not currently tracked');
    status.className+=r.current?' roster-live':'';
    identity.append(link,node('span','channel',r.channel),status);
    const seen=node('span','saved-seen',r.last_seen_at?`Last seen ${ageText(Math.max(0,(now-Date.parse(r.last_seen_at))/1000))}`:'Not seen yet');
    if(r.last_seen_at)seen.title=localTime(r.last_seen_at);
    row.append(level,identity,seen);return row;
  }));
  if(focus)[...el('entries').querySelectorAll('a')].find(a=>a.getAttribute('href')===focus)?.focus({preventScroll:true});
  el('empty').hidden=rows.length>0 || !data;
  el('empty').textContent=search?'No characters match your search.':'No saved characters yet.';
  el('board-count').textContent=data?`${all.length} character${all.length===1?'':'s'}${data.warming?.length?` · ${data.warming.length} more loading`:''}`:failed?'Tracker unavailable':'Loading characters…';
  el('ranking-note').textContent='Each character\'s last known level';
  el('ranking-note').title='Open a character to see its EXP history. Tracked doesn\'t mean the stream is live.';
  el('ranking-count').textContent=`${search?`${rows.length} found · `:''}${all.filter(r=>r.current).length} currently tracked`;
}
function selectBoard(mode,historyMode='push') {
  if(!['streamers','characters'].includes(mode) || mode===boardMode)return;
  boardMode=mode;
  if(historyMode!=='none'){
    const url=new URL(location.href);if(mode==='characters')url.searchParams.set('mode',mode);else url.searchParams.delete('mode');
    history.pushState(null,'',url);
  }
  data=null;renderBoard();
  if(activeController)activeController.abort();else poll();
}
function renderPlayer() {
  const p=data?.player,r=p?.reading;
  if(!p) {
    if(warming) {
      // Warming can mean ownership changed: never retain another character's display.
      for(const id of ['level','exp','percentage','movement','rate','pp-rate','eta','age','tracked-exp','tracked-note','early-value','eta-note','segment-note','history-note','window-rate']) {
        const target=el(id);if(target){amount(id,'—','—');target.title='';}
      }
      el('level').textContent='Lv. —';el('progress').hidden=true;el('progress').value=0;
      for(const id of ['player-name','player-source','streamer','character'])if(el(id)){el(id).textContent=channel;el(id).title='';}
      el('history-chart')?.replaceChildren();if(el('level-event'))el('level-event').hidden=true;
      hideTip();
    }
    el('status').textContent=warming?'Preparing saved history…':failed?'Tracker unavailable':'Waiting for EXP';return;
  }
  const s=current(p),pace=publicPace(p),m=pace?.estimates ?? (view==='player' && p.recent_windows?null:s.metrics);
  if(view==='overlay') { el('streamer').textContent=sourceText(p);el('character').textContent=p.character?.label ?? p.channel;el('character').title=el('character').textContent;el('streamer').title=sourceText(p);el('card').dataset.stale=String(s.stale||failed);el('card').dataset.recovered=String(['grammar_recovered','conditional_symbol'].includes(r?.evidence)); }
  else { el('player-name').textContent=p.character?.label ?? p.channel;el('player-source').textContent=sourceText(p); }
  el('level').textContent=`Lv. ${levelText(p)}`;el('level').title=levelTitle(p);
  el('level').dataset.lastKnown=String(lastKnown(p));
  el('level').dataset.inferred=String(!!levelTransition(p) || !!LEVEL_SOURCES[displayLevel(p)?.status]);
  el('progress').value=r?.bp!=null?r.bp/100:0;
  el('progress').hidden=r?.bp==null;
  const absolute=displayedExp(r,true);
  amount('exp',absolute==='—'?'—':absolute+' EXP',displayedExp(r));el('exp').title=expTitle(r);
  el('percentage').textContent=percentageText(r);el('percentage').title=r?.evidence==='manual_admin'?expTitle(r):'';
  el('status').textContent=statusText(p);
  el('age').textContent=r?`Updated ${ageText(s.age)}`:'';el('age').title=r?.timestamp?localTime(r.timestamp):'';
  const observed=view==='player'?observedWindow(p):null;
  const movement=view==='overlay'?(p.segment?.readings>=2?p.segment.difference_percentage_points:null):observed?.difference_percentage_points ?? (!p.recent_windows && selectedWindow(p)?.eligible?selectedWindow(p).difference_percentage_points:null);
  const summary=observed ?? (movement!=null?{difference_percentage_points:movement}:null);
  el('movement').textContent=(observed || !s.stale && !failed) && (summary?.estimated_exp || movement!=null)?movementText(summary):'—';
  amount('movement',el('movement').textContent==='—'?'—':summary?.estimated_exp?`+${expText(summary.estimated_exp.value.approximate,true)} EXP`:el('movement').textContent,el('movement').textContent);
  el('movement').dataset.paused=String(!!observed && (observed.paused || s.stale || failed));
  el('movement').title=observed?`${el('movement').dataset.fullNumber}${movement!=null?` (+${movement}% of level)`:''} gained between the first and last update in this time.`:windowNote(p);
  amount('rate',m?.exp_per_hour?`~${expText(m.exp_per_hour.value.approximate,true)}`:'—',m?.exp_per_hour?`~${expText(m.exp_per_hour.value.approximate)}`:'—');el('rate').title=(view==='overlay' && earlyText(p)?earlyText(p)+'. ':'')+rateTitle(m?.exp_per_hour);
  el('pp-rate').textContent=m?.percentage_per_hour?`~${m.percentage_per_hour.value.approximate.toFixed(2)}`:'—';
  el('pp-rate').title='Estimated level % per hour.';
  const savedETA=publicETA(p),eta=view==='player' && p.recent_windows?savedETA?.estimate:m?.eta;
  amount('eta',etaText(eta),etaText(eta,true));el('eta').title=eta?`${etaText(eta)} to the next level at ${savedETA?`the ${savedETA.window_minutes} min pace${Date.parse(savedETA.estimated_at)?`, estimated ${localTime(savedETA.estimated_at)}`:''}`:'the recent pace'}. Not a live countdown.`:'Needs recent EXP gains';
  if(view==='overlay')el('eta').textContent=etaText(eta);
  if(view==='overlay') for(const id of ['exp','movement','rate','pp-rate','eta']) el(id).dataset.size=el(id).textContent.length>(id==='exp'?16:8)?'long':'normal';
  el('rate').dataset.paused=String(!!pace && !pace.active);
  if(pace)el('rate').title=`${pace.label} · ${rateTitle(m?.exp_per_hour ?? m?.percentage_per_hour)}`;
  if(view==='overlay') {
    if(el('eta').clientWidth>0 && el('eta').scrollWidth>el('eta').clientWidth+1)el('eta').textContent=etaText(eta,true);
    if(pace && !pace.active && !failed && !p.twitch && !levelTransition(p) && !p.percentage_state?.pending_since && !['capture_finished','capture_interrupted','historical_session','stopped','coordinator_stopped'].includes(p.activity?.state))el('status').textContent=`Last estimate ${ageText(pace.age)}`;
    el('rate-label').textContent=pace && !pace.active?'Last EXP / hour':'EXP / hour';
  }
  if(view==='player') {
    const rolling=rollingData?.character_id===p.character?.id?rollingData:null;
    amount('tracked-exp',rolling?.tracked_exp?`~${expText(rolling.tracked_exp.approximate,true)}`:'—',rolling?.tracked_exp?`~${expText(rolling.tracked_exp.approximate)}`:'—');
    el('tracked-exp').title=rolling?`${el('tracked-exp').dataset.fullNumber} EXP gained in the last 24 hours while tracked.`:'';
    const rollingAge=(performance.now()-rollingReceived)/1000;
    el('tracked-note').textContent=rollingFailed?(rolling?`Saved · updated ${ageText(rollingAge)}`:'History unavailable'):rolling?.status==='history_limit'?'History unavailable':rolling?(rolling.tracked_exp?`${spanText(rolling.coverage_seconds.approximate)} tracked`:'Not enough data'):'Loading history';
    const early=p.early_pace,text=earlyText(p);
    el('early-value').textContent=pace?pace.label:text ?? (early?.segment?'Paused':'Calculating…');
    el('rate-label').textContent=m?.exp_per_hour?'EXP / hour':'% / hour';
    if(!m?.exp_per_hour && m?.percentage_per_hour)amount('rate',`~${m.percentage_per_hour.value.approximate.toFixed(2)}%`,`~${m.percentage_per_hour.value.approximate.toFixed(2)}%`);
    el('movement-label').textContent=`${observed?.historical || s.stale && ['completed','interrupted'].includes(p.capture_lifecycle)?'Saved':'Last'} ${windowMinutes} min`;
    el('segment-note').textContent=windowNote(p);
    el('window-rate').textContent=selectedWindow(p)?.eligible && s.metrics?.exp_per_hour?`~${expText(s.metrics.exp_per_hour.value.approximate)}`:observed?(s.stale || failed || observed.paused?'Paused':`Needs a full ${windowMinutes} min`):'Calculating…';
    if(selectedWindow(p)?.eligible && s.metrics?.exp_per_hour)amount('window-rate',`~${expText(s.metrics.exp_per_hour.value.approximate,true)}`,el('window-rate').textContent);
    else {delete el('window-rate').dataset.fullNumber;delete el('window-rate').dataset.compactNumber;}
    el('window-rate-label').textContent=`${windowMinutes} min EXP / hour`;
    el('pp-stat').hidden=!!m?.exp_per_hour || !m?.percentage_per_hour;
    el('eta-stat').hidden=false;
    el('eta-note').textContent=savedETA?(savedETA.historical?`Estimated ${ageText(savedETA.age)} · ${savedETA.window_minutes} min pace`:savedETA.tentative?'Early estimate':`At your ${savedETA.window_minutes} min pace`):eta?`At your ${windowMinutes} min pace`:'Needs recent EXP gains';
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
    const rolling=g?.policy==='public_endpoint_window_v2';
    if(!row.connect_previous || !Number.isFinite(a) || !Number.isFinite(b) || b<=a || a<previousEnd || (rolling?b<start || b-a>range*1000:a<start) || b>anchor || !Number.isFinite(amount) || amount<0 && g.policy!=='public_endpoint_window_v1')continue;
    previousEnd=b;
    if(rolling || g.policy==='public_endpoint_window_v1') {
      const bin=bins[Math.min(bins.length-1,Math.floor((b-start)/step))];
      bin.value=(bin.value ?? 0)+amount;bin.covered=Math.min(seconds,bin.covered+(b-a)/1000);bin.intervals++;bin.gap=true;
      continue;
    }
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
  const intervals=currentLevelOnly?rolling?.current_level_chart_intervals ?? rolling?.chart_intervals:rolling?.chart_intervals;
  const history=intervals?intervals.map(g=>({gain:g,connect_previous:true,level:{value:g.level}})):data?.history ?? [],level=rolling?.current_level ?? displayLevel(data?.player ?? {})?.value;
  const rows=currentLevelOnly?history.filter(p=>p.level.value===level):history,anchor=Date.parse(rolling?.as_of ?? data?.player?.recent_windows?.[String(windowMinutes)]?.end ?? data?.player?.latest_attempt_at ?? history.at(-1)?.timestamp);
  const chart=bucketSeconds===1800 && rolling?{
    start:Date.parse(rolling.start),end:Date.parse(rolling.end),seconds:1800,range:86400,
    bins:rolling.buckets.map(b=>({...b,start:Date.parse(b.start),end:Date.parse(b.end),value:b.value?.approximate ?? null,covered:b.covered.approximate}))
  }:bucketHistory(bucketSeconds===1800?[]:rows,bucketSeconds===1800?Date.parse(data?.served_at):anchor,bucketSeconds,bucketSeconds===1800?null:windowMinutes*60);
  if(!chart){el('history-note').textContent='Your next adventure starts here.';return;}
  const width=Math.max(300,Math.min(960,svg.clientWidth||960)),plotWidth=width-76;
  svg.setAttribute('viewBox',`0 0 ${width} 250`);svg.setAttribute('aria-label','EXP gained over time; dashes mean no data');
  svg.dataset.start=new Date(chart.start).toISOString();svg.dataset.end=new Date(chart.end).toISOString();
  const max=Math.max(1,...chart.bins.map(b=>b.value ?? 0)),scale=10**Math.floor(Math.log10(max)),top=Math.ceil(max/scale)*scale;
  const bottom=Math.min(0,...chart.bins.map(b=>b.value ?? 0)),yValue=v=>200-(v-bottom)/(top-bottom)*160;
  const x=t=>54+(t-chart.start)/(chart.end-chart.start)*plotWidth;
  function shape(tag,attrs,title){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(title)n.append(node('title','',title));svg.append(n);return n;}
  for(let i=0;i<=4;i++){
    const y=200-i*40;
    shape('line',{x1:54,x2:width-22,y1:y,y2:y,class:'chart-grid'});
    shape('text',{x:44,y:y+4,'text-anchor':'end'}).textContent=expText(bottom+(top-bottom)*i/4);
  }
  for(const bin of chart.bins){
    const left=x(bin.start)+2,w=Math.max(2,x(bin.end)-x(bin.start)-4),height=bin.value==null?0:Math.max(2,Math.abs(yValue(bin.value)-yValue(0)));
    shape('rect',{x:left,y:bin.state==='missing'?205:Math.min(yValue(bin.value),yValue(0)),width:w,height:bin.state==='missing'?2:height,rx:2,
      class:`exp-column ${bin.state}`});
    inspect(shape('rect',{x:left,y:25,width:w,height:183,fill:'transparent',class:'bar-hit'}),`bar:${bin.start}:${bin.end}`,
      `${localTime(bin.start)}\n${bin.value==null?'No data (not zero EXP)':`~${expText(bin.value,true)} EXP\n${bin.state==='partial'?'Partly tracked':'Fully tracked'}`}`);
  }
  const ticks=width<600?3:5;
  for(let i=0;i<ticks;i++){
    const tick=new Date(chart.start+(chart.end-chart.start)*i/(ticks-1)).toISOString();
    const attrs={x:54+plotWidth*i/(ticks-1),'text-anchor':i===0?'start':i===ticks-1?'end':'middle'};
    shape('text',{...attrs,y:232}).textContent=tick.slice(11,16);
    if(chart.range===86400)shape('text',{...attrs,y:248}).textContent=tick.slice(5,10);
  }
  const count=chart.bins.filter(b=>b.value!=null).length;
  el('history-note').textContent=`${chart.seconds/60} min per bar · last ${chart.range<3600?chart.range/60+' min':chart.range/3600+' hours'} · times in UTC${current(data.player).stale || rollingFailed && bucketSeconds===1800?' · saved history':''}${count?'':' · no data in this period'}`;
  el('history-note').title='The 24h view always includes all levels.';
}
function drawHistory() {
  const focus=document.activeElement?.dataset?.tipKey,openKey=tipKey,position=tipPosition;
  document.querySelectorAll('[data-chart]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.chart===chartMode)));
  document.querySelectorAll('[data-bucket]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.bucket)===bucketSeconds)));
  el('bucket-controls').hidden=chartMode!=='exp';
  if(chartMode==='exp')drawExpHistory();else drawPercentageHistory();
  const all=data?.history ?? [],anchor=Date.parse(data?.tracked_history?.as_of ?? data?.player?.recent_windows?.[String(windowMinutes)]?.end ?? data?.player?.latest_attempt_at ?? all.at(-1)?.timestamp);
  const event=(data?.player?.level_events ?? []).filter(e=>Date.parse(e.timestamp)>=anchor-windowMinutes*60000).at(-1);
  const label=!event?'':event.inferred?`Level ${event.level} reached`:`Level ${event.level} reached!`;
  if(el('level-event').textContent!==label)el('level-event').textContent=label;
  el('level-event').hidden=!event;
  el('level-event').title=!event?'':event.inferred?`Up from Lv. ${event.previous_level}, spotted when the EXP bar reset${event.status==='corroborated'?' and since confirmed':'; not confirmed yet'}.`:`Reached ${localTime(event.timestamp)}.`;
  const targets=[...document.querySelectorAll('#history-chart [data-tip-key]')];
  if(focus){targets.find(n=>n.dataset.tipKey===focus)?.focus({preventScroll:true});if(!openKey)hideTip();}
  if(openKey){const target=targets.find(n=>n.dataset.tipKey===openKey);if(target)showTip(target,position);else hideTip();}
}
function drawPercentageHistory() {
  const svg=el('history-chart');svg.replaceChildren();
  svg.setAttribute('aria-label','Level % over time; level-ups are marked');
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
  const visible=p=>p.reading && p.reading.bp!=null && p.level.value!=null && (!currentLevelOnly || p.level.value===level);
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
      x1:x(previous.time),y1:y(previous.reading.bp/100),x2:x(p.time),y2:y(p.reading.bp/100),class:'trend'});
    if(visible(p))inspect(shape('circle',{cx:x(p.time),cy:y(p.reading.bp/100),r:4,class:p.reading.evidence==='grammar_recovered'?'recovered':'sample'}),
      `point:${p.event_id}`,`${localTime(p.timestamp)}\n${p.level.value!=null?'Lv. '+p.level.value+' · ':''}${p.reading.percentage}%\n${p.reading.exp!=null || p.reading.estimated_exp?displayedExp(p.reading,true)+' EXP':'EXP unavailable'}`);
    else inspect(shape('path',{d:`M${x(p.time)-3} 185l6 6m0-6-6 6`,class:'missing'}),`point:${p.event_id}`,`${localTime(p.timestamp)}\nCouldn't read EXP`);
  });
  let previousLevel=null;
  for(const p of windowPoints.filter(p=>p.reading && p.level.value!=null)) {
    if(previousLevel!=null && p.level.value!==previousLevel) {
      const event=(data.player.level_events ?? []).find(e=>e.level===p.level.value && Date.parse(e.first_observed_at)<=p.time);
      shape('line',{x1:x(p.time),x2:x(p.time),y1:20,y2:180,class:'level-transition'});
      shape('text',{x:Math.min(width-75,x(p.time)+4),y:16,class:'level-transition-label'}).textContent=
        !event?`Lv. ${p.level.value}`:event.inferred && event.status!=='corroborated'?`Lv. ${p.level.value}`:`Level ${p.level.value}!`;
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
  el('history-note').textContent=`${currentLevelOnly && level!=null?'Lv. '+level+' · ':''}Last ${windowMinutes} min · times in UTC${readable?'':' · no data in this period'}${unavailable?' · ✕ couldn\'t read EXP':''}${current(data.player).stale?' · saved history':''}`;
  el('history-note').title='';
}
async function poll() {
  if(activeController)return;
  clearTimeout(pollTimer);
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),5000),requested=performance.now();
  const requestedView=viewCharacter;
  const requestedMode=boardMode,unchanged=()=>requestedView===viewCharacter && requestedMode===boardMode;
  activeController=controller;
  try {
    // Name the chart history and tracked packet already held; the server omits them while unchanged.
    const held=channel && data?.history!==undefined && data.tracked_history!==undefined && data.history_revision && data.tracked_revision;
    const query=new URLSearchParams(held?{history:data.history_revision,tracked:data.tracked_revision}:{});
    if(requestedView)query.set('character',requestedView);
    if(view==='board' && requestedMode==='characters')query.set('mode','characters');
    const response=await fetch(String(query)?`${endpoint}?${query}`:endpoint,{cache:'no-store',signal:controller.signal});
    const body=await response.json().catch(()=>({}));
    if(!unchanged())return;  // The visitor chose another character or homepage mode meanwhile.
    // The first publication or a changed character/session is not ready yet.
    warming=response.status===503 && body.error==='warming_up';
    if(warming){data=null;rollingData=null;rollingRevision=null;}
    if(response.status===404 && body.error==='unknown_character'){selectCharacter(null,'replace');return;}
    if(!response.ok)throw new Error();
    // An omitted section is the same revision this page holds; anything else arrives in full.
    if(held && body.history===undefined && body.history_revision===data.history_revision)body.history=data.history;
    if(held && body.tracked_history===undefined && body.tracked_revision===data.tracked_revision)body.tracked_history=data.tracked_history;
    data=body;receivedAt=requested;failed=false;
    if(view==='player' && Array.isArray(data.roster))roster=data.roster;
    if(view==='player' && data.tracked_history){rollingData=data.tracked_history;rollingReceived=performance.now();rollingFailed=false;}
    if(view==='board')renderBoard();else { renderPlayer();if(view==='player'){renderRoster();drawHistory();if(Array.isArray(data.history))pollRolling();} }
  } catch { if(!unchanged())return;failed=true;if(view==='board')renderBoard();else renderPlayer(); }
  finally { clearTimeout(timeout);activeController=null;pollTimer=setTimeout(poll,unchanged()?2000:0); }
}

function rosterLink(r,viewing,className) {
  const link=node('a',className),seen=node('span',r.current?'roster-live':'roster-seen',r.current?'Current':r.last_seen_at?'':'Not seen yet');
  // The tracked character's link follows live tracking; others are stable, shareable views.
  link.href=r.current?location.pathname:`${location.pathname}?character=${r.id}`;link.dataset.character=r.id;
  if(String(r.id)===viewing)link.setAttribute('aria-current','page');
  if(!r.current && r.last_seen_at)seen.dataset.seen=r.last_seen_at;
  const meta=node('span','roster-meta',`Lv. ${r.level ?? '—'} · `);meta.append(seen);
  link.append(node('span','roster-name',r.label),meta);
  link.title=`${r.label} · ${r.current?'currently tracked':r.last_seen_at?'last seen '+localTime(r.last_seen_at):'not seen yet'}`;
  link.addEventListener('click',e=>{
    if(e.button!==0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)return;
    e.preventDefault();el('roster-all').open=false;selectCharacter(r.current?null:String(r.id));
  });
  return link;
}
function rosterEdges() {
  const track=el('roster-track'),start=track.scrollLeft>1,end=track.scrollLeft+track.clientWidth<track.scrollWidth-1;
  track.dataset.more=start && end?'both':start?'start':end?'end':'';
}
function rosterAges() {
  const now=data?.served_at?Date.parse(data.served_at)+(performance.now()-receivedAt):Date.now();
  document.querySelectorAll('#roster [data-seen]').forEach(n=>{n.textContent=ageText(Math.max(0,(now-Date.parse(n.dataset.seen))/1000));});
}
function renderRoster() {
  // Two or more saved characters; the server already excludes the unrecognized placeholder.
  el('roster').hidden=roster.length<2;
  const viewing=viewCharacter ?? String(roster.find(r=>r.current)?.id ?? '');
  const key=JSON.stringify([roster.map(r=>[r.id,r.label,r.level,r.current,r.current?null:r.last_seen_at]),viewing]);
  if(key!==rosterKey) {
    rosterKey=key;
    const track=el('roster-track'),left=track.scrollLeft,focused=document.activeElement?.closest?.('#roster a');
    const focus=focused && [focused.dataset.character,focused.closest('#roster-list')?'roster-list':'roster-track'];
    track.replaceChildren(...roster.map(r=>rosterLink(r,viewing,'roster-chip')));track.scrollLeft=left;
    el('roster-list').replaceChildren(...roster.map(r=>{const item=node('li');item.dataset.name=r.label.toLowerCase();item.append(rosterLink(r,viewing,'roster-option'));return item;}));
    el('roster-all').hidden=roster.length<7;
    el('roster-count').textContent=`All ${roster.length}`;el('roster-count').setAttribute('aria-label',`All ${roster.length} characters`);
    filterRoster();
    if(focus)el(focus[1]).querySelector(`[data-character="${focus[0]}"]`)?.focus({preventScroll:true});
  }
  // Ages change chip widths; fill them before positioning the viewed character.
  rosterAges();
  if(viewing!==rosterViewing)el('roster-track').querySelector('[aria-current]')?.scrollIntoView({block:'nearest',inline:'center'});
  rosterViewing=viewing;rosterEdges();
}
function filterRoster() {
  const text=el('roster-search').value.trim().toLowerCase();
  for(const item of el('roster-list').children)item.hidden=!!text && !item.dataset.name.includes(text);
}
function selectCharacter(id,mode='push') {
  if(id===viewCharacter)return;
  viewCharacter=id;
  if(mode!=='none') {
    const url=new URL(location.href);if(id)url.searchParams.set('character',id);else url.searchParams.delete('character');
    history[mode==='replace'?'replaceState':'pushState'](null,'',url);
  }
  // Never show the previous character's numbers while the chosen one loads.
  data=null;rollingData=null;rollingRevision=null;warming=true;
  renderPlayer();renderRoster();hideTip();
  if(activeController)activeController.abort();else poll();
}

async function pollRolling(force=false) {
  if(data?.tracked_history)return;
  if(view!=='player' || rollingController)return;
  const revision=JSON.stringify([data?.player?.character?.id,data?.player?.session_id,data?.player?.latest_attempt_at,data?.player?.manual_correction?.id]);
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
if(view==='board') {
  document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>selectBoard(button.dataset.mode)));
  el('character-filter').addEventListener('input',renderBoard);el('character-sort').addEventListener('change',renderBoard);
  globalThis.addEventListener?.('popstate',()=>selectBoard(boardParam(),'none'));
}
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
  globalThis.addEventListener?.('resize',()=>{renderPlayer();drawHistory();rosterEdges();});
  const url=`${location.origin}/live/overlay/${encodeURIComponent(channel)}`;
  el('overlay-link').href=url;el('diagnostics').href=`/dashboard/${channel}`;el('history-link').href=`/dashboard/${channel}`;
  const track=el('roster-track'),all=el('roster-all');
  const modified=e=>e.ctrlKey || e.metaKey || e.shiftKey || e.altKey;
  let drag=null,suppressClick=false;
  track.addEventListener('wheel',e=>{
    if(modified(e) || e.deltaX || !e.deltaY)return;
    const before=track.scrollLeft,max=track.scrollWidth-track.clientWidth;
    const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?track.clientWidth:1);
    if(max<=1 || delta<0 && before<=1 || delta>0 && before>=max-1)return;
    track.scrollLeft=Math.max(0,Math.min(max,before+delta));
    if(track.scrollLeft!==before)e.preventDefault();
  },{passive:false});
  const finishDrag=e=>{
    if(!drag || e.pointerId!==drag.id)return;
    const id=drag.id;drag=null;delete track.dataset.dragging;
    if(track.hasPointerCapture(id))track.releasePointerCapture(id);
  };
  track.addEventListener('pointerdown',e=>{
    suppressClick=false;
    if(e.pointerType!=='mouse' || e.isPrimary===false || e.button!==0 || modified(e) || track.scrollWidth<=track.clientWidth+1)return;
    drag={id:e.pointerId,x:e.clientX,left:track.scrollLeft,moved:false};
  });
  track.addEventListener('pointermove',e=>{
    if(!drag || drag.id!==e.pointerId)return;
    if(!(e.buttons&1) || modified(e)){finishDrag(e);return;}
    const distance=e.clientX-drag.x;
    if(!drag.moved && Math.abs(distance)<6)return;
    if(!drag.moved){drag.moved=true;suppressClick=true;track.dataset.dragging='true';track.setPointerCapture(e.pointerId);}
    e.preventDefault();track.scrollLeft=drag.left-distance;
  });
  for(const type of ['pointerup','pointercancel','lostpointercapture'])track.addEventListener(type,finishDrag);
  track.addEventListener('pointerleave',e=>{if(drag && !drag.moved)finishDrag(e);});
  track.addEventListener('dragstart',e=>{if(drag)e.preventDefault();});
  // Capture phase prevents the character link from handling the click after a drag.
  track.addEventListener('click',e=>{
    if(!suppressClick || e.detail===0 || e.button!==0 || modified(e))return;
    suppressClick=false;e.preventDefault();e.stopImmediatePropagation();
  },true);
  track.addEventListener('scroll',rosterEdges,{passive:true});
  track.addEventListener('keydown',e=>{
    const links=[...track.querySelectorAll('a')],at=links.indexOf(document.activeElement);
    const next={ArrowRight:at+1,ArrowLeft:at-1,Home:0,End:links.length-1}[e.key];
    if(at<0 || next==null || !links[next])return;
    e.preventDefault();links[next].focus();links[next].scrollIntoView({block:'nearest',inline:'nearest'});
  });
  el('roster-search').addEventListener('input',filterRoster);
  all.addEventListener('toggle',()=>{if(all.open){el('roster-search').value='';filterRoster();el('roster-search').focus();}});
  all.addEventListener('keydown',e=>{if(e.key==='Escape' && all.open){e.stopPropagation();all.open=false;all.querySelector('summary').focus();}});
  document.addEventListener('pointerdown',e=>{if(all.open && !all.contains(e.target))all.open=false;});
  globalThis.addEventListener?.('popstate',()=>selectCharacter(characterParam(),'none'));
  el('copy-overlay').addEventListener('click',async()=>{try {await navigator.clipboard.writeText(url);el('copy-status').textContent='Copied · use a 500 × 160 Browser Source';}catch{el('copy-status').textContent='Copy the Open OBS overlay link · 500 × 160';}});
}
poll();setInterval(()=>{if(view==='board')renderBoard();else renderPlayer();if(view==='player')rosterAges();},1000);
