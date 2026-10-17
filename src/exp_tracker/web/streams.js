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
    const title=node("h2"),link=node("a",`ttv/${row.channel}`); link.href=`/dashboard/${encodeURIComponent(row.channel)}`; title.append(link);
    const run=failed && row.run_status==='active' ? 'previously active · current activity unknown' :
      ({active:"active capture",unfinished:"unfinished · activity unknown",completed:"completed · capture stopped",interrupted:"interrupted",waiting:"waiting"})[row.run_status] ?? "unknown";
    const age=row.age_seconds==null?null:row.age_seconds+elapsed;
    const stale=row.stale || age==null || age>row.stale_after_seconds;
    const pctAge=row.percentage_age_seconds==null?null:row.percentage_age_seconds+elapsed;
    const label=kind=>({strict_full:"original strict full EXP",strict_percentage_only:"original percentage-only",grammar_recovered:"grammar-recovered proposal"})[kind] ?? "unknown evidence";
    card.append(title,node("p",row.character?.label ?? "Character not selected"),
      node("small",`Capture: ${row.source_status}${row.reasons?.length?" · "+row.reasons.join(", "):""} · Run: ${run}`),
      node("small",row.unfinished_run_count?`${row.unfinished_run_count} unfinished database run(s); only explicitly active runs establish worker activity`:"No unfinished database runs"),
      node("p",age==null?"No capture attempts yet":`${Math.floor(age)}s since latest attempt${stale?" · STALE":" · local age only"}`),
      node("p",row.percentage?`Last percentage: ${row.percentage.percentage}% · ${label(row.percentage.evidence)} · ${pctAge==null?"age unknown":Math.floor(pctAge)+"s old"}${row.percentage_stale || pctAge>row.stale_after_seconds?" · STALE":""}`:"Percentage unavailable in recent history"),
      node("p",row.full_exp?`Last full EXP: ${nf.format(BigInt(row.full_exp.exp))} [${row.full_exp.percentage}%] · ${label(row.full_exp.evidence)} · recorded ${row.full_exp.timestamp}`:"Full EXP unavailable in recent history"),
      node("small",`Latest level evidence: Tesseract ${row.visual_level ?? "unavailable"} / neural ${row.neural_level ?? "unavailable"}`),
      node("p",row.movement?.difference_bp!=null?`EXPERIMENTAL displayed movement: ${row.movement.difference_bp>0?"+":""}${row.movement.difference_percentage_points} pp${stale||failed?" · old/cached evidence":""}${row.movement.change==="negative"?" · break; no level-up inferred":""}`:
        `Progress unavailable: ${(row.progress_reason ?? "insufficient history").replaceAll("_"," ")}`),
      node("small","UNVERIFIED · explicit assignment does not authenticate the visible game character"));
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
