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
 plus:'<path d="M12 5v14M5 12h14"/>',
 arrow:'<path d="m5 12 7-7 7 7m-7-7v14"/>',
 info:'<circle cx="12" cy="12" r="10"/><path d="M12 11v6m0-9v.5"/>',
 photo:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.2" cy="8" r="1.5"/><path d="m3 17 5-5 4 3 4-4 5 6"/>',
 mic:'<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M6 11a6 6 0 0 0 12 0m-6 6v4m-4 0h8"/>',
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
const esc=val=>String(val||'').trim();
const time=iso=>{try{return new Date(iso).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false})}catch{return ''}};
const date=iso=>{try{return new Date(iso).toLocaleDateString('zh-CN',{month:'long',day:'numeric'})}catch{return ''}};
function messageBubble(msg){
 const row=document.createElement('article');row.className='ep-im-row ep-im-'+(msg.author==='human'?'mine':'theirs');
 const bubble=document.createElement('div');bubble.className='ep-im-bubble';bubble.textContent=msg.text||'';
 row.append(bubble);
 if(msg.author==='human'){const delivery=document.createElement('small');delivery.className='ep-im-delivery';delivery.textContent=msg.delivery==='stored_not_delivered'?'已存入私人会话 · 未发送给 AI':'仅保存在本机 · 尚未发送给 AI';row.append(delivery)}
 return row;
}
async function getRemote(conversationId){
 if(!conversationId||!window.EmoiRelay?.enabled)return [];
 try{const result=await window.EmoiRelay.request('/emoi/v2/conversations/'+encodeURIComponent(conversationId)+'/messages');
  return (result.messages||[]).map(msg=>({id:msg.id,author:msg.author,text:msg.text,created_at:msg.created_at,delivery:msg.delivery}));
 }catch{return[]}
}
function open(root,{kind='contact',item,conversationId,goBack,contactNames=[]}){
 const ident=item.id;
 const key=(kind==='group'?'group:':'contact:')+ident;
 root.className='ep-view ep-im-screen';
 const header=document.createElement('header');header.className='ep-im-header';
 const back=document.createElement('button');back.type='button';back.className='ep-im-back';back.setAttribute('aria-label','返回信息');back.innerHTML=icon('back');back.onclick=goBack;
 const person=document.createElement('button');person.type='button';person.className='ep-im-peer';
 const avatar=document.createElement('span');avatar.className='ep-im-avatar';
 if(kind==='group')avatar.innerHTML=icon('people');else avatar.textContent=item.name?.slice(0,1)||'A';
 const info=document.createElement('span');info.className='ep-im-peer-info';
 const title=document.createElement('strong');title.textContent=item.name||'联系人';
 const subtitle=document.createElement('small');subtitle.textContent=kind==='group'?contactNames.join(' · ')||'自建群聊':'未连接 AI · 独立会话';
 info.append(title,subtitle);person.append(avatar,info);
 const more=document.createElement('button');more.type='button';more.className='ep-im-more';more.setAttribute('aria-label','会话信息');more.innerHTML=icon('info');
 more.onclick=()=>{const d=$('#epImInfo');if(!d)return;
 $('#epImInfoTitle').textContent=item.name;
 $('#epImInfoBody').textContent='独立身份 ID：'+ident+'\n记忆空间：'+(item.memory_namespace||'contact:'+ident)+'\n欲望空间：'+(kind==='contact'?(item.desire_namespace||'desire:contact:'+ident):'群聊不运行个人欲望系统')+'\n状态：尚未接通独立模型服务；这段会话不会调用其他 AI 的接口。';
 d.showModal();
 };
 person.onclick=more.onclick;
 header.append(back,person,more);
 root.append(header);
 const body=document.createElement('main');body.className='ep-im-timeline';body.setAttribute('aria-label','与'+(item.name||'联系人')+'的消息');
 const content=document.createElement('div');content.className='ep-im-content';
 const initial=document.createElement('div');initial.className='ep-im-conversation-start';
 const big=document.createElement('div');big.className='ep-im-big-avatar';if(kind==='group')big.innerHTML=icon('people');else big.textContent=item.name?.slice(0,1)||'A';
 const note=document.createElement('p');note.textContent='这是与'+item.name+'的独立会话。';
 const hint=document.createElement('small');hint.textContent='尚未接通模型；你写下的消息只会保存，不会被发送给其他 AI。';
 initial.append(big,note,hint);content.append(initial);
 const history=document.createElement('div');history.className='ep-im-history';
 content.append(history);body.append(content);root.append(body);
 const notice=document.createElement('div');notice.className='ep-im-notice';notice.textContent='AI 服务未连接 · 当前只存储消息';root.append(notice);
 const footer=document.createElement('form');footer.className='ep-im-footer';footer.autocomplete='off';
 const attach=document.createElement('button');attach.type='button';attach.className='ep-im-attach';attach.setAttribute('aria-label','添加图片');attach.innerHTML=icon('plus');
 const composer=document.createElement('div');composer.className='ep-im-composer';
 const input=document.createElement('textarea');input.rows=1;input.maxLength=10000;input.placeholder='iMessage';input.setAttribute('aria-label','输入消息');
 const submit=document.createElement('button');submit.type='submit';submit.className='ep-im-submit';submit.setAttribute('aria-label','保存消息');submit.innerHTML=icon('arrow');submit.disabled=true;
 composer.append(input,submit);
 const file=document.createElement('input');file.type='file';file.accept='image/png,image/jpeg,image/webp';file.hidden=true;file.setAttribute('aria-label','选择图片');
 attach.onclick=()=>file.click();
 file.onchange=()=>{const f=file.files?.[0];file.value='';if(!f)return;
  const d=$('#epImInfo');if(d){$('#epImInfoTitle').textContent='图片附件';$('#epImInfoBody').textContent='已选择 '+f.name+'。独立 AI 的图片上传接口尚未连接，为了不误传私人图片，这次不保存或发送附件。';d.showModal()}
 };
 footer.append(attach,composer,file);root.append(footer);
 const persistRows=()=>{
   const rows=(local[key]||[]).filter(x=>x&&x.text);
   history.replaceChildren(...rows.map(messageBubble));
   body.scrollTop=body.scrollHeight;
 };
 persistRows();
 if(conversationId){
  void getRemote(conversationId).then(rows=>{if(!rows.length||!root.isConnected)return;
    const existing=new Set((local[key]||[]).map(r=>r.id));
    for(const row of rows)if(!existing.has(row.id)) (local[key]??=[]).push(row);
    (local[key]??=[]).sort((a,b)=>String(a.created_at).localeCompare(String(b.created_at)));
    save(local);persistRows();
  });
 }
 input.addEventListener('input',()=>{
   submit.disabled=!input.value.trim();input.style.height='28px';input.style.height=Math.min(input.scrollHeight,122)+'px';
 });
 input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!submit.disabled)footer.requestSubmit()}});
 footer.onsubmit=async e=>{
  e.preventDefault();
  const text=input.value.trim();if(!text)return;
  const id=crypto.randomUUID?.()||Date.now().toString(36)+Math.random().toString(36).slice(2);
  const nonce=(crypto.randomUUID?.()||String(Date.now())+Math.random().toString(36)).replace(/-/g,'');
  const msg={id,author:'human',text,created_at:new Date().toISOString(),delivery:'local_only'};
  (local[key]??=[]).push(msg);
  if(!save(local)){(local[key]??=[]).pop();notice.textContent='浏览器存储已满，消息没有保存';return}
  input.value='';input.style.height='28px';submit.disabled=true;persistRows();
  if(conversationId&&window.EmoiRelay?.enabled){
   try{
    const answer=await window.EmoiRelay.json('/emoi/v2/conversations/'+encodeURIComponent(conversationId)+'/messages','POST',{text,nonce});
    if(answer?.message){
      msg.id=answer.message.id;
      msg.delivery='stored_not_delivered';
      save(local);persistRows();
    }
   }catch(error){notice.textContent='本机消息已保存，但云端存储未成功：'+(error?.message||'网络异常')}
  }
 };
 if(kind==='contact')window.EmoiWallpapers?.activate('chat:contact:'+ident);
 else window.EmoiWallpapers?.activate('chat:group:'+ident);
}
function installInfoDialog(){
 const dlg=document.createElement('dialog');dlg.id='epImInfo';dlg.className='ep-edit-dialog ep-im-info-dialog';
 const h=document.createElement('header');const title=document.createElement('strong');title.id='epImInfoTitle';
 const close=document.createElement('button');close.type='button';close.innerHTML=icon('back');close.setAttribute('aria-label','关闭');close.onclick=()=>dlg.close();
 h.append(title,close);
 const p=document.createElement('pre');p.id='epImInfoBody';p.className='ep-im-info-content';
 dlg.append(h,p);document.body.append(dlg);
}
window.EmoiMessageApp={open};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',installInfoDialog);else installInfoDialog();
})();
