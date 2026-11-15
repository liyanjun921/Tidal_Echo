(() => {
 'use strict';
 const relay=window.EmoiRelay, path='/emoi/v2/media-connections';
 const $=id=>document.getElementById(id);
 const form=$('contactMediaForm'), list=$('contactMediaList'), status=$('contactMediaStatus');
 const values=form.elements;
 let rows=[], editing=null;
 const labels={images:'OpenAI 兼容生图',minimax:'MiniMax',elevenlabs:'ElevenLabs'};
 function paintFields(){
  const provider=values.provider.value;
  values.voice_id.closest('label').hidden=provider==='images';
  values.voice_id.required=provider!=='images';
  values.group_id.closest('label').hidden=provider!=='minimax';
 }
 function edit(row){
  form.reset();editing=row?.id||null;
  for(const key of ['provider','name','base_url','model','voice_id','group_id'])
   if(row?.[key]!==undefined)values[key].value=row[key];
  values.key.required=!row?.key_set;
  values.key.placeholder=row?.key_set?'留空沿用原密钥':'API Key';
  paintFields();form.hidden=false;values.name.focus();
 }
 function paint(result){
  rows=result.connections;list.replaceChildren();
  for(const row of rows){
   const item=document.createElement('div');item.className='model-connection-row';
   const copy=document.createElement('div'),title=document.createElement('strong'),summary=document.createElement('small');
   title.textContent=row.name;summary.textContent=labels[row.provider]+' · '+row.model;copy.append(title,summary);
   const editButton=document.createElement('button');editButton.type='button';editButton.className='soft-button';editButton.textContent='编辑';editButton.onclick=()=>edit(row);
   const remove=document.createElement('button');remove.type='button';remove.className='soft-button';remove.textContent='移除';
   remove.onclick=async()=>{
    if(!confirm('移除此媒体连接？绑定此接口的联系人需要重新选择。'))return;
    try{paint(await relay.request(path+'/'+encodeURIComponent(row.id),{method:'DELETE'}));if(editing===row.id)close()}
    catch(error){status.textContent=error.message}
   };
   item.append(copy,editButton,remove);list.append(item);
  }
 }
 function close(){form.reset();form.hidden=true;editing=null}
 $('addContactMedia').onclick=()=>edit();
 $('cancelContactMedia').onclick=close;
 values.provider.onchange=paintFields;
 form.onsubmit=async event=>{
  event.preventDefault();
  const submit=event.submitter;if(submit)submit.disabled=true;
  try{
   const body=Object.fromEntries(new FormData(form));
   if(editing)body.id=editing;
   paint(await relay.json(path,'POST',body));close();status.textContent='媒体接口已保存';
  }catch(error){status.textContent=error.message}
  finally{if(submit)submit.disabled=false}
 };
 async function open(){
  close();list.replaceChildren();status.textContent='';
  $('addContactMedia').disabled=!relay.enabled;
  if(!relay.enabled){status.textContent='请先连接私人服务器';return}
  try{paint(await relay.request(path))}catch(error){status.textContent=error.message}
 }
 async function bind(form){
  if(!relay.enabled)return;
  const editId=form.closest('dialog').dataset.editId;
  const results=await Promise.allSettled([relay.request(path),relay.request('/app/loop/contact-memory-servers')]);
  if(form.closest('dialog').dataset.editId!==editId)return;
  const connections=results[0].status==='fulfilled'?results[0].value.connections:[];
  const servers=results[1].status==='fulfilled'?results[1].value.servers:[];
  for(const [field,title,entries] of [
   ['voice_connection','语音接口',connections.filter(row=>row.provider!=='images')],
   ['image_connection','生图接口',connections.filter(row=>row.provider==='images')],
   ['ob_server','共享 OB 空间',servers.filter(row=>row.configured!==false).map(row=>({id:row.name,name:(row.label||row.name)+(row.search===false?'（未连通）':'')}))]
  ]){
   const select=form.elements[field], selected=select.value;
   select.replaceChildren(new Option('未绑定 '+title,''));
   for(const item of entries)select.add(new Option(item.name,item.id));
   if(selected&&![...select.options].some(option=>option.value===selected))select.add(new Option('当前绑定 · '+selected,selected));
   select.value=selected;
  }
 }
 const obSpaces=[
  ['ob-space-one','空间一 · 谢临川'],
  ['ob-space-two','空间二 · 沈知予'],
  ['ob-space-three','空间三'],
 ];
 const el=(tag,copy)=>{const node=document.createElement(tag);if(copy)node.textContent=copy;return node};
 function mountOb(body){
  function panel(title){
   const section=el('section');section.className='ep-ob-panel settings-card form-stack';
   section.append(el('h3',title));body.append(section);return section;
  }
  function field(form,title,input){
   const label=el('label',title);label.append(input);form.append(label);return input;
  }
  function button(title,type='button'){
   const item=el('button',title);item.type=type;item.className='soft-button';return item;
  }
  function help(text){const p=el('p',text);p.className='form-help';return p}
  const page=panel('原有 OB 窗口');
  const launch=el('a','打开原有 Ombre Brain');launch.className='soft-button';
  launch.target='_blank';launch.rel='noopener noreferrer';launch.hidden=true;
  const dashboardForm=el('form');dashboardForm.className='form-stack';
  const dashboard=field(dashboardForm,'OB 管理页地址',el('input'));dashboard.type='url';dashboard.placeholder='https://你的 OB 地址/';
  const dashboardSubmit=button('保存管理页地址','submit');dashboardForm.append(dashboardSubmit);
  page.append(launch,dashboardForm,help('复制图 3 那个 OB 窗口在 Safari 地址栏的链接。点击「打开原有 Ombre Brain」后，沿用 OB 自己的登录和空间切换。'));
  const spaces=panel('连接空间 1、2、3');
  const rows=el('ul');rows.className='ep-ob-spaces';spaces.append(rows);
  const spaceForm=el('form');spaceForm.className='form-stack';
  const space=field(spaceForm,'选择 OB 空间',el('select'));
  for(const [value,label] of obSpaces)space.add(new Option(label,value));
  const endpoint=field(spaceForm,'该空间的 MCP 地址',el('input'));
  endpoint.type='url';endpoint.placeholder='https://…/mcp';endpoint.required=true;
  const authorization=field(spaceForm,'该空间的 MCP 令牌（如需）',el('input'));
  authorization.type='password';authorization.autocomplete='off';authorization.placeholder='地址未变时可留空，沿用已保存的令牌';
  const connect=button('保存并连接','submit');spaceForm.append(connect);
  const refresh=button('刷新空间状态');
  spaces.append(spaceForm,refresh,help('每个空间填它自己的 MCP 地址。管理页链接和 MCP 地址分别保存。'));
  const bindings=panel('联系人绑定');
  bindings.append(help('选择对应的 OB 空间再保存。同一个联系人只绑定一个空间，下一轮私聊生效。'));
  const contactRows=el('div');contactRows.className='ep-ob-contacts';bindings.append(contactRows);
  const status=el('p');status.className='ep-ob-status form-help';status.setAttribute('role','status');body.prepend(status);
  let servers=[];
  function useDashboard(url){
   dashboard.value=url||'';
   launch.hidden=!url;
   if(url)launch.href=url;else launch.removeAttribute('href');
  }
  function useSpace(){endpoint.value=servers.find(row=>row.name===space.value)?.mcp_url||'';authorization.value=''}
  space.onchange=useSpace;
  function useServers(result){
   servers=result.servers;
   rows.replaceChildren();
   for(const [key,label] of obSpaces){
    const entry=servers.find(item=>item.name===key);
    const text=!entry?.configured?'待配置':!entry.online?'未连通':!entry.search?'未提供记忆检索':entry.archive?'可检索及归档':'可检索 · 未提供聊天归档';
    const line=el('li');line.append(el('strong',label),el('span',text));rows.append(line);
   }
   useSpace();
  }
  function useContacts(contacts){
   contactRows.replaceChildren();
   if(!contacts.length){contactRows.append(help('先在「信息 → 联系人」添加联系人。'));return}
   for(const person of contacts){
    const form=el('form');form.className='ep-ob-contact';
    const picker=field(form,person.name,el('select'));
    picker.add(new Option('未绑定',''));
    const current=person.profile?.ob_server||'';
    for(const [key,label] of obSpaces){
     const row=servers.find(item=>item.name===key);
     const option=new Option(label+(row?.search?'':'（尚未连通）'),key);
     option.disabled=!row?.search&&current!==key;picker.add(option);
    }
    if(current&&!obSpaces.some(([key])=>key===current))picker.add(new Option('当前绑定 · '+current,current));
    picker.value=current;
    const save=button('保存','submit');form.append(save);
    form.onsubmit=async event=>{
     event.preventDefault();save.disabled=true;
     try{
      await relay.json('/emoi/v2/contacts/'+encodeURIComponent(person.id),'PATCH',{profile:{ob_server:picker.value}});
      status.textContent='已更新 '+person.name+' 的 OB 空间';
      window.dispatchEvent(new Event('emoi-ob-binding-changed'));
     }catch(error){status.textContent=error.message}
     finally{save.disabled=false}
    };
    contactRows.append(form);
   }
  }
  async function load(){
   refresh.disabled=true;connect.disabled=true;status.textContent='正在检查 OB 空间…';
   try{
    const [settings,people]=await Promise.all([relay.request('/app/loop/contact-memory-servers'),relay.request('/emoi/v2/contacts')]);
    if(!body.isConnected)return;
    useDashboard(settings.dashboard_url);useServers(settings);useContacts(people.contacts);status.textContent='';
   }catch(error){status.textContent=error.message}
   finally{refresh.disabled=false;connect.disabled=false}
  }
  if(!relay.enabled){
   status.textContent='连接 Émoi 私人服务器后可设置 OB。';
   for(const item of body.querySelectorAll('input,select,button'))item.disabled=true;
   return;
  }
  dashboardForm.onsubmit=async event=>{
   event.preventDefault();dashboardSubmit.disabled=true;
   try{
    const result=await relay.json('/app/loop/contact-ob/dashboard','POST',{url:dashboard.value.trim()});
    useDashboard(result.dashboard_url);status.textContent='OB 管理页地址已保存';
   }catch(error){status.textContent=error.message}
   finally{dashboardSubmit.disabled=false}
  };
  spaceForm.onsubmit=async event=>{
   event.preventDefault();connect.disabled=true;space.disabled=true;refresh.disabled=true;status.textContent='正在连接这个空间…';
   try{
    const settings=await relay.request('/app/loop/contact-ob/space',{method:'POST',timeout:55000,
     body:JSON.stringify({space:space.value,url:endpoint.value.trim(),authorization:authorization.value.trim()})});
    useServers(settings);
    const {contacts}=await relay.request('/emoi/v2/contacts');
    useContacts(contacts);
    status.textContent=servers.find(row=>row.name===space.value)?.search?'这个空间已连通，可绑定联系人。':'地址已保存，OB 尚未连通，请核对该空间的地址和令牌。';
   }catch(error){status.textContent=error.message}
   finally{connect.disabled=false;space.disabled=false;refresh.disabled=false}
  };
  refresh.onclick=()=>void load();
  void load();
 }
 $('connectionDialog').addEventListener('close',close);
 $('contactObOpen').onclick=()=>window.EmoiUiMode?.openOb();
 window.EmoiContactMedia={open,bind,mountOb};
})();
