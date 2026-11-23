// One selectable previous-username popup, shared by profiles and search results.
(() => {
  const tip=document.createElement('div');
  tip.id='username-history';tip.className='username-history';tip.hidden=true;
  tip.setAttribute('role','region');tip.setAttribute('aria-label','Previous Twitch username');
  const label=document.createElement('div');label.textContent='Previous Twitch username';
  const name=document.createElement('strong');
  tip.append(label,name);document.body.append(tip);
  const filter=document.getElementById('character-filter');
  const search=()=>filter?.value.trim().toLowerCase() || '';
  let active=null,pinned=false,timer=null,autoQuery=null,searchKey=null,queued=false;
  function hide(){clearTimeout(timer);tip.hidden=true;active?.setAttribute('aria-expanded','false');active=null;pinned=false;autoQuery=null;}
  function show(button){
    clearTimeout(timer);
    if(active!==button){active?.setAttribute('aria-expanded','false');pinned=false;}
    const previous=JSON.parse(button.dataset.previousUsernames || '[]');
    if(!previous.length){hide();return;}
    const query=search(),alias=previous.find(n=>query && n.toLowerCase().includes(query)) || previous[0];
    name.replaceChildren();
    let cursor=0,index;
    while(query && (index=alias.toLowerCase().indexOf(query,cursor))!==-1){
      const mark=document.createElement('mark');mark.textContent=alias.slice(index,index+query.length);
      name.append(document.createTextNode(alias.slice(cursor,index)),mark);cursor=index+query.length;
    }
    name.append(document.createTextNode(alias.slice(cursor)));
    autoQuery=button.matches('.alias-query-match')?query:null;
    active=button;tip.hidden=false;button.setAttribute('aria-expanded','true');
    const r=button.getBoundingClientRect();
    if(r.bottom<0 || r.top>innerHeight){hide();return;}
    const row=button.closest('.entry')?.getBoundingClientRect(),width=document.documentElement.clientWidth;
    if(row && matchMedia('(min-width:651px)').matches && r.right+10+tip.offsetWidth<width-8){
      tip.style.left=(r.right+10)+'px';
      tip.style.top=Math.max(8,Math.min(innerHeight-tip.offsetHeight-8,(row.top+row.bottom-tip.offsetHeight)/2))+'px';
    }else{
      tip.style.left=Math.max(8,Math.min(width-tip.offsetWidth-8,r.right-tip.offsetWidth))+'px';
      tip.style.top=(r.bottom+6+tip.offsetHeight<=innerHeight?r.bottom+6:Math.max(8,r.top-tip.offsetHeight-6))+'px';
    }
  }
  function later(){clearTimeout(timer);timer=setTimeout(()=>{
    if(pinned || autoQuery && autoQuery===search() || tip.matches(':hover') || active?.matches(':hover,:focus-visible') || !getSelection().isCollapsed)return;
    hide();
  },450);}
  const trigger='.rename-history,.history-target';
  document.addEventListener('pointerover',e=>{const b=e.target.closest(trigger);if(b)show(b);});
  document.addEventListener('pointerout',e=>{if(e.target.closest(trigger))later();});
  document.addEventListener('focusin',e=>{if(e.target.matches(trigger))show(e.target);});
  document.addEventListener('focusout',e=>{if(e.target.matches(trigger))later();});
  document.addEventListener('click',e=>{
    const b=e.target.closest(trigger);
    if(b?.tagName==='A')return;
    if(b){e.preventDefault();if(active===b && pinned)hide();else {show(b);pinned=true;}return;}
    if(!tip.contains(e.target))hide();
  });
  tip.addEventListener('pointerenter',()=>clearTimeout(timer));
  tip.addEventListener('pointerleave',later);
  document.addEventListener('selectionchange',()=>{if(!tip.hidden && getSelection().isCollapsed)later();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')hide();});
  function scheduleSearch(){
    if(queued)return;queued=true;
    requestAnimationFrame(()=>{
      queued=false;
      const query=search(),first=document.querySelector('.alias-query-match');
      const key=query+'|'+(first?.dataset.currentUsername || '');
      if(key===searchKey)return;searchKey=key;
      if(query && first)show(first);else hide();
    });
  }
  filter?.addEventListener('input',()=>{hide();searchKey=null;scheduleSearch();});
  const entries=document.getElementById('entries');
  if(entries)new MutationObserver(scheduleSearch).observe(entries,{childList:true,subtree:true,characterData:true});
  scheduleSearch();
  window.addEventListener('resize',hide);
  window.addEventListener('scroll',()=>{if(active && getSelection().isCollapsed)show(active);},true);
  globalThis.UsernameHistory={decorate(source,player,query=''){
    if(source.tagName==='SPAN'){
      const button=document.createElement('button');button.className='channel';button.type='button';
      button.textContent=source.textContent;source=button;
    }
    source.classList.add('history-target');source.setAttribute('aria-describedby','username-history');
    source.dataset.previousUsernames=JSON.stringify(player.previous_usernames);
    source.dataset.currentUsername=player.channel;
    query=query.trim().toLowerCase();
    if(query && !player.channel.toLowerCase().includes(query) && player.previous_usernames.some(n=>n.toLowerCase().includes(query)))source.classList.add('alias-query-match');
    return source;
  }};
})();
