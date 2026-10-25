/* Luné's daily checklist, using the existing workspace records and relay. */
(()=>{'use strict';
const $=(s,r=document)=>r.querySelector(s);
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
const button=(label,fn,cls='checklist-button')=>{const b=el('button',cls,label);b.type='button';b.onclick=fn;return b};
const names={user:'我',gpt:'GPT',claude:'Claude'};
let current=null,editing=null,wired=false;
const localDay=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};
const localTime=ms=>new Date(ms).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});
const cycleName=d=>d.cycle==='daily'?'每天':d.cycle==='once'?'今天一次':d.cycle==='timed'?'到点提醒':'原有待办';
const zone=()=>Intl.DateTimeFormat().resolvedOptions().timeZone||'Asia/Shanghai';
function recordDay(value,timezone){try{const parts=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:timezone||zone(),year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(value).map(p=>[p.type,p.value]));return `${parts.year}-${parts.month}-${parts.day}`}catch{return localDay()}}
function rollover(ctx){if(ctx.relay.enabled)return;const today=Date.now();let changed=false;
 for(let i=ctx.records.length-1;i>=0;i--){const item=ctx.records[i],d=item.data||{};if(item.kind!=='todo'||!['daily','once','timed'].includes(d.cycle))continue;
  const day=recordDay(today,d.timezone),started=d.cycle_day||recordDay(new Date(item.created_at||today),d.timezone);
  if(started>=day)continue;
  if(d.cycle==='once'||d.cycle==='timed'&&d.done){ctx.records.splice(i,1);changed=true;continue}
  if(d.cycle==='daily'){d.done=false;changed=true}d.cycle_day=day;
 }
 if(changed)ctx.save();
}
function wire(){if(wired)return;wired=true;const dialog=$('#checklistEditor'),form=$('#checklistForm');
 $('#checklistClose').onclick=()=>dialog.close();
 form.elements.cycle.onchange=()=>syncForm();form.elements.scope.onchange=()=>syncForm();form.elements.schedule.onchange=()=>syncForm();
 $('#checklistDelete').onclick=async()=>{if(!editing||!current)return;try{dialog.close();await current.deleteRecord(editing)}catch(e){current.toast(e.message)}};
 form.onsubmit=async e=>{e.preventDefault();if(!current)return;const f=e.target,kind=f.elements.cycle.value,data={...(editing?.data||{})},scope=f.elements.scope.value;
  data.owner=f.elements.owner.value;data.done=!!editing?.data?.done;
  if(kind==='legacy'){delete data.cycle;delete data.trigger_at;delete data.alarm_room;delete data.timezone;delete data.cycle_day}
  else{data.cycle=kind;data.timezone=zone();data.cycle_day=editing?.data?.cycle_day||localDay();delete data.due;delete data.time;
   if(kind==='timed'){
    let when;
    if(f.elements.schedule.value==='minutes')when=Date.now()+Number(f.elements.minutes.value)*60000;
    else{when=new Date(f.elements.date.value+'T'+f.elements.time.value).getTime();if(f.elements.date.value===localDay()&&when<=Date.now())when+=86400000}
    if(!Number.isFinite(when)||when<=Date.now()||when>Date.now()+366*86400000){current.toast('请填写未来一年内的提醒时间');return}
    data.trigger_at=Math.trunc(when);data.alarm_room=scope==='shared'?f.elements.alarm_room.value:scope;
   }else{delete data.trigger_at;delete data.alarm_room}
  }
  try{await current.putRecord({...(editing||{}),kind:'todo',scope,title:f.elements.title.value.trim(),content:f.elements.content.value.trim(),data});dialog.close();current.renderPage();current.toast(kind==='timed'&&!current.relay.enabled?'已保存到本机；连接服务器后才能到点发消息':'清单已保存')}
  catch(err){current.toast(err.message)}
 };
}
function syncForm(){const f=$('#checklistForm'),cycle=f.elements.cycle.value,timed=cycle==='timed',clock=f.elements.schedule.value==='clock';
 $('[data-checklist-schedule]',f).hidden=!timed;$('[data-checklist-clock]',f).hidden=!timed||!clock;$('[data-checklist-minutes]',f).hidden=!timed||clock;$('[data-checklist-room]',f).hidden=!timed||f.elements.scope.value!=='shared';
 f.elements.date.required=timed&&clock;f.elements.time.required=timed&&clock;f.elements.minutes.required=timed&&!clock;
 if(timed&&f.elements.scope.value!=='shared')f.elements.alarm_room.value=f.elements.scope.value;
}
function open(ctx,item=null){wire();current=ctx;editing=item;const f=$('#checklistForm');f.reset();$('#checklistTitle').textContent=item?'编辑清单项':'新建清单项';$('#checklistDelete').hidden=!item;
 f.elements.title.value=item?.title||'';f.elements.content.value=item?.content||'';f.elements.scope.value=item?.scope||ctx.selectedChat;f.elements.owner.value=item?.data?.owner||'user';f.elements.cycle.value=item?.data?.cycle||item&&'legacy'||'daily';
 f.elements.alarm_room.value=item?.data?.alarm_room||ctx.selectedChat;
 const time=item?.data?.trigger_at?new Date(item.data.trigger_at):new Date(Date.now()+3600000);
 f.elements.date.value=`${time.getFullYear()}-${String(time.getMonth()+1).padStart(2,'0')}-${String(time.getDate()).padStart(2,'0')}`;
 f.elements.time.value=`${String(time.getHours()).padStart(2,'0')}:${String(time.getMinutes()).padStart(2,'0')}`;
 f.elements.schedule.value='clock';f.elements.minutes.value='30';syncForm();$('#checklistEditor').showModal();f.elements.title.focus()}
function priority(x){const d=x.data||{};if(d.done)return 4;if(d.cycle==='timed')return d.trigger_at<=Date.now()?0:1;if(d.cycle==='daily')return 2;return 3}
function itemRow(ctx,item){const d=item.data||{},late=!d.done&&(d.cycle==='timed'&&d.trigger_at<=Date.now()||d.due&&d.due<localDay()),row=el('div','checklist-row'+(d.done?' done':'')+(late?' late':''));
 const tick=button(d.done?'✓':'',async()=>{try{await ctx.putRecord({...item,data:{...d,done:!d.done}});ctx.renderPage()}catch(e){ctx.toast(e.message);window.dispatchEvent(new Event('lune-workspace'))}},'checklist-tick');tick.setAttribute('aria-label',(d.done?'取消完成：':'完成：')+item.title);
 const main=button('',()=>open(ctx,item),'checklist-main'),title=el('strong','',item.title),meta=el('span','checklist-meta');let detail=cycleName(d);
 if(d.cycle==='timed'){detail+=' · '+localTime(d.trigger_at);if(late)detail+=' · 已过时间'}else if(d.due)detail+=' · '+d.due+(d.time?' '+d.time:'');
 detail+=' · '+(ctx.scopes[item.scope]||item.scope);meta.textContent=detail;main.append(title,meta);
 if(d.cycle==='timed'){const state=el('span','checklist-alarm-state',ctx.relay.enabled?'等待同步':'本机记录 · 未启用提醒');state.dataset.alarmState=item.id;main.append(state)}
 row.append(tick,main);return row}
function loadStates(ctx){if(!ctx.relay.enabled)return;ctx.relay.request('/lune/checklist/alarms').then(result=>{const states=new Map(result.items.map(x=>[x.todo_id,x]));for(const label of document.querySelectorAll('[data-alarm-state]')){const a=states.get(label.dataset.alarmState);label.textContent=!a?'等待同步':({pending:'等待时间',running:'正在联系',delivered:'已发消息',failed:'未能送达',cancelled:'已取消'}[a.state]||a.state)}}).catch(()=>{})}
function render(ctx){wire();current=ctx;rollover(ctx);const {host,toolbar,records}=ctx;$('#pageTitle').textContent='今日清单';$('#pageAdd').onclick=()=>open(ctx);
 for(const [id,label]of [['all','全部'],['user','我的'],['gpt','GPT 的'],['claude','Claude 的']])toolbar.append(button(label,()=>{ctx.setFilter(id);ctx.renderPage()},'filter'+(ctx.filter===id?' active':'')));
 const rows=records.filter(x=>x.kind==='todo'),visible=rows.filter(x=>ctx.filter==='all'||(x.data?.owner||'user')===ctx.filter).sort((a,b)=>priority(a)-priority(b)||(a.data?.trigger_at||0)-(b.data?.trigger_at||0)||(a.created_at||'').localeCompare(b.created_at||''));
 const banner=el('section','checklist-banner');banner.append(el('span','checklist-kicker','A SMALL LIST FOR TODAY'),el('h3','',new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'})),el('p','',`${rows.filter(x=>x.data?.done).length} / ${rows.length} 已完成 · 慢慢做也很好`));banner.append(button('＋ 写下一件事',()=>open(ctx)));host.append(banner);
 const columns=el('div','checklist-columns');const groups=ctx.filter==='all'?[['user','我的清单'],['ai','一起留下的']]:[[ctx.filter,names[ctx.filter]+' 的清单']];
 for(const [id,label]of groups){const column=el('section','checklist-column'),items=visible.filter(x=>id==='ai'?(x.data?.owner||'user')!=='user':(x.data?.owner||'user')===id);column.append(el('h4','',label+' · '+items.filter(x=>!x.data?.done).length));for(const item of items)column.append(itemRow(ctx,item));if(!items.length)column.append(el('p','checklist-empty','这一栏还没有清单项。'));columns.append(column)}host.append(columns);
 $('#pageFoot').textContent=(ctx.relay.enabled?'服务器每 15 秒检查到点项；模型成功生成后保存消息并推送':'本机清单可用；到点消息需连接自己的服务器与模型')+' · 旧待办保持原样';loadStates(ctx)}
window.LuneChecklist={render,open};
})();
