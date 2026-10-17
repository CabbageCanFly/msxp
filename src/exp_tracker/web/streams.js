"use strict";
let directory = null, receivedAt = 0, failed = false;
const nf = new Intl.NumberFormat("en-US");
function node(tag, text) { const el=document.createElement(tag); if(text!=null) el.textContent=text; return el; }
function renderDirectory() {
  const elapsed=(performance.now()-receivedAt)/1000;
  document.getElementById("directory-notice").textContent=failed?"Viewer disconnected · cached UNVERIFIED data; capture activity unknown":directory?.truncated?"First 25 configured channels shown":"Local diagnostic data · no online status or numerical trust implied";
  const rows=directory?.streams ?? [];
  document.getElementById("directory-empty").hidden=rows.length>0 || !directory;
  document.getElementById("streams").replaceChildren(...rows.map(row=>{
    const card=node("section"); card.className="panel stream-card"; card.dataset.channel=row.channel;
    const title=node("h2"),link=node("a",`${row.source_kind==='file'?'Video · ':row.source_kind==='twitch'?'ttv/':''}${row.channel}`); link.href=`/dashboard/${encodeURIComponent(row.channel)}`; title.append(link);
    const run=failed && row.run_status==='active' ? 'previously active · current activity unknown' :
      ({active:"active capture",unfinished:"unfinished · activity unknown",completed:"completed · capture stopped",interrupted:"interrupted",waiting:"waiting"})[row.run_status] ?? "unknown";
    const age=row.age_seconds==null?null:row.age_seconds+elapsed;
    const stale=row.stale || age==null || age>row.stale_after_seconds;
    const pctAge=row.percentage_age_seconds==null?null:row.percentage_age_seconds+elapsed;
    const label=kind=>({strict_full:"original strict full EXP",strict_percentage_only:"original percentage-only",grammar_recovered:"grammar-recovered proposal"})[kind] ?? "unknown evidence";
    const state=row.operation?.state;
    let activity=({running:'Running',waiting:'Waiting for next capture',capture_delayed:'Capture delayed',capture_failing:'Capture failing',stopped:'Coordinator stopped',coordinator_stopped:'Coordinator stopped',previous_unfinished_run:'Previous unfinished run · activity unknown'})[state] ?? run;
    const virtualNow=Date.parse(directory?.served_at)+elapsed*1000;
    if(state==='waiting' && virtualNow>Date.parse(row.operation.next_due_at)+2000) activity='Capture delayed';
    if(state==='running' && virtualNow>Date.parse(row.operation.updated_at)+row.operation.expected_completion_seconds*1000) activity='Capture delayed';
    if(failed) activity='Capture activity unknown · cached readings';
    const percentage=node('p',row.percentage?`${row.percentage.percentage}%`:'Percentage unavailable in recent history');
    if(row.percentage) {
      percentage.className='stream-value';
      percentage.append(node('small',`${label(row.percentage.evidence)}${row.percentage_stale || pctAge>row.stale_after_seconds?' · STALE':''}`));
    }
    card.append(title,node("p",row.character?.label ?? "Character not selected"),
      node("p",activity),node('small',`Run: ${run}`),
      node("p",`Level evidence: ${row.visual_level ?? '—'}${row.neural_level!=null?` · neural ${row.neural_level}`:''}`),
      node("p",age==null?"No capture attempts yet":`${Math.floor(age)}s since latest attempt${stale?" · STALE":" · local age only"}`),
      percentage,
      node("p",row.full_exp?`${nf.format(BigInt(row.full_exp.exp))} EXP · ${label(row.full_exp.evidence)}`:"Full EXP unavailable in recent history"),
      node("p",row.movement?.difference_bp!=null?`EXPERIMENTAL displayed movement: ${row.movement.difference_bp>0?"+":""}${row.movement.difference_percentage_points} pp${stale||failed?" · old/cached evidence":""}${row.movement.change==="negative"?" · break; no level-up inferred":""}`:
        `Progress unavailable: ${(row.progress_reason ?? "insufficient history").replaceAll("_"," ")}`),
      node("small",`Last attempt: ${row.last_attempt_at ?? 'not available'}`));
    const details=node('details');details.append(node('summary','Capture details'),
      node('small',`${row.source_status} · ${row.reasons?.join(', ') || 'No additional failure codes'}`),
      node('small',`${row.unfinished_run_count ?? 0} unfinished run(s); explicit assignment does not authenticate on-screen identity.`),
      node('small',`Full EXP source time: ${row.full_exp?.timestamp ?? 'unavailable'}`));
    card.append(details);
    return card;
  }));
}
async function pollDirectory() {
  let timer;
  try {
    if(document.hidden) return;
    const controller=new AbortController();timer=setTimeout(()=>controller.abort(),5000);
    const response=await fetch("/dev/api/streams",{cache:"no-store",signal:controller.signal});
    if(!response.ok) throw new Error("Directory unavailable");
    directory=await response.json();receivedAt=performance.now();failed=false;
    renderDirectory();
  } catch { failed=true;renderDirectory(); }
  finally { clearTimeout(timer);setTimeout(pollDirectory,document.hidden?10000:2000); }
}
pollDirectory();setInterval(renderDirectory,1000);
