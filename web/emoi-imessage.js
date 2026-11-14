/* Émoi Messages: independent iMessage-inspired UI. No Uranus code reused.
   Real local conversation records are scoped by immutable contact/conversation ID.
   Model responses and receipts are NEVER fabricated.
*/
(()=>{
'use strict';
const KEY='emoi-ui-conversation-drafts-v1', PIN_KEY='emoi-message-pins-v1';
const MAX_MEDIA_BYTES=8*1024*1024;
const mediaLabels={image:'图片',sticker:'表情包',voice:'语音消息'};
const imageTypes=new Map([['image/jpeg','jpg'],['image/png','png'],['image/gif','gif'],['image/webp','webp'],['image/avif','avif']]);
const audioTypes=new Map([['audio/mp4','m4a'],['audio/webm','webm'],['audio/ogg','ogg'],['audio/wav','wav']]);
const $=(s,r=document)=>r.querySelector(s);
const icons={
 plus:'<path d="M12 5v14M5 12h14"/>',
 mic:'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2m-7 9v3m-3 0h6"/>',
 video:'<rect x="2" y="5" width="14" height="14" rx="3"/><path d="m16 10 6-4v12l-6-4"/>',
 dial:'<path d="M6 5h.1M12 5h.1M18 5h.1M6 10h.1M12 10h.1M18 10h.1M6 15h.1M12 15h.1M18 15h.1M12 20h.1" stroke-width="3"/>',
 stop:'<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
 pin:'<path d="m16 3 5 5-3 2-3 5-2 1-5-5 1-2 5-3 2-3ZM9 15l-6 6"/>',
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
function pins(){
 try{const value=JSON.parse(localStorage.getItem(PIN_KEY)||'[]');return new Set(Array.isArray(value)?value:[])}catch{return new Set()}
}
const pinned=(kind,id)=>pins().has(kind+':'+id);
function togglePin(kind,id){
 const values=pins(), key=kind+':'+id;
 if(values.has(key))values.delete(key);else values.add(key);
 localStorage.setItem(PIN_KEY,JSON.stringify([...values]));
 return values.has(key);
}
function mediaStore(id,blob){
 return new Promise((resolve,reject)=>{
  const open=indexedDB.open('emoi-message-media',1);
  open.onupgradeneeded=()=>open.result.createObjectStore('files');
  open.onerror=()=>reject(open.error);
  open.onsuccess=()=>{
   const db=open.result, tx=db.transaction('files',blob?'readwrite':'readonly'), store=tx.objectStore('files');
   const request=blob?store.put(blob,id):store.get(id);
   tx.oncomplete=()=>{db.close();resolve(request.result)};
   tx.onabort=()=>{db.close();reject(tx.error||new Error('本机附件存储失败'))};
  };
 });
}
function button(label,glyph,action,className='ep-im-more'){
 const el=document.createElement('button');el.type='button';el.className=className;
 el.setAttribute('aria-label',label);el.title=label;el.innerHTML=icon(glyph);el.onclick=action;
 return el;
}
function dialogFor(title,{persistent=false}={}){
 const dialog=document.createElement('dialog');dialog.className='ep-edit-dialog ep-im-tool';
 const heading=document.createElement('h2');heading.textContent=title;
 const close=document.createElement('button');close.type='button';close.className='ep-home-control';close.textContent='关闭';
 close.onclick=()=>dialog.close();dialog.setAttribute('aria-label',title);
 dialog.append(heading);document.body.append(dialog);
 if(!persistent)dialog.addEventListener('close',()=>dialog.remove(),{once:true});
 return {dialog,close};
}
function openDialpad(){
 const {dialog,close}=dialogFor('电话键盘');
 const number=document.createElement('input');number.type='tel';number.inputMode='none';number.setAttribute('aria-label','电话号码');
 const keys=document.createElement('div');keys.className='ep-im-dial-keys';
 for(const digit of '123456789*0#'){
  const key=document.createElement('button');key.type='button';key.textContent=digit;
  key.onclick=()=>{number.value+=digit;number.dispatchEvent(new Event('input'))};keys.append(key);
 }
 const erase=document.createElement('button');erase.type='button';erase.className='ep-home-control';erase.textContent='删除一位';
 erase.onclick=()=>{number.value=number.value.slice(0,-1);number.dispatchEvent(new Event('input'))};
 const call=document.createElement('a');call.textContent='用系统电话拨打';call.className='ep-home-control';call.hidden=true;
 number.oninput=()=>{
  const value=number.value.replace(/[\s()-]/g,'');
  call.hidden=!/^\+?[0-9*#]{1,32}$/.test(value);
  if(!call.hidden)call.href='tel:'+value.replace(/#/g,'%23');else call.removeAttribute('href');
 };
 dialog.append(number,keys,erase,call,close);dialog.showModal();
}
async function openVideo(){
 const {dialog,close}=dialogFor('视频预览');
 const video=document.createElement('video');video.autoplay=true;video.muted=true;video.playsInline=true;video.hidden=true;
 const note=document.createElement('p');note.textContent='本机摄像头预览 · 此会话尚未接入视频通话';
 let stream;
 dialog.addEventListener('close',()=>stream?.getTracks().forEach(track=>track.stop()),{once:true});
 dialog.append(note,video,close);dialog.showModal();
 try{
  stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user'},audio:false});
  if(!dialog.open){stream.getTracks().forEach(track=>track.stop());return}
  video.srcObject=stream;video.hidden=false;
 }catch{note.textContent='无法打开摄像头 · 请检查浏览器权限'}
}
function renderAttachment(bubble,attachment,registerURL){
 const isVoice=attachment.kind==='voice';
 const media=document.createElement(isVoice?'audio':'img');
 if(isVoice){media.controls=true;media.preload='metadata';media.setAttribute('aria-label','播放语音消息')}
 else{media.alt=mediaLabels[attachment.kind]||'聊天图片';media.decoding='async';media.loading='lazy'}
 const status=document.createElement('span');status.textContent='正在载入'+mediaLabels[attachment.kind]+'…';
 bubble.append(status);
 const load=attachment.localId?mediaStore(attachment.localId).then(blob=>{
  if(!blob)throw new Error('找不到本机附件');
  return registerURL(attachment.localId,blob);
 }):window.EmoiRelay?.enabled?window.EmoiRelay.media(attachment):Promise.reject();
 load.then(url=>{if(bubble.isConnected&&url){media.src=url;status.replaceWith(media)}})
  .catch(()=>{status.textContent=mediaLabels[attachment.kind]+'暂不可用'});
}
const formatDate=iso=>new Date(iso).toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'});
const deliveryLabels={
 local_only:'仅保存在本机 · 尚未发送给 AI',
 stored_not_delivered:'已存入会话 · 未绑定回复模型',
 replying:'等待 AI 回复…', partial:'部分成员未能回复',
 model_failed:'模型回复失败 · 请检查联系人绑定和 API 设置',
 interrupted:'回复因服务重启中断'
};
function messageBubble(msg,members,showName,registerURL){
 const row=document.createElement('article');row.className='ep-im-row ep-im-'+(msg.author==='human'?'mine':'theirs');
 if(msg.author==='contact'&&showName){
  const name=document.createElement('small');name.className='ep-im-sender';name.textContent=members.get(msg.contact_id)||'原群成员';row.append(name);
 }
 const bubble=document.createElement('div');bubble.className='ep-im-bubble';
 if(msg.attachment){
  bubble.dataset.media=msg.attachment.kind;renderAttachment(bubble,msg.attachment,registerURL);
  if(msg.text&&msg.text!=='['+mediaLabels[msg.attachment.kind]+']')bubble.append(document.createElement('br'),msg.text);
 }else bubble.textContent=msg.text||'';
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
 const back=button('返回信息','back',goBack,'ep-im-back');
 const person=button(item.name||'联系人','info',null,'ep-im-peer');
 person.replaceChildren();
 const avatar=document.createElement('span');avatar.className='ep-im-avatar';
 if(kind==='group')avatar.innerHTML=icon('people');else avatar.textContent=item.name?.slice(0,1)||'A';
 const info=document.createElement('span');info.className='ep-im-peer-info';
 const title=document.createElement('strong');title.textContent=(item.name||'联系人')+' ›';
 info.append(title);person.append(avatar,info);
 const {dialog:options,close:closeOptions}=dialogFor(item.name||'会话设置',{persistent:true});
 const pin=button('置顶会话','pin',()=>{
  try{paintPin(togglePin(kind,ident))}catch{report('无法保存置顶状态')}
 },'ep-home-control');
 function paintPin(state){
  const label=state?'取消置顶':'置顶会话';pin.textContent=label;pin.setAttribute('aria-label',label);pin.title=label;
 }
 paintPin(pinned(kind,ident));
 const wallpaper=button('更换聊天背景','photo',()=>{
  options.close();
  void window.EmoiWallpapers?.activate('chat:'+key);
  window.EmoiWallpapers?.open();
 },'ep-home-control');
 wallpaper.textContent='更换聊天背景';
 options.append(pin,wallpaper);
 if(manage){
  const more=button('管理群聊','info',()=>{options.close();manage()},'ep-home-control');more.textContent='管理群聊';
  options.append(more);
 }
 options.append(closeOptions);root.append(options);
 person.onclick=()=>options.showModal();
 const actions=document.createElement('div');actions.className='ep-im-actions';
 actions.append(button('视频预览','video',openVideo),button('电话键盘','dial',openDialpad));
 header.append(back,person,actions);root.append(header);
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
 const attach=button('添加附件','plus',()=>{picker.hidden=!picker.hidden},'ep-im-attach');
 const mic=button('录制语音','mic',recordVoice,'ep-im-attach ep-im-mic');
 const picker=document.createElement('div');picker.className='ep-im-picker';picker.hidden=true;
 const preview=document.createElement('div');preview.className='ep-im-pending';preview.hidden=true;
 composer.append(input,mic,submit);footer.append(attach,composer);root.append(picker,preview,footer);
 let sending=false,replying=false,timer,remoteRows=[],pendingRequest=null,attachment=null,recording=null,starting=false;
 const isOpen=()=>root.contains(history);
 const mediaURLs=new Map();
 function registerURL(id,blob){
  if(!isOpen())return null;
  if(!mediaURLs.has(id))mediaURLs.set(id,URL.createObjectURL(blob));
  return mediaURLs.get(id);
 }
 const removal=new MutationObserver(()=>{
  if(isOpen())return;
  removal.disconnect();clearTimeout(timer);
  if(recording?.recorder.state==='recording')recording.recorder.stop();
  recording?.stream.getTracks().forEach(track=>track.stop());
  mediaURLs.forEach(url=>URL.revokeObjectURL(url));
 });
 removal.observe(root,{childList:true});
 for(const kind of ['image','sticker']){
  const pick=document.createElement('input');pick.type='file';pick.accept=[...imageTypes.keys()].join(',');pick.hidden=true;
  const label=kind==='image'?'选照片':'选表情包';
  const tile=button(label,'photo',()=>pick.click(),'ep-home-control');tile.textContent=label;
  pick.onchange=()=>{const file=pick.files?.[0];pick.value='';if(file)setAttachment(file,kind)};
  picker.append(tile,pick);
 }
 const emojiRow=document.createElement('div');emojiRow.className='ep-im-emoji';
 for(const emoji of ['🤍','🫧','🥺','🫶','🌙','✨']){
  const tile=document.createElement('button');tile.type='button';tile.textContent=emoji;
  tile.setAttribute('aria-label','表情包 '+emoji);
  tile.onclick=()=>{
   const canvas=document.createElement('canvas');canvas.width=160;canvas.height=160;
   const ctx=canvas.getContext('2d');if(!ctx)return;
   ctx.font='112px "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif';
   ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(emoji,80,84);
   canvas.toBlob(blob=>{if(blob&&isOpen())setAttachment(blob,'sticker')},'image/png');
  };
  emojiRow.append(tile);
 }
 picker.append(emojiRow);
 const typing=document.createElement('div');typing.className='ep-im-typing';typing.hidden=true;typing.setAttribute('aria-label','等待 AI 回复');
 for(let i=0;i<3;i++)typing.append(document.createElement('i'));
 content.append(typing);
 let stickToBottom=true;
 body.addEventListener('scroll',()=>{stickToBottom=body.scrollHeight-body.scrollTop-body.clientHeight<60},{passive:true});
 const observer=window.ResizeObserver&&new ResizeObserver(()=>{
  if(!isOpen()){observer.disconnect();return}
  if(stickToBottom)body.scrollTop=body.scrollHeight;
 });
 observer?.observe(body);
 const report=text=>{notice.textContent=text;notice.hidden=!text};
 const updateSend=()=>{
  const ready=Boolean(input.value.trim()||attachment);
  submit.disabled=!ready||sending||replying||Boolean(recording)||starting;
  submit.hidden=!ready;mic.hidden=ready&&!recording;typing.hidden=!replying;
 };
 function setAttachment(blob,kind){
  if(sending||recording)return;
  const mime=blob.type.split(';')[0].toLowerCase();
  const ext=(kind==='voice'?audioTypes:imageTypes).get(mime);
  if(!ext||!blob.size||blob.size>MAX_MEDIA_BYTES){report('请选择支持的格式，附件大小须在 8 MB 以内');return}
  attachment={file:new File([blob],kind+'.'+ext,{type:mime}),kind};
  const remove=button('移除附件','plus',()=>{attachment=null;preview.hidden=true;updateSend()},'ep-im-remove');
  remove.textContent='移除';
  preview.replaceChildren(document.createTextNode(mediaLabels[kind]+' · 待发送'),remove);
  preview.hidden=false;picker.hidden=true;updateSend();
 }
 async function recordVoice(){
  if(recording){recording.recorder.stop();return}
  if(starting||sending)return;
  if(!window.MediaRecorder||!navigator.mediaDevices?.getUserMedia){report('当前浏览器无法录音');return}
  starting=true;updateSend();
  let stream;
  try{
   stream=await navigator.mediaDevices.getUserMedia({audio:true});
   if(!isOpen()){stream.getTracks().forEach(track=>track.stop());return}
   const mime=[...audioTypes.keys()].find(type=>MediaRecorder.isTypeSupported(type));
   const recorder=mime?new MediaRecorder(stream,{mimeType:mime}):new MediaRecorder(stream);
   const chunks=[];
   recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
   recorder.onstop=()=>{
    clearTimeout(limit);stream.getTracks().forEach(track=>track.stop());recording=null;
    if(!isOpen())return;
    mic.innerHTML=icon('mic');mic.setAttribute('aria-label','录制语音');report('');
    if(chunks.length)setAttachment(new Blob(chunks,{type:recorder.mimeType||chunks[0].type}),'voice');
    updateSend();
   };
   recorder.onerror=()=>{if(recorder.state==='recording')recorder.stop();stream.getTracks().forEach(track=>track.stop());report('录音中断')};
   recorder.start();
   const limit=setTimeout(()=>{if(recorder.state==='recording')recorder.stop()},60000);
   recording={recorder,stream};
   picker.hidden=true;mic.innerHTML=icon('stop');mic.setAttribute('aria-label','停止录音');
   report('录音中 · 点方块结束');
  }catch{stream?.getTracks().forEach(track=>track.stop());report('无法录音 · 请检查麦克风权限')}
  finally{starting=false;updateSend()}
 }
 const rendered=new Map();
 let hydrated=false;
 function paint(){
  const rows=[...(local[key]||[]).filter(msg=>msg.delivery==='local_only'),...remoteRows];
  rows.sort((a,b)=>String(a.created_at).localeCompare(String(b.created_at)));
  const atBottom=stickToBottom;
  const scrollPosition=body.scrollTop;
  initial.hidden=rows.length>0;
  const fragments=[], keep=new Set();
  let prior=null;
  for(const row of rows){
   const showTime=!prior||Date.parse(row.created_at)-Date.parse(prior.created_at)>=30*60*1000;
   const sameSender=!showTime&&row.author===prior.author&&row.contact_id===prior.contact_id;
   const signature=JSON.stringify([row.text,row.attachment,row.delivery,sameSender]);
   let entry=rendered.get(row.id);
   if(!entry||entry.signature!==signature){
    const node=messageBubble(row,names,kind==='group'&&!sameSender,registerURL);
    if(hydrated&&!entry)node.classList.add('ep-im-arriving');
    entry={signature,node,time:entry?.time};rendered.set(row.id,entry);
   }
   if(showTime){
    if(!entry.time){entry.time=document.createElement('time');entry.time.className='ep-im-date';entry.time.textContent=formatDate(row.created_at)}
    fragments.push(entry.time);
   }
   entry.node.classList.toggle('ep-im-joined',sameSender);
   fragments.push(entry.node);keep.add(row.id);prior=row;
  }
  for(const id of rendered.keys())if(!keep.has(id))rendered.delete(id);
  // Keep audio, focus and existing bubbles attached during polling.
  const nextNodes=new Set(fragments);
  for(const node of [...history.children])if(!nextNodes.has(node))node.remove();
  let anchor=history.firstChild;
  for(const node of fragments){
   if(node===anchor)anchor=anchor.nextSibling;
   else history.insertBefore(node,anchor);
  }
  body.scrollTop=atBottom?body.scrollHeight:scrollPosition;
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
   saveConversation();paint();updateSend();hydrated=true;
  }catch{
   if(isOpen())report('暂时无法同步会话');
  }
  schedule();
 }
 // Previously synced rows remain available during a temporary disconnect.
 remoteRows=(local[key]||[]).filter(msg=>msg.delivery!=='local_only');
 paint();
 if(endpoint&&window.EmoiRelay?.enabled)void refresh();
 else{report('未连接会话服务器 · 消息保存在本机');hydrated=true}
 updateSend();
 input.addEventListener('input',()=>{
  updateSend();input.style.height='32px';input.style.height=Math.min(input.scrollHeight,94)+'px';
 });
 input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229){e.preventDefault();if(!submit.disabled)footer.requestSubmit()}});
 footer.onsubmit=async e=>{
  e.preventDefault();
  const text=input.value.trim(), media=attachment;
  if((!text&&!media)||sending||replying||recording||starting)return;
  sending=true;updateSend();
  try{
   if(endpoint&&window.EmoiRelay?.enabled){
    if(pendingRequest?.text!==text||pendingRequest?.media!==media)pendingRequest={text,media,nonce:crypto.randomUUID()};
    if(media&&!pendingRequest.attachment){
     const uploaded=await window.EmoiRelay.upload(media.file);
     pendingRequest.attachment={kind:media.kind,id:uploaded.url.split('/').pop()};
    }
    const {nonce,attachment:uploaded}=pendingRequest;
    const answer=await window.EmoiRelay.request(endpoint,{method:'POST',
     body:JSON.stringify({text,nonce,attachment:uploaded}),timeout:media?.kind==='voice'?60000:30000});
    pendingRequest=null;
    const row=answer.message;
    remoteRows=remoteRows.filter(msg=>msg.id!==row.id);
    remoteRows.push(row);replying=row.delivery==='replying';
    saveConversation();
    if(!isOpen())return;
    report(replying?'等待 AI 回复…':row.delivery==='stored_not_delivered'?'未绑定回复模型':'');
    schedule();
   }else{
    const id=crypto.randomUUID(), rows=local[key]??=[];
    if(media)await mediaStore(id,media.file);
    rows.push({id,author:'human',text:text||'['+mediaLabels[media.kind]+']',
     attachment:media?{localId:id,kind:media.kind}:null,created_at:new Date().toISOString(),delivery:'local_only'});
    if(!save(local)){rows.pop();throw new Error('本机存储已满，消息没有保存')}
   }
   if(!isOpen())return;
   hydrated=true;
   if(input.value.trim()===text){input.value='';input.style.height=''}
   if(attachment===media){attachment=null;preview.hidden=true}
   paint();if(stickToBottom)body.scrollTop=body.scrollHeight;
  }catch(error){if(isOpen())report(error.message||'消息发送失败')}
  finally{sending=false;updateSend()}
 };
 function saveConversation(){
  local[key]=[...(local[key]||[]).filter(msg=>msg.delivery==='local_only'),...remoteRows];
  save(local);
 }
 window.EmoiWallpapers?.activate('chat:'+key);
}
function latest(kind,id){
 return (local[kind+':'+id]||[]).reduce((recent,row)=>!recent||row.created_at>recent.created_at?row:recent,null);
}
window.EmoiMessageApp={open,latest,pinned,togglePin};
})();
