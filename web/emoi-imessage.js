/* Émoi Messages: independent iMessage-inspired UI. No Uranus code reused.
   Real local conversation records are scoped by immutable contact/conversation ID.
   Model responses and receipts are NEVER fabricated.
*/
(()=>{
'use strict';
const KEY='emoi-ui-conversation-drafts-v1';
const $=(s,r=document)=>r.querySelector(s);
const icons={
 back:'<path d="m15 18-6-6 6-6"/>',
 arrow:'<path d="m5 12 7-7 7 7m-7-7v14"/>',
 info:'<circle cx="12" cy="12" r="10"/><path d="M12 11v6m0-9v.5"/>',
 photo:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m4 17 5-5 4 4 3-3 4 4"/>',
 people:'<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6m-2-5c4 0 7 2 8 5"/>'
};
const icon=name=>'<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round">'+(icons[name]||icons.info)+'</svg>';
function read(){
 try{const v=JSON.parse(localStorage.getItem(KEY)||'{}');return v&&typeof v==='object'&&!Array.isArray(v)?v:{}}catch{return{}}
}
function save(data){
 try{localStorage.setItem(KEY,JSON.stringify(data));return true}catch{return false}
}
const local=read();
const formatDate=iso=>new Date(iso).toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'});
const deliveryLabels={
 local_only:'仅保存在本机 · 尚未发送给 AI',
 stored_not_delivered:'已存入会话 · 未绑定回复模型',
 replying:'等待 AI 回复…', partial:'部分成员未能回复',
 model_failed:'模型回复失败 · 请检查联系人绑定和模型连接',
 interrupted:'回复因服务重启中断'
};
function messageBubble(msg,members,showName){
 const row=document.createElement('article');row.className='ep-im-row ep-im-'+(msg.author==='human'?'mine':'theirs');
 if(msg.author==='contact'&&showName){
  const name=document.createElement('small');name.className='ep-im-sender';name.textContent=members.get(msg.contact_id)||'原群成员';row.append(name);
 }
 const bubble=document.createElement('div');bubble.className='ep-im-bubble';bubble.textContent=msg.text||'';
 row.append(bubble);
 if(msg.author==='human'&&deliveryLabels[msg.delivery]){
  const status=document.createElement('small');status.className='ep-im-delivery';status.textContent=deliveryLabels[msg.delivery];row.append(status);
 }
 return row;
}
function open(root,{kind='contact',item,conversationId,goBack,members=[],manage}){
 const ident=item.id;
 const key=kind+':'+ident;
 const endpoint=conversationId?'/emoi/v2/conversations/'+encodeURIComponent(conversationId)+'/messages':'';
 const names=new Map(members.map(member=>[member.id,member.name]));
 root.className='ep-view ep-im-screen';
 const header=document.createElement('header');header.className='ep-im-header';
 const back=document.createElement('button');back.type='button';back.className='ep-im-back';back.setAttribute('aria-label','返回信息');back.innerHTML=icon('back');back.onclick=goBack;
 const person=document.createElement('div');person.className='ep-im-peer';
 const avatar=document.createElement('span');avatar.className='ep-im-avatar';
 if(kind==='group')avatar.innerHTML=icon('people');else avatar.textContent=item.name?.slice(0,1)||'A';
 const info=document.createElement('span');info.className='ep-im-peer-info';
 const title=document.createElement('strong');title.textContent=item.name||'联系人';
 const subtitle=document.createElement('small');subtitle.textContent=kind==='group'?[...names.values()].join(' · '):'信息';
 info.append(title,subtitle);person.append(avatar,info);
 const actions=document.createElement('div');actions.className='ep-im-actions';
 const wallpaper=document.createElement('button');wallpaper.type='button';wallpaper.className='ep-im-more';
 wallpaper.setAttribute('aria-label','更换聊天背景');wallpaper.innerHTML=icon('photo');
 wallpaper.onclick=()=>{
  void window.EmoiWallpapers?.activate('chat:'+key);
  window.EmoiWallpapers?.open();
 };
 actions.append(wallpaper);
 header.append(back,person,actions);
 if(manage){
  const more=document.createElement('button');more.type='button';more.className='ep-im-more';more.setAttribute('aria-label','管理群聊');more.innerHTML=icon('info');more.onclick=manage;actions.append(more);
 }
 root.append(header);
 if(kind==='contact')void window.EmoiAvatars?.paint(avatar,item.id);
 const body=document.createElement('main');body.className='ep-im-timeline';body.setAttribute('aria-label','与'+(item.name||'联系人')+'的消息');
 const content=document.createElement('div');content.className='ep-im-content';
 const initial=document.createElement('div');initial.className='ep-im-conversation-start';
 const note=document.createElement('p');note.textContent='信息';
 const hint=document.createElement('small');hint.textContent='还没有消息';
 initial.append(note,hint);content.append(initial);
 const history=document.createElement('div');history.className='ep-im-history';
 content.append(history);body.append(content);root.append(body);
 const notice=document.createElement('div');notice.className='ep-im-notice';notice.setAttribute('role','status');notice.hidden=true;root.append(notice);
 const footer=document.createElement('form');footer.className='ep-im-footer';footer.autocomplete='off';
 const composer=document.createElement('div');composer.className='ep-im-composer';
 const input=document.createElement('textarea');input.rows=1;input.maxLength=10000;input.placeholder='信息';input.setAttribute('aria-label','输入消息');
 const submit=document.createElement('button');submit.type='submit';submit.className='ep-im-submit';submit.setAttribute('aria-label','发送消息');submit.innerHTML=icon('arrow');submit.disabled=true;
 composer.append(input,submit);footer.append(composer);root.append(footer);
 let sending=false,replying=false,timer,remoteRows=[],pendingRequest=null;
 const isOpen=()=>root.contains(history);
 let stickToBottom=true;
 body.addEventListener('scroll',()=>{
  stickToBottom=body.scrollHeight-body.scrollTop-body.clientHeight<60;
 },{passive:true});
 if(window.ResizeObserver){
  const observer=new ResizeObserver(()=>{
   if(!isOpen()){observer.disconnect();return}
   if(stickToBottom)body.scrollTop=body.scrollHeight;
  });
  observer.observe(body);
 }

 const report=text=>{notice.textContent=text;notice.hidden=!text};
 const updateSend=()=>{submit.disabled=!input.value.trim()||sending||replying};
 function paint(){
  const rows=[...(local[key]||[]).filter(msg=>msg.delivery==='local_only'),...remoteRows];
  rows.sort((a,b)=>String(a.created_at).localeCompare(String(b.created_at)));
  const atBottom=body.scrollHeight-body.scrollTop-body.clientHeight<60;
  initial.hidden=rows.length>0;
  const fragments=[];
  let prior=null;
  for(const row of rows){
   if(!prior||Date.parse(row.created_at)-Date.parse(prior.created_at)>=30*60*1000){
    const time=document.createElement('time');time.className='ep-im-date';time.textContent=formatDate(row.created_at);fragments.push(time);
   }
   fragments.push(messageBubble(row,names,kind==='group'));prior=row;
  }
  history.replaceChildren(...fragments);
  if(atBottom)body.scrollTop=body.scrollHeight;
 }
 function schedule(){
  clearTimeout(timer);
  if(isOpen()&&replying)timer=setTimeout(refresh,1800);
 }
 async function refresh(){
  if(!isOpen()||!endpoint||!window.EmoiRelay?.enabled)return;
  try{
   const result=await window.EmoiRelay.request(endpoint);
   if(!isOpen())return;
   const incoming=result.messages||[];
   const saved=new Map(remoteRows.map(row=>[row.id,row]));
   for(const row of incoming)saved.set(row.id,row);
   remoteRows=[...saved.values()];
   replying=Boolean(result.replying);
   report(result.model_connected?'':'未绑定回复模型');
   local[key]=[...(local[key]||[]).filter(msg=>msg.delivery==='local_only'),...remoteRows];
   save(local);paint();updateSend();
  }catch{
   if(isOpen())report('暂时无法同步会话');
  }
  schedule();
 }
 // Previously synced rows remain available during a temporary disconnect.
 remoteRows=(local[key]||[]).filter(msg=>msg.delivery!=='local_only');
 paint();
 if(endpoint&&window.EmoiRelay?.enabled)void refresh();
 else report('未连接会话服务器 · 消息保存在本机');
 input.addEventListener('input',()=>{
  updateSend();input.style.height='28px';input.style.height=Math.min(input.scrollHeight,122)+'px';
 });
 input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!submit.disabled)footer.requestSubmit()}});
 footer.onsubmit=async e=>{
  e.preventDefault();
  const text=input.value.trim();if(!text||sending||replying)return;
  if(endpoint&&window.EmoiRelay?.enabled){
   sending=true;updateSend();
   if(pendingRequest?.text!==text)pendingRequest={text,nonce:crypto.randomUUID()};
   try{
    const answer=await window.EmoiRelay.json(endpoint,'POST',pendingRequest);
    pendingRequest=null;
    if(!isOpen())return;
    const row=answer.message;
    remoteRows=remoteRows.filter(msg=>msg.id!==row.id);
    remoteRows.push(row);replying=row.delivery==='replying';
    local[key]=[...(local[key]||[]).filter(msg=>msg.delivery==='local_only'),...remoteRows];
    save(local);
    report(answer.model_dispatched?'':notice.textContent);
    schedule();
   }catch(error){
    if(isOpen())report(error.message||'消息发送失败');
    return;
   }finally{sending=false;updateSend()}
  }else{
   const rows=local[key]??=[];
   rows.push({id:crypto.randomUUID(),author:'human',text,created_at:new Date().toISOString(),delivery:'local_only'});
   if(!save(local)){rows.pop();report('本机存储已满，消息没有保存');return}
  }
  if(input.value.trim()===text){input.value='';input.style.height='28px'}
  updateSend();paint();body.scrollTop=body.scrollHeight;
 };
 window.EmoiWallpapers?.activate('chat:'+key);
}
function latest(kind,id){
 return (local[kind+':'+id]||[]).reduce((recent,row)=>!recent||row.created_at>recent.created_at?row:recent,null);
}
window.EmoiMessageApp={open,latest};
})();
