/* Owner controls for the separate Latent engine. No provider keys or fake results. */
(()=>{'use strict';
const $=s=>document.querySelector(s), relay=()=>window.LuneRelay;
const preview=window.LUNE_PREVIEW===true, names={shared:'共享',gpt:'GPT 私有',claude:'Claude 私有',group:'群聊共同'};
let settings=null;
const node=(tag,text,cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n};
const notice=text=>$('#memoryEngineStatus').textContent=text;
function disabled(value){document.querySelectorAll('#memorySettingsForm input,#memorySettingsForm button,#memorySearchForm button,#memoryLoopForm input,#memoryLoopForm select,#memoryLoopForm button,#memoryEngineCheck,#memoryHistory').forEach(n=>n.disabled=value)}
async function refresh(){
 if(preview||!relay().enabled){disabled(true);notice(preview?'界面预览 · 未连接真实记忆服务。这里展示操作入口，不生成示例检索结果。':'请先连接自己的 Luné 服务器。原有本机记忆仍可查看。');return}
 disabled(false);const status=await relay().request('/lune/memory/status');settings=status.settings;
 for(const name of ['enabled','auto_recall','model_writes'])$('#memorySettingsForm').elements[name].checked=!!settings[name];
 notice(status.message+(status.engine==='basic'?'\n当前引擎：基础记忆':'\n主动检索：Latent')+'\n'+(status.passive.enabled?status.passive.message:'原版 Passive Recall 已关闭；主动检索仍可使用。'));
 const list=$('#memoryLoopList');list.replaceChildren();
 for(const item of status.loops){const card=node('article','', 'entry-card');card.append(node('span',names[item.scope],'scope-badge'),node('p',item.summary));const edit=node('button','修改','quiet-button');edit.type='button';edit.onclick=async()=>{const summary=prompt('修改这件未完事项',item.summary);if(summary===null)return;try{await relay().json('/lune/memory/loops','POST',{...item,summary});await refresh()}catch(e){notice(e.message)}};const b=node('button','标记完成','soft-button');b.type='button';b.onclick=async()=>{if(!confirm('将这件未完事项标记完成？'))return;try{await relay().json('/lune/memory/loops','POST',{...item,status:'closed'});await refresh()}catch(e){notice(e.message)}};card.append(edit,b);list.append(card)}
 if(!status.loops.length)list.append(node('p','当前没有未完事项。','form-help'));
}
async function open(){if(!$('#memoryEngineDialog').open)$('#memoryEngineDialog').showModal();$('#memorySearchResults').replaceChildren();$('#memoryHistoryResults').replaceChildren();try{await refresh()}catch(e){notice(e.message)}}
function memoryCard(item,allowEdit=true){
 const card=node('article','','entry-card');card.append(node('span',(names[item.scope]||'')+' · v'+item.version+' · '+({current:'当前',superseded:'已变更',retracted:'已撤回'}[item.status]||'当前'),'scope-badge'),node('h3',item.title),node('p',item.content,'memory-quote'),node('p','当下状态：'+item.current_state,'form-help'));
 if(item.source_message_id)card.append(node('small','出处：用户消息 #'+item.source_message_id));
 if(allowEdit&&item.status==='current'){const b=node('button','查看与修改','soft-button');b.type='button';b.onclick=()=>{window.dispatchEvent(new CustomEvent('lune-edit-memory',{detail:item}))};card.append(b)}
 const history=node('button','查看修改记录','quiet-button');history.type='button';history.onclick=async()=>{try{const result=await relay().request('/lune/memories/'+encodeURIComponent(item.id)+'/revisions');const old=card.querySelector('[data-revisions]');old?.remove();const box=node('div','','memory-revisions');box.dataset.revisions='true';for(const r of result.revisions)box.append(node('p','v'+r.version+'：'+r.snapshot.content,'memory-quote'));if(!result.revisions.length)box.append(node('p','没有更早的编辑版本。','form-help'));card.append(box)}catch(e){notice(e.message)}};card.append(history);return card;
}
function wire(){
 document.querySelectorAll('[data-memory-open]').forEach(b=>b.onclick=open);
 $('#memoryEngineClose').onclick=()=>$('#memoryEngineDialog').close();
 $('#memorySettingsForm').onsubmit=async e=>{e.preventDefault();if(!settings||preview||!relay().enabled)return;const body={version:settings.version};for(const key of ['enabled','auto_recall','model_writes'])body[key]=e.target.elements[key].checked;try{await relay().json('/lune/memory/settings','PATCH',body);await refresh();notice('设置已保存。自动召回只影响模型请求，不改写原始聊天。')}catch(err){notice(err.message)}};
 $('#memoryEngineCheck').onclick=async()=>{try{notice('正在检查原版 Passive Recall 与本地语义模型…');const r=await relay().json('/lune/memory/check','POST',{});notice(r.ok&&r.passive.native?'原版 Passive Recall 运行检查通过 · 本地 '+r.passive.dimension+' 维 · 临时模式；未调用聊天或付费接口。':'检查未通过')}catch(e){notice(e.message)}};
 $('#memorySearchForm').onsubmit=async e=>{e.preventDefault();if(preview||!relay().enabled)return;const host=$('#memorySearchResults');host.replaceChildren();try{const r=await relay().json('/lune/memory/search','POST',{view:e.target.elements.view.value,query:e.target.elements.query.value});for(const m of r.matches)host.append(memoryCard(m));if(!r.matches.length)host.append(node('p',r.text,'form-help'));notice('已检索所选房间及共享范围；返回片段仍需核对。')}catch(err){notice(err.message)}};
 $('#memoryLoopForm').onsubmit=async e=>{e.preventDefault();if(preview||!relay().enabled)return;try{await relay().json('/lune/memory/loops','POST',{scope:e.target.elements.scope.value,summary:e.target.elements.summary.value});e.target.reset();await refresh()}catch(err){notice(err.message)}};
 $('#memoryHistory').onclick=async()=>{try{const r=await relay().request('/lune/memories?history=1'),host=$('#memoryHistoryResults');host.replaceChildren();for(const m of r.memories.filter(m=>m.status!=='current'))host.append(memoryCard(m,false));if(!host.children.length)host.append(node('p','没有已变更或撤回的记忆。','form-help'))}catch(e){notice(e.message)}};
}
window.LuneMemory={open};
window.addEventListener('lune-memories',()=>{if($('#memoryEngineDialog')?.open){$('#memorySearchResults').replaceChildren();$('#memoryHistoryResults').replaceChildren();refresh().catch(e=>notice(e.message))}});
document.addEventListener('DOMContentLoaded',wire);
})();
