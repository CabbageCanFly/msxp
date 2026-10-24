// Desired streamer settings use the same protected preview/save API as corrections.
export function streamerUI({api, onSaved=()=>{}}) {
  const $=id=>document.getElementById(id), form=$('streamer-form');
  let rows=[], preview=null, busy=false, loading=false, version=0;
  const flags=['authorized','tracking_enabled','public_visible','automatic_characters','experimental_neural_level','save_crops'];
  const numeric=['interval','timeout','max_age','ocr_timeout'];
  function message(text,error=false){$('streamer-status').textContent=text;$('streamer-status').classList.toggle('warning',error);}
  function cancel(){version++;preview=null;$('streamer-review').hidden=true;}
  function edit(row=null){
    cancel();form.reset();form.hidden=false;form.dataset.action=row?'roster_update':'roster_add';
    $('streamer-login').readOnly=!!row;$('streamer-login').value=row?.channel??'';
    for(const key of flags)$('streamer-'+key).checked=row?.[key]??['authorized','public_visible','automatic_characters','experimental_neural_level'].includes(key);
    $('streamer-authorization').hidden=!row;
    for(const key of numeric)$('streamer-'+key).value=row?.[key]??({interval:20,timeout:20,max_age:15,ocr_timeout:10}[key]);
    $('streamer-quality').value=row?.quality??'best';
    $('streamer-form-title').textContent=row?`Configure ${row.channel}`:'Add Twitch streamer';
    $('streamer-login').focus();
  }
  async function refresh(){
    if(loading)return;loading=true;
    try{
      const data=await api('/api/streamers');rows=data.streamers;
      $('streamer-add').disabled=!data.managed;
      if(!data.managed){message(data.notice,true);return;}
      const list=$('streamer-list');list.replaceChildren();
      for(const row of rows){
        const article=document.createElement('article'), heading=document.createElement('h3'), info=document.createElement('p'), button=document.createElement('button');
        heading.textContent=`${row.channel} · ${row.character?.label??'Pending character'}`;
        const runtime=row.runtime;
        const stale=runtime && Date.now()-Date.parse(runtime.heartbeat_at)>120000;
        info.textContent=`${row.tracking_enabled?'Tracking requested':'Paused'} · ${row.public_visible?'Public':'Hidden'} · ${row.automatic_characters?'Automatic names':'Manual identity'} · ${stale?'Coordinator status is old':runtime?.state??'Waiting for coordinator'}`+
          ((runtime?.last_attempt_at??row.last_capture_at)?` · Last attempt ${new Date(runtime?.last_attempt_at??row.last_capture_at).toLocaleString()}`:'')+
          (row.validated_level!=null?` · Validated level ${row.validated_level}`:'')+
          (row.identity?` · Identity ${row.identity.risk?'conflict: '+row.identity.risk:row.identity.verified?'verified':'pending verification'}`:'');
        button.type='button';button.textContent='Configure';button.addEventListener('click',()=>edit(row));
        article.append(heading,info);
        if(runtime?.error){const error=document.createElement('p');error.className='warning';error.textContent=runtime.error;article.append(error);}
        article.append(button);list.append(article);
      }
      if(!rows.length)list.textContent='No managed streamers yet.';
    }catch(error){message(error.message,true);}finally{loading=false;}
  }
  form.addEventListener('input',cancel);
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;busy=true;cancel();
    const requestVersion=version;
    try{
      const data={action:form.dataset.action,channel:$('streamer-login').value.trim(),quality:$('streamer-quality').value,
        reason:$('streamer-reason').value};
      for(const key of flags)data[key]=$('streamer-'+key).checked;
      for(const key of numeric)data[key]=Number($('streamer-'+key).value);
      const result=await api('/api/preview',data);
      if(requestVersion!==version)return;
      preview=result.preview_id;
      $('streamer-review-json').textContent=JSON.stringify({before:result.before,after:result.after},null,2);
      $('streamer-review').hidden=false;$('streamer-review').focus();message(result.notice);
    }catch(error){message(error.message,true);}finally{busy=false;}
  });
  $('streamer-confirm').addEventListener('click',async()=>{
    if(busy||!preview)return;busy=true;
    try{
      await api('/api/save',{preview_id:preview});cancel();form.hidden=true;
      message('Saved. The running coordinator will apply the settings after any in-flight capture finishes.');
      await refresh();await onSaved();
    }catch(error){cancel();message(error.message,true);}finally{busy=false;}
  });
  $('streamer-add').addEventListener('click',()=>edit());
  $('streamer-cancel').addEventListener('click',()=>{cancel();form.hidden=true;});
  $('streamer-review-cancel').addEventListener('click',cancel);
  $('streamer-refresh').addEventListener('click',refresh);
  refresh();
  const timer=setInterval(()=>{if(!document.hidden)refresh();},5000);
  return {refresh,close:()=>clearInterval(timer)};
}
