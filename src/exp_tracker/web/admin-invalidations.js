import {localCandidates,localTimestamp,timezone,when,offset} from './admin-time.js';

const $=id=>document.getElementById(id);
const option=(value,label)=>new Option(label,String(value));
function text(node,value,tag='p',className='') {
  const e=document.createElement(tag);e.textContent=value;e.className=className;node.append(e);return e;
}
function button(node,label,fn) {const e=text(node,label,'button');e.type='button';e.addEventListener('click',fn);return e;}
function values(node,row) {
  const original=row.original ?? {};
  const parts=[original.level==null ? null : `Level ${original.level}`,original.current_exp==null ? null : `${original.current_exp} EXP`,
    original.percentage==null ? null : `${original.percentage}%`].filter(v=>v!=null);
  text(node,parts.join(' · ') || 'No level or EXP could be read.');
}

export function invalidationUI({api,onSaved}) {
  let scope=null,channels=[],request=null,review=null,busy=false,generation=0,more=null,moreHistory=null;
  const zone=timezone();
  function status(message,error=false) {$('invalidation-status').textContent=message;$('invalidation-status').classList.toggle('warning',error);}
  function block(value) {
    busy=value;$('invalidate-form').inert=value;$('invalidated-list').inert=value;$('invalidation-history').inert=value;
    for(const id of ['confirm-invalidation','invalidation-previous','invalidation-next','review-invalidation-again']) $(id).disabled=value;
    if(!value && review) {
      $('invalidation-previous').disabled=review.page===0;$('invalidation-next').disabled=review.page+1>=review.pages;
    }
  }
  function cancel() {
    generation++;request=null;review=null;$('invalidation-review').hidden=true;
  }
  function clear() {cancel();scope=null;$('invalidated-list').replaceChildren();$('invalidation-history').replaceChildren();}
  function drawReview(value) {
    review=value;
    const restore=request.action!=='invalidate';const verb=restore ? 'Restore' : 'Invalidate';
    $('invalidation-summary').textContent=`${verb} ${value.count} reading${value.count===1?'':'s'} for ${value.character.label}. `+
      `${value.total} reading${value.total===1?'':'s'} reviewed.`+(value.total>value.count ? ' Readings already changed or changed separately will be left as they are.' : '');
    const selection=value.selection;
    $('invalidation-range').textContent=selection.start ?
      `From ${when(selection.start)} (${offset(selection.start)}, included) to ${when(selection.end)} (${offset(selection.end)}, not included). Timezone: ${zone}.` :
      selection.timestamp ? `${when(selection.timestamp)} (${offset(selection.timestamp)}). Timezone: ${zone}.` : `Restoring the still-excluded readings from this batch. Timezone: ${zone}.`;
    if(value.reason)text($('invalidation-range'),`Reason: ${value.reason}`);
    drawPage(value);
    $('confirm-invalidation').textContent=`${verb} ${value.count} reading${value.count===1?'':'s'}`;
    $('confirm-invalidation').hidden=false;$('review-invalidation-again').hidden=true;
    $('invalidation-audit').textContent=JSON.stringify(value,null,2);
    $('invalidation-review').hidden=false;$('invalidation-review').focus();
  }
  function drawPage(value) {
    $('invalidation-list').replaceChildren();
    for(const row of value.readings) {
      const card=document.createElement('article');card.dataset.validityIdentity=row.identity;text(card,when(row.timestamp),'h3');values(card,row);
      if(!row.selected)text(card,row.invalidated ? 'Already invalidated — left excluded.' : 'Already restored — left as it is.','p','muted');
      else if(row.invalidated)text(card,'Invalidated — will be restored.','p','muted');
      $('invalidation-list').append(card);
    }
    $('invalidation-pages').hidden=value.pages<=1;$('invalidation-page').textContent=`Page ${value.page+1} of ${value.pages}`;
  }
  async function start(data) {
    if(busy)return;
    const epoch=++generation;request=data;block(true);status('Reviewing readings…');
    try {const value=await api('/api/preview',data);if(epoch!==generation)return;drawReview(value);status('Review the readings, then confirm when you are ready.');}
    catch(e) {if(epoch===generation) {cancel();status(e.message,true);}}
    finally {block(false);}
  }
  async function page(next) {
    if(busy || !review)return;
    const epoch=generation;
    block(true);
    try {
      const value=await api('/api/invalidation-preview?'+new URLSearchParams({preview_id:review.preview_id,page:String(next)}));
      if(epoch!==generation)return;
      Object.assign(review,value);drawPage(review);
    } catch(e) {
      if(epoch!==generation)return;
      $('confirm-invalidation').hidden=true;$('review-invalidation-again').hidden=false;status(e.message,true);
    } finally {block(false);}
  }
  async function save() {
    if(busy || !review)return;
    const name=review.character.label;
    block(true);
    try {
      const value=await api('/api/save',{preview_id:review.preview_id});
      $('invalidation-saved-audit').textContent=JSON.stringify(value,null,2);$('invalidation-receipt').hidden=false;
      const action=value.action==='invalidate'?'Invalidated':'Restored';
      cancel();await onSaved();status(`${action} ${value.event.count} reading${value.event.count===1?'':'s'} for ${name}.`);
    } catch(e) {
      $('confirm-invalidation').hidden=true;$('review-invalidation-again').hidden=false;status(e.message,true);
    } finally {block(false);}
  }
  function single(row,owner,action='invalidate') {
    start({action,channel:owner.channel,character_id:String(owner.character.id),kind:row.kind,
      identity:String(row.identity),timestamp:row.timestamp});
  }
  function renderExcluded(data,append=false) {
    if(!append)$('invalidated-list').replaceChildren();
    for(const row of data.readings) {
      const card=document.createElement('article');card.dataset.invalidatedIdentity=row.identity;
      text(card,when(row.timestamp),'h3');values(card,row);text(card,'Invalidated — excluded from tracking.','p','muted');
      if(row.reason)text(card,row.reason);
      button(card,'Restore',()=>single(row,scope,'restore'));$('invalidated-list').append(card);
    }
    more=data.next_before;$('invalidated-more').hidden=!more;
    if(!$('invalidated-list').children.length)text($('invalidated-list'),'No invalidated readings.');
  }
  function renderHistory(data,append=false) {
    if(!append)$('invalidation-history').replaceChildren();
    for(const event of data.batches) {
      const card=document.createElement('article');card.dataset.invalidationBatch=event.id;
      text(card,`${event.action==='invalidate'?'Invalidated':'Restored'} ${event.count} reading${event.count===1?'':'s'}`,'h3');
      text(card,when(event.committed_at),'p','muted');if(event.reason)text(card,event.reason);
      if(event.action==='invalidate' && event.remaining)button(card,`Restore batch (${event.remaining})`,()=>start({action:'restore_batch',channel:scope.channel,character_id:String(scope.character.id),batch_id:String(event.id)}));
      else if(event.action==='invalidate')text(card,'No readings remain excluded by this batch.','p','muted');
      const advanced=document.createElement('details');text(advanced,'Advanced details','summary');text(advanced,JSON.stringify(event,null,2),'pre');card.append(advanced);
      $('invalidation-history').append(card);
    }
    moreHistory=data.next_before;$('invalidation-history-more').hidden=!moreHistory;
    if(!$('invalidation-history').children.length)text($('invalidation-history'),'No invalidation history.');
  }
  async function loadMore(history=false) {
    if(!scope || busy)return;block(true);
    const epoch=generation;
    try {
      const path=history?'/api/invalidation-history?':'/api/invalidated?';
      const data=await api(path+new URLSearchParams({channel:scope.channel,character_id:String(scope.character.id),before:String(history?moreHistory:more)}));
      if(epoch!==generation)return;
      if(history)renderHistory(data,true);else renderExcluded(data,true);
    } catch(e) {status(e.message,true);}finally {block(false);}
  }
  async function batchChannel() {
    if(busy)return;block(true);
    try {
      const data=await api('/api/inspect?'+new URLSearchParams({channel:$('invalidate-channel').value}));
      $('invalidate-character').replaceChildren(...data.characters.map(c=>option(c.id,c.label)));
      if(data.character)$('invalidate-character').value=String(data.character.id);
    } catch(e) {$('invalidate-character').replaceChildren();status(e.message,true);}finally {block(false);}
  }
  function fold(prefix) {
    const date=$(`${prefix}-date`).value,time=$(`${prefix}-time`).value,select=$(`${prefix}-choice`);
    $(`${prefix}-fold`).hidden=true;select.required=false;select.value='';
    if(!date || !time)return;
    try {
      const choices=localCandidates(date,time);
      if(choices.length>1) {
        select.replaceChildren(option('','Choose a time…'),...choices.map(s=>option(s,`${when(s)} (${offset(s)})`)));
        $(`${prefix}-fold`).hidden=false;select.required=true;
      }
    } catch { /* Native required fields and localTimestamp check incomplete input on review. */ }
  }
  $('invalidate-form').addEventListener('submit',e=>{
    e.preventDefault();
    try {
      if(timezone()!==zone)throw Error('Your timezone changed. Reload before choosing local times.');
      const stamp=prefix=>localTimestamp($(`${prefix}-date`).value,$(`${prefix}-time`).value,$(`${prefix}-choice`).value);
      const data={action:'invalidate',channel:$('invalidate-channel').value,character_id:$('invalidate-character').value,
        start:stamp('invalidate-start'),end:stamp('invalidate-end')};
      if($('invalidate-reason').value)data.reason=$('invalidate-reason').value;
      start(data);
    } catch(error){status(error.message,true);}
  });
  for(const prefix of ['invalidate-start','invalidate-end'])for(const suffix of ['date','time'])$(`${prefix}-${suffix}`).addEventListener('input',()=>fold(prefix));
  $('invalidate-timezone').textContent=`Your local timezone: ${zone}. Start is included; end is not included.`;
  $('invalidate-channel').addEventListener('change',batchChannel);
  $('invalidation-previous').addEventListener('click',()=>page(review.page-1));$('invalidation-next').addEventListener('click',()=>page(review.page+1));
  $('confirm-invalidation').addEventListener('click',save);$('cancel-invalidation').addEventListener('click',()=>{cancel();status('Nothing changed.');});
  $('review-invalidation-again').addEventListener('click',()=>start(request));
  $('invalidated-more').addEventListener('click',()=>loadMore());$('invalidation-history-more').addEventListener('click',()=>loadMore(true));
  $('invalidate-form').addEventListener('input',()=>{if(review)cancel();});
  return {single,cancel,clear,update(data,availableChannels) {
    const changed=!scope || scope.channel!==data.channel || scope.character?.id!==data.character?.id;
    if(changed)cancel();scope=data;channels=availableChannels;
    if(changed) {
      $('invalidate-form').reset();$('invalidate-channel').replaceChildren(...channels.map(c=>option(c.login,c.login)));
      $('invalidate-channel').value=data.channel;
      $('invalidate-character').replaceChildren(...data.characters.map(c=>option(c.id,c.label)));
      if(data.character)$('invalidate-character').value=String(data.character.id);
      for(const prefix of ['invalidate-start','invalidate-end'])fold(prefix);
    }
    renderExcluded(data.invalidated ?? {readings:[],next_before:null});renderHistory(data.invalidation_history ?? {batches:[],next_before:null});
  }};
}
