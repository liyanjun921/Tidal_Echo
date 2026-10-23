/* Luné adapter for Tidal Echo. Model keys are sent to the server, never persisted here. */
(()=>{'use strict';
const $=s=>document.querySelector(s);
const defaults={base:'/relay',remember:false};
let config={...defaults};try{config={...defaults,...JSON.parse(localStorage.getItem('lune-connection')||'{}')}}catch{}
let secret=sessionStorage.getItem('lune-secret')||(config.remember?localStorage.getItem('lune-secret'):'')||'';
let stream=null,poll=null,owner='',activeRoom='gpt',epoch=0;
const drafts=new Map(),blobUrls=new Map();
const emit=(name,detail)=>window.dispatchEvent(new CustomEvent('lune-'+name,{detail}));
const toast=t=>emit('notice',t);
const apiUrl=path=>config.base.replace(/\/$/,'')+path;
async function request(path,opts={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),opts.timeout||30000);
 try{const r=await fetch(apiUrl(path),{...opts,signal:opts.signal||controller.signal,headers:{Authorization:'Bearer '+secret,...(opts.body&&typeof opts.body==='string'?{'Content-Type':'application/json'}:{}),...opts.headers}});
 if(!r.ok){let message='请求失败 HTTP '+r.status;try{const d=await r.json();message=typeof d.detail==='string'?d.detail:message}catch{};throw new Error(message)}
 return opts.blob?await r.blob():await r.json();
 }finally{clearTimeout(timer)}
}
const json=(path,method,body)=>request(path,{method,body:JSON.stringify(body)});
function db(){return new Promise((resolve,reject)=>{const r=indexedDB.open('lune-cloud-cache',1);r.onupgradeneeded=()=>r.result.createObjectStore('rooms');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
async function cache(room,rows){try{const d=await db(),tx=d.transaction('rooms','readwrite');tx.objectStore('rooms').put(rows.slice(-100),owner+':'+room);tx.oncomplete=()=>d.close()}catch{}}
async function cached(room){try{const d=await db();return await new Promise(resolve=>{const r=d.transaction('rooms').objectStore('rooms').get(owner+':'+room);r.onsuccess=()=>{resolve(r.result||[]);d.close()};r.onerror=()=>{resolve([]);d.close()}})}catch{return []}}
function message(m){return {id:String(m.id),role:m.from==='human'?'user':(m.meta?.agent_id||'gpt'),text:m.text||'',ts:m.ts,kind:m.kind,meta:m.meta||{},time:m.meta?.date_unknown?'导入记录 · 日期未知':new Date(m.ts).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})}}
async function load(room,{before=0,quiet=false}={}){
 const current=epoch;
 if(!quiet&&!before){const rows=await cached(room);if(rows.length&&current===epoch)emit('room',{room,messages:rows,cached:true})}
 const result=await request(`/lune/rooms/${room}/messages?limit=40${before?'&before='+before:''}`);
 if(current!==epoch)return;
 const rows=result.messages.map(message);
 emit('room',{room,messages:rows,older:!!before,hasMore:result.has_more,runs:result.runs});
 if(!before)cache(room,rows);
 return result;
}
async function sync(){if(!secret||document.hidden)return;try{await load(activeRoom,{quiet:true})}catch(e){emit('status','连接暂不可用，已显示本机缓存')}}
function realtime(){
 stream?.close();if(!secret)return;
 const current=epoch;
 stream=new EventSource(apiUrl('/app/stream?token='+encodeURIComponent(secret)));
 stream.onopen=()=>{if(current===epoch){emit('status','已连接 · 服务器保存');sync()}};
 stream.onerror=()=>emit('status','正在重连 · 已保存的消息会补取');
 stream.onmessage=e=>{if(current!==epoch)return;let m;try{m=JSON.parse(e.data)}catch{return}
  if(m.type==='lune_run'){load(m.room,{quiet:true}).catch(()=>{});return}
  if(m.type==='reply_delta'){
   const room=(m.api_session||'').replace('lune-','');if(!['gpt','claude','group'].includes(room))return;
   const key=m.stream_id;const d=drafts.get(key)||{id:'stream-'+key,role:m.agent_id||room,text:'',kind:'stream',meta:{api_session:m.api_session},time:'正在回复…'};
   d.text+=m.text||'';drafts.set(key,d);emit('draft',{room,message:d});return;
  }
  if(m.from){const room=(m.meta?.api_session||'').replace('lune-','');if(!['gpt','claude','group'].includes(room))return;
   if(m.meta?.stream_id){drafts.delete(m.meta.stream_id);emit('draft-remove',{room,id:'stream-'+m.meta.stream_id})}
   emit('message',{room,message:message(m)});
  }
 };
 clearInterval(poll);poll=setInterval(sync,12000);
}
async function connect(){
 if(!secret){emit('status','尚未连接 · 可查看本机资料');return}
 const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(config.base+'\0'+secret));
 owner=Array.from(new Uint8Array(bytes)).map(n=>n.toString(16).padStart(2,'0')).join('');
 emit('connected',{});
 for(const room of ['gpt','claude','group']){const rows=await cached(room);if(rows.length)emit('room',{room,messages:rows,cached:true})}
 try{await request('/lune/rooms')}catch(e){emit('status','服务器暂不可用 · 已显示本机缓存');throw e}realtime();
 await Promise.all(['gpt','claude','group'].map(room=>load(room).catch(e=>toast(e.message))));
 await memories();
}
async function memories(){const result=await request('/lune/memories');emit('memories',result.memories.map(m=>({...m,date:m.updated_at.slice(0,10)})));return result.memories}
function disconnect(){epoch++;stream?.close();clearInterval(poll);secret='';sessionStorage.removeItem('lune-secret');localStorage.removeItem('lune-secret');drafts.clear();for(const u of blobUrls.values())URL.revokeObjectURL(u);blobUrls.clear();emit('disconnected',{});emit('status','已断开连接')}
function pending(){try{return JSON.parse(localStorage.getItem('lune-outbox-'+owner)||'[]')}catch{return []}}
function keepPending(m){const rows=pending().filter(x=>x.nonce!==m.nonce);rows.push({...m,status:'failed',time:'待核对发送状态'});localStorage.setItem('lune-outbox-'+owner,JSON.stringify(rows))}
function clearPending(nonce){localStorage.setItem('lune-outbox-'+owner,JSON.stringify(pending().filter(x=>x.nonce!==nonce)))}
async function media(att){
 const path=String(att.url||'');if(!/^\/[\w/-]*uploads\/[^/]+$/.test(path)||/[?#]/.test(path))throw new Error('附件来源无效');
 if(blobUrls.has(path))return blobUrls.get(path);
 const file=await request('/uploads/'+encodeURIComponent(path.split('/').pop()),{blob:true});const u=URL.createObjectURL(file);blobUrls.set(path,u);return u;
}
async function tts(text){
 if(window.LuneRelay.audio){window.LuneRelay.audio.pause();window.LuneRelay.audio=null;return}
 if(text.length>900)throw new Error('单次朗读最多 900 字符，请分段朗读');
 const blob=await request('/app/tts',{method:'POST',body:JSON.stringify({text}),blob:true,timeout:60000});
 const url=URL.createObjectURL(blob),audio=new Audio(url);window.LuneRelay.audio=audio;
 audio.onended=()=>{URL.revokeObjectURL(url);window.LuneRelay.audio=null};await audio.play();
}
async function notify(){
 if(!('Notification'in window)||!('serviceWorker'in navigator)||!('PushManager'in window))throw new Error('当前环境不支持通知，请在 iPhone 主屏幕应用中检查');
 if(Notification.permission!=='granted'&&await Notification.requestPermission()!=='granted')throw new Error('通知权限尚未开启');
 const reg=await navigator.serviceWorker.ready;
 const result=await request('/app/vapid_public');const key=result.public_key||result.key;
 if(!key)throw new Error('服务器尚未配置通知密钥');
 const str=key.replace(/-/g,'+').replace(/_/g,'/'),bytes=Uint8Array.from(atob(str+'='.repeat((4-str.length%4)%4)),c=>c.charCodeAt(0));
 const sub=await reg.pushManager.getSubscription()||await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes});
 await json('/app/subscribe','POST',sub.toJSON());toast('消息通知已订阅，锁屏送达仍需实机检查');
}
async function settings(){
 const dialog=$('#connectionDialog');$('#relayBase').value=config.base;$('#relaySecret').value='';$('#rememberConnection').checked=!!config.remember;if(!dialog.open)dialog.showModal();
 if(!secret)return;
 try{const {agents}=await request('/app/loop/agents');for(const name of ['gpt','claude']){
 const f=$('#agent-'+name);for(const key of ['url','model','persona','protocol'])f.elements[key].value=agents[name][key]||'';f.elements.key.placeholder=agents[name].key_set?'已保存；留空保持':'API Key';f.elements.key.value='';
 }await toolStatus()}catch(e){$('#settingsStatus').textContent=e.message}
}
async function toolStatus(){const r=await request('/app/loop/mcp');$('#toolStatus').textContent=JSON.stringify(r,null,2)}
function wire(){
 document.querySelectorAll('[data-settings]').forEach(b=>b.onclick=settings);
 $('#closeConnection').onclick=()=>$('#connectionDialog').close();
 $('#connectionForm').onsubmit=async e=>{e.preventDefault();const raw=$('#relayBase').value.trim().replace(/\/$/,'');
 if(!raw.startsWith('/')&&!/^https:\/\//.test(raw)&&!/^http:\/\/(127\.0\.0\.1|localhost)(:|\/)/.test(raw)){toast('请使用同站路径或 HTTPS 地址');return}
 config={base:raw||'/relay',remember:$('#rememberConnection').checked};secret=$('#relaySecret').value.trim()||secret;
 localStorage.setItem('lune-connection',JSON.stringify(config));sessionStorage.setItem('lune-secret',secret);
 if(config.remember)localStorage.setItem('lune-secret',secret);else localStorage.removeItem('lune-secret');epoch++;
 try{await connect();$('#relaySecret').value='';$('#settingsStatus').textContent='连接成功';await settings()}catch(e){$('#settingsStatus').textContent=e.message}
 };
 $('#disconnectButton').onclick=()=>{disconnect();$('#connectionDialog').close()};
 for(const name of ['gpt','claude']){
 $('#agent-'+name).onsubmit=async e=>{e.preventDefault();const f=e.target,body={agent:name};for(const key of ['url','model','key','persona','protocol'])body[key]=f.elements[key].value;
 try{await json('/app/loop/agents','POST',body);f.elements.key.value='';toast(name.toUpperCase()+' 设置已保存到服务器')}catch(e){toast(e.message)}};
 $('#test-'+name).onclick=async()=>{try{$('#settingsStatus').textContent='正在测试…';await json('/app/loop/agents/test','POST',{agent:name});$('#settingsStatus').textContent=name.toUpperCase()+' 测试通过'}catch(e){$('#settingsStatus').textContent=e.message}};
 }
 $('#mcpForm').onsubmit=async e=>{e.preventDefault();const f=e.target;try{await json('/app/loop/mcp','POST',{name:f.elements.serverName.value,transport:'http',url:f.elements.url.value,enabled:true});await toolStatus();toast('工具服务器已保存')}catch(e){toast(e.message)}};
 $('#notificationButton').onclick=()=>notify().catch(e=>toast(e.message));
 $('#pushTestButton').onclick=()=>json('/app/push_test','POST',{}).then(()=>toast('已发起通知测试，请检查实际送达')).catch(e=>toast(e.message));
 $('#exportButton').onclick=async()=>{try{const data=secret?await request('/lune/export'):{format:'lune-local-v04',data:window.LuneApp.snapshot()};const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='Lune-backup-'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){toast(e.message)}};
 $('#importFile').onchange=async e=>{const file=e.target.files[0];e.target.value='';if(!file)return;if(file.size>20*1024*1024){toast('请选择 20 MB 内的 JSON 备份');return}
 try{const body=JSON.parse(await file.text());if(!confirm('导入会追加聊天与记忆，不覆盖现有数据。示例记忆会跳过。继续？'))return;
 if(secret){const r=await json('/lune/import','POST',body);toast(r.duplicate?'这份备份已导入':`已导入 ${r.messages} 条消息、${r.memories} 条记忆`);await connect()}else await window.LuneApp.importData(body);
 }catch(e){toast('导入失败：'+e.message)}};
 window.addEventListener('online',()=>{if(secret)realtime();sync()});document.addEventListener('visibilitychange',()=>{if(document.hidden){stream?.close();stream=null}else{if(secret)realtime();sync()}});
 navigator.serviceWorker?.addEventListener('message',e=>{if(e.data?.type==='backfill')sync()});
 if('serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>toast('离线缓存暂不可用，在线聊天不受影响'));
}
window.LuneRelay={get enabled(){return !!secret},get base(){return config.base},request,json,load,memories,media,tts,settings,connect,wire,pending,keepPending,clearPending,
 select(room){activeRoom=room;if(secret)load(room).catch(e=>toast(e.message))},
 send(room,text,attachments,nonce){return json(`/lune/rooms/${room}/send`,'POST',{text,attachments,nonce})},
 async upload(file){return request('/app/upload?name='+encodeURIComponent(file.name),{method:'POST',body:file,headers:{'Content-Type':file.type||'application/octet-stream'}})},
 stop(id){return json('/lune/runs/'+encodeURIComponent(id)+'/stop','POST',{})}
};
})();
