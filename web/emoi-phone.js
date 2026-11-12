/* Émoi UI modes · independent original phone shell.
   Float was inspected for high-level UX only; no code/assets are reused.
   A phone-mode contact is a local design-stage profile, never a connected agent.
*/
(()=>{
'use strict';
const MODE_KEY='emoi-ui-mode-v1';
const CONTACTS_KEY='emoi-ui-contacts-v1';
const GROUPS_KEY='emoi-ui-groups-v1';
const phone=document.getElementById('emoiPhone');
if(!phone)return;
const $=(s,r=document)=>r.querySelector(s);
const icoPaths={
  chat:'<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5 9 9 0 0 1-4-.95L3 21l1.95-5a9 9 0 1 1 16.05-4.5Z"/>',
  contacts:'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  memory:'<path d="M12 3a9 9 0 1 0 9 9"/><path d="M12 3v6h6M7.5 14a5 5 0 0 0 9 2"/><path d="M12 11v4"/>',
  reading:'<path d="M12 6C9 4 5 4 3 5v14c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1Zm0 0v14"/>',
  journal:'<path d="M6 3h12v18H6zM9 7h6M9 11h6M9 15h3"/><path d="M4 7v2M4 12v2"/>',
  calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18m-13 4h3m4 0h2m-9 4h3"/>',
  cinema:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 9h18M8 5l3 4m4-4 3 4M9 13v5l5-2.5z"/>',
  checklist:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m6 10 2 2 3-4m3 2h4m-12 6 2 2 3-4m3 2h4"/>',
  room:'<path d="m3 11 9-8 9 8v10H3zM9 21v-7h6v7"/>',
  settings:'<path d="M12 2.5v3m0 13v3M2.5 12h3m13 0h3m-16-6 2.2 2.2m10.6 10.6 2.2 2.2m0-15-2.2 2.2M8.7 15.3l-2.2 2.2"/><circle cx="12" cy="12" r="4"/>',
  more:'<circle cx="6" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18" cy="12" r="1.6"/>',
  photo:'<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.2" cy="8.5" r="1.4"/><path d="m3.5 17 5.4-5 3.4 3.2 3-3 5.2 5.2"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/>',
  back:'<path d="m15 18-6-6 6-6"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  right:'<path d="m9 5 7 7-7 7"/>',
  x:'<path d="M5 5l14 14M19 5 5 19"/>',
  moon:'<path d="M20 16a8 8 0 0 1-12-11A8 8 0 1 0 20 16Z"/>',
  sparkle:'<path d="m12 2 2.7 7.3L22 12l-7.3 2.7L12 22l-2.7-7.3L2 12l7.3-2.7Z"/>',
  bookcase:'<path d="M4 3v18m0-18h4v18H4zm7 2h4v16h-4zm7-2h3v18h-3z"/>',
  connect:'<path d="M8 16 5 19a4 4 0 0 1-6-6l6-6a4 4 0 0 1 6 0m2 1 3-3a4 4 0 0 1 6 6l-6 6a4 4 0 0 1-6 0"/>',
  shield:'<path d="M12 2 4 5v6c0 5 3.2 8.4 8 11 4.8-2.6 8-6 8-11V5z"/><path d="m9 12 2 2 4-4"/>',
  switch:'<rect x="3" y="7" width="18" height="11" rx="5.5"/><circle cx="8.5" cy="12.5" r="3"/>'
};
const icon=name=>'<svg viewBox="0 0 24 24" role="presentation" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+(icoPaths[name]||icoPaths.more)+'</svg>';
const launcherGlyphs={
 chat:'<path d="M12 3.5c-5.1 0-9.2 3.4-9.2 7.9 0 2.4 1.2 4.5 3.3 5.9l-.7 3.1 3.9-1.8c.9.3 1.8.4 2.7.4 5.1 0 9.2-3.4 9.2-7.6 0-4.5-4.1-7.9-9.2-7.9Z"/>',
 contacts:'<circle cx="12" cy="7.4" r="4"/><path d="M4.1 19.5c0-4 3.4-6.8 7.9-6.8s7.9 2.8 7.9 6.8c0 .8-.5 1.2-1.4 1.2h-13c-.9 0-1.4-.4-1.4-1.2Z"/>',
 reading:'<path d="M2.8 5.4c3.3-1 6.4-.5 8.4 1v13.3c-2.5-1.6-5.4-2-8.4-1.1Zm18.4 0c-3.3-1-6.4-.5-8.4 1v13.3c2.5-1.6 5.4-2 8.4-1.1Z"/>',
 more:'<circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/>',
 room:'<path d="m2 11 9.2-8a1.2 1.2 0 0 1 1.6 0l9.2 8-1.8 2-1.2-1v7.5a1 1 0 0 1-1 1h-3.5v-6h-5v6H6a1 1 0 0 1-1-1V12l-1.2 1Z"/>'
};
function homeIcon(name){
 const glyph=launcherGlyphs[name];
 return glyph?'<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">'+glyph+'</svg>':icon(name);
}
const apps=[
 {id:'chat',label:'信息',icon:'chat',tone:'sky'},
 {id:'contacts',label:'通讯录',icon:'contacts',tone:'stone'},
 {id:'memory',label:'记忆',icon:'memory',tone:'lilac'},
 {id:'reading',label:'共读',icon:'reading',tone:'mint'},
 {id:'journal',label:'日记',icon:'journal',tone:'cream'},
 {id:'calendar',label:'日历',icon:'calendar',tone:'rose'},
 {id:'cinema',label:'影院',icon:'cinema',tone:'night'},
 {id:'room',label:'Room',icon:'room',tone:'ocean'},
 {id:'checklist',label:'清单',icon:'checklist',tone:'warm'},
 {id:'more',label:'更多',icon:'more',tone:'silver'},
 {id:'settings',label:'设置',icon:'settings',tone:'blue'}
];
const dockIds=['chat','contacts','more','settings'];
function safeRead(key){
 try{const value=JSON.parse(localStorage.getItem(key));return Array.isArray(value)?value:[];}catch{return [];}
}
let contacts=safeRead(CONTACTS_KEY).filter(x=>x&&typeof x.id==='string'&&typeof x.name==='string');
let groups=safeRead(GROUPS_KEY).filter(x=>x&&typeof x.id==='string'&&typeof x.name==='string');
const remote={direct:new Map()};
const modelInactive='尚未绑定独立模型';
async function remoteSaveContact(person,isNew){
 if(!window.EmoiRelay?.enabled)return;
 try{
   const path=isNew?'/emoi/v2/contacts':'/emoi/v2/contacts/'+encodeURIComponent(person.id);
   const payload={id:person.id,name:person.name,notes:person.notes||'',model_route:person.model_route||''};
   const data=await window.EmoiRelay.json(path,isNew?'POST':'PATCH',payload);
   if(data.contact)Object.assign(person,{memory_namespace:data.contact.memory_namespace,desire_namespace:data.contact.desire_namespace});
   if(data.conversation_id)remote.direct.set(person.id,data.conversation_id);
   save(CONTACTS_KEY,contacts);
 }catch(e){console.warn('Émoi 联系人同步未完成：',e.message)}
}
async function remoteSaveGroup(group,isNew){
 if(!window.EmoiRelay?.enabled)return;
 try{
   const path=isNew?'/emoi/v2/conversations':'/emoi/v2/conversations/'+encodeURIComponent(group.id);
   await window.EmoiRelay.json(path,isNew?'POST':'PATCH',{id:group.id,title:group.name,kind:'group',members:group.members});
   group.remote=true;save(GROUPS_KEY,groups)
 }catch(e){console.warn('Émoi 群聊草稿同步未完成：',e.message)}
}
async function syncRemote(){
 if(!window.EmoiRelay?.enabled)return;
 try{
  const [people,rooms]=await Promise.all([
    window.EmoiRelay.request('/emoi/v2/contacts'),window.EmoiRelay.request('/emoi/v2/conversations')
  ]);
  const onServer=new Map((people.contacts||[]).map(x=>[x.id,x]));
  // Keep any local work, including unsynced files. Never replace by name.
  for(const c of contacts){
    if(!onServer.has(c.id))await remoteSaveContact(c,true);
  }
  for(const item of (people.contacts||[])){
   const local=contacts.find(c=>c.id===item.id);
   if(local)Object.assign(local,{memory_namespace:item.memory_namespace,desire_namespace:item.desire_namespace});
   else contacts.push({id:item.id,name:item.name,notes:item.notes||'',model_route:item.model_route||'',memory_namespace:item.memory_namespace,desire_namespace:item.desire_namespace});
  }
  save(CONTACTS_KEY,contacts);
  for(const conv of rooms.conversations||[]){
    if(conv.kind==='direct')for(const id of conv.members||[])remote.direct.set(id,conv.id);
    if(conv.kind==='group'&&!groups.some(g=>g.id===conv.id))groups.push({id:conv.id,name:conv.title,members:conv.members||[],remote:true});
  }
  for(const g of groups){if(!(rooms.conversations||[]).some(c=>c.id===g.id))await remoteSaveGroup(g,true)}
  save(GROUPS_KEY,groups);
  if(screen==='messages')openMessages();
  if(screen==='contacts')openContacts();
 }catch(e){console.warn('Émoi v2 名册尚未同步：',e.message)}
}
let mode=(()=>{try{return localStorage.getItem(MODE_KEY)==='art'?'art':'phone'}catch{return 'phone'}})();
let screen='home';
let detail=null;
function save(key,data){try{localStorage.setItem(key,JSON.stringify(data));return true}catch{alert('本机存储空间不足，请清理浏览器空间后重试。');return false}}
function create(tag,className,text){
 const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el;
}
function actionButton(label,iconName,callback,className='ep-round'){
 const b=create('button',className);b.type='button';b.setAttribute('aria-label',label);b.innerHTML=icon(iconName);b.addEventListener('click',callback);return b;
}
function timeText(){return new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false})}
function updateClock(){
 const now=new Date();
 for(const n of document.querySelectorAll('[data-ep-clock]'))n.textContent=timeText();
 for(const n of document.querySelectorAll('[data-ep-date]'))n.textContent=now.toLocaleDateString('zh-CN',{month:'long',year:'numeric'});
 for(const n of document.querySelectorAll('[data-ep-day]'))n.textContent=now.getDate();
 for(const n of document.querySelectorAll('[data-ep-weekday]'))n.textContent=now.toLocaleDateString('zh-CN',{weekday:'long'});
}
function setMode(next){
 if(next!=='phone'&&next!=='art')return;
 mode=next;document.body.dataset.uiMode=next;
 try{localStorage.setItem(MODE_KEY,next)}catch{}
 if(next==='phone'){const menu=$('#moreMenu');if(menu)menu.hidden=true;const drawer=$('#drawerWrap');if(drawer)drawer.hidden=true;const workspace=$('#workspaceDialog');if(workspace?.open)workspace.close();openHome()}else{phone.hidden=true;document.getElementById('app').inert=false;document.getElementById('app').removeAttribute('aria-hidden');}
}
function setScreen(next){
 if(next!=='home'){homeEditing=false;homeSelection=null}
 screen=next;
 document.body.dataset.phoneScreen=next;
 phone.hidden=next==='legacy'||mode!=='phone';
 const app=document.getElementById('app');
 app.inert=mode==='phone'&&next!=='legacy';
 if(app.inert)app.setAttribute('aria-hidden','true');else app.removeAttribute('aria-hidden');
 if(mode!=='phone')return;
 if(next==='home')window.EmoiWallpapers?.activate('page:home');
 else if(['contacts','messages'].includes(next))window.EmoiWallpapers?.activate('page:'+next);
 updateClock();
}
function header(title,onBack){
 const el=create('header','ep-page-header');
 el.append(actionButton('返回', 'back',onBack,'ep-header-button'));
 el.append(create('strong','',title));
 el.append(create('span','ep-header-spacer'));
 return el;
}
function view(){const v=$('#emoiPhoneView');v.replaceChildren();return v}
const HOME_LAYOUT_KEY='emoi-home-layout-v1';
const homeWidgets={
 calendar:{label:'日历', icon:'calendar', markup:'<span class="ep-widget-month" data-ep-date></span><strong class="ep-widget-day" data-ep-day></strong><span data-ep-weekday></span>'},
 reading:{label:'共读', icon:'reading', markup:'<strong>书房</strong><span>继续共读</span>'},
 room:{label:'Room', icon:'room', markup:'<strong>自主空间</strong><span>打开 Room</span>'}
};
const widgetId=id=>'widget:'+id;
const homeApps=apps.filter(app=>!['more','settings'].includes(app.id));
const initialHomeLayout=[
 {id:widgetId('calendar'),wide:false},{id:widgetId('reading'),wide:false},
 ...homeApps.map(({id})=>({id,wide:false}))
];
let homeLayout=readHomeLayout();
let homeEditing=false, homeSelection=null;

function readHomeLayout(){
 try{
  const stored=JSON.parse(localStorage.getItem(HOME_LAYOUT_KEY));
  if(!Array.isArray(stored))return initialHomeLayout.slice();
  const allowed=new Set([...homeApps.map(({id})=>id),...Object.keys(homeWidgets).map(widgetId)]);
  const items=[];
  for(const item of stored){
   if(!allowed.delete(item?.id))continue;
   items.push({id:item.id,wide:item.wide===true && item.id.startsWith('widget:')});
  }
  for(const {id} of homeApps)if(allowed.has(id))items.push({id,wide:false});
  return items;
 }catch{return initialHomeLayout.slice()}
}

function homeTextButton(label,handler){
 const button=create('button','ep-home-control',label);
 button.type='button';button.onclick=handler;
 return button;
}

function editHome(enabled,selection=null){
 homeEditing=enabled;homeSelection=selection;
 openHome();
 (selection?phone.querySelector('[data-home-id="'+selection+'"]'):null)?.focus({preventScroll:true});
}

function commitHomeLayout(items,selection){
 if(!save(HOME_LAYOUT_KEY,items))return;
 homeLayout=items;
 editHome(true,selection);
}

function moveHomeItem(id,index){
 const items=homeLayout.slice();
 const current=items.findIndex(item=>item.id===id);
 if(current<0||current===index||index<0||index>=items.length)return;
 const [item]=items.splice(current,1);
 items.splice(index,0,item);
 commitHomeLayout(items,id);
}

function openWidgetPicker(){
 const picker=create('dialog','ep-home-picker');
 picker.setAttribute('aria-label','添加小组件');
 picker.append(create('h2','','添加小组件'));
 for(const [id,{label}] of Object.entries(homeWidgets)){
  const button=homeTextButton(label,()=>{
   const key=widgetId(id);
   picker.close();
   commitHomeLayout([{id:key,wide:false},...homeLayout],key);
  });
  button.disabled=homeLayout.some(item=>item.id===widgetId(id));
  picker.append(button);
 }
 picker.append(homeTextButton('关闭',()=>picker.close()));
 picker.addEventListener('close',()=>picker.remove(),{once:true});
 document.body.append(picker);picker.showModal();
}

function bindHomeGesture(button,id){
 let press,ignoreClick=false;
 const clear=()=>{if(press)clearTimeout(press.timer);press=null};
 button.addEventListener('pointerdown',event=>{
  if(!event.isPrimary||event.button!==0)return;
  ignoreClick=false;
  press={x:event.clientX,y:event.clientY,id:event.pointerId,dragging:false};
  if(!homeEditing)press.timer=setTimeout(()=>{
   clear();editHome(true,id);
  },500);
  else button.setPointerCapture(event.pointerId);
 });
 button.addEventListener('pointermove',event=>{
  if(!press||press.id!==event.pointerId||Math.hypot(event.clientX-press.x,event.clientY-press.y)<9&&!press.dragging)return;
  if(!homeEditing){clear();return}
  press.dragging=true;
  button.classList.add('ep-home-dragging');
  const target=document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-home-id]');
  const grid=button.parentElement;
  grid.querySelector('.ep-home-drop')?.classList.remove('ep-home-drop');
  press.target=target?.parentElement===grid&&target!==button?target:null;
  press.target?.classList.add('ep-home-drop');
 });
 function finish(event){
  if(!press||press.id!==event.pointerId)return;
  const {dragging,target}=press;
  clear();
  button.classList.remove('ep-home-dragging');
  target?.classList.remove('ep-home-drop');
  if(!dragging)return;
  ignoreClick=true;
  if(event.type==='pointerup'&&target)moveHomeItem(id,homeLayout.findIndex(item=>item.id===target.dataset.homeId));
 }
 button.addEventListener('pointerup',finish);
 button.addEventListener('pointercancel',finish);
 button.addEventListener('lostpointercapture',finish);
 button.addEventListener('pointerleave',()=>{if(!homeEditing)clear()});
 button.addEventListener('contextmenu',event=>event.preventDefault());
 button.addEventListener('click',event=>{
  if(ignoreClick&&event.detail){ignoreClick=false;return}
  if(homeEditing)editHome(true,id);
  else openApp(id.replace(/^widget:/,''));
 });
}

function openHome(){
 setScreen('home');
 const previousScroll=phone.querySelector('.ep-home-scroll')?.scrollTop||0;
 const root=view();root.className='ep-view ep-home';
 root.toggleAttribute('data-home-editing',homeEditing);
 const top=create('header','ep-home-top');
 const clock=create('time','ep-desktop-clock');clock.setAttribute('data-ep-clock','');
 const actions=create('div','ep-home-actions');
 const wallpaper=actionButton('更换桌面壁纸','photo',()=>window.EmoiWallpapers?.open(),'ep-home-control ep-home-square');
 wallpaper.setAttribute('data-ep-optics','');
 actions.append(wallpaper);
 if(homeEditing)actions.append(homeTextButton('添加小组件',openWidgetPicker));
 const edit=homeTextButton(homeEditing?'完成':'编辑',()=>{
  editHome(!homeEditing);
  phone.querySelector('.ep-home-edit').focus({preventScroll:true});
 });
 edit.classList.add('ep-home-edit');edit.setAttribute('aria-pressed',String(homeEditing));
 actions.append(edit);top.append(clock,actions);root.append(top);
 if(homeEditing){
  const bar=create('div','ep-home-editbar');
  const index=homeLayout.findIndex(item=>item.id===homeSelection);
  if(index<0)bar.append(create('span','','拖动图标或小组件，也可点选后移动'));
  else{
   const selected=homeLayout[index];
   const widget=homeWidgets[selected.id.split(':')[1]];
   for(const [label,offset] of [['前移',-1],['后移',1]]){
    const control=homeTextButton(label,()=>moveHomeItem(selected.id,index+offset));
    control.disabled=!homeLayout[index+offset];bar.append(control);
   }
   if(widget){
    bar.append(homeTextButton(selected.wide?'缩小':'放大',()=>commitHomeLayout(
     homeLayout.map(item=>item===selected?{...item,wide:!item.wide}:item),selected.id)));
    bar.append(homeTextButton('移除',()=>commitHomeLayout(homeLayout.filter(item=>item!==selected),null)));
   }
  }
  root.append(bar);
 }
 const scroll=create('div','ep-home-scroll');
 const grid=create('div','ep-home-grid');
 for(const {id,wide} of homeLayout){
  const widget=homeWidgets[id.split(':')[1]];
  const button=create('button',widget?'ep-home-widget':'ep-app');
  button.type='button';button.dataset.homeId=id;
  if(homeEditing)button.setAttribute('aria-pressed',String(homeSelection===id));
  if(widget){
   button.dataset.widget=id.split(':')[1];
   button.toggleAttribute('data-wide',wide);
   button.setAttribute('data-ep-optics','');
   button.setAttribute('aria-label',id===widgetId('reading')?'打开共读书房':'打开'+widget.label);
   button.innerHTML='<span class="ep-widget-copy">'+widget.markup+'</span><span class="ep-widget-glyph">'+icon(widget.icon)+'</span>';
  }else{
   const app=homeApps.find(item=>item.id===id);
   button.dataset.epApp=id;
   const lens=create('span','ep-app-icon');lens.setAttribute('data-ep-optics','');lens.innerHTML=homeIcon(app.icon);
   button.append(lens,create('span','ep-app-label',app.label));
  }
  bindHomeGesture(button,id);grid.append(button);
 }
 scroll.append(grid);root.append(scroll);
 scroll.scrollTop=previousScroll;
 const bottom=create('div','ep-home-bottom');
 const search=actionButton('搜索联系人','search',openContacts,'ep-home-control ep-home-search');
 search.innerHTML='<span>'+icon('search')+'搜索</span>';
 search.setAttribute('data-ep-optics','');
 const dock=create('nav','ep-dock');dock.setAttribute('aria-label','常用应用');
 for(const id of dockIds){
  const app=apps.find(item=>item.id===id);
  const button=actionButton(app.label,app.icon,()=>openApp(id),'ep-dock-app');
  button.innerHTML='<span class="ep-dock-icon" data-ep-optics>'+homeIcon(app.icon)+'</span>';
  dock.append(button);
 }
 dock.setAttribute('data-ep-optics','');
 bottom.append(search,dock);root.append(bottom);
 updateClock();
}
function listItem(id,title,subtitle,iconName,handler){
 const b=create('button','ep-list-row');b.type='button';b.dataset.entry=id;
 const ava=create('span','ep-list-avatar');ava.innerHTML=icon(iconName);if(contacts.some(p=>p.id===id))queueMicrotask(()=>window.EmoiAvatars?.paint(ava,id));
 const content=create('span','ep-list-copy');content.append(create('strong','',title),create('small','',subtitle));
 b.append(ava,content);const arrow=create('span','ep-row-chevron');arrow.innerHTML=icon('right');b.append(arrow);b.addEventListener('click',handler);return b;
}
function openMessages(){
 setScreen('messages');const root=view();root.className='ep-view ep-list-screen';root.append(header('信息',openHome));
 const content=create('div','ep-list-scroll');
 const title=create('div','ep-list-intro');title.append(create('small','','MESSAGES'),create('h2','','对话'));
 content.append(title);
 const topActions=create('div','ep-list-actions');
 topActions.append(actionButton('添加联系人','plus',()=>openContactEditor()));
 const addText=create('button','ep-link','新联系人');addText.type='button';addText.onclick=()=>openContactEditor();topActions.append(addText);
 content.append(topActions);
 const list=create('div','ep-list-panel');
 for(const p of contacts)list.append(listItem(p.id,p.name,modelInactive,'contacts',()=>openContactConversation(p.id)));
 for(const g of groups)list.append(listItem(g.id,g.name,'私人群聊 · '+g.members.length+' 位成员','chat',()=>openGroupConversation(g.id)));
 if(!contacts.length&&!groups.length){
   const empty=create('div','ep-list-empty');empty.innerHTML='<span class="ep-empty-symbol">'+icon('chat')+'</span><strong>还没有联系人</strong><p>这里不会预先替你创建 GPT 或 Claude。<br>添加属于自己的 AI 联系人，再决定如何连接。</p>';
   list.append(empty);
 }
 content.append(list);
 const btn=create('button','ep-compat-link','打开原有会话（兼容入口）');btn.type='button';btn.addEventListener('click',openLegacy);content.append(btn);
 const group=create('button','ep-quiet-link');group.innerHTML=icon('plus')+' 创建群聊草稿';group.type='button';group.addEventListener('click',openGroupEditor);content.append(group);
 root.append(content);
}
function openContacts(){
 setScreen('contacts');const root=view();root.className='ep-view ep-list-screen';root.append(header('通讯录',openHome));
 const content=create('div','ep-list-scroll');
 const intro=create('div','ep-list-intro');intro.append(create('small','','CONTACTS'),create('h2','','我的联系人'));
 const toolbar=create('div','ep-contact-actions');
 const add=create('button','ep-action-primary','添加联系人');add.type='button';add.addEventListener('click',()=>openContactEditor());
 const upload=create('button','ep-outline-action','导入 AI 档案');upload.type='button';
 const file=create('input');file.type='file';file.accept='.json,.txt,application/json,text/plain';file.hidden=true;file.setAttribute('aria-label','选择 AI 角色 JSON 或 TXT');
 upload.onclick=()=>file.click();
 file.onchange=async()=>{
  const picked=file.files?.[0];file.value='';if(!picked)return;
  if(picked.size>1024*1024){alert('角色档案最多 1 MB');return}
  try{
    const txt=await picked.text();
    let json;try{json=JSON.parse(txt)}catch{json={name:picked.name.replace(/\.[^.]*$/,''),description:txt}}
    const data=json.data&&typeof json.data==='object'?json.data:json;
    const name=String(data.name||data.char_name||data.displayName||'').trim().slice(0,50);
    if(!name)throw Error('档案中没有角色名字');
    const notes=[data.description,data.personality,data.scenario,data.persona,data.system_prompt,data.creator_notes,data.first_mes].filter(x=>typeof x==='string').join('\n\n').slice(0,5000);
    openContactEditor(null,{name,notes});
  }catch(e){alert('无法解析角色档案：'+e.message)}
 };
 toolbar.append(add,upload,file);intro.append(toolbar);content.append(intro);
 const list=create('div','ep-list-panel');
 if(!contacts.length)list.append(create('p','ep-inline-empty','尚未添加联系人。姓名、头像与个人档案都由你决定。'));
 for(const p of contacts)list.append(listItem(p.id,p.name,'个人资料 · 本机草稿','contacts',()=>openContactDetail(p.id)));
 content.append(list);
 content.append(create('p','ep-help','联系人首先保存在本设备；连接私人服务器后同步身份和独立命名空间。模型、OB 与欲望系统运行权限仍要分别接通和验收。'));
 root.append(content);
}
function openContactConversation(id){
 const p=contacts.find(x=>x.id===id);if(!p){openMessages();return}
 setScreen('imessage');const root=view();
 window.EmoiMessageApp?.open(root,{kind:'contact',item:p,conversationId:remote.direct.get(p.id)||p.conversation_id||'',goBack:openMessages});
}
function openGroupConversation(id){
 const g=groups.find(x=>x.id===id);if(!g){openMessages();return}
 setScreen('imessage');const root=view();
 const names=(g.members||[]).map(id=>contacts.find(x=>x.id===id)?.name).filter(Boolean);
 window.EmoiMessageApp?.open(root,{kind:'group',item:g,contactNames:names,conversationId:g.remote?g.id:'',goBack:openMessages});
}
function openContactDetail(id){
 const person=contacts.find(x=>x.id===id);if(!person){openContacts();return;}
 detail=id;setScreen('contact-detail');const root=view();root.className='ep-view ep-detail-screen';
 root.append(header('联系人',openContacts));
 const body=create('div','ep-detail-body');
 const avatar=create('div','ep-profile-avatar');avatar.textContent=person.name.slice(0,1).toUpperCase();
 body.append(avatar,create('h2','',person.name),create('p','ep-subtitle',person.notes||'还没有填写人物简介'));
 const status=create('div','ep-status-card');
 status.innerHTML='<span class="ep-status-dot"></span><div><strong>尚未绑定 AI 服务</strong><p>这是可编辑的联系人档案。聊天、记忆和唤醒不会误接到其他联系人。</p></div>';
 body.append(status);
 const edit=create('button','ep-action-primary','编辑联系人');edit.type='button';edit.onclick=()=>openContactEditor(person.id);body.append(edit);
 const del=create('button','ep-danger-action','删除联系人草稿');del.type='button';del.onclick=()=>{if(!confirm('确认删除这张本机联系人草稿？已有云端数据不会修改。'))return;contacts=contacts.filter(x=>x.id!==id);save(CONTACTS_KEY,contacts);if(window.EmoiRelay?.enabled)void window.EmoiRelay.request('/emoi/v2/contacts/'+encodeURIComponent(id),{method:'DELETE'}).catch(e=>console.warn(e.message));openContacts()};body.append(del);
 root.append(body);
 void window.EmoiAvatars?.paint(avatar,id);
}
function openGroupDetail(id){
 const g=groups.find(x=>x.id===id);if(!g){openMessages();return}
 setScreen('group-detail');const root=view();root.className='ep-view ep-detail-screen';root.append(header('群聊草稿',openMessages));
 const body=create('div','ep-detail-body');const av=create('div','ep-profile-avatar');av.innerHTML=icon('chat');body.append(av,create('h2','',g.name));
 const names=g.members.map(id=>contacts.find(x=>x.id===id)?.name).filter(Boolean);
 body.append(create('p','ep-subtitle',names.length?'成员：'+names.join('、'):'尚未添加成员'));
 const status=create('p','ep-help','这是本机群聊草稿，并未创建真实的群聊会话或授权共享记忆。');body.append(status);
 const edit=create('button','ep-action-primary','编辑群聊');edit.onclick=()=>openGroupEditor(g.id);body.append(edit);
 const del=create('button','ep-danger-action','删除群聊草稿');del.onclick=()=>{if(!confirm('确认删除这份本机群聊草稿？'))return;groups=groups.filter(x=>x.id!==id);save(GROUPS_KEY,groups);if(window.EmoiRelay?.enabled)void window.EmoiRelay.request('/emoi/v2/conversations/'+encodeURIComponent(id),{method:'DELETE'}).catch(e=>console.warn(e.message));openMessages()};body.append(del);root.append(body);
}
let contactDialog=null;
let groupDialog=null;
function openContactEditor(id=null,prefill=null){
 const p=contacts.find(x=>x.id===id);
 if(contactDialog?.open)contactDialog.close();
 contactDialog=$('#epContactDialog');const form=$('#epContactForm');
 form.reset();form.elements.name.value=p?.name||prefill?.name||'';form.elements.notes.value=p?.notes||prefill?.notes||'';form.elements.model_route.value=p?.model_route||'';
 $('#epContactHeading').textContent=p?'编辑联系人':'添加联系人';
 contactDialog.dataset.editId=p?.id||'';
 contactDialog.showModal();
 form.elements.name.focus();
}
function openGroupEditor(id=null){
 const g=groups.find(x=>x.id===id);
 const dlg=$('#epGroupDialog'),form=$('#epGroupForm');
 if(dlg.open)dlg.close();
 form.reset();form.elements.name.value=g?.name||'';
 dlg.dataset.editId=g?.id||'';
 const members=$('#epGroupMembers');members.replaceChildren();
 for(const c of contacts){
  const label=create('label','ep-member');
  const input=create('input');input.type='checkbox';input.name='members';input.value=c.id;input.checked=Boolean(g?.members.includes(c.id));
  label.append(input,create('span','',c.name));members.append(label);
 }
 if(!contacts.length)members.append(create('p','ep-help','先添加联系人，才能选择群成员。'));
 dlg.showModal();form.elements.name.focus();
}
function openSettings(){
 setScreen('settings');const root=view();root.className='ep-view ep-settings';root.append(header('设置',openHome));
 const body=create('div','ep-list-scroll');
 const lead=create('div','ep-settings-heading');lead.append(create('small','','PERSONALIZE YOUR SPACE'),create('h2','','界面与外观'),create('p','','Émoi 可以拥有两套完全不同的外观，数据和联系人保持同一份。'));
 body.append(lead);
 const modeCard=create('div','ep-settings-panel');
 modeCard.append(create('strong','ep-settings-title','界面模式'));
 const toggle=create('div','ep-mode-toggle');
 const phoneButton=create('button','ep-mode-choice ep-current','小手机');phoneButton.type='button';phoneButton.setAttribute('aria-pressed','true');
 const artButton=create('button','ep-mode-choice','艺术模式');artButton.type='button';artButton.setAttribute('aria-pressed','false');
 phoneButton.onclick=()=>setMode('phone');
 artButton.onclick=()=>setMode('art');
 toggle.append(phoneButton,artButton);modeCard.append(toggle);
 modeCard.append(create('p','ep-help','艺术模式暂时沿用已有界面，之后单独重新设计；它不会影响小手机模式的数据。'));
 body.append(modeCard);
 const rows=create('div','ep-settings-panel');
 rows.append(listItem('wall','桌面壁纸','为小手机首页更换背景','photo',()=>window.EmoiWallpapers?.open()));
 rows.append(listItem('appearance','全局配色','玻璃透明度、浅色与深色','settings',()=>launchPage('appearance')));
 rows.append(listItem('connect','连接与模型','连接旧版服务，新的多 AI 独立身份后续实现','connect',()=>openConnection()));
 body.append(rows);
 const priv=create('div','ep-privacy-note');priv.innerHTML=icon('shield')+'<p>界面模式与联系人草稿保存在当前浏览器，不会清空 Émoi 原有聊天或记忆。切换模式不重建服务。</p>';
 body.append(priv);root.append(body);
}
function openMore(){
 setScreen('more');const root=view();root.className='ep-view ep-list-screen';root.append(header('全部应用',openHome));
 const body=create('div','ep-list-scroll');const title=create('div','ep-list-intro');title.append(create('small','','ÉMOI APPS'),create('h2','','更多空间'));body.append(title);
 const groups=[
 ['私人生活',[['whisper','悄悄话','journal'],['report','日报','reading'],['health','健康记录','memory'],['todo','待办清单','checklist']]],
 ['系统',[['repo','仓库','bookcase'],['appearance','外观','settings'],['connection','模型连接','connect'],['legacy','旧版聊天','chat']]]
 ];
 for(const [section,items] of groups){
 const s=create('section','ep-app-section');s.append(create('h3','',section));
 for(const [id,label,iconName] of items)s.append(listItem(id,label,'打开应用',iconName,()=>id==='connection'?openConnection():id==='legacy'?openLegacy():launchPage(id)));
 body.append(s);
 }
 root.append(body);
}
function openConnection(){
 const btn=document.querySelector('#moreMenu [data-settings]')||document.querySelector('.drawer [data-settings]');
 if(btn)btn.click();
}
function openLegacy(){
 setScreen('legacy');
 const app=document.getElementById('app');app.inert=false;
 window.EmoiWallpapers?.activate('chat:gpt');
}
function launchPage(name){
 if(name==='room'){
 const opener=$('#openWrenRoom');if(opener)opener.click();else alert('Room 当前还未加载。');return;
 }
 window.EmoiApp?.openPage(name);
}
function openApp(id){
 if(id==='chat')return openMessages();
 if(id==='contacts')return openContacts();
 if(id==='settings')return openSettings();
 if(id==='more')return openMore();
 if(id==='checklist')return launchPage('todo');
 if(id==='room')return launchPage('room');
 return launchPage(id);
}
function installDialogs(){
 const c=document.createElement('dialog');c.id='epContactDialog';c.className='ep-edit-dialog';c.innerHTML='<form id="epContactForm"><header><strong id="epContactHeading">添加联系人</strong><button type="button" data-ep-close="contact" aria-label="关闭">'+icon('x')+'</button></header><p>每位 AI 都拥有永久独立身份、记忆及欲望命名空间。模型绑定仍需另行完成。</p><label>联系人姓名<input name="name" type="text" required maxlength="50" autocomplete="off" placeholder="自定义名字"></label><label>角色档案 / 人物简介<textarea name="notes" maxlength="5000" rows="4" placeholder="可以导入人物档案或手动填写"></textarea></label><label>头像（仅存当前设备）<input name="avatar" type="file" accept="image/jpeg,image/png,image/webp"></label><label>模型接口别名（可留空）<input name="model_route" maxlength="100" autocomplete="off" placeholder="例如：我自己的云端模型"></label><footer><button type="button" data-ep-close="contact">取消</button><button type="submit">保存联系人</button></footer></form>';
 const g=document.createElement('dialog');g.id='epGroupDialog';g.className='ep-edit-dialog';g.innerHTML='<form id="epGroupForm"><header><strong>创建群聊草稿</strong><button type="button" data-ep-close="group" aria-label="关闭">'+icon('x')+'</button></header><p>仅保存群组名称与成员，尚未连接群聊消息和记忆授权。</p><label>群聊名称<input name="name" required maxlength="50" placeholder="给群聊起个名字"></label><strong>选择联系人</strong><div id="epGroupMembers" class="ep-member-list"></div><footer><button type="button" data-ep-close="group">取消</button><button type="submit">保存群聊</button></footer></form>';
 document.body.append(c,g);
 c.querySelectorAll('[data-ep-close]').forEach(b=>b.onclick=()=>c.close());
 g.querySelectorAll('[data-ep-close]').forEach(b=>b.onclick=()=>g.close());
 c.querySelector('form').onsubmit=e=>{
  e.preventDefault();const form=e.currentTarget,name=form.elements.name.value.trim(),notes=form.elements.notes.value.trim(),model_route=form.elements.model_route.value.trim();if(!name)return;
  const id=c.dataset.editId;let person;
  if(id){person=contacts.find(x=>x.id===id);if(person)Object.assign(person,{name,notes,model_route})}
  else {const cid=crypto.randomUUID();person={id:cid,name,notes,model_route,memory_namespace:'contact:'+cid,desire_namespace:'desire:contact:'+cid,createdAt:new Date().toISOString()};contacts.push(person)}
  if(!save(CONTACTS_KEY,contacts))return;
  const avatarFile=form.elements.avatar.files?.[0];c.close();
  if(avatarFile)void window.EmoiAvatars?.save(person.id,avatarFile).then(()=>{
   if(screen==='contact-detail')openContactDetail(person.id);else if(screen==='contacts')openContacts();
  }).catch(err=>alert('头像处理失败：'+err.message));
  void remoteSaveContact(person,!id);id?openContactDetail(id):openContacts();
 };
 g.querySelector('form').onsubmit=e=>{
  e.preventDefault();const form=e.currentTarget,name=form.elements.name.value.trim();if(!name)return;
  const members=[...form.querySelectorAll('input[name="members"]:checked')].map(x=>x.value);
  const id=g.dataset.editId;
  if(id){const old=groups.find(x=>x.id===id);if(old)Object.assign(old,{name,members})}
  else groups.push({id:crypto.randomUUID(),name,members});
  if(!save(GROUPS_KEY,groups))return;g.close();const saved=groups.find(x=>x.id===(id||groups[groups.length-1]?.id));if(saved)void remoteSaveGroup(saved,!id);id?openGroupDetail(id):openMessages();
 };
}
function init(){
 const artButton=$('#emoiSwitchToPhone');
 if(artButton)artButton.addEventListener('click',()=>setMode('phone'));
 const back=document.createElement('button');back.id='epLegacyHome';back.type='button';back.setAttribute('aria-label','返回小手机桌面');
 back.innerHTML=icon('back');back.addEventListener('click',openHome);
 document.querySelector('#app .topbar')?.prepend(back);
 installDialogs();setMode(mode);
 updateClock();setInterval(updateClock,60000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)updateClock()});
 for(const dlg of ['workspaceDialog','wrenRoom']){
 document.getElementById(dlg)?.addEventListener('close',()=>{if(mode==='phone'&&screen==='home')window.EmoiWallpapers?.activate('page:home')});
 }
 window.addEventListener('emoi-ui-mode',e=>setMode(e.detail?.mode));
 window.addEventListener('emoi-connected',()=>void syncRemote());
 if(window.EmoiRelay?.enabled)void syncRemote();
}
window.EmoiUiMode={setMode,getMode:()=>mode,openHome,openApp};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
