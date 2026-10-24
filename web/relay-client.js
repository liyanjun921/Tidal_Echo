/* Luné adapter for Tidal Echo. Model keys are sent to the server, never persisted here. */
(()=>{'use strict';
const $=s=>document.querySelector(s);
const preview=window.LUNE_PREVIEW===true;
const defaults={base:'/relay',remember:false};
let config={...defaults};try{config={...defaults,...JSON.parse(localStorage.getItem('lune-connection')||'{}')}}catch{}
let secret=sessionStorage.getItem('lune-secret')||(config.remember?localStorage.getItem('lune-secret'):'')||'';
if(preview)secret='';
let stream=null,poll=null,owner='',activeRoom='gpt',epoch=0,speechVersion=0,speechEpoch=0,speechController=null,speechUrl=null;
const drafts=new Map(),blobUrls=new Map();
const emit=(name,detail)=>window.dispatchEvent(new CustomEvent('lune-'+name,{detail}));
const toast=t=>emit('notice',t);
const apiUrl=path=>config.base.replace(/\/$/,'')+path;
async function request(path,opts={}){
 if(preview)throw new Error('界面预览未连接服务器，请勿在此填写密钥');
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),opts.timeout||30000),abort=()=>controller.abort();if(opts.signal?.aborted)controller.abort();else opts.signal?.addEventListener('abort',abort,{once:true});
 try{const r=await fetch(apiUrl(path),{...opts,signal:controller.signal,headers:{Authorization:'Bearer '+secret,...(opts.body&&typeof opts.body==='string'?{'Content-Type':'application/json'}:{}),...opts.headers}});
 if(!r.ok){let message='请求失败 HTTP '+r.status;try{const d=await r.json();message=typeof d.detail==='string'?d.detail:message}catch{};throw new Error(message)}
 return opts.blob?await r.blob():await r.json();
 }finally{clearTimeout(timer);opts.signal?.removeEventListener('abort',abort)}
}
const json=(path,method,body)=>request(path,{method,body:JSON.stringify(body)});
function db(){return new Promise((resolve,reject)=>{const r=indexedDB.open('lune-cloud-cache',1);r.onupgradeneeded=()=>r.result.createObjectStore('rooms');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
async function cache(room,rows,limit=100){try{const d=await db(),tx=d.transaction('rooms','readwrite');tx.objectStore('rooms').put(rows.slice(-limit),owner+':'+room);tx.oncomplete=()=>d.close()}catch{}}
async function cached(room){try{const d=await db();return await new Promise(resolve=>{const r=d.transaction('rooms').objectStore('rooms').get(owner+':'+room);r.onsuccess=()=>{resolve(r.result||[]);d.close()};r.onerror=()=>{resolve([]);d.close()}})}catch{return []}}
function message(m){return {id:String(m.id),role:m.from==='human'?'user':(m.meta?.agent_id||'gpt'),text:m.text||'',ts:m.ts,kind:m.kind,meta:m.meta||{},time:m.meta?.date_unknown?'导入记录 · 日期未知':new Date(m.ts).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})}}
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
  if(m.type==='workspace'){emit('workspace',m);return}
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
 if(!secret){emit('status',preview?'界面预览 · 示例内容，未连接模型':'尚未连接 · 可查看本机资料');return}
 const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(config.base+'\0'+secret));
 owner=Array.from(new Uint8Array(bytes)).map(n=>n.toString(16).padStart(2,'0')).join('');
 emit('connected',{});
 for(const room of ['gpt','claude','group']){const rows=await cached(room);if(rows.length)emit('room',{room,messages:rows,cached:true})}
 try{await request('/lune/rooms')}catch(e){emit('status','服务器暂不可用 · 已显示本机缓存');throw e}realtime();
 await Promise.all(['gpt','claude','group'].map(room=>load(room).catch(e=>toast(e.message))));
 await memories();
}
async function memories(){const result=await request('/lune/memories');emit('memories',result.memories.map(m=>({...m,date:m.updated_at.slice(0,10)})));return result.memories}
function disconnect(){stopSpeech();epoch++;stream?.close();clearInterval(poll);secret='';sessionStorage.removeItem('lune-secret');localStorage.removeItem('lune-secret');drafts.clear();for(const u of blobUrls.values())URL.revokeObjectURL(u);blobUrls.clear();emit('disconnected',{});emit('status','已断开连接')}
function pending(){try{return JSON.parse(localStorage.getItem('lune-outbox-'+owner)||'[]')}catch{return []}}
function keepPending(m){const rows=pending().filter(x=>x.nonce!==m.nonce);rows.push({...m,status:'failed',time:'待核对发送状态'});localStorage.setItem('lune-outbox-'+owner,JSON.stringify(rows))}
function clearPending(nonce){localStorage.setItem('lune-outbox-'+owner,JSON.stringify(pending().filter(x=>x.nonce!==nonce)))}
async function media(att){
 const path=String(att.url||'');if(!/^\/[\w/-]*uploads\/[^/]+$/.test(path)||/[?#]/.test(path))throw new Error('附件来源无效');
 if(blobUrls.has(path))return blobUrls.get(path);
 const file=await request('/uploads/'+encodeURIComponent(path.split('/').pop()),{blob:true});const u=URL.createObjectURL(file);blobUrls.set(path,u);return u;
}
function stopSpeech(){speechEpoch++;speechController?.abort();speechController=null;const audio=$('#speechAudio');audio.pause();audio.removeAttribute('src');audio.load();if(speechUrl)URL.revokeObjectURL(speechUrl);speechUrl=null;$('#speechPlayback').hidden=true;$('#speechAudio').hidden=true;window.LuneRelay.audio=null}
async function tts(text){
 if(preview)throw new Error('界面预览不能合成语音，请连接正式服务器');
 if(window.LuneRelay.audio||speechController){stopSpeech();return}
 if(text.length>900)throw new Error('单次朗读最多 900 字符，请分段朗读');
 const ticket=++speechEpoch,audio=$('#speechAudio');speechController=new AbortController();$('#speechPlayback').hidden=false;$('#speechStatus').textContent='正在合成朗读…';audio.hidden=true;
 try{const blob=await request('/app/tts',{method:'POST',body:JSON.stringify({text}),blob:true,timeout:60000,signal:speechController.signal});if(ticket!==speechEpoch)return;speechController=null;
 speechUrl=URL.createObjectURL(blob);audio.src=speechUrl;audio.hidden=false;window.LuneRelay.audio=audio;$('#speechStatus').textContent='消息朗读';
 audio.onended=()=>{if(ticket===speechEpoch)stopSpeech()};audio.onerror=()=>{if(ticket===speechEpoch){stopSpeech();toast('音频未能播放，请重新点击朗读')}};
 try{await audio.play()}catch{if(ticket===speechEpoch)$('#speechStatus').textContent='音频已就绪，请点播放'}
 }catch(e){if(ticket===speechEpoch){stopSpeech();throw e}}
}
function paintSpeech(config){speechVersion=config.version;const f=$('#speechForm');f.elements.provider.value=config.provider;for(const [name,p]of Object.entries(config.providers))for(const key of ['key','voice_id','model','base_url','group_id']){const input=f.elements[name+'_'+key];if(!input)continue;if(key==='key'){input.value='';input.placeholder=p.key_set?'已保存；留空保持':'API Key'}else input.value=p[key]||''}speechProvider();$('#speechConfigStatus').textContent=Object.entries(config.providers).map(([n,p])=>(n==='minimax'?'MiniMax':'ElevenLabs')+' · '+(p.ready?'已配置，尚需实际试听':'待填写密钥与音色')).join(' / ')}
function speechProvider(){const name=$('#speechForm').elements.provider.value;document.querySelectorAll('[data-speech-provider]').forEach(e=>e.hidden=e.dataset.speechProvider!==name)}
async function speechSettings(){if(!preview&&secret)paintSpeech(await request('/lune/speech'))}
async function notify(){
 if(preview)throw new Error('界面预览不申请通知权限；请在正式应用中订阅');
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
 emit('settings-open',{});
 const dialog=$('#connectionDialog');$('#relayBase').value=config.base;$('#relaySecret').value='';$('#rememberConnection').checked=!!config.remember;if(!dialog.open)dialog.showModal();
 if(preview){$('#settingsStatus').textContent='当前为私人界面预览。模型、通知、MiniMax / ElevenLabs 朗读和 MCP 需部署正式服务后连接；请勿在这里填写密钥。生活页的本机保存可以实际使用。';document.querySelectorAll('#connectionForm input,#connectionForm button,#agent-gpt input,#agent-gpt textarea,#agent-gpt select,#agent-gpt button,#agent-claude input,#agent-claude textarea,#agent-claude select,#agent-claude button,#mcpForm input,#mcpForm button,#contextForm input,#contextForm select,#contextForm button,#speechForm input,#speechForm button').forEach(e=>e.disabled=true);return}
 if(!secret)return;
 try{await speechSettings()}catch(e){$('#speechConfigStatus').textContent=e.message}
 try{const {agents}=await request('/app/loop/agents');for(const name of ['gpt','claude']){
 const f=$('#agent-'+name);for(const key of ['url','model','persona','protocol'])f.elements[key].value=agents[name][key]||'';f.elements.key.placeholder=agents[name].key_set?'已保存；留空保持':'API Key';f.elements.key.value='';
 }emit('agents',agents);const cfg=await request('/app/loop/config');const f=$('#contextForm');for(const key of ['history_n','history_images','max_tool_steps','vision'])if(cfg[key]!==undefined)f.elements[key].value=cfg[key];await toolStatus()}catch(e){$('#settingsStatus').textContent=e.message}
}
async function toolStatus(){const r=await request('/app/loop/mcp');$('#toolStatus').textContent=r.available?'MCP 客户端已安装':'MCP 客户端未安装';const list=$('#mcpServerList');list.replaceChildren();for(const server of r.servers||[]){const row=document.createElement('div');row.className='mcp-item';const text=document.createElement('span');text.textContent=server.name;const status=document.createElement('small');status.textContent=server.status+' · '+(server.tools?.length||0)+' 个工具';text.append(status);row.append(text);for(const [label,action]of [['重连',()=>json('/app/loop/mcp/'+encodeURIComponent(server.name)+'/reconnect','POST',{})],['移除',()=>request('/app/loop/mcp/'+encodeURIComponent(server.name),{method:'DELETE'})]]){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=async()=>{try{await action();await toolStatus()}catch(e){toast(e.message)}};row.append(b)}list.append(row)}}
async function workspace(){try{const result=await request('/lune/workspace');cache('workspace',result.items,2000);return result.items}catch(e){const rows=await cached('workspace');if(rows.length)return rows;throw e}}
function wire(){
 $('#speechStop').onclick=stopSpeech;$('#speechForm').elements.provider.onchange=speechProvider;
 $('#speechForm').onsubmit=async e=>{e.preventDefault();if(!secret){toast('请先连接自己的服务器');return}const f=e.target,name=f.elements.provider.value,values={};for(const key of ['key','voice_id','model','base_url','group_id']){const input=f.elements[name+'_'+key];if(input)values[key]=input.value}try{const config=await json('/lune/speech','PATCH',{provider:name,version:speechVersion,providers:{[name]:values}});paintSpeech(config);toast('朗读设置已保存到服务器')}catch(err){toast(err.message)}};
 $('#speechTest').onclick=async()=>{if(preview){toast('此处仅预览朗读设置，不会提交语音请求');return}if(!secret){toast('请先连接自己的服务器');return}try{await tts('你好，这是 Luné 的朗读测试。');if(window.LuneRelay.audio){$('#settingsStatus').textContent='试听音频已就绪；如未自动播放，请关闭设置后点播放器。'}}catch(err){toast(err.message)}};

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
 $('#mcpForm').onsubmit=async e=>{e.preventDefault();const f=e.target;try{const auth=f.elements.authorization.value.trim();await json('/app/loop/mcp','POST',{name:f.elements.serverName.value,transport:'http',url:f.elements.url.value,headers:auth?{Authorization:auth}:{},enabled:true});f.elements.authorization.value='';await toolStatus();toast('工具服务器已保存')}catch(e){toast(e.message)}};
 $('#notificationButton').onclick=()=>notify().catch(e=>toast(e.message));
 $('#pushTestButton').onclick=()=>json('/app/push_test','POST',{}).then(()=>toast('已发起通知测试，请检查实际送达')).catch(e=>toast(e.message));
 $('#exportButton').onclick=async()=>{try{const data=secret?await request('/lune/export'):{format:'lune-local-v04',data:window.LuneApp.snapshot()};const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='Lune-backup-'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(e){toast(e.message)}};
 $('#importFile').onchange=async e=>{const file=e.target.files[0];e.target.value='';if(!file)return;if(file.size>20*1024*1024){toast('请选择 20 MB 内的 JSON 备份');return}
 try{const body=JSON.parse(await file.text());if(!confirm('导入会追加聊天与记忆，不覆盖现有数据。示例记忆会跳过。继续？'))return;
 if(secret){const r=await json('/lune/import','POST',body);toast(r.duplicate?'这份备份已导入':`已导入 ${r.messages} 条消息、${r.memories} 条记忆`);await connect()}else await window.LuneApp.importData(body);
 }catch(e){toast('导入失败：'+e.message)}};
 window.addEventListener('online',()=>{if(secret)realtime();sync()});document.addEventListener('visibilitychange',()=>{if(document.hidden){stream?.close();stream=null}else{if(secret)realtime();sync()}});
 navigator.serviceWorker?.addEventListener('message',e=>{if(e.data?.type==='backfill')sync()});
 if(!preview&&'serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>toast('离线缓存暂不可用，在线聊天不受影响'));
}
window.LuneRelay={get enabled(){return !!secret},get base(){return config.base},request,json,load,memories,media,tts,settings,connect,wire,pending,keepPending,clearPending,workspace,
 select(room){activeRoom=room;if(secret)load(room).catch(e=>toast(e.message))},
 send(room,text,attachments,nonce){return json(`/lune/rooms/${room}/send`,'POST',{text,attachments,nonce})},
 async upload(file){return request('/app/upload?name='+encodeURIComponent(file.name),{method:'POST',body:file,headers:{'Content-Type':file.type||'application/octet-stream'}})},
 stop(id){return json('/lune/runs/'+encodeURIComponent(id)+'/stop','POST',{})}
};
})();
