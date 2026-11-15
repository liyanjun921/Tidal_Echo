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
   ['ob_server','共享 OB 空间',servers.map(row=>({id:row.name,name:row.name+(row.online?'':'（离线）')}))]
  ]){
   const select=form.elements[field], selected=select.value;
   select.replaceChildren(new Option('未绑定 '+title,''));
   for(const item of entries)select.add(new Option(item.name,item.id));
   if(selected&&![...select.options].some(option=>option.value===selected))select.add(new Option('当前绑定 · '+selected,selected));
   select.value=selected;
  }
 }
 $('connectionDialog').addEventListener('close',close);
 window.EmoiContactMedia={open,bind};
})();
