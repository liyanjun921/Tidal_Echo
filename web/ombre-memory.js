/* The native Ombre Dashboard stays functional inside Luné; records aren't demos. */
(()=>{'use strict';
const $=s=>document.querySelector(s),R=()=>window.LuneRelay;
const button=document.createElement('button');button.id='openOmbreMemory';button.type='button';button.className='soft-button';button.textContent='Ombre-Brain · 情绪与经历记忆';
$('#nativeMemoryOpen').after(button);
const dialog=document.createElement('dialog');dialog.id='ombreMemoryDialog';dialog.className='sheet ombre-sheet';
dialog.innerHTML=`<header class="sheet-head"><button type="button" id="ombreClose" class="icon-button" aria-label="关闭 Ombre">‹</button><h2>Ombre-Brain</h2><span class="head-balance"></span></header><div class="sheet-body form-stack"><p id="ombreStatus" role="status">尚未连接真实服务。</p><label>记忆空间<select id="ombreScope"><option value="gpt">GPT 私聊</option><option value="claude">Claude 私聊</option><option value="group_gpt">群聊中的 GPT</option><option value="group_claude">群聊中的 Claude</option></select></label><p class="form-help">Latent 继续保留。Ombre 四个空间独立保存经历和感受；You 与 Them 沿用原版独立开关及可见性。</p><label class="inline-check"><input id="ombreEnabled" type="checkbox"/>让此空间的模型使用 Ombre</label><label class="inline-check"><input id="ombreAutomatic" type="checkbox"/>开场浮现，并在每轮按当前话题自然联想</label><div class="settings-actions"><button id="ombreSave" class="soft-button">保存开关</button><button id="ombreRefresh" class="soft-button">刷新状态</button><button id="ombreManage" class="primary-button">打开完整管理页</button></div><p class="form-help">完整管理页包含桶、情感坐标、检索调试、记忆网络、承诺、信件、I、You/Them、导入、备份、配置和诊断。模型整理使用对应模型连接，本地向量默认复用现有 BGE；原版已消化或设为不主动浮现的记忆仍可主动检索。第三方服务与同步需你配置后启用。</p><div id="ombreFeatures" class="entry-list"></div><iframe id="ombreDashboard" title="Ombre 原版完整管理面板" referrerpolicy="no-referrer" hidden></iframe></div>`;
document.body.append(dialog);
let state=null;
const say=t=>$('#ombreStatus').textContent=t;
const scope=()=>$('#ombreScope').value;
function disconnected(){return window.LUNE_PREVIEW===true||!R()?.enabled}
function render(){if(disconnected()){say('界面预览 · 当前没有连接真实 Ombre、模型或后台任务。');return}const row=state?.scopes.find(r=>r.scope===scope());$('#ombreEnabled').checked=!!row?.enabled;$('#ombreAutomatic').checked=!!row?.automatic;$('#ombreManage').disabled=!row?.running;say(!state?.installed?'原版尚未安装或校验通过。':row?.running?`原版 ${state.version} 已运行 · 当前空间 ${row.tools.length} 个工具；真实模型连接仍需验收。`:'原版服务尚未运行，请检查电脑后台。')}
async function guarded(fn){try{if(disconnected()){say('界面预览 · 当前没有连接真实 Ombre、模型或后台任务。');return}await fn()}catch(e){say(e.message||'操作未完成')}}
async function refresh(){if(disconnected()){say('界面预览 · 当前没有连接真实 Ombre、模型或后台任务。');for(const id of ['ombreManage','ombreSave','ombreEnabled','ombreAutomatic'])$('#'+id).disabled=true;return}for(const id of ['ombreSave','ombreEnabled','ombreAutomatic'])$('#'+id).disabled=false;state=await R().request('/lune/ombre/status');render();const box=$('#ombreFeatures');box.replaceChildren();for(const f of state.features){const card=document.createElement('article');card.className='entry-card';const h=document.createElement('h3'),p=document.createElement('p');h.textContent=f.name;p.textContent=f.detail;p.className='form-help';card.append(h,p);box.append(card)}}
button.onclick=()=>{dialog.showModal();guarded(refresh);if(disconnected())refresh()};
$('#ombreClose').onclick=()=>{dialog.close();$('#ombreDashboard').removeAttribute('src');$('#ombreDashboard').hidden=true};
$('#ombreRefresh').onclick=()=>guarded(refresh);
$('#ombreScope').onchange=()=>{$('#ombreDashboard').removeAttribute('src');$('#ombreDashboard').hidden=true;render()};
$('#ombreSave').onclick=()=>guarded(async()=>{await R().json('/lune/ombre/'+scope()+'/settings','PATCH',{enabled:$('#ombreEnabled').checked,automatic:$('#ombreAutomatic').checked});await refresh()});
$('#ombreManage').onclick=()=>guarded(async()=>{const opened=await R().json('/lune/ombre/'+scope()+'/open','POST',{});const frame=$('#ombreDashboard');frame.src=opened.url;frame.hidden=false;frame.scrollIntoView({behavior:'smooth',block:'start'})});
})();
