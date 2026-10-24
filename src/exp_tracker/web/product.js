"use strict";

const view=document.body.dataset.view;
if(view==='board' || view==='player') {
  const background=new URLSearchParams(location.search).get('background');
  document.body.dataset.background=['sleepywood','kerning'].includes(background)?background:new Date().getDate()%2?'sleepywood':'kerning';
  prepareBackground(document.body.dataset.background);
  try {
    if(!sessionStorage.getItem('site-intro-seen'))document.body.dataset.intro='true';
    sessionStorage.setItem('site-intro-seen','true');
  } catch {} // Storage can be unavailable; the header stays visible.
}
async function prepareBackground(town) {
  document.body.dataset.backgroundState='loading';
  const files=[`${town}.webp`,town==='sleepywood'?'sleepywood-forest.webp':'kerning-sky.webp'];
  try {
    await Promise.all(files.map(file=>{const image=node('img');image.src=`/static/${file}`;return image.decode();}));
    document.body.dataset.backgroundState='ready';
  } catch { document.body.dataset.backgroundState='failed'; } // Keep the navy fallback if either layer fails.
}
const channel=view==='overlay'?location.pathname.split('/')[3]:view==='player'?location.pathname.split('/')[2]:null;
// The static Pages export names its API origin on <html data-api> (tools/export_pages.py); the Python server
// leaves it unset, so requests stay same-origin. Same exact-origin rule as the server's --cors-origin.
const apiOrigin=document.documentElement?.dataset.api ?? '';
if(apiOrigin && !/^(https:\/\/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+|http:\/\/(?:localhost|127\.0\.0\.1))(?::[0-9]{1,5})?$/.test(apiOrigin))
  throw new Error(`Invalid data-api origin: ${apiOrigin}`);
const endpoint=channel?`${apiOrigin}/api/players/${encodeURIComponent(channel)}`:`${apiOrigin}/api/players`;
// The server lowercases logins; an empty path keeps the static HTML title.
if(view==='player' && channel)document.title=`${channel.toLowerCase()} · EXP Tracker`;
const numbers=new Intl.NumberFormat('en-US'),shortNumber=new Intl.NumberFormat('en-US',{maximumSignificantDigits:3});
const wholeNumbers=new Intl.NumberFormat('en-US',{maximumFractionDigits:0});
// Times use the visitor's zone, or one they picked (remembered in this browser only).
let timeZone,localDates,clockMinutes,clockSeconds,monthDay;
function setTimeZone(zone) {
  try {new Intl.DateTimeFormat('en-US',{timeZone:zone || undefined});} catch {zone=null;}
  timeZone=zone || undefined;
  localDates=new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'long',timeZone});
  clockMinutes=new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',timeZone});
  clockSeconds=new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone});
  monthDay=new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',timeZone});
}
setTimeZone((()=>{try {return localStorage.getItem('timezone');} catch {return null;}})());
function zoneLabel() { return new Intl.DateTimeFormat('en-US',{timeZone,timeZoneName:'short'}).formatToParts(new Date()).find(p=>p.type==='timeZoneName')?.value ?? 'local time'; }
// Live updates wait while the visitor has text selected, so re-rendering doesn't clear the selection.
let deferredRender=false,characterFade=false;
const selecting=()=>{const s=globalThis.getSelection?.();return !!s && s.rangeCount>0 && !s.isCollapsed;};
const sorts=new Set(['exp_hour','level','day']);
let data=null,receivedAt=0,failed=false,sort='level',characterSort='level',windowMinutes=view==='player'?15:5,chartMode='exp',bucketSeconds=1800,pollTimer=null,activeController=null;
// The character page's charts keep their own time windows, separate from the stat cards above them.
let chartWindow=60,longChartWindow=1440,lineWindow=15;
// Overlay options come from the copied overlay URL; anything unknown falls back to the first choice.
const OVERLAY_CHOICES={layout:['card','bar','rates','chart'],title:['site','tracker'],icon:['off','on'],name:['both','character','twitch','none'],theme:['night','day'],interval:['60','300','1800'],range:['60','15','30','720','1440']};
const OVERLAY_COLORS=['header','bar','accent'];
const THEME_COLORS={night:{header:'705035',bar:'a6ef2e',accent:'ffc56b'},day:{header:'8a6440',bar:'7fcc12',accent:'a8520a'}};
function headerInk(hex) {
  const rgb=hex.match(/../g).map(channel=>{const s=parseInt(channel,16)/255;return s<=.04045?s/12.92:((s+.055)/1.055)**2.4;});
  return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]>.179?'dark':'light';
}
// Colors dim only once values are this old; the ~1 min stale flag is too twitchy for a cosmetic cue.
const FADE_AFTER_SECONDS=300;
function faded(age) { return failed || age==null || age>FADE_AFTER_SECONDS; }
function overlayOptions(search) {
  const q=new URLSearchParams(search),options={};
  for(const [key,allowed] of Object.entries(OVERLAY_CHOICES))options[key]=allowed.includes(q.get(key))?q.get(key):allowed[0];
  if(options.interval==='1800'){if(!['720','1440'].includes(options.range))options.range='1440';}
  else if(['720','1440'].includes(options.range))options.range='60';
  for(const key of OVERLAY_COLORS)if(/^[0-9a-f]{6}$/i.test(q.get(key) ?? ''))options[key]=q.get(key).toLowerCase();
  return options;
}
// Also called by the character page's live preview (same origin) as options change.
function applyOverlay(o) {
  Object.assign(document.body.dataset,{layout:o.layout,theme:o.theme,name:o.name,icon:o.icon,interval:o.interval,range:o.range});
  document.body.dataset.headerInk=headerInk(o.header ?? THEME_COLORS[o.theme].header);
  const historyLabel=`${Number(o.interval)/60} min · ${o.range==='1440'?'24h':o.range==='720'?'12h':o.range==='60'?'last hour':`last ${o.range} min`}`;
  if(view==='overlay'){
    el('general-history-caption').textContent=historyLabel;
    el('general-chart').setAttribute('aria-label',`EXP history: ${historyLabel}; dashes mean no data`);
  }
  for(const key of OVERLAY_COLORS)if(/^[0-9a-f]{6}$/.test(o[key] ?? ''))document.body.style.setProperty('--'+key,'#'+o[key]);else document.body.style.removeProperty?.('--'+key);
  el('overlay-brand').textContent=o.title==='site'?'msxp.pages.dev':'EXP TRACKER';
  if(data?.player)renderPlayer();
}
let rollingData=null,rollingReceived=0,rollingRevision=null,rollingFailed=false,rollingController=null,rollingTimer=null;
let tip=null,tipKey=null,tipPosition=null,tipDismissed=false,lastPointer=null;
let currentLevelOnly=false,warming=false;
// View-only character choice (?character=ID); null follows whichever character is being tracked.
const characterParam=()=>{const id=new URLSearchParams(location.search).get('character');return view==='overlay'?id || null:view==='player' && /^[1-9][0-9]{0,17}$/.test(id ?? '')?id:null;};
let viewCharacter=characterParam(),roster=[],rosterKey='',rosterViewing=null;
const boardParam=()=>new URLSearchParams(location.search).get('mode')==='characters'?'characters':'streamers';
let boardMode=boardParam(),shownMode=boardMode;  // shownMode: the list on screen, which switches only once its data has arrived.
const inactiveView=()=>view!=='board' && data?.view?.current===false;
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
// One unit only; the exact time is in the hover text. Years are capped so the fixed-width roster chip never overflows.
function ageText(seconds) { if(seconds==null)return 'No reading yet';if(seconds<60)return `${Math.floor(seconds)}s ago`;if(seconds<3600)return `${Math.floor(seconds/60)}m ago`;if(seconds<86400)return `${Math.floor(seconds/3600)}h ago`;if(seconds<7*86400)return `${Math.floor(seconds/86400)}d ago`;if(seconds<365*86400)return `${Math.floor(seconds/(7*86400))}w ago`;return `${Math.min(99,Math.floor(seconds/(365*86400)))}y ago`; }
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
// No "EXP" suffix: the card's label already says "EXP gained", and the suffix overflowed narrow cards.
function movementText(summary) { return summary?.estimated_exp?`+${expText(summary.estimated_exp.value.approximate)}`:summary?.difference_percentage_points!=null?`+${summary.difference_percentage_points}%`:'—'; }
function displayedExp(r,full=false) {
  return r?.exp!=null?(['grammar_recovered','conditional_symbol'].includes(r.evidence)?'~ ':'')+expText(r.exp,full):
    r?.estimated_exp?`~${expText(r.estimated_exp.value.approximate,full)}`:'—';
}
// Public hover text stays short; the evidence behind each value is in the local Advanced pages.
function expTitle(r) {
  if(r?.evidence==='manual_admin')return `Entered manually by the tracker operator.${r.estimated_exp?' EXP is estimated from the entered %.':''}${r.estimated_percentage?' % is estimated from the entered EXP.':''}${r.exp_validity?.status==='invalid'?' The entered EXP and % don\'t fully match.':''}`;
  if(r?.estimated_exp)return 'Estimated from the level %; the exact EXP isn\'t shown on stream.';
  if(r?.evidence==='level_start')return 'Start of the new level · no EXP read at this level yet';
  return r?.exp_validity?.status==='invalid'?'EXP hidden: it didn\'t match the level and %':r?.exp==null?'EXP not available yet':`${numbers.format(BigInt(r.exp))} EXP${['grammar_recovered','conditional_symbol'].includes(r.evidence)?' · partly unclear on stream, may be slightly off':''}`;
}
function percentageText(r) { return r?.percentage!=null?`${r.estimated_percentage?'~':''}${r.percentage}%`:'—'; }
function sourceText(p) { return `${p.source_kind==='file'?'Video · ':p.source_kind==='twitch'?'ttv/':''}${p.channel}`; }
// On a phone the channel sits right beside the name, so it opens the same profile instead of Twitch (the profile links there).
function sourceLink(p,profile) {
  if(profile && globalThis.matchMedia?.('(max-width:650px)').matches) {
    const source=node('a','channel',sourceText(p));source.href=profile;source.tabIndex=-1;return source;  // The name is the keyboard stop.
  }
  const source=node(p.source_kind==='twitch'?'a':'span','channel',sourceText(p));
  if(p.source_kind==='twitch') {
    source.href=`https://www.twitch.tv/${encodeURIComponent(p.channel)}`;source.target='_blank';source.rel='noopener noreferrer';
    source.title=`Watch ${p.channel} on Twitch`;
  }
  return source;
}
function lastSeenReading(p) { return p.last_seen?.reading ?? p.last_seen?.full_exp ?? null; }
// A level newer than the reading's: show that level's start, never the old level's % beside it.
function shownReading(r,level) {
  return r?.level?.value!=null && level?.value!=null && level.value>r.level.value && Date.parse(level.timestamp)>Date.parse(r.timestamp)
    ?{...r,exp:'0',percentage:'0.00',bp:0,estimated_exp:null,estimated_percentage:false,exp_validity:null,evidence:'level_start'}:r;
}
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
    const rate=e.exp_per_hour?`${expText(e.exp_per_hour.value.approximate)} EXP/hour`:e.percentage_per_hour?`${e.percentage_per_hour.value.approximate.toFixed(2)}% / hour`:null;
    return rate?`${rate} · ${pace.label}`:'Paused';
  }
  const early=p.early_pace;
  if(!early?.active || current(p).stale || failed)return null;
  const e=early.estimates;
  const rate=e.exp_per_hour?`${expText(e.exp_per_hour.value.approximate)} EXP/hour`:e.percentage_per_hour?`${e.percentage_per_hour.value.approximate.toFixed(2)}% / hour`:null;
  return rate?`${rate} · Early estimate`:null;
}
function publicPace(p,minutes=null) {
  // minutes reads that lookback's saved pace (overlay rates); otherwise the page's own selection.
  const windowed=view==='player' || view==='overlay' || minutes!=null,recent=minutes!=null?p.recent_windows?.[String(minutes)]:recentWindow(p);
  if(windowed && recent?.status==='history_limit')return null;
  const compatible=p.responsive_pace?.level==null || p.responsive_pace.level===(p.reading?.level?.value ?? p.display_level?.value);
  const pace=windowed && recent?(recent.pace ?? recent.last_observed_pace ?? ((minutes ?? windowMinutes)===5 && compatible?p.responsive_pace:null)):p.responsive_pace;
  if(!pace)return null;
  const age=pace.age_seconds+(performance.now()-receivedAt)/1000;
  const policy=pace.presentation;
  const active=pace.active && !inactiveView() && !(windowed && recent && !recent.pace) && !current(p).stale && !failed && (!policy || policy.state==='observed');
  let estimates=active?pace.estimates:{...pace.estimates,eta:null};
  const expired=policy?.state==='paused' || policy?.running && age>=(policy.expire_after_seconds ?? policy.pause_after_seconds);
  if(expired)estimates={exp_per_hour:null,percentage_per_hour:null,eta:null};
  return {active,age,label:expired?'Paused':failed?`As of ${ageText(age)}`:active?(pace.tentative?'Early estimate':'Recent pace'):`As of ${ageText(age)}`,
    estimates,source:pace};
}
function publicETA(p,minutes=null) {
  const recent=minutes==null?recentWindow(p):p.recent_windows?.[String(minutes)],saved=recent?.eta;
  if(!saved)return null;
  const age=saved.age_seconds+(performance.now()-receivedAt)/1000;
  const pace=recent?.pace;
  return {...saved,age,historical:saved.historical || inactiveView() || failed || current(p).stale || !pace?.active || (pace.presentation && pace.presentation.state!=='observed')};
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
  if(o)return o.span_seconds.approximate>=windowMinutes*60?`Based on the full ${windowMinutes} min`:`Based on ${spanText((o.coverage_seconds ?? o.span_seconds).approximate)} tracked`;
  if(inactiveView())return 'Saved history';
  if(current(p).stale || failed)return 'Waiting for an update';
  if(w?.eligible)return `Based on the full ${windowMinutes} min`;
  return 'Calculating…';
}
function statusText(p) {
  // Another character's saved state: never the tracked character's capture or Twitch status.
  if(inactiveView())return `Not currently tracked · ${p.reading?'updated '+ageText(current(p).age):'nothing saved yet'}`;
  // Public status is deliberately two-state; delays and capture issues still read as Online.
  if(p.twitch?.status==='offline')return 'Offline';
  // Live in another category (e.g. Just Chatting) isn't tracked, so it doesn't read as Online either.
  const game=p.twitch?.status==='live' && p.twitch.game_name?.trim();
  return game && !/maplestory/i.test(game)?'Not in MapleStory':'Online';
}
function etaText(value,compact=false) {
  const seconds=value?.seconds?.approximate;
  if(!Number.isFinite(seconds) || seconds<0)return '—';
  const minutes=Math.round(seconds/60);
  if(!minutes)return seconds>0?'<1m':'0m';
  const days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60),rest=minutes%60;
  const parts=[];if(days)parts.push(`${days}d`);if(hours)parts.push(`${hours}h`);
  if(rest && !(compact && days))parts.push(`${rest}m`);
  return parts.join(' ');
}
function rateTitle(rate) { return rate?'Estimated from recent stream updates.':'Not enough recent updates yet.'; }
function metricValue(p,key,minutes=windowMinutes) {
  if(key==='level')return displayLevel(p)?.value ?? null;
  // A saved 24h total, so it ranks whether or not the stream is live right now.
  if(key==='day')return p.tracked_status==='ready' && p.tracked_windows?.['1440']?.available?p.tracked_windows['1440'].gain?.approximate ?? null:null;
  if(failed)return null;
  // The selected lookback also limits how old a ranked pace can be.
  const pace=publicPace(p,minutes);
  return pace && pace.age>=0 && pace.age<=minutes*60?pace.estimates.exp_per_hour?.value.approximate ?? null:null;
}
// Level ties break on EXP % within the level (Lv. 65 at 75% ranks above Lv. 65 at 50%).
function sortValue(p,key) { const value=metricValue(p,key);return key==='level' && value!=null?value+(shownReading(p.reading,p.display_level)?.bp ?? 0)/10000:value; }
function ranked(players,key) {
  const rows=players.map(player=>({player,value:metricValue(player,key),order:sortValue(player,key)})).sort((a,b)=>(a.order==null)-(b.order==null)||(b.order??0)-(a.order??0)||a.player.channel.localeCompare(b.player.channel));
  let rank=null,previous=null;
  return rows.map(({player,value,order},i)=>{if(order!=null && order!==previous)rank=i+1;previous=order;return {player,value,rank:order==null?null:rank};});
}
// A row's 24 h at a glance: tracked EXP per 30 min, a dash where nothing was tracked (never zero).
function dayChart(values) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),top=Math.max(1,...values.map(v=>v ?? 0));
  for(const [k,v] of Object.entries({class:'day-chart',viewBox:`0 0 ${values.length*3} 16`,preserveAspectRatio:'none','aria-hidden':'true'}))svg.setAttribute(k,v);
  const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent='Tracked EXP per 30 min over the last 24 hours. Dashes mean no data.';svg.append(title);
  values.forEach((v,i)=>{
    const bar=document.createElementNS('http://www.w3.org/2000/svg','rect'),height=v==null?1:Math.max(1.5,Math.max(0,v)/top*16);
    for(const [k,a] of Object.entries({x:i*3,y:16-height,width:2,height}))bar.setAttribute(k,a);
    if(v==null)bar.setAttribute('class','missing');
    svg.append(bar);
  });
  return svg;
}
// The EXP bar and beneath it the 24 h chart, today's total, the next-level ETA and the reading's age.
// The homepage keeps these short: no ~ marks, since nearly every number here is an estimate.
function expSection(r,{label,buckets,day,eta,age,ageTitle,empty='Waiting for EXP'}) {
  const section=node('div','exp-section'),bar=node('div','exp-bar'),progress=node('progress');progress.max=100;progress.value=r?.bp!=null?r.bp/100:0;progress.hidden=r?.bp==null;progress.setAttribute('aria-label',`${label} EXP progress`);
  bar.dataset.missing=String(!r);  // Partly unclear EXP keeps its ~ and hover note; the bar's border stays the same as every row's.
  const text=node('span','exp-label'),integer=node('span','exp-number',displayedExp(r,true));
  integer.dataset.compactNumber=displayedExp(r);text.title=expTitle(r);text.append(node('small','','EXP'),integer,node('span','percentage',r?.percentage!=null?`[${percentageText(r)}]`:empty));
  bar.append(progress,text);
  const meta=node('div','exp-meta');
  if(buckets?.length)meta.append(dayChart(buckets));
  if(day!=null){const total=node('span','fact',`${expText(day)} today`);total.title=`${expText(day,true)} EXP tracked in the last 24 hours`;meta.append(total);}
  if(eta){
    const title=`At the ${eta.minutes} min pace, estimated ${ageText(eta.age)}. Not a live countdown.`;
    const soon=node('span','fact eta',`Next level in ${eta.text}`),short=node('span','fact eta-short',`↑ ETA ${eta.text}`);  // Phones show the short one.
    soon.title=short.title=title;meta.append(soon,short);
  }
  const updated=node('span','updated',age);if(ageTitle)updated.title=ageTitle;
  meta.append(updated);section.append(bar,meta);return section;
}
// Phones show the reading's age beside the score label instead of under the EXP bar; CSS draws its ◎ mark.
function scoreAge(score,ago,title) { if(!ago)return;const seen=node('small','score-age',ago);if(title)seen.title=title;score.append(seen); }
// The level badge with an indicator light in its corner: lit while online, dark otherwise.
function levelPill(text,online,label) {
  const level=node('span','level'),led=node('span','led');led.dataset.on=String(online);led.setAttribute('role','img');led.setAttribute('aria-label',label);led.title=label;
  level.append(node('small','','LV.'),node('strong','',text),led);return level;
}
// Online/offline filter, shared by Streamers and Characters until the page reloads: All, then Online only, then Offline only.
const PRESENCE={all:{label:'All',next:'online',title:'Showing everyone · click for online only'},
  online:{label:'Online',next:'offline',title:'Showing online only · click for offline only'},
  offline:{label:'Offline',next:'all',title:'Showing offline only · click to show everyone'}};
let presence='all';
const shown=online=>presence==='all' || online===(presence==='online');
function showPresence() {
  const toggle=el('presence'),{label,title}=PRESENCE[presence];toggle.dataset.presence=presence;toggle.title=title;toggle.setAttribute('aria-label',title);
  if(toggle.textContent!==label)toggle.textContent=label;
}
function rowETA(p,minutes=windowMinutes) {
  // Retain dated durations within the selected window; never turn them into a countdown.
  const saved=publicETA(p,minutes);
  return saved && saved.age>=0 && saved.age<=minutes*60 && etaText(saved.estimate)!=='—'
    ?{text:etaText(saved.estimate),minutes:saved.window_minutes,age:saved.age}:null;
}
function entry({player:p,value,rank}) {
  const r=shownReading(p.reading,p.display_level),s=current(p),row=node('li','entry streamer-entry');row.dataset.channel=p.channel;row.dataset.rank=rank??'';row.dataset.stale=String(s.stale && faded(s.age));
  row.dataset.metric=sort;
  const badge=node('span','rank',rank??'—');badge.dataset.medal=rank!=null && rank<=3?rank:'';badge.setAttribute('aria-label',rank==null?'Not ranked yet':`Rank ${rank}`);
  const level=levelPill(levelText(p),statusText(p)==='Online',statusText(p));level.title=levelTitle(p);
  const identity=node('div','identity'),name=node('a','character',p.character?.label ?? 'Character not selected');name.href=`/stream/${p.channel}`;name.title=name.textContent;
  identity.append(name,sourceLink(p,name.href));
  const ago=r?ageText(s.age):null,seenAt=r?.timestamp?localTime(r.timestamp):'';
  const section=expSection(r,{label:p.character?.label ?? p.channel,buckets:p.day_buckets,day:metricValue(p,'day'),eta:rowETA(p),age:ago?'Updated '+ago:'No reading yet',ageTitle:seenAt});
  row.append(badge,level,identity,section);
  if(sort==='level')value=metricValue(p,'exp_hour',5);
  const score=node('div','score');score.append(node('strong','score-value',value==null?'—':expText(value)),node('small','score-label',sort==='day'?'EXP · 24h':'EXP / hour'));
  score.title=sort!=='day'?rateTitle(value):value==null?'No tracked EXP in the last 24 hours':`${expText(value,true)} EXP in the last 24 hours while tracked`;
  scoreAge(score,ago,seenAt);row.append(score);return row;
}
// Rows update in place instead of being replaced, so hover, open tooltips and selections survive the 1 s refresh.
function patch(live,fresh) {
  if(live.nodeName!==fresh.nodeName){live.replaceWith(fresh);return;}
  if(live.nodeType!==1){if(live.nodeValue!==fresh.nodeValue)live.nodeValue=fresh.nodeValue;return;}
  for(const {name} of [...live.attributes])if(!fresh.hasAttribute(name))live.removeAttribute(name);
  for(const {name,value} of fresh.attributes)if(live.getAttribute(name)!==value)live.setAttribute(name,value);
  patchChildren(live,[...fresh.childNodes]);
}
function patchChildren(parent,nodes) {
  if(!parent.childNodes){parent.replaceChildren(...nodes);return;}  // The Node tests' stand-in DOM.
  nodes.forEach((n,i)=>{const live=parent.childNodes[i];if(live)patch(live,n);else parent.append(n);});
  while(parent.childNodes.length>nodes.length)parent.lastChild.remove();
}
function renderBoard() {
  const characters=shownMode==='characters';
  el('board-count').dataset.loading=String(!failed && (!data || !!data.warming?.length));
  document.querySelectorAll('[data-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.mode===boardMode)));
  el('entries').setAttribute('aria-busy',String(boardMode!==shownMode));  // The other list is on its way.
  el('streamer-metrics').hidden=characters;el('streamer-windows').hidden=characters || sort!=='exp_hour';el('character-sort-control').hidden=!characters;
  el('connection').textContent=failed?'Reconnecting':'';  // CSS animates the dots; the numbers shown are the last known.
  showPresence();
  if(characters){renderCharacters();return;}
  const search=el('character-filter').value.trim().toLowerCase();
  const all=data?.players ?? [],rows=ranked(all.filter(p=>shown(statusText(p)==='Online') && `${p.character?.label ?? ''} ${p.channel}`.toLowerCase().includes(search)),sort);
  const focus=document.activeElement?.closest?.('#entries a')?.getAttribute('href');
  patchChildren(el('entries'),rows.map(entry));
  [...el('entries').querySelectorAll('.exp-number')].filter(n=>n.clientWidth>0 && n.scrollWidth>n.clientWidth+1).forEach(n=>{n.textContent=n.dataset.compactNumber;});
  if(focus) [...el('entries').querySelectorAll('a')].find(a=>a.getAttribute('href')===focus)?.focus({preventScroll:true});
  el('empty').hidden=rows.length>0 || !data;
  el('empty').textContent=search?'No streamers match your search.':all.length?`No ${presence} players right now.`:'No players are being tracked yet.';
  el('board-count').textContent=data?`${rows.length<all.length?`${rows.length} of `:''}${all.length} player${all.length===1?'':'s'}${data.warming?.length?` · ${data.warming.length} more loading`:''}`:failed?'Tracker unavailable':'Loading players…';
  el('ranking-count').textContent='';el('ranking-note').textContent='';
  document.querySelectorAll('[data-sort]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.sort===sort)));
  // Only EXP / hour ranks by the short time window, so the window buttons are shown only then.
  document.querySelectorAll('[data-window]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.window)===windowMinutes)));
}
function renderCharacters() {
  const search=el('character-filter').value.trim().toLowerCase(),order=characterSort;
  document.querySelectorAll('[data-character-sort]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.characterSort===order)));
  const all=data?.characters ?? [],rows=all.filter(r=>shown(!!r.online) && `${r.label} ${r.channel}`.toLowerCase().includes(search));
  rows.sort((a,b)=>(order==='level'?(b.level ?? -1)-(a.level ?? -1):order==='name'?a.label.localeCompare(b.label):
    (Date.parse(b.reading?.timestamp) || 0)-(Date.parse(a.reading?.timestamp) || 0)) || a.channel.localeCompare(b.channel) || a.id-b.id);
  const focus=document.activeElement?.closest?.('#entries a')?.getAttribute('href');
  const now=data?.served_at?Date.parse(data.served_at)+(performance.now()-receivedAt):Date.now();
  patchChildren(el('entries'),rows.map((r,index)=>{
    const row=node('li','entry character-entry');row.dataset.channel=r.channel;row.dataset.character=r.id;row.dataset.rank=order==='level'?index+1:'';
    const badge=node('span','rank',index+1);badge.dataset.medal=order==='level' && index<3?index+1:'';badge.setAttribute('aria-label',`Rank ${index+1}`);
    const level=levelPill(r.level ?? '—',!!r.online,r.online?'Online':r.current?'Offline':'Not currently tracked');
    const identity=node('div','identity'),link=node('a','character',r.label);link.href=`/stream/${encodeURIComponent(r.channel)}?character=${r.id}`;
    identity.append(link,sourceLink({...r,source_kind:r.source_kind ?? 'twitch'},link.href));
    // The refresher's saved summary: undefined until it is built, null reading if nothing was ever read.
    const at=r.reading?.timestamp ?? r.last_seen_at,ago=at?ageText(Math.max(0,(now-Date.parse(at))/1000)):null;
    const section=expSection(shownReading(r.reading,r.display_level) ?? null,{label:r.label,buckets:r.day_buckets,day:r.day,eta:rowETA(r,5),empty:r.reading===undefined?'Loading EXP…':'No saved EXP',
      age:ago?`Updated ${ago}`:'Not seen yet',ageTitle:at?localTime(at):''});
    const value=metricValue(r,'exp_hour',5),score=node('div','score');
    score.append(node('strong','score-value',value==null?'—':expText(value)),node('small','score-label','EXP / hour'));score.title=rateTitle(value);scoreAge(score,ago,at?localTime(at):'');
    row.append(level,identity,section,badge,score);return row;
  }));
  if(focus)[...el('entries').querySelectorAll('a')].find(a=>a.getAttribute('href')===focus)?.focus({preventScroll:true});
  el('empty').hidden=rows.length>0 || !data;
  el('empty').textContent=search?'No characters match your search.':all.length?`No ${presence} characters right now.`:'No saved characters yet.';
  el('board-count').textContent=data?`${rows.length<all.length?`${rows.length} of `:''}${all.length} character${all.length===1?'':'s'}${data.warming?.length?` · ${data.warming.length} more loading`:''}`:failed?'Tracker unavailable':'Loading characters…';
  el('ranking-note').textContent='';el('ranking-count').textContent='';  // The header count covers search and filter results.
}
function selectBoard(mode,historyMode='push') {
  if(!['streamers','characters'].includes(mode) || mode===boardMode)return;
  boardMode=mode;
  if(historyMode!=='none'){
    const url=new URL(location.href);if(mode==='characters')url.searchParams.set('mode',mode);else url.searchParams.delete('mode');
    history.pushState(null,'',url);
  }
  renderBoard();  // Only the pressed button changes; the current list stays until the other arrives (see poll).
  if(activeController)activeController.abort();else poll();
}
function renderPlayer() {
  const p=data?.player,r=p?.reading;
  if(!p) {
    if(warming || view==='overlay' && viewCharacter && failed) {
      // Warming can mean ownership changed: never retain another character's display.
      for(const id of ['level','exp','percentage','movement','rate','pp-rate','eta','age','tracked-exp','tracked-note','early-value','eta-note','segment-note','history-note','window-rate']) {
        const target=el(id);if(target){amount(id,'—','—');target.title='';}
      }
      el('level').textContent='Lv. —';el('progress').hidden=true;el('progress').value=0;
      if(view==='overlay'){
        el('general-chart').replaceChildren();el('overlay-chart').replaceChildren();el('hour-total').textContent='—';
        document.querySelectorAll('[data-rate-window]').forEach(n=>{n.textContent='—';});
      }
      for(const id of ['player-name','player-source','streamer','character'])if(el(id)){el(id).textContent=channel;el(id).title='';}
      if(!data?.summary?.day_buckets)el('history-chart')?.replaceChildren();if(el('level-event'))el('level-event').hidden=true;
      // A chosen saved character keeps its roster name, level and last sighting while its history loads.
      const chosen=view==='player' && roster.find(r=>viewCharacter?String(r.id)===viewCharacter:r.current);
      if(chosen){el('player-name').textContent=chosen.label;el('level').textContent=`Lv. ${chosen.level ?? '—'}`;
        if(chosen.last_seen_at)el('age').textContent=`Updated ${ageText(Math.max(0,(Date.now()-Date.parse(chosen.last_seen_at))/1000))}`;}
      const saved=chosen && String(data?.summary?.character_id)===String(chosen.id)?data.summary:null,reading=shownReading(saved?.reading,saved?.display_level);
      if(reading) {
        const bp=reading.bp ?? (reading.percentage!=null?Math.round(Number(reading.percentage)*100):null);
        el('progress').hidden=bp==null;el('progress').value=bp==null?0:bp/100;
        const exp=displayedExp(reading,true);amount('exp',exp==='—'?'—':`${exp} EXP`,displayedExp(reading));el('exp').title=expTitle(reading);
        el('percentage').textContent=percentageText(reading);
        el('age').textContent=`Updated ${ageText(Math.max(0,(Date.now()-Date.parse(reading.timestamp))/1000))}`;el('age').title=localTime(reading.timestamp);
      }
      if(saved?.day!=null) {
        amount('tracked-exp',`${expText(saved.day,true)}`,`${expText(saved.day)}`);
        el('tracked-note').textContent='Saved · preparing history';
      }
      hideTip();
    }
    el('status').textContent=warming?'Preparing saved history…':failed?'Tracker unavailable':'Waiting for EXP';return;
  }
  const s=current(p),pace=publicPace(p),m=pace?.estimates ?? (p.recent_windows?null:s.metrics),last=lastSeenReading(p);
  if(view==='overlay') { el('streamer').textContent=p.channel;el('character').textContent=p.character?.label ?? p.channel;el('character').title=el('character').textContent;el('streamer').title=sourceText(p);el('card').dataset.stale=String((s.stale||failed) && faded(s.age));el('card').dataset.recovered=String(['grammar_recovered','conditional_symbol'].includes(r?.evidence)); }
  else {
    el('player-name').textContent=p.character?.label ?? p.channel;el('player-source').textContent=p.channel;
    // Video and demo sources have no channel page, so they link to Twitch itself.
    el('twitch-link').href=p.source_kind==='twitch'?`https://www.twitch.tv/${encodeURIComponent(p.channel)}`:'https://www.twitch.tv/';
    el('twitch-link').title=p.source_kind==='twitch'?`Watch ${p.channel} on Twitch`:'Open Twitch';
  }
  el('level').textContent=`Lv. ${levelText(p)}`;el('level').title=levelTitle(p);
  el('level').dataset.lastKnown=String(lastKnown(p));
  el('level').dataset.inferred=String(!!levelTransition(p) || !!LEVEL_SOURCES[displayLevel(p)?.status]);
  const shown=shownReading(r ?? (s.stale?last:null),p.display_level);
  const shownBp=shown?.bp ?? (shown?.percentage!=null?Math.round(Number(shown.percentage)*100):null);
  el('progress').value=shownBp!=null?shownBp/100:0;
  el('progress').hidden=shownBp==null;
  const absolute=displayedExp(shown,true);
  amount('exp',absolute==='—'?'—':absolute+' EXP',displayedExp(shown));el('exp').title=expTitle(shown);
  el('percentage').textContent=percentageText(shown);el('percentage').title=shown?.evidence==='manual_admin'?expTitle(shown):'';
  el('status').textContent=statusText(p);el('status').dataset.online=String(statusText(p)==='Online');
  // Skip "Updated …" when the status already says how long ago, e.g. "Not currently tracked · updated 13m ago".
  const lastAge=p.last_seen?.age_seconds==null?s.age:p.last_seen.age_seconds+(performance.now()-receivedAt)/1000;
  el('age').textContent=/\bago\b/.test(el('status').textContent)?'':shown && s.stale?`Updated ${ageText(lastAge)}`:r?`Updated ${ageText(s.age)}`:'';el('age').title=shown?.timestamp?localTime(shown.timestamp):'';
  if(view==='overlay' && inactiveView())el('age').textContent=r?`Updated ${ageText(s.age)}`:'No saved reading';
  const observed=observedWindow(p);
  let movement=observed?.difference_percentage_points ?? null;
  if(movement==null && !p.recent_windows && !p.tracked_status)
    movement=view==='overlay'?(p.segment?.readings>=2?p.segment.difference_percentage_points:null):selectedWindow(p)?.eligible?selectedWindow(p).difference_percentage_points:null;
  const summary=observed ?? (movement!=null?{difference_percentage_points:movement}:null);
  el('movement').textContent=(observed || !s.stale && !failed) && (summary?.estimated_exp || movement!=null)?movementText(summary):'—';
  amount('movement',el('movement').textContent==='—'?'—':summary?.estimated_exp?`+${expText(summary.estimated_exp.value.approximate,true)}`:el('movement').textContent,el('movement').textContent);
  if(view==='overlay')el('movement').textContent=el('movement').textContent.replace(/ EXP$/,'');
  el('movement').dataset.paused=String(!!observed && (observed.paused || s.stale || failed) && faded(s.age));
  el('movement').title=observed?`${el('movement').dataset.fullNumber}${summary?.estimated_exp?' EXP':''}${movement!=null?` (+${movement}% of level)`:''} gained between the first and last update in this time.`:windowNote(p);
  amount('rate',m?.exp_per_hour?`${expText(m.exp_per_hour.value.approximate,true)}`:'—',m?.exp_per_hour?`${expText(m.exp_per_hour.value.approximate)}`:'—');el('rate').title=(view==='overlay' && earlyText(p)?earlyText(p)+'. ':'')+rateTitle(m?.exp_per_hour);
  el('pp-rate').textContent=m?.percentage_per_hour?`${m.percentage_per_hour.value.approximate.toFixed(2)}`:'—';
  el('pp-rate').title='Estimated level % per hour.';
  const savedETA=publicETA(p),eta=p.recent_windows?savedETA?.estimate:m?.eta;
  amount('eta',etaText(eta),etaText(eta,true));el('eta').title=eta?`${etaText(eta)} to the next level at ${savedETA?`the ${savedETA.window_minutes} min pace${Date.parse(savedETA.estimated_at)?`, estimated ${localTime(savedETA.estimated_at)}`:''}`:'the recent pace'}. Not a live countdown.`:'Needs recent EXP gains';
  if(view==='overlay')el('eta').textContent=etaText(eta);
  if(view==='overlay') for(const id of ['exp','movement','rate','pp-rate','eta']) el(id).dataset.size=el(id).textContent.length>(id==='exp'?16:8)?'long':'normal';
  el('rate').dataset.paused=String(!!pace && !pace.active && faded(pace.age));
  if(pace)el('rate').title=`${pace.label} · ${rateTitle(m?.exp_per_hour ?? m?.percentage_per_hour)}`;
  if(view==='overlay') {
    if(el('eta').clientWidth>0 && el('eta').scrollWidth>el('eta').clientWidth+1)el('eta').textContent=etaText(eta,true);
    if(pace && !pace.active && !failed && !p.twitch && !levelTransition(p) && !p.percentage_state?.pending_since && !['capture_finished','capture_interrupted','historical_session','stopped','coordinator_stopped'].includes(p.activity?.state))el('status').textContent=`Last estimate ${ageText(pace.age)}`;
    el('rate-label').textContent=pace && !pace.active?'Last EXP / hour':'EXP / hour';
    for(const n of document.querySelectorAll('[data-rate-window]')) {
      const windowPace=publicPace(p,Number(n.dataset.rateWindow)),rate=windowPace?.estimates.exp_per_hour;
      n.textContent=rate?`${expText(rate.value.approximate)}`:'—';n.dataset.paused=String(!!windowPace && !windowPace.active && faded(windowPace.age));
    }
    if(document.body.dataset.layout==='card')drawHourChart(el('general-chart'),Number(document.body.dataset.interval),Number(document.body.dataset.range)*60);
    else if(document.body.dataset.layout==='chart')drawHourChart();
  }
  if(view==='player') {
    const rolling=rollingData?.character_id===p.character?.id?rollingData:null;
    amount('tracked-exp',rolling?.tracked_exp?`${expText(rolling.tracked_exp.approximate,true)}`:'—',rolling?.tracked_exp?`${expText(rolling.tracked_exp.approximate)}`:'—');
    el('tracked-exp').title=rolling?`${el('tracked-exp').dataset.fullNumber} EXP gained in the last 24 hours while tracked.`:'';
    const rollingAge=(performance.now()-rollingReceived)/1000;
    el('tracked-note').textContent=rollingFailed?(rolling?`Saved · updated ${ageText(rollingAge)}`:'History unavailable'):rolling?.status==='history_limit'?'History unavailable':rolling?(rolling.tracked_exp?`${spanText(rolling.coverage_seconds.approximate)} tracked`:'Not enough data'):'Loading history';
    const early=p.early_pace,text=earlyText(p);
    el('early-value').textContent=pace?pace.label:text ?? (early?.segment?'Paused':'Calculating…');
    el('rate-label').textContent=m?.exp_per_hour?'EXP / hour':'% / hour';
    if(!m?.exp_per_hour && m?.percentage_per_hour)amount('rate',`${m.percentage_per_hour.value.approximate.toFixed(2)}%`,`${m.percentage_per_hour.value.approximate.toFixed(2)}%`);
    el('movement-label').textContent=`${observed?.historical || s.stale && ['completed','interrupted'].includes(p.capture_lifecycle)?'Saved':'Last'} ${windowMinutes} min`;
    el('segment-note').textContent=windowNote(p);
    el('window-rate').textContent=selectedWindow(p)?.eligible && s.metrics?.exp_per_hour?`${expText(s.metrics.exp_per_hour.value.approximate)}`:observed?(s.stale || failed || observed.paused?'Paused':`Needs a full ${windowMinutes} min`):'Calculating…';
    if(selectedWindow(p)?.eligible && s.metrics?.exp_per_hour)amount('window-rate',`${expText(s.metrics.exp_per_hour.value.approximate,true)}`,el('window-rate').textContent);
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
    if(!row.connect_previous || !Number.isFinite(a) || !Number.isFinite(b) || b<=a || b-a>3600000 || a<previousEnd || (rolling?b<start || b-a>range*1000:a<start) || b>anchor || !Number.isFinite(amount) || amount<0 && g.policy!=='public_endpoint_window_v1')continue;
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
function chartBucketValue(bucket) { return (bucket.chart_value===undefined?bucket.value:bucket.chart_value)?.approximate ?? null; }
function drawExpHistory() {
  const svg=el('history-chart');svg.replaceChildren();
  delete svg.dataset.start;delete svg.dataset.end;
  const rolling=rollingData?.character_id===data?.player?.character?.id?rollingData:null;
  const intervals=currentLevelOnly?rolling?.current_level_chart_intervals ?? rolling?.chart_intervals:rolling?.chart_intervals;
  const history=intervals?intervals.map(g=>({gain:g,connect_previous:true,level:{value:g.level}})):data?.history ?? [],level=rolling?.current_level ?? displayLevel(data?.player ?? {})?.value;
  const rows=currentLevelOnly?history.filter(p=>p.level.value===level):history,anchor=Date.parse(rolling?.as_of ?? data?.player?.recent_windows?.[String(windowMinutes)]?.end ?? data?.player?.latest_attempt_at ?? history.at(-1)?.timestamp);
  const saved=!data?.player && data?.summary?.character_id===Number(viewCharacter ?? roster.find(r=>r.current)?.id)?data.summary:null;
  const savedEnd=Date.parse(saved?.as_of);
  const chart=bucketSeconds===1800 && saved?.day_buckets?.length===48 && Number.isFinite(savedEnd) && !currentLevelOnly?{
    start:savedEnd-86400000,end:savedEnd,seconds:1800,range:86400,
    bins:saved.day_buckets.map((value,i)=>({start:savedEnd-(48-i)*1800000,end:savedEnd-(47-i)*1800000,value,state:value==null?'missing':'saved'}))
  }:bucketSeconds===1800 && rolling?{
    start:Date.parse(rolling.start),end:Date.parse(rolling.end),seconds:1800,range:86400,
    bins:rolling.buckets.map(b=>({...b,start:Date.parse(b.start),end:Date.parse(b.end),value:chartBucketValue(b),state:chartBucketValue(b)==null?'missing':b.state,covered:b.covered.approximate}))
  }:bucketHistory(bucketSeconds===1800?[]:rows,bucketSeconds===1800?Date.parse(data?.served_at):anchor,bucketSeconds,bucketSeconds===1800?null:chartWindow*60);
  if(!chart || !Number.isFinite(chart.start) || !Number.isFinite(chart.end)){el('history-note').textContent='';return;}
  if(bucketSeconds===1800 && longChartWindow===720){chart.bins=chart.bins.slice(-24);chart.range=43200;chart.start=chart.end-43200000;}
  const width=Math.max(300,Math.min(960,svg.clientWidth||960)),plotWidth=width-76;
  // Starts at y=20: nothing is drawn above the bars' hover area (y=25), and 230 tall matches the CSS box, so it is not shrunk.
  svg.setAttribute('viewBox',`0 20 ${width} 230`);svg.setAttribute('aria-label','EXP gained over time; dashes mean no data');
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
      class:bin.state==='missing'?'exp-column missing':'exp-column'});
    inspect(shape('rect',{x:left,y:25,width:w,height:183,fill:'transparent',class:'bar-hit'}),`bar:${bin.start}:${bin.end}`,
      `${localTime(bin.start)}\n${bin.value==null?'No data (not zero EXP)':`${expText(bin.value,true)} EXP`}`);
  }
  const ticks=width<600?3:5;
  for(let i=0;i<ticks;i++){
    const tick=new Date(chart.start+(chart.end-chart.start)*i/(ticks-1)).toISOString();
    const attrs={x:54+plotWidth*i/(ticks-1),'text-anchor':i===0?'start':i===ticks-1?'end':'middle'};
    shape('text',{...attrs,y:232}).textContent=clockMinutes.format(new Date(tick));
    if(chart.range>=43200)shape('text',{...attrs,y:248}).textContent=monthDay.format(new Date(tick));
  }
  const count=chart.bins.filter(b=>b.value!=null).length;
  el('history-note').textContent=`${chart.seconds/60} min per bar · last ${chart.range<3600?chart.range/60+' min':chart.range/3600+' hours'} · times in ${zoneLabel()}${count?'':' · no data in this period'}`;
  el('history-note').title='The 24h view always includes all levels.';
}
// Overlay history uses the same minute intervals and 24h buckets as the player chart.
function drawHourChart(svg=el('overlay-chart'),seconds=300,range=3600) {
  const tracked=data?.tracked_history;svg.replaceChildren();
  const chart=seconds===1800?(tracked?.buckets?.length===48?{bins:tracked.buckets.slice(range===43200?-24:0).map(b=>({value:chartBucketValue(b)}))}:null)
    :bucketHistory((tracked?.chart_intervals ?? []).map(g=>({gain:g,connect_previous:true})),Date.parse(tracked?.as_of),seconds,range);
  if(!chart){el('hour-total').textContent='—';return;}
  const shape=(tag,attrs)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);svg.append(n);return n;};
  const max=Math.max(1,...chart.bins.map(b=>b.value ?? 0));
  // The "Last hour" layout gets a y-axis and the peak's value; the General card's mini chart stays bare.
  // No time labels: the caption already says "last hour", and a "now" would crowd the Updated line below.
  // It is drawn at its real pixel size so the text is not stretched (OBS keeps the source a fixed size).
  const labelled=svg===el('overlay-chart'),width=labelled?svg.clientWidth || 462:462,height=labelled?svg.clientHeight || 90:76;
  const left=labelled?28:0,top=labelled?11:2,bottom=height-2,scale=10**Math.floor(Math.log10(max));
  const ceiling=labelled?Math.ceil(max/scale)*scale:max;  // A round top value such as 20K, like the profile chart.
  if(labelled)svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  const step=(width-left)/chart.bins.length,gap=Math.min(6,step/4),y=v=>bottom-Math.max(0,v)/ceiling*(bottom-top);
  if(labelled)for(const v of [ceiling,ceiling/2]){
    shape('line',{x1:left,x2:width,y1:y(v),y2:y(v),class:'grid'});
    shape('text',{x:left-5,y:y(v)+3,'text-anchor':'end',class:'axis'}).textContent=expText(v);
  }
  chart.bins.forEach((b,i)=>{
    const tall=b.value==null?2:Math.max(2,bottom-y(b.value));
    shape('rect',{x:left+i*step+gap/2,y:bottom-tall,width:step-gap,height:tall,rx:b.value==null?1:3,class:b.value==null?'none':'bar'});
  });
  if(labelled) {
    const peak=chart.bins.reduce((best,b,i)=>b.value!=null && b.value>(chart.bins[best]?.value ?? -Infinity)?i:best,-1);
    if(peak>=0 && chart.bins[peak].value>0)shape('text',{x:left+(peak+.5)*step,y:y(chart.bins[peak].value)-3,'text-anchor':'middle',class:'peak'}).textContent=expText(chart.bins[peak].value);
  }
  const seen=chart.bins.filter(b=>b.value!=null);
  el('hour-total').textContent=seen.length?`${expText(seen.reduce((sum,b)=>sum+b.value,0))} EXP`:'—';
}
function drawHistory() {
  const focus=document.activeElement?.dataset?.tipKey,openKey=tipKey,position=tipPosition;
  document.querySelectorAll('[data-chart]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.chart===chartMode)));
  document.querySelectorAll('[data-bucket]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.bucket)===bucketSeconds)));
  document.querySelectorAll('[data-chart-window]').forEach(b=>{const minutes=Number(b.dataset.chartWindow);b.disabled=(minutes>=720)!==(bucketSeconds===1800);b.setAttribute('aria-pressed',String(!b.disabled && minutes===(bucketSeconds===1800?longChartWindow:chartWindow)));});
  document.querySelectorAll('[data-line-window]').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.lineWindow)===lineWindow)));
  el('bucket-controls').hidden=chartMode!=='exp';el('line-controls').hidden=chartMode==='exp';
  if(chartMode==='exp')drawExpHistory();else drawPercentageHistory();
  const all=data?.history ?? [],anchor=Date.parse(data?.tracked_history?.as_of ?? data?.player?.recent_windows?.[String(windowMinutes)]?.end ?? data?.player?.latest_attempt_at ?? all.at(-1)?.timestamp);
  const event=(data?.player?.level_events ?? []).filter(e=>Date.parse(e.timestamp)>=anchor-(chartMode!=='exp'?lineWindow:bucketSeconds===1800?longChartWindow:chartWindow)*60000).at(-1);
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
  const first=anchor-lineWindow*60000,last=anchor;
  const windowPoints=all.filter(p=>p.time>=first && p.time<=last);
  const level=displayLevel(data?.player ?? {})?.value;
  const points=currentLevelOnly?windowPoints.filter(p=>!p.reading || p.level.value===level):windowPoints;
  // Unknown level points are retained as gaps, never assigned to the displayed level.
  const visible=p=>p.reading && p.reading.bp!=null && p.level.value!=null && (!currentLevelOnly || p.level.value===level);
  const values=points.filter(visible).map(p=>p.reading.bp/100),min=values.length?Math.min(...values):0,max=values.length?Math.max(...values):100;
  const padding=Math.max(.01,(max-min)*.1),low=Math.max(0,min-padding),high=Math.min(100,max+padding);
  function shape(tag,attrs,title) { const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(title)n.append(node('title','',title));svg.append(n);return n; }
  if(!points.length)shape('text',{x:60,y:100}).textContent='';
  const x=t=>60+(t-first)/Math.max(1,last-first)*plotWidth,y=v=>190-(v-low)/Math.max(.01,high-low)*165;
  for(let i=0;i<=4;i++) {
    const value=low+(high-low)*i/4;
    shape('line',{x1:60,x2:width-40,y1:y(value),y2:y(value),class:i?'chart-grid':'chart-axis'});
    shape('text',{x:52,y:y(value)+4,'text-anchor':'end'}).textContent=value.toFixed(2)+'%';
  }
  shape('line',{x1:60,x2:60,y1:20,y2:190,class:'chart-axis'});
  // Display only: each readable point joins the previous readable one; unreadable points stay hoverable off the line.
  points.filter(visible).forEach((p,i,readable)=>{
    const previous=readable[i-1];
    if(previous)shape('line',{x1:x(previous.time),y1:y(previous.reading.bp/100),x2:x(p.time),y2:y(p.reading.bp/100),class:'trend'});
  });
  points.forEach(p=>{
    if(visible(p))inspect(shape('circle',{cx:x(p.time),cy:y(p.reading.bp/100),r:4,class:'sample'}),
      `point:${p.event_id}`,`${localTime(p.timestamp)}\n${p.level.value!=null?'Lv. '+p.level.value+' · ':''}${p.reading.percentage}%\n${p.reading.exp!=null || p.reading.estimated_exp?displayedExp(p.reading,true)+' EXP':'EXP unavailable'}`);
    else inspect(shape('path',{d:`M${x(p.time)-3} 194l6 6m0-6-6 6`,class:'missing'}),`point:${p.event_id}`,`${localTime(p.timestamp)}\nCouldn't read EXP`);
  });
  let previousLevel=null;
  for(const p of windowPoints.filter(p=>p.reading && p.level.value!=null)) {
    if(previousLevel!=null && p.level.value!==previousLevel) {
      const event=(data.player.level_events ?? []).find(e=>e.level===p.level.value && Date.parse(e.first_observed_at)<=p.time);
      shape('line',{x1:x(p.time),x2:x(p.time),y1:20,y2:190,class:'level-transition'});
      shape('text',{x:Math.min(width-75,x(p.time)+4),y:16,class:'level-transition-label'}).textContent=
        !event?`Lv. ${p.level.value}`:event.inferred && event.status!=='corroborated'?`Lv. ${p.level.value}`:`Level ${p.level.value}!`;
    }
    previousLevel=p.level.value;
  }
  const ticks=width<600?3:5;
  for(let i=0;i<ticks;i++) {
    const time=first+(last-first)*i/(ticks-1);
    shape('text',{x:60+plotWidth*i/(ticks-1),y:218,'text-anchor':i===0?'start':i===ticks-1?'end':'middle'}).textContent=clockSeconds.format(new Date(time));
  }
  svg.dataset.start=new Date(first).toISOString();svg.dataset.end=new Date(last).toISOString();
  const readable=points.filter(visible).length,unavailable=points.length-readable;
  el('history-note').textContent=`${currentLevelOnly && level!=null?'Lv. '+level+' · ':''}Last ${lineWindow} min · times in ${zoneLabel()}${readable?'':' · no data in this period'}${unavailable?' · ✕ couldn\'t read EXP':''}`;
  el('history-note').title='';
}
// Rows change about once per capture (~40 s each), so the list refreshes every 4 s, and every 30 s while
// its tab is hidden (returning refreshes at once). Profiles and OBS overlays keep 2 s; their polls are small.
function pollDelay() { return view!=='board'?2000:document.hidden?30000:4000; }
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
    if(warming){
      data=body.summary?body:null;rollingData=null;rollingRevision=null;failed=false;
      if(Array.isArray(body.roster))roster=body.roster;
      fadeSwitch(render);return;
    }
    if(response.status===404 && body.error==='unknown_character'){
      if(view==='player'){selectCharacter(null,'replace');return;}
      data=null;throw new Error();
    }
    if(!response.ok)throw new Error();
    if(view==='overlay' && requestedView && String(body.player?.character?.id)!==requestedView)throw new Error();
    // An omitted section is the same revision this page holds; anything else arrives in full.
    if(held && body.history===undefined && body.history_revision===data.history_revision)body.history=data.history;
    if(held && body.tracked_history===undefined && body.tracked_revision===data.tracked_revision)body.tracked_history=data.tracked_history;
    data=body;receivedAt=requested;failed=false;
    const swap=view==='board' && shownMode!==requestedMode;shownMode=requestedMode;
    if(view==='player' && Array.isArray(data.roster))roster=data.roster;
    if(view==='player' && data.tracked_history){rollingData=data.tracked_history;rollingReceived=performance.now();rollingFailed=false;}
    if(selecting())deferredRender=true;else if(swap)crossFade(render);else fadeSwitch(render);
    if(view==='player' && Array.isArray(data.history))pollRolling();
  } catch { if(!unchanged())return;failed=true;if(view==='board')renderBoard();else renderPlayer(); }
  finally { clearTimeout(timeout);activeController=null;delete document.body.dataset.loading;pollTimer=setTimeout(poll,unchanged()?pollDelay():0); }
}

function rosterReading(r) {
  const p=data?.player,reading=String(p?.character?.id)===String(r.id)?p.reading ?? lastSeenReading(p):null;
  return reading ?? (r.last_exp_at?{timestamp:r.last_exp_at}:null);
}
function rosterStamp(r) {
  return rosterReading(r)?.timestamp ?? (r.last_exp_at===undefined?r.last_seen_at:r.last_exp_at);
}
function rosterSeenText(r) {
  const reading=rosterReading(r);
  const stamp=rosterStamp(r),now=data?.served_at?Date.parse(data.served_at)+(performance.now()-receivedAt):Date.now();
  const age=(now-Date.parse(stamp))/1000;
  if(!Number.isFinite(age))return 'Pending';
  if(r.current && reading && age>=0 && age<=300)return 'Current';
  return ageText(Math.max(0,age));
}
function rosterLink(r,viewing,className) {
  const link=node('a',className),seen=node('span','roster-seen',rosterSeenText(r));seen.dataset.character=String(r.id);seen.dataset.seen=r.last_seen_at ?? '';
  // The tracked character's link follows live tracking; others are stable, shareable views.
  link.href=r.current?location.pathname:`${location.pathname}?character=${r.id}`;link.dataset.character=r.id;
  if(String(r.id)===viewing)link.setAttribute('aria-current','page');
  const meta=node('span','roster-meta',`Lv. ${r.level ?? '—'} · `);meta.append(seen);
  link.append(node('span','roster-name',r.label),meta);
  const stamp=rosterStamp(r);
  link.title=`${r.label} · ${r.current?'currently tracked':stamp?'updated '+localTime(stamp):'pending'}`;
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
  const characters=new Map(roster.map(r=>[String(r.id),r]));
  document.querySelectorAll('#roster [data-seen]').forEach(n=>{const r=characters.get(n.dataset.character);if(r)n.textContent=rosterSeenText(r);});
}
function renderRoster() {
  renderOverlayCharacters();
  // Two or more saved characters; the server already excludes the unrecognized placeholder.
  el('roster').hidden=roster.length<2;
  const viewing=viewCharacter ?? String(roster.find(r=>r.current)?.id ?? '');
  const key=JSON.stringify([roster.map(r=>[r.id,r.label,r.level,r.current,r.current?null:r.last_seen_at,r.last_exp_at]),viewing]);
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
function renderOverlayCharacters() {
  const select=el('overlay-character'),key=JSON.stringify(roster.map(r=>[r.id,r.label,r.current]));
  if(select.dataset.roster===key)return;
  const selected=select.value,automatic=node('option','','Automatic (most recent character)');automatic.value='';
  const options=roster.map(r=>{const option=node('option','',r.label);option.value=String(r.id);return option;});
  if(selected && !roster.some(r=>String(r.id)===selected)){
    const missing=node('option','','Locked character unavailable');missing.value=selected;options.push(missing);
  }
  select.replaceChildren(automatic,...options);select.value=selected;select.dataset.roster=key;
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
  crossFade(()=>{renderPlayer();renderRoster();},true);hideTip();
  characterFade=true;  // The chosen character's first numbers fade in too.
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
    const response=await fetch(`${apiOrigin}/api/players/${encodeURIComponent(channel)}/history`,{cache:'no-store',signal:controller.signal});
    if(!response.ok)throw new Error('History unavailable');
    const result=await response.json();
    if(!Array.isArray(result.buckets) || result.buckets.length!==48)throw new Error('Invalid history');
    if(result.character_id!==data?.player?.character?.id)return;
    rollingData=result;rollingReceived=performance.now();rollingRevision=revision;rollingFailed=false;
  } catch { rollingFailed=true; }
  finally { clearTimeout(timeout);rollingController=null;if(selecting())deferredRender=true;else {renderPlayer();drawHistory();}rollingTimer=setTimeout(()=>pollRolling(true),30000); }
}
document.addEventListener?.('visibilitychange',()=>{if(!document.hidden)poll();});
globalThis.addEventListener?.('pageshow',poll);
if(view==='board')globalThis.addEventListener?.('resize',renderBoard);
if(view==='board') {
  document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>selectBoard(button.dataset.mode)));
  el('character-filter').addEventListener('input',renderBoard);
  document.querySelectorAll('[data-character-sort]').forEach(button=>button.addEventListener('click',()=>{
    if(!['name','level','recent'].includes(button.dataset.characterSort))return;
    characterSort=button.dataset.characterSort;renderBoard();
  }));
  globalThis.addEventListener?.('popstate',()=>selectBoard(boardParam(),'none'));
}
if(view==='board')el('presence').addEventListener('click',()=>{presence=PRESENCE[presence].next;renderBoard();});
if(view==='board') document.querySelectorAll('[data-sort]').forEach(button=>button.addEventListener('click',()=>{sort=button.dataset.sort;if(sorts.has(sort))renderBoard();}));
document.querySelectorAll('[data-window]').forEach(button=>button.addEventListener('click',()=>{
  const minutes=Number(button.dataset.window);if(![5,10,15,30,60].includes(minutes))return;windowMinutes=minutes;
  if(view==='board')renderBoard();else if(data?.player){renderPlayer();drawHistory();}
}));
if(view==='player') {
  const overlayTip=el('history-overlay-tip');
  let tipStrikes=0;
  overlayTip.addEventListener('click',()=>{
    if(overlayTip.disabled)return;
    overlayTip.dataset.strikes=String(++tipStrikes);
    if(tipStrikes<3) {
      overlayTip.setAttribute('aria-label',tipStrikes===1?'Bar chart transfers below. Cross out tip again.':'Bar chart transfers below. Dismiss tip.');
      return;
    }
    const focused=document.activeElement===overlayTip;
    overlayTip.disabled=true;
    const remove=()=>{
      if(focused && (document.activeElement===overlayTip || document.activeElement===document.body))document.querySelector('.overlay-board button')?.focus({preventScroll:true});
      overlayTip.remove();
    };
    if(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches || !overlayTip.animate){remove();return;}
    overlayTip.animate([
      {transform:'rotate(-12deg) scale(1)',opacity:1,filter:'blur(0px)'},
      {transform:'rotate(-8deg) scale(1.12)',opacity:.8,filter:'blur(1px)',offset:.3},
      {transform:'rotate(-17deg) scale(.55)',opacity:0,filter:'blur(5px)'},
    ],{duration:360,easing:'ease-out',fill:'forwards'}).finished.then(remove,remove);
  });
  el('current-level-only').addEventListener('change',e=>{currentLevelOnly=e.target.checked;if(data?.player){renderPlayer();drawHistory();}});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){tipDismissed=true;hideTip();}else if(e.key==='Tab')tipDismissed=false;});
  document.addEventListener('pointermove',e=>{if(!lastPointer || lastPointer.x!==e.clientX || lastPointer.y!==e.clientY)tipDismissed=false;lastPointer={x:e.clientX,y:e.clientY};});
  document.addEventListener('pointerdown',e=>{if(!e.target.closest?.('[data-tip-key]'))hideTip();});
  globalThis.addEventListener?.('scroll',hideTip,true);
  document.querySelectorAll('[data-chart]').forEach(b=>b.addEventListener('click',()=>{if(!['exp','percentage'].includes(b.dataset.chart))return;chartMode=b.dataset.chart;drawHistory();}));
  document.querySelectorAll('[data-bucket]').forEach(b=>b.addEventListener('click',()=>{if(![60,300,1800].includes(Number(b.dataset.bucket)))return;bucketSeconds=Number(b.dataset.bucket);drawHistory();updateBuilder();}));
  document.querySelectorAll('[data-chart-window]').forEach(b=>b.addEventListener('click',()=>{const minutes=Number(b.dataset.chartWindow);if(![15,30,60,720,1440].includes(minutes) || (minutes>=720)!==(bucketSeconds===1800))return;if(bucketSeconds===1800)longChartWindow=minutes;else chartWindow=minutes;drawHistory();updateBuilder();}));
  document.querySelectorAll('[data-line-window]').forEach(b=>b.addEventListener('click',()=>{if(![5,10,15,30,60].includes(Number(b.dataset.lineWindow)))return;lineWindow=Number(b.dataset.lineWindow);drawHistory();}));
  globalThis.addEventListener?.('resize',()=>{renderPlayer();drawHistory();rosterEdges();scalePreview();});
  const builder=overlayOptions(''),SIZES={card:[500,160],bar:[500,160],rates:[500,110],chart:[500,180]};
  const frame=el('overlay-preview');
  const overlayURL=()=>{
    const q=new URLSearchParams();
    for(const [key,allowed] of Object.entries(OVERLAY_CHOICES))if(builder[key]!==allowed[0])q.set(key,builder[key]);
    for(const key of OVERLAY_COLORS)if(builder[key])q.set(key,builder[key]);
    if(el('overlay-character').value)q.set('character',el('overlay-character').value);
    return `${location.origin}/live/overlay/${encodeURIComponent(channel)}${String(q)?'?'+q:''}`;
  };
  function scalePreview() {
    const scale=Math.min(1,((el('overlay-stage').clientWidth || 524)-26)/frame.width);
    frame.style.transform=`scale(${scale})`;el('overlay-stage').style.height=`${Math.ceil(frame.height*scale)+26}px`;
  }
  function updateBuilder() {
    builder.interval=String(bucketSeconds);builder.range=String(bucketSeconds===1800?longChartWindow:chartWindow);
    const url=overlayURL(),[width,height]=SIZES[builder.layout];
    el('overlay-url').value=url;el('overlay-link').href=url;el('overlay-size').textContent=`OBS size · ${width} × ${height}`;el('copy-status').textContent='';
    document.querySelectorAll('[data-option] button').forEach(b=>b.setAttribute('aria-pressed',String(builder[b.closest('[data-option]').dataset.option]===b.dataset.value)));
    document.querySelectorAll('[data-color]').forEach(input=>{input.value='#'+(builder[input.dataset.color] ?? THEME_COLORS[builder.theme][input.dataset.color]);});
    frame.width=width;frame.height=height;scalePreview();
    // The preview is this site's own overlay page, so options apply in place without reloading it.
    const character=el('overlay-character').value || '';
    if((frame.dataset.character ?? '')!==character){
      frame.dataset.character=character;frame.dataset.loaded='';frame.src=url;
    } else if(frame.dataset.loaded)frame.contentWindow?.applyOverlay?.(builder);else if(!frame.src)frame.src=url;
  }
  frame.addEventListener('load',()=>{frame.dataset.loaded='true';frame.contentWindow?.applyOverlay?.(builder);});
  el('overlay-character').addEventListener('change',updateBuilder);
  document.querySelectorAll('[data-option] button').forEach(b=>b.addEventListener('click',()=>{
    const key=b.closest('[data-option]').dataset.option;if(!OVERLAY_CHOICES[key]?.includes(b.dataset.value))return;builder[key]=b.dataset.value;updateBuilder();
  }));
  document.querySelectorAll('[data-color]').forEach(input=>input.addEventListener('input',()=>{builder[input.dataset.color]=input.value.slice(1).toLowerCase();updateBuilder();}));
  el('overlay-reset').addEventListener('click',()=>{for(const key of OVERLAY_COLORS)delete builder[key];updateBuilder();});
  updateBuilder();
  el('diagnostics').href=`/dashboard/${channel}`;el('history-link').href=`/dashboard/${channel}`;
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
  el('copy-overlay').addEventListener('click',async()=>{const [width,height]=SIZES[builder.layout];try {await navigator.clipboard.writeText(overlayURL());el('copy-status').textContent=`Copied · use a ${width} × ${height} Browser Source`;}catch{el('copy-status').textContent='Select the URL above and copy it';}});
}
function render() { if(view==='board')renderBoard();else {renderPlayer();if(view==='player'){renderRoster();drawHistory();}} }
// A Streamers/Characters switch lands all at once with a short cross-fade, never seen half rebuilt.
let fadeTransition=null;
function crossFade(update,slow=false) {
  if(!document.startViewTransition || !globalThis.matchMedia?.('(prefers-reduced-motion: no-preference)').matches){update();return;}
  const transition=fadeTransition=document.startViewTransition(update),root=document.documentElement;
  if(slow)root.dataset.fade='slow';else delete root.dataset.fade;
  // A newer transition skips this one; only the latest may clear the slower timing.
  transition.finished.finally(()=>{if(fadeTransition===transition)delete root.dataset.fade;});
}
// Unchanged panels look identical in both snapshots, so only the text and bars that change visibly fade.
// Stays armed through "preparing saved history" replies until the character's own numbers arrive.
function fadeSwitch(update) { if(!characterFade){update();return;}if(data?.player)characterFade=false;crossFade(update,true); }
const zoneSelect=view==='overlay'?null:el('timezone');
if(zoneSelect) {
  const local=new Intl.DateTimeFormat().resolvedOptions().timeZone,zones=Intl.supportedValuesOf?.('timeZone') ?? [];
  const option=(value,text)=>{const o=node('option','',text);o.value=value;return o;};
  zoneSelect.append(option('',`${local.replaceAll('_',' ')} (local)`),...(zones.includes('UTC')?zones:['UTC',...zones]).map(z=>option(z,z.replaceAll('_',' '))));
  zoneSelect.value=timeZone ?? '';
  zoneSelect.addEventListener('change',()=>{
    setTimeZone(zoneSelect.value);
    try {if(zoneSelect.value)localStorage.setItem('timezone',zoneSelect.value);else localStorage.removeItem('timezone');} catch {}
    if(data)render();
  });
}
if(view==='overlay')applyOverlay(overlayOptions(location.search));
poll();setInterval(()=>{
  if(selecting())return;
  if(deferredRender){deferredRender=false;if(data)render();}
  else if(view==='board')renderBoard();else renderPlayer();
  if(view==='player')rosterAges();
},1000);

// Decorative MapleStory mobs (sprites credited in README) wander along the first card: hover flinches, a click does something random.
const MOBS=['snail','blue-snail','red-snail','shroom','slime','orange-mushroom','ribbon-pig','stump','green-mushroom','lupin','pig'],BOSSES=['mano','mushmom'];
const pick=list=>list[Math.floor(Math.random()*list.length)],sprite=(slug,action)=>`/static/mobs/${slug}-${action}.${slug==='slime'?'webp':'gif'}`;  // The slime's soft edges need WebP alpha; as GIF they dither.
function spawnBoss() {
  // A rare faded boss floats slowly across the background behind the cards: a steady drift (translate) plus a gentle bob and sway (transform).
  const boss=node('img','boss'),ltr=Math.random()<.5,[from,to]=ltr?[-150,innerWidth+150]:[innerWidth+150,-150],y=innerHeight*(.08+Math.random()*.32);
  boss.src=sprite(pick(BOSSES),'stand');boss.alt='';document.body.prepend(boss);
  boss.animate([{translate:`${from}px ${y}px`},{translate:`${to}px ${y+(Math.random()-.5)*160}px`}],{duration:28000}).finished.then(()=>boss.remove());
  boss.animate([{transform:'translateY(-14px) rotate(-7deg)'},{transform:'translateY(14px) rotate(7deg)'}],{duration:3200,iterations:Infinity,direction:'alternate',easing:'ease-in-out'});
}
function spawnMob(lane) {
  const slug=pick(MOBS),mob=node('div','mob'),img=node('img');img.alt='';img.draggable=false;img.src=sprite(slug,'move');mob.append(img);
  img.decode().then(()=>{
    if(document.hidden || lane.querySelectorAll('.mob').length>=3)return;
    lane.append(mob);
    // Sprites face left, so walking right mirrors the mob. It walks until half its body hangs over the card's edge.
    const half=img.naturalWidth/2,width=lane.clientWidth,right=Math.random()<.5;
    const at=f=>`translateX(${right?half+f*(width-half):(width-half)*(1-f)}px) scaleX(${right?-1:1})`;
    const walk=mob.animate([{transform:at(0)},{transform:at(1)}],{duration:(width-half)/(25+Math.random()*15)*1000,fill:'forwards'});
    let gone=false;
    const end=(frames,duration)=>{gone=true;walk.pause();img.style.pointerEvents='none';img.animate(frames,{duration,easing:'ease-in',fill:'forwards'}).finished.then(()=>mob.remove());};
    const fall=()=>{img.src=sprite(slug,'hit');end([{transform:'none'},{transform:`translate(-${half+10}px,260px) rotate(-110deg)`,opacity:0}],900);};
    const die=()=>{
      img.src=sprite(slug,'die');
      end([{opacity:1},{opacity:1,offset:.6},{opacity:0}],1100);
    };
    const hop=()=>img.animate([{transform:'none'},{transform:'translateY(-28px)'},{transform:'none'}],{duration:450,easing:'ease-out'});
    const reactions=[()=>walk.updatePlaybackRate(3),hop,fall,die];
    walk.finished.then(()=>{if(!gone)fall();});
    img.addEventListener('pointerenter',()=>{
      if(gone || walk.playState!=='running')return;
      walk.pause();img.src=sprite(slug,'hit');
      setTimeout(()=>{if(!gone){img.src=sprite(slug,'move');walk.play();}},500);
    });
    img.addEventListener('click',()=>{
      if(gone)return;
      const hit=node('span','mob-hit',String(7+Math.floor(Math.random()*40)));
      hit.style.left=`${mob.getBoundingClientRect().left-lane.getBoundingClientRect().left}px`;hit.style.bottom=`${img.height+4}px`;lane.append(hit);setTimeout(()=>hit.remove(),1000);
      pick(reactions)();
    });
  },()=>{});  // A sprite that fails to load is simply skipped.
}
// Every 10–45 s, whether or not others are still walking: occasionally a boss (one at a time), otherwise a mob, at most 3 at once.
function wander(lane) {
  if(!document.hidden) {
    if(Math.random()<1/12 && !document.querySelector('.boss'))spawnBoss();
    else if(lane.querySelectorAll('.mob').length<3)spawnMob(lane);
  }
  setTimeout(()=>wander(lane),10000+Math.random()*35000);
}
// No matchMedia (the Node tests) or reduced motion: no mobs. Never on the OBS overlay.
if(view!=='overlay' && globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches===false) {
  const board=document.querySelector('.board'),lane=node('div','mob-lane');lane.setAttribute('aria-hidden','true');
  if(board){
    board.before(lane);setTimeout(()=>wander(lane),3000);
    let frozen=[];
    document.addEventListener('visibilitychange',()=>{
      if(document.hidden) {
        const animations=[...lane.getAnimations({subtree:true}),...(document.querySelector('.boss')?.getAnimations() ?? [])];
        frozen=animations.filter(a=>a.playState==='running' || a.playState==='paused').map(a=>[a,a.playbackRate]);
        // Zero speed also keeps a hover timeout's play() from restarting movement while hidden.
        frozen.forEach(([a])=>{a.playbackRate=0;});
      } else {
        frozen.forEach(([a,rate])=>{a.playbackRate=rate;});frozen=[];
      }
    });
  }
}
