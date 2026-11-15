(() => {
 'use strict';
 const relay=window.EmoiRelay, path='/emoi/v2/worldbooks';
 const newEntry=()=>({title:'',text:'',keys:[],always:false,enabled:true});
 function element(tag,label,className){
  const node=document.createElement(tag);
  if(label)node.textContent=label;
  if(className)node.className=className;
  return node;
 }
 function button(label,action){
  const node=element('button',label,'soft-button');
  node.type='button';node.onclick=action;return node;
 }
 function label(text,input){
  const wrap=element('label',text);wrap.append(input);return wrap;
 }
 function check(text,checked){
  const input=element('input');input.type='checkbox';input.checked=checked;
  const wrap=element('label','', 'ep-worldbook-check');wrap.append(input,text);
  return {input,wrap};
 }
 function edit(book,onSave){
  const dialog=element('dialog','','ep-edit-dialog ep-worldbook-editor');
  dialog.setAttribute('aria-label',book?'编辑世界书':'新建世界书');
  const form=element('form','','form-stack');
  const heading=element('h2',book?'编辑世界书':'新建世界书');
  const name=element('input');name.required=true;name.maxLength=80;name.value=book?.name||'';
  const enabled=check('启用这本世界书',book?.enabled??true);
  const global=check('全局启用',book?.is_global??false);
  const entries=element('div','','ep-worldbook-entries');
  const status=element('p');status.setAttribute('role','status');
  const save=element('button','保存','primary-button');save.type='submit';
  const remove=button('删除世界书',async()=>{
   if(!confirm('删除「'+book.name+'」及其联系人绑定？'))return;
   remove.disabled=true;save.disabled=true;
   try{await relay.request(path+'/'+encodeURIComponent(book.id),{method:'DELETE'});dialog.close();await onSave()}
   catch(error){status.textContent=error.message;remove.disabled=false;save.disabled=false}
  });
  function addEntry(value=newEntry(),expanded=true){
   if(entries.childElementCount>=80){status.textContent='每本最多 80 个条目';return}
   const section=element('details','','ep-worldbook-entry');section.open=expanded;
   const summary=element('summary',value.title||'未命名条目');
   const title=element('input');title.maxLength=80;title.value=value.title;
   title.oninput=()=>{summary.textContent=title.value||'未命名条目'};
   const text=element('textarea');text.rows=5;text.maxLength=6000;text.required=true;text.value=value.text;
   const keys=element('textarea');keys.rows=2;keys.maxLength=2400;keys.value=value.keys.join('，');
   keys.placeholder='用逗号或换行分隔';
   const always=check('常驻条目',value.always), usable=check('启用条目',value.enabled);
   function setKeyState(){keys.disabled=always.input.checked;keys.required=usable.input.checked&&!always.input.checked}
   always.input.onchange=setKeyState;usable.input.onchange=setKeyState;setKeyState();
   for(const [field,node] of Object.entries({title,text,keys,always:always.input,enabled:usable.input}))node.dataset.field=field;
   section.append(summary,label('条目名称',title),usable.wrap,always.wrap,label('触发词',keys),label('条目内容',text),button('移除此条目',()=>section.remove()));
   entries.append(section);
  }
  for(const entry of book?.entries||[])addEntry(entry,false);
  if(!book)addEntry();
  const actions=element('footer');actions.append(button('取消',()=>dialog.close()),save);
  if(book)actions.prepend(remove);
  form.append(heading,label('世界书名称',name),enabled.wrap,global.wrap,
   element('p','全局启用后，每位联系人都可触发此书。也可以在联系人档案里单独勾选。','ep-help'),
   entries,button('添加条目',()=>addEntry()),status,actions);
  form.addEventListener('invalid',event=>{
   const entry=event.target.closest('details');if(entry)entry.open=true;
  },true);
  form.onsubmit=async event=>{
   event.preventDefault();save.disabled=true;remove.disabled=true;status.textContent='';
   const body={name:name.value,enabled:enabled.input.checked,is_global:global.input.checked,
    entries:[...entries.children].map(section=>Object.fromEntries([...section.querySelectorAll('[data-field]')]
     .map(node=>[node.dataset.field,node.type==='checkbox'?node.checked:node.value])))};
   try{
    await relay.json(book?path+'/'+encodeURIComponent(book.id):path,book?'PUT':'POST',body);
    dialog.close();await onSave();
   }catch(error){status.textContent=error.message}
   finally{save.disabled=false;remove.disabled=false}
  };
  dialog.append(form);document.body.append(dialog);
  dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
 }
 async function open({root,header}){
  root.className='ep-view ep-list-screen';root.append(header);
  const body=element('div','','ep-list-scroll ep-worldbook-list');
  root.append(body);
  if(!relay.enabled){body.append(element('p','连接 Émoi 服务器后可管理世界书。'));return}
  const notice=element('p');notice.setAttribute('role','status');
  const list=element('div','','ep-worldbook-items');
  const create=button('新建世界书',()=>edit(null,refresh));create.disabled=true;
  body.append(create,notice,list);
  async function refresh(){
   try{
    const {books}=await relay.request(path);
    list.replaceChildren();create.disabled=false;notice.textContent=books.length?'':'还没有世界书';
    for(const book of books){
     const row=element('button','','ep-settings-panel ep-worldbook-row');row.type='button';
     row.append(element('strong',book.name),
      element('span',(book.enabled?(book.is_global?'全局启用':'按联系人启用'):'已停用')+' · '+book.entries.length+' 个条目'));
     row.onclick=()=>edit(book,refresh);list.append(row);
    }
   }catch(error){notice.textContent=error.message}
  }
  await refresh();
 }
 const pending=new WeakMap();
 async function contactSelector(target,ids){
  const ticket={};pending.set(target,ticket);
  delete target.dataset.ready;
  target.replaceChildren(element('p','正在读取世界书…','ep-help'));
  if(!relay.enabled){target.firstChild.textContent='连接服务器后可选择世界书。';return}
  try{
   const {books}=await relay.request(path);
   if(pending.get(target)!==ticket)return;
   target.replaceChildren();
   for(const book of books){
    const suffix=book.enabled?(book.is_global?'（已全局启用）':''):'（已停用）';
    const {input,wrap}=check(book.name+suffix,ids.includes(book.id));
    input.value=book.id;target.append(wrap);
   }
   if(!books.length)target.append(element('p','可在设置的「世界书」里新建。','ep-help'));
   target.dataset.ready='true';
  }catch(error){if(pending.get(target)===ticket)target.firstChild.textContent=error.message}
 }
 window.EmoiWorldbooks={open,contactSelector};
})();
