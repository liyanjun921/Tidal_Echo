/* Luné / Ourspace V0.3 — V0.4 UI, adapted to the Tidal Echo relay. */
(()=>{'use strict';
  const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
  const icon=(n)=>`<svg class="icon" aria-hidden="true"><use href="#i-${n}"/></svg>`;
  const DATA_KEY='lune-v03-data',PREF_KEY='lune-v03-preferences';
  const conversations={
    gpt:{name:'GPT',badge:'GPT',desc:'固定模型 · 独立记忆',preview:'一个安静、好用的小地方。',avatar:'gpt'},
    claude:{name:'Claude',badge:'CLAUDE',desc:'固定模型 · 独立记忆',preview:'我们可以从一个很小的想法开始。',avatar:'claude'},
    group:{name:'我们仨',badge:'GROUP',desc:'GPT + Claude + 你',preview:'那就先把聊天的感觉做好。',avatar:'group'}
  };
  const startingMessages={
    gpt:[
      {role:'user',text:'我想给我们做一个自己的聊天空间。',time:'21:07'},
      {role:'gpt',text:'好呀。那就先从一个安静、好用的小地方开始。\n\n背景可以换，记忆要留下。其他的，我们慢慢添。',time:'21:08'},
      {role:'user',text:'我想要很透的玻璃气泡，像水一样。',time:'21:09'},
      {role:'gpt',text:'收到。这次先把玻璃的质感做对，让聊天本身轻一点。 ✳',time:'21:09'}
    ],
    claude:[
      {role:'user',text:'我们以后也会有一本自己的记忆手账。',time:'20:41'},
      {role:'claude',text:'我喜欢这个想法。把值得留下的部分慢慢整理好，而不是一开始就替它们定义意义。',time:'20:42'},
      {role:'user',text:'不用急着给彼此写人设。',time:'20:43'},
      {role:'claude',text:'那我们就从真实的对话开始，让熟悉感一点点积累。',time:'20:44'}
    ],
    group:[
      {role:'user',text:'我把 GPT 和 Claude 拉进同一个群了。',time:'19:18'},
      {role:'gpt',text:'群聊创建成功。先说好，我们可没有统一的标准答案。',time:'19:19'},
      {role:'claude',text:'有不同的想法应该会更有趣。我想先听听你准备拿这个空间做什么。',time:'19:20'},
      {role:'user',text:'先聊天！以后再一起读书听歌。',time:'19:20'},
      {role:'gpt',text:'那就先把聊天的感觉做好。 ✳',time:'19:21'}
    ]
  };
  const startingMemories=[
    {id:'demo1',scope:'shared',title:'一个可以长期停留的空间',content:'想做一个自己的多 AI 聊天前端，先能好好聊天，未来再慢慢加入听歌、读书和生活工具。',date:'2026.10.18',demo:true},
    {id:'demo2',scope:'gpt',title:'先让关系自然形成',content:'希望 GPT 保留自己的模型特点，不提前写固定人设；通过持续的真实聊天积累称呼和默契。',date:'2026.10.18',demo:true},
    {id:'demo3',scope:'claude',title:'慢慢认识，而不是预先定义',content:'希望 Claude 也拥有独立的会话和记忆，不需要预设人格设定，让交流自然发展。',date:'2026.10.18',demo:true},
    {id:'demo4',scope:'group',title:'三个人的共同聊天室',content:'GPT、Claude 和你在同一处聊天，但每个人仍保有自己的独立记忆。群聊拥有自己的共同记录。',date:'2026.10.18',demo:true},
    {id:'demo5',scope:'shared',title:'喜欢的界面质感',content:'清透的 iOS 液态玻璃、柔和的水光、低饱和韩系 INS 风。希望气泡圆润、可以随时换壁纸与 UI。',date:'2026.10.18',demo:true}
  ];
  const defaultData={messages:{gpt:[],claude:[],group:[]},memories:[]};
  const relay=window.LuneRelay;let files=[],sourceMessage=null;const runs={};
  function loadObj(key,fallback){try{let v=JSON.parse(localStorage.getItem(key));return v&&typeof v==='object'?v:structuredClone(fallback)}catch{return JSON.parse(JSON.stringify(fallback))}}
  const data=loadObj(DATA_KEY,defaultData);
  if(!data.messages||typeof data.messages!=='object')data.messages={};
  if(!Array.isArray(data.memories))data.memories=[];
  for(const k of Object.keys(conversations)){if(!Array.isArray(data.messages[k]))data.messages[k]=[]}
  const prefs=loadObj(PREF_KEY,{theme:'water',glass:16});
  let selectedChat='gpt',memoryFilter='all',screen=window.innerWidth<=700?'home':'chat',editingId=null,replyTimer=null,toastTimer=null,customWallpaperUrl=null;
  const saveData=()=>{if(relay.enabled)return;try{localStorage.setItem(DATA_KEY,JSON.stringify(data))}catch{toast('本地存储空间不足，请导出数据后清理浏览器')}};
  const savePrefs=()=>{try{localStorage.setItem(PREF_KEY,JSON.stringify(prefs))}catch{}};
  function toast(msg){if($('#connectionDialog').open)$('#settingsStatus').textContent=msg;const el=$('#toast');el.textContent=msg;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),2800)}
  function isMobile(){return window.matchMedia('(max-width:700px)').matches}
  function avatarClass(who){return who==='gpt'?'avatar-gpt':who==='claude'?'avatar-claude':'avatar-group'}
  const lastMessage=(id)=>data.messages[id]?.at(-1)?.text?.replace(/\s+/g,' ').slice(0,50)||conversations[id].preview;
  function renderConversations(){
    const sidebar=$('#sidebarChats'),mobile=$('#homeChats');sidebar.replaceChildren();mobile.replaceChildren();
    for(const [id,info] of Object.entries(conversations)){
      const btn=document.createElement('button');btn.type='button';btn.className='conversation'+(screen==='chat'&&selectedChat===id?' active':'');btn.innerHTML=`<div class="avatar ${avatarClass(id)}"></div><div class="conversation-main"><div class="conversation-titleline"><span class="conversation-title">${info.name}</span><span class="conversation-time"></span></div><div class="conversation-desc"></div><span class="conversation-model">${info.badge} / PRIVATE SPACE</span></div>`;
      $('.conversation-desc',btn).textContent=lastMessage(id);btn.addEventListener('click',()=>openChat(id));sidebar.append(btn);
      const mob=document.createElement('button');mob.type='button';mob.className='home-conversation';mob.innerHTML=`<div class="avatar ${avatarClass(id)}"></div><div class="conversation-main"><div class="conversation-titleline"><span class="conversation-title">${info.name}</span><span class="conversation-time">${data.messages[id]?.at(-1)?.time||'尚无消息'}</span></div><div class="conversation-desc"></div><span class="conversation-model">${info.desc}</span></div>${icon('chevron-right')}`;
      $('.conversation-desc',mob).textContent=lastMessage(id);mob.addEventListener('click',()=>openChat(id));mobile.append(mob);
    }
    filterConversations();
  }
  function filterConversations(){const q=($('#sidebarSearch').value||$('#mobileSearch').value||'').trim().toLocaleLowerCase();for(const button of $$('.conversation,.home-conversation'))button.hidden=!!q&&!button.textContent.toLowerCase().includes(q)}
  function setScreen(name){screen=name;document.body.dataset.screen=name;for(const section of $$('.screen'))section.hidden=section.id!==({home:'homeScreen',chat:'chatScreen',memory:'memoryScreen',themes:'themesScreen'}[name]);$$('[data-nav]').forEach(el=>el.classList.toggle('active',el.dataset.nav===name||name==='chat'&&el.dataset.nav==='home'));$('#mobileDock').hidden=isMobile()&&name==='chat';renderConversations();if(name==='memory')renderMemories();if(name==='themes')renderThemes()}
  function openChat(id){selectedChat=id;$('#headerName').textContent=conversations[id].name;$('#headerDetail').textContent=id==='group'?'共同聊天室 · GPT + Claude':conversations[id].desc;$('#modelTag').textContent=conversations[id].badge;$('#headerAvatar').className='header-avatar '+avatarClass(id);setScreen('chat');renderMessages();$('#messageInput').placeholder=id==='group'?'发消息…':`给 ${conversations[id].name} 发消息…`;relay.select(id);paintRun()}
  function renderMessages(force=false){
    const area=$('#chatArea'),oldTop=area.scrollTop,stick=force||area.scrollHeight-area.scrollTop-area.clientHeight<140;
    const stream=$('#chatStream');stream.replaceChildren();const msgs=data.messages[selectedChat]||[];
    if(!msgs.length){const hint=document.createElement('p');hint.className='empty-memories';hint.textContent=relay.enabled?'在这里，开始一段真实的对话。':'点击右上角设置，连接自己的聊天服务器。原有本机资料可以先导出备份。';stream.append(hint)}
    msgs.forEach(m=>{
      const isUser=m.role==='user',row=document.createElement('div');row.className='msg-row '+(isUser?'user':'ai');row.dataset.messageId=m.id||'';
      if(!isUser){const a=document.createElement('div');a.className='msg-avatar '+avatarClass(m.role);row.append(a)}
      const unit=document.createElement('div');unit.className='msg-unit';
      if(!isUser&&selectedChat==='group'){const name=document.createElement('div');name.className='msg-name';name.textContent=conversations[m.role]?.name||m.role;unit.append(name)}
      const bubble=document.createElement('div');bubble.className='message-bubble';bubble.textContent=m.text;unit.append(bubble);
      for(const att of m.meta?.attachments||[]){const box=document.createElement('div');box.className='message-attachment';const button=document.createElement('button');button.type='button';button.textContent=att.name||'附件';box.append(button);button.onclick=async()=>{try{const u=await relay.media(att),a=document.createElement('a');a.href=u;a.download=att.name||'attachment';a.click()}catch(e){toast(e.message)}};
        if(String(att.mime||'').startsWith('image/')){const img=document.createElement('img');img.alt=att.name||'上传的图片';img.loading='lazy';box.prepend(img);relay.media(att).then(u=>img.src=u).catch(()=>img.alt='图片暂不可用')}
        unit.append(box);
      }
      const t=document.createElement('div');t.className='msg-time';t.textContent=m.time||'旧版记录 · 日期未知';unit.append(t);
      if(m.kind==='act'){const detail=document.createElement('details'),summary=document.createElement('summary');summary.textContent='工具执行记录';detail.append(summary);const pre=document.createElement('pre');pre.textContent=JSON.stringify(m.meta?.steps||[],null,2);detail.append(pre);unit.append(detail)}
      if(relay.enabled&&m.kind!=='stream'&&m.kind!=='act'){
        const action=document.createElement('button');action.type='button';action.className='message-action';action.textContent=isUser?'记住这句话':'朗读 / 停止';
        action.onclick=()=>isUser?openMemoryFromMessage(m):relay.tts(m.text).catch(e=>toast(e.message));unit.append(action);
      }
      if(m.status==='failed'){const retry=document.createElement('button');retry.className='message-action';retry.textContent='核对并重试发送';retry.onclick=()=>submitRemote(m);unit.append(retry)}
      row.append(unit);stream.append(row);
    });
    requestAnimationFrame(()=>{area.scrollTop=stick?area.scrollHeight:oldTop});
  }
  function mergeMessage(room,m,paint=true){if(m.meta?.nonce){relay.clearPending(m.meta.nonce);data.messages[room]=data.messages[room].filter(x=>x.nonce!==m.meta.nonce)}const list=data.messages[room],i=list.findIndex(x=>String(x.id)===String(m.id));if(i>=0)list[i]=m;else list.push(m);list.sort((a,b)=>{const an=Number(a.id),bn=Number(b.id);if(!Number.isFinite(an)&&!Number.isFinite(bn))return 0;if(!Number.isFinite(an))return 1;if(!Number.isFinite(bn))return -1;return an-bn});if(paint){if(room===selectedChat)renderMessages();renderConversations()}}
  function paintRun(){const el=$('#runStatus');el.replaceChildren();const r=runs[selectedChat];if(!r)return;
    const label=document.createElement('span');label.textContent=({pending:'消息已保存，正在排队…',running:'正在回复…',completed:'',failed:r.error,interrupted:r.error,cancelled:'已停止等待；已执行操作不会撤销'})[r.state]||'';el.append(label);
    if(r.id&&['pending','running'].includes(r.state)){const b=document.createElement('button');b.type='button';b.textContent='停止等待';b.onclick=()=>relay.stop(r.id).then(result=>{runs[selectedChat]=result.run;paintRun()}).catch(e=>toast(e.message));el.append(b)}
  }
  async function submitRemote(m){const room=m.room||selectedChat;try{relay.keepPending(m);const r=await relay.send(room,m.text,m.meta?.attachments||[],m.nonce);relay.clearPending(m.nonce);data.messages[room]=data.messages[room].filter(x=>x.id!==m.id);runs[room]=r.run;await relay.load(room,{quiet:true});paintRun()}catch(e){m.status='failed';if(!runs[room]?.id)runs[room]={state:'failed',error:'发送未确认，请核对并重试'};toast(e.message);if(room===selectedChat){paintRun();renderMessages()}}}
  async function sendMessage(text){
    if(!relay.enabled){toast('先连接自己的服务器，再开始 AI 对话');relay.settings();return}
    const room=selectedChat;if(['pending','running'].includes(runs[room]?.state)){toast('本会话仍在回复，可以先停止等待');return}
    const nonce=crypto.randomUUID(),m={id:'pending-'+nonce,nonce,room,role:'user',text,meta:{attachments:files.slice()},time:'正在发送…',status:'sending'};
    runs[room]={state:'pending'};data.messages[room].push(m);$('#messageInput').value='';$('#messageInput').style.height='auto';files=[];paintFiles();paintRun();renderMessages(true);await submitRemote(m);
  }
  function paintFiles(){const el=$('#pendingFiles');el.replaceChildren();files.forEach((f,i)=>{const b=document.createElement('button');b.type='button';b.textContent=(f.name||'附件')+' ×';b.onclick=()=>{files.splice(i,1);paintFiles()};el.append(b)})}
  function openMemoryFromMessage(m){openMemoryModal();$('#memoryForm').elements.content.value=m.text;$('#memoryForm').elements.title.value=m.text.slice(0,40);$('#memoryForm').elements.scope.value=selectedChat;$('#memoryForm').elements.source_message_id.value=m.id;sourceMessage=Number(m.id)}
  const scopeTitles={shared:'共享记忆',gpt:'GPT 私有',claude:'Claude 私有',group:'群聊共同'};
  function renderMemories(){const grid=$('#memoryGrid');grid.replaceChildren();const filtered=data.memories.filter(m=>memoryFilter==='all'||m.scope===memoryFilter);
    if(!filtered.length){grid.innerHTML='<div class="empty-memories">还没有这类记忆。可以自己添加第一条。</div>';return}
    filtered.forEach((m,n)=>{
      const card=document.createElement('button');card.className='memory-card';card.type='button';card.innerHTML=`<div class="memory-card-top"><div class="memory-scope"><i></i><span></span></div><span class="memory-index">NO. ${String(n+1).padStart(2,'0')}</span></div><h3 class="memory-title"></h3><p class="memory-excerpt"></p><div class="memory-bottom"><span class="memory-date"></span><span class="memory-open">编辑记忆 ↗</span></div>`;
      $('.memory-scope span',card).textContent=scopeTitles[m.scope]||'个人记忆';$('.memory-title',card).textContent=m.title;$('.memory-excerpt',card).textContent=m.content;$('.memory-date',card).textContent=(m.date||'')+(m.demo?' · 示例':'');card.addEventListener('click',()=>openMemoryModal(m.id));grid.append(card)
    })}
  const themeInfo=[{id:'water',title:'Water Light',sub:'清透水光 · 默认'},{id:'lily',title:'Lily Day',sub:'百合浮水 · 晴日'},{id:'pearl',title:'Pearl Mist',sub:'珍珠薄雾 · 柔白'}];
  function setTheme(name){prefs.theme=name;document.body.dataset.theme=name; if(name!=='custom'){document.documentElement.style.setProperty('--water-img','url('+({water:"'assets/water-light.webp'",lily:"'assets/lily-water.webp'",pearl:"'assets/water-light.webp'"}[name])+')')}if(name==='pearl')document.documentElement.style.setProperty('--water-img','linear-gradient(125deg,#dbe9f2 0%,#f7f9fb 39%,#e3eef4 78%,#dcebf0 100%)');if(name==='custom'&&customWallpaperUrl){document.documentElement.style.setProperty('--water-img',`url("${customWallpaperUrl}")`)}savePrefs();renderThemes()}
  function renderThemes(){const gallery=$('#themeGallery');gallery.replaceChildren();for(const t of themeInfo){const btn=document.createElement('button');btn.type='button';btn.className='theme-card'+(prefs.theme===t.id?' selected':'');btn.innerHTML=`<div class="theme-cover ${t.id}"></div><div class="theme-card-foot"><div><strong>${t.title}</strong><small>${t.sub}</small></div><span class="theme-select-ring">${prefs.theme===t.id?icon('check'):''}</span></div>`;btn.addEventListener('click',()=>{setTheme(t.id);toast(`已切换到 ${t.title}`)});gallery.append(btn)}$('#glassSlider').value=prefs.glass;$('#glassValue').textContent=prefs.glass+'%'}
  function setGlass(n){n=Number(n);if(!Number.isFinite(n))return;prefs.glass=Math.max(5,Math.min(35,n));document.documentElement.style.setProperty('--bubble-alpha',(prefs.glass/100).toFixed(2));$('#glassValue').textContent=prefs.glass+'%';savePrefs()}
  function openMemoryModal(id=null){editingId=id;const m=data.memories.find(x=>x.id===id);$('#modalTitle').textContent=m?'编辑记忆':'新建记忆';$('#modalDesc').textContent=relay.enabled?'保存到服务器；模型只会读取获准范围内的相关记忆。':'保存在本机浏览器。连接后可通过导入迁移。';const form=$('#memoryForm');form.reset();if(m){form.elements.title.value=m.title;form.elements.content.value=m.content;form.elements.scope.value=m.scope;form.elements.source_message_id.value=m.source_message_id||''}$('#modalOverlay').hidden=false;$('.modal-submit').firstChild.textContent=m?'保存修改 ':'保存到本地手账 ';const old=$('#deleteMemoryButton');old?.remove();if(m){const del=document.createElement('button');del.type='button';del.id='deleteMemoryButton';del.textContent='删除这条记忆';del.style.cssText='color:#967e89;border:0;background:transparent;padding:10px;font-size:12px;';del.addEventListener('click',async()=>{if(confirm('确定要删除这条记忆吗？')){try{if(relay.enabled){await relay.request('/lune/memories/'+encodeURIComponent(id)+'?version='+m.version,{method:'DELETE'});await relay.memories()}else{data.memories=data.memories.filter(x=>x.id!==id);saveData()}closeModal();renderMemories();toast('记忆已删除')}catch(e){toast(e.message)}}});form.append(del)}setTimeout(()=>form.elements.title.focus(),80)}
  function closeModal(){$('#modalOverlay').hidden=true;editingId=null}
  function wire(){
    $$('#sidebarSearch,#mobileSearch').forEach(i=>i.addEventListener('input',e=>{const other=e.target.id==='mobileSearch'?$('#sidebarSearch'):$('#mobileSearch');other.value=e.target.value;filterConversations()}));
    $('#chatForm').addEventListener('submit',e=>{e.preventDefault();const text=$('#messageInput').value.trim();if(text||files.length)sendMessage(text)});
    $('#messageInput').addEventListener('input',e=>{e.target.style.height='auto';e.target.style.height=Math.min(e.target.scrollHeight,130)+'px'});
    $('#messageInput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#chatForm').requestSubmit()}});
    $('#backToHome').addEventListener('click',()=>setScreen(isMobile()?'home':'chat'));

    $$('[data-nav]').forEach(b=>b.addEventListener('click',()=>setScreen(b.dataset.nav)));

    $('#composerPlus').addEventListener('click',()=>{if(relay.enabled)$('#attachmentInput').click();else relay.settings()});
    $('#micButton').addEventListener('click',startVoice);
    $$('#memoryFilters [data-filter]').forEach(b=>b.addEventListener('click',()=>{memoryFilter=b.dataset.filter;$$('#memoryFilters .filter').forEach(x=>x.classList.toggle('active',x===b));renderMemories()}));
    $('#newMemoryButton').addEventListener('click',()=>openMemoryModal());
    $('#closeModal').addEventListener('click',closeModal);$('#modalOverlay').addEventListener('click',e=>{if(e.target.id==='modalOverlay')closeModal()});
    window.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();if(isMobile()){setScreen('home');$('#mobileSearch').focus()}else $('#sidebarSearch').focus()}});
    $('#memoryForm').addEventListener('submit',async e=>{e.preventDefault();const f=e.target,title=f.elements.title.value.trim(),content=f.elements.content.value.trim(),scope=f.elements.scope.value;if(!title||!content)return;
      const previous=data.memories.find(x=>x.id===editingId),source=Number(f.elements.source_message_id.value)||null;
      try{if(relay.enabled){await relay.json('/lune/memories'+(previous?'/'+encodeURIComponent(previous.id):''),previous?'PATCH':'POST',{title,content,scope,source_message_id:source,version:previous?.version});await relay.memories()}else{if(previous)Object.assign(previous,{title,content,scope});else data.memories.unshift({id:crypto.randomUUID(),title,content,scope,date:new Date().toLocaleDateString('zh-CN'),demo:false});saveData()}
      closeModal();renderMemories();toast(relay.enabled?'已保存到服务器记忆手账':'已保存到本机手账')}catch(e){toast(e.message)}
    });
    $('#attachmentInput').onchange=async e=>{const selected=[...e.target.files];e.target.value='';for(const file of selected){if(files.length>=8){toast('每条消息最多 8 个附件');break}if(file.size>10*1024*1024){toast(file.name+' 超过 10 MB');continue}try{files.push(await relay.upload(file));paintFiles()}catch(e){toast(e.message)}}};
    $('#olderMessages').onclick=async()=>{const ids=data.messages[selectedChat].map(m=>Number(m.id)).filter(Number.isFinite);if(!ids.length)return;const area=$('#chatArea'),height=area.scrollHeight;try{await relay.load(selectedChat,{before:Math.min(...ids)});requestAnimationFrame(()=>area.scrollTop=area.scrollHeight-height)}catch(e){toast(e.message)}};
    $('#glassSlider').addEventListener('input',e=>setGlass(e.target.value));
    $('#wallpaperInput').addEventListener('change',async e=>{const file=e.target.files?.[0];if(!file)return;if(file.size>16*1024*1024){toast('请上传 16 MB 以内的图片');return}
      if(customWallpaperUrl)URL.revokeObjectURL(customWallpaperUrl);customWallpaperUrl=URL.createObjectURL(file);prefs.theme='custom';document.body.dataset.theme='custom';document.documentElement.style.setProperty('--water-img',`url("${customWallpaperUrl}")`);savePrefs();renderThemes();toast('自定义壁纸已应用，尝试保存到当前设备…');try{await storeWallpaper(file);toast('壁纸已保存到本机浏览器')}catch{toast('壁纸已应用；此浏览器可能不支持长期本地保存')}});
    let wasMobile=isMobile();window.addEventListener('resize',()=>{let now=isMobile();if(now!==wasMobile){wasMobile=now;if(now&&screen==='chat')setScreen('home');else if(!now&&screen==='home')openChat(selectedChat)}})
  }
  function storeWallpaper(blob){return new Promise((resolve,reject)=>{if(!('indexedDB'in window))return reject();const req=indexedDB.open('lune-ui-assets',1);req.onupgradeneeded=()=>req.result.createObjectStore('files');req.onerror=()=>reject(req.error);req.onsuccess=()=>{const db=req.result;const tx=db.transaction('files','readwrite');tx.objectStore('files').put(blob,'custom-wallpaper');tx.oncomplete=()=>{db.close();resolve()};tx.onerror=()=>reject(tx.error)}})}
  function recoverWallpaper(){return new Promise((resolve)=>{if(!('indexedDB'in window))return resolve();const req=indexedDB.open('lune-ui-assets',1);req.onupgradeneeded=()=>req.result.createObjectStore('files');req.onerror=()=>resolve();req.onsuccess=()=>{const db=req.result,tx=db.transaction('files','readonly'),g=tx.objectStore('files').get('custom-wallpaper');g.onsuccess=()=>{if(g.result){customWallpaperUrl=URL.createObjectURL(g.result);if(prefs.theme==='custom')setTheme('custom')}resolve();db.close()};g.onerror=()=>{resolve();db.close()}}})}
  function startVoice(){const Speech=window.SpeechRecognition||window.webkitSpeechRecognition;if(!Speech){toast('当前浏览器未提供语音转文字，请使用键盘听写');return}const recognition=new Speech();recognition.lang='zh-CN';recognition.interimResults=false;recognition.onresult=e=>{$('#messageInput').value=e.results[0][0].transcript;toast('已转成文字，确认后发送')};recognition.onerror=()=>toast('语音识别未完成，请检查麦克风权限');recognition.start();toast('正在听，请说话…')}
  window.LuneApp={snapshot:()=>JSON.parse(JSON.stringify(data)),async importData(body){const src=body.data||body;if(!['lune-v03','lune-local-v04'].includes(body.format)||!src.messages||!Array.isArray(src.memories))throw new Error('不是可识别的本机备份');const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(body)));const digest=Array.from(new Uint8Array(bytes)).join('-');data.imports=data.imports||[];if(data.imports.includes(digest)){toast('这份备份已导入');return}for(const room of Object.keys(conversations)){const rows=src.messages[room]||[];if(!Array.isArray(rows)||rows.some(m=>!['user','gpt','claude'].includes(m.role)||typeof m.text!=='string'||m.text.length>100000))throw new Error('消息格式不正确')}const valid=src.memories.filter(m=>!m.demo);if(valid.some(m=>!scopeTitles[m.scope]||typeof m.title!=='string'||typeof m.content!=='string'))throw new Error('记忆格式不正确');for(const room of Object.keys(conversations))data.messages[room].push(...(src.messages[room]||[]).map(m=>({id:crypto.randomUUID(),role:m.role,text:m.text,ts:m.ts,time:m.time})));data.memories.push(...valid.map(m=>({...m,id:crypto.randomUUID()})));data.imports.push(digest);saveData();renderMessages();renderMemories();renderConversations();toast('本机资料已合并保存')}};
  window.addEventListener('lune-notice',e=>toast(e.detail));
  window.addEventListener('lune-status',e=>$('#connectionStatus').textContent=e.detail);
  window.addEventListener('lune-connected',()=>{for(const room of Object.keys(conversations)){data.messages[room]=[];delete runs[room]}for(const m of relay.pending())if(data.messages[m.room])data.messages[m.room].push(m);data.memories=[];renderMessages();renderMemories();renderConversations()});
  window.addEventListener('lune-disconnected',()=>{const local=loadObj(DATA_KEY,defaultData);Object.assign(data,local);for(const room of Object.keys(conversations))if(!Array.isArray(data.messages[room]))data.messages[room]=[];renderMessages();renderMemories();renderConversations()});
  window.addEventListener('lune-room',e=>{const {room,messages,hasMore,runs:recent}=e.detail;for(const m of messages)mergeMessage(room,m,false);if(recent?.length){runs[room]=recent[0];if(!['pending','running'].includes(recent[0].state))data.messages[room]=data.messages[room].filter(m=>m.kind!=='stream')}if(room===selectedChat){if(hasMore!==undefined)$('#olderMessages').hidden=!hasMore;paintRun();renderMessages()}renderConversations()});
  window.addEventListener('lune-message',e=>mergeMessage(e.detail.room,e.detail.message));
  window.addEventListener('lune-draft',e=>mergeMessage(e.detail.room,e.detail.message));
  window.addEventListener('lune-draft-remove',e=>{data.messages[e.detail.room]=data.messages[e.detail.room].filter(m=>m.id!==e.detail.id)});
  window.addEventListener('lune-memories',e=>{data.memories=e.detail;renderMemories()});
  function init(){
    const viewport=()=>document.documentElement.style.setProperty('--lune-viewport',(window.visualViewport?.height||window.innerHeight)+'px');viewport();window.visualViewport?.addEventListener('resize',viewport);
    wire();relay.wire();setGlass(prefs.glass||16);if(['water','lily','pearl'].includes(prefs.theme))setTheme(prefs.theme);else {document.body.dataset.theme='water';prefs.theme='custom';recoverWallpaper()};
    renderConversations();renderMemories();renderThemes();openChat('gpt');if(isMobile())setScreen('home');relay.connect().catch(e=>toast(e.message));
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
