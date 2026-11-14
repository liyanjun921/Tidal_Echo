/* Owner-managed model connections. Provider keys stay in the form until sent to the relay. */
(()=>{
'use strict';
const relay=window.EmoiRelay;
const endpoint='/app/loop/model-connections';
const $=id=>document.getElementById(id);
const apiForm=$('modelConnectionForm');
const planForm=$('contactPlanForm');
const apiStatus=$('modelConnectionStatus');
const formStatus=$('modelConnectionFormStatus');
const planStatus=$('contactPlanStatus');
const add=$('addModelConnection');
const fetchModels=$('fetchModelConnectionModels');
const planRefresh=$('contactPlanRefresh');
let connections=[], planModels=[], apiModels=[], editing=null, editorRevision=0, connectionEpoch=0;

function node(tag,text,className){
 const el=document.createElement(tag);
 if(text!==undefined)el.textContent=text;
 if(className)el.className=className;
 return el;
}
function action(text,handler){
 const button=node('button',text,'soft-button');
 button.type='button';button.onclick=handler;
 return button;
}
function option(value,text){
 const el=node('option',text);el.value=value;return el;
}
function paintPlan(saved){
 const select=planForm.elements.model;
 select.replaceChildren(option('','请选择订阅模型'));
 for(const model of planModels)select.append(option(model.id,model.name===model.id?model.id:model.name+' · '+model.id));
 if(saved&&!planModels.some(model=>model.id===saved))select.append(option(saved,saved+'（已保存）'));
 select.value=saved||'';
}
function renderConnections(){
 const list=$('modelConnectionList');list.replaceChildren();
 if(!connections.length)list.append(node('p','还没有添加自定义 API。','form-help'));
 for(const connection of connections){
  const row=node('div',undefined,'model-connection-row');
  const copy=node('div');
  copy.append(node('strong',connection.name),node('small',connection.model));
  const editButton=action('编辑',()=>edit(connection));
  editButton.setAttribute('aria-label','编辑 '+connection.name);
  const removeButton=action('移除',async()=>{
   if(!confirm('移除「'+connection.name+'」？使用它的联系人需要重新选择连接。'))return;
   removeButton.disabled=true;
   try{
    const result=await relay.request(endpoint+'/'+encodeURIComponent(connection.id),{method:'DELETE'});
    if(editing===connection.id)closeEditor();
    accept(result);apiStatus.textContent='已移除';
   }catch(error){apiStatus.textContent=error.message;removeButton.disabled=false}
  });
  removeButton.setAttribute('aria-label','移除 '+connection.name);
  row.append(copy,editButton,removeButton);list.append(row);
 }
}
function accept(result){
 connections=result.connections;
 renderConnections();
 window.dispatchEvent(new CustomEvent('emoi-model-connections',{detail:connections}));
 return connections;
}
async function load(){
 if(!relay.enabled)return [];
 const epoch=connectionEpoch;
 const result=await relay.request(endpoint);
 return epoch===connectionEpoch&&relay.enabled?accept(result):[];
}
function closeEditor(){
 editorRevision++;apiForm.reset();
 apiForm.hidden=true;
 editing=null;
}
function edit(connection){
 editorRevision++;apiForm.reset();editing=connection?.id||null;
 const f=apiForm.elements;
 f.label.value=connection?.name||'';
 f.url.value=connection?.url||'';
 f.protocol.value=connection?.protocol||'openai';
 f.model.value=connection?.model||'';
 f.key.placeholder=connection?.key_set?'已保存，留空沿用':'输入 API Key';
 f.key.required=!connection?.key_set;
 formStatus.textContent='';apiModels=[];$('modelCatalog').hidden=true;
 apiForm.hidden=false;f.label.focus();
}
function formPayload(){
 const f=apiForm.elements;
 return {id:editing,name:f.label.value.trim(),url:f.url.value.trim(),protocol:f.protocol.value,key:f.key.value,model:f.model.value.trim()};
}
function paintCatalog(){
 const f=apiForm.elements, filter=f.filter.value.trim().toLowerCase();
 const models=apiModels.filter(model=>model.id.toLowerCase().includes(filter)||model.name.toLowerCase().includes(filter));
 f.catalog.replaceChildren(option('',models.length?'请选择模型':'没有匹配的模型'));
 for(const model of models)f.catalog.append(option(model.id,model.name===model.id?model.id:model.name+' · '+model.id));
 f.catalog.value=f.model.value;
 if(f.catalog.selectedIndex===-1)f.catalog.selectedIndex=0;
}
add.onclick=()=>edit();
$('cancelModelConnection').onclick=closeEditor;
apiForm.elements.filter.oninput=paintCatalog;
apiForm.elements.catalog.onchange=()=>{if(apiForm.elements.catalog.value)apiForm.elements.model.value=apiForm.elements.catalog.value};
for(const key of ['url','protocol','key'])apiForm.elements[key].addEventListener('input',()=>{
 apiModels=[];$('modelCatalog').hidden=true;formStatus.textContent='';
});
fetchModels.onclick=async()=>{
 const f=apiForm.elements;
 if(!f.url.reportValidity()||!f.key.reportValidity())return;
 const body=formPayload(), revision=editorRevision;
 fetchModels.disabled=true;formStatus.textContent='正在拉取模型…';
 try{
  const result=await relay.json(endpoint+'/models','POST',body);
  const current=formPayload();
  if(apiForm.hidden||revision!==editorRevision||['id','url','protocol','key'].some(key=>current[key]!==body[key]))return;
  apiModels=result.models;
  f.filter.value='';paintCatalog();$('modelCatalog').hidden=!apiModels.length;
  formStatus.textContent=apiModels.length?'找到 '+apiModels.length+' 个模型':'此连接暂未返回模型，可手填模型 ID。';
 }catch(error){if(!apiForm.hidden&&revision===editorRevision)formStatus.textContent=error.message}
 finally{fetchModels.disabled=false}
};
apiForm.onsubmit=async event=>{
 event.preventDefault();
 const submit=apiForm.querySelector('[type=submit],button:not([type])'),revision=editorRevision;
 submit.disabled=true;
 try{
  const result=await relay.json(endpoint,'POST',formPayload());
  accept(result);
  if(revision===editorRevision)closeEditor();
  apiStatus.textContent='API 已保存，可在联系人里选择';
 }catch(error){if(revision===editorRevision)formStatus.textContent=error.message}
 finally{submit.disabled=false}
};
planRefresh.onclick=async()=>{
 planRefresh.disabled=true;planStatus.textContent='正在拉取模型…';
 try{
  const result=await relay.request('/app/loop/subscriptions/chatgpt/models');
  const saved=planForm.elements.model.value;
  planModels=result.models;paintPlan(saved);
  planStatus.textContent=planModels.length?'请选择订阅模型并保存':'当前授权账户未返回可选模型';
 }catch(error){planStatus.textContent=error.message}
 finally{planRefresh.disabled=false}
};
planForm.onsubmit=async event=>{
 event.preventDefault();
 const submit=planForm.querySelector('button:not([type])');
 submit.disabled=true;
 try{
  const result=await relay.json(endpoint+'/subscription','POST',{model:planForm.elements.model.value});
  paintPlan(result.subscription_model);
  planStatus.textContent='订阅模型已保存，可在联系人里选择 GPT Work 订阅直连';
 }catch(error){planStatus.textContent=error.message}
 finally{submit.disabled=false}
};
async function open(){
 closeEditor();planModels=[];paintPlan('');apiStatus.textContent='';planStatus.textContent='';
 const connected=relay.enabled;
 for(const button of [add,planRefresh,planForm.querySelector('button:not([type])')])button.disabled=!connected;
 if(!connected){connections=[];renderConnections();apiStatus.textContent='请先连接自己的 Émoi 服务器';return}
 const epoch=connectionEpoch;
 try{
  const result=await relay.request(endpoint);
  if(epoch===connectionEpoch&&relay.enabled){accept(result);paintPlan(result.subscription_model)}
 }catch(error){if(epoch===connectionEpoch)apiStatus.textContent=error.message}
}
$('connectionDialog').addEventListener('close',closeEditor);
window.addEventListener('emoi-connected',()=>{connectionEpoch++});
window.addEventListener('emoi-disconnected',()=>{
 connectionEpoch++;closeEditor();planModels=[];paintPlan('');
 accept({connections:[]});
 for(const button of [add,planRefresh,planForm.querySelector('button:not([type])')])button.disabled=true;
 apiStatus.textContent='请先连接自己的 Émoi 服务器';
});
window.EmoiModelConnections={load,open};
})();
