/* Émoi Studio: genuine home + desktop visual structure without changing relay/OB data. */
(() => {
  'use strict';
  const root = document.documentElement;
  const body = document.body;
  const home = document.getElementById('emoiHome');
  const viewStorage = 'emoi-studio-view-v1';
  if (!home) return;
  let current = 'chat';
  const isMobile = () => window.matchMedia('(max-width: 1023px)').matches;
  const allowed = new Set(['home','chat']);
  const safeRead = () => {
    try { return localStorage.getItem(viewStorage); } catch { return null; }
  };
  const saveView = value => {
    try { localStorage.setItem(viewStorage,value); } catch {}
  };
  function updateNav() {
    document.querySelectorAll('[data-emoi-view]').forEach(btn=>{
      btn.setAttribute('aria-current',current===btn.dataset.emoiView?'page':'false');
    });
    const room = document.querySelector('#modelTag')?.textContent || 'GPT';
    document.querySelectorAll('.emoi-studio .emoi-thread[data-room]').forEach(btn=>{
      const id=btn.dataset.room;
      btn.setAttribute('aria-current',id==='group'?String(room.includes('+')):id==='claude'?String(room.toLowerCase().includes('claude')&&!room.includes('+')):String(!room.toLowerCase().includes('claude')&&!room.includes('+')));
    });
  }
  function setView(view, options={}) {
    if (!allowed.has(view)) return;
    current=view;
    body.dataset.emoiView=view;
    home.hidden=view!=='home';
    if (options.persist!==false) saveView(view);
    updateNav();
    if (view==='home') {
      window.EmoiWallpapers?.activate('page:home');
    } else {
      const key=document.querySelector('.emoi-studio .emoi-thread[aria-current="true"]')?.dataset.room || 'gpt';
      window.EmoiWallpapers?.activate('chat:'+key);
    }
  }
  function goChat(id='gpt') {
    setView('chat');
    window.EmoiApp?.openChat(id);
    document.querySelectorAll('.emoi-studio .emoi-thread').forEach(btn=>
      btn.setAttribute('aria-current',String(btn.dataset.room===id)));
  }
  function init() {
    const defaultView=safeRead();
    const initial=isMobile()?(allowed.has(defaultView)?defaultView:'home'):'chat';
    const date=new Date();
    const dateLabel=document.getElementById('emoiTodayLabel');
    if(dateLabel) dateLabel.textContent='TODAY / '+date.toLocaleDateString('zh-CN',{month:'long',day:'numeric'});
    setView(initial,{persist:false});
    document.querySelectorAll('[data-emoi-view]').forEach(btn=>{
      btn.addEventListener('click',()=>setView(btn.dataset.emoiView));
    });
    document.querySelectorAll('[data-emoi-chat]').forEach(btn=>{
      btn.addEventListener('click',()=>goChat(btn.dataset.emoiChat));
    });
    document.getElementById('homeWallpaperButton')?.addEventListener('click',()=>{
      window.EmoiWallpapers?.activate('page:home');
      window.EmoiWallpapers?.open();
    });
    document.addEventListener('click',event=>{
      const room=event.target.closest('[data-room]');
      if(room) {
        if(isMobile()) setView('chat');
        const id=room.dataset.room;
        if(id) document.querySelectorAll('.emoi-studio .emoi-thread').forEach(btn=>
          btn.setAttribute('aria-current',String(btn.dataset.room===id)));
      }
    },true);
    // The wallpaper module restores the last chat background on workspace close.
    // Reapply home's wallpaper when a modal was launched from the home screen.
    document.getElementById('workspaceDialog')?.addEventListener('close',()=>{
      if(current==='home') window.EmoiWallpapers?.activate('page:home');
    });
    window.addEventListener('resize',()=>{if(!isMobile() && current==='home') updateNav()});
  }
  window.EmoiStudio={goHome:()=>setView('home'),goChat};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init);
  else init();
})();
