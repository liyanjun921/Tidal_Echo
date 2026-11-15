(() => {
 'use strict';
 const relay=window.EmoiRelay, path='/emoi/v2/albums';
 function el(tag,text){const node=document.createElement(tag);if(text)node.textContent=text;return node}
 async function upload(file){
  if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>12*1024*1024)
   throw Error('请选择 12 MB 内的 JPG、PNG 或 WebP 图片');
  const result=await relay.upload(file);
  return result.url.split('/').pop();
 }
 async function uploadFields(form){
  const fields={};
  for(const input of form.querySelectorAll('[data-profile-picture]')){
   if(input.files[0])fields[input.name]=await upload(input.files[0]);
  }
  return fields;
 }
 async function open({root,header,contacts}){
  root.className='ep-view ep-list-screen';root.append(header);
  const body=el('div');body.className='ep-list-scroll';root.append(body);
  if(!relay.enabled){body.append(el('p','连接私人服务器后可使用共享相册。'));return}
  const status=el('p');status.setAttribute('role','status');
  const settings=el('details');settings.className='ep-album-settings';settings.append(el('summary','相册设置'));
  const report=el('p');report.setAttribute('role','status');
  const tabs=el('nav');tabs.className='ep-album-tabs';tabs.setAttribute('aria-label','相册视图');
  const library=el('button','图库'), collections=el('button','精选集');
  tabs.append(library,collections);
  const form=el('form');form.className='form-stack';
  const name=el('input');name.required=true;name.maxLength=80;name.placeholder='相册名称';name.setAttribute('aria-label','相册名称');
  const create=el('button','新建相册');create.className='soft-button';form.append(name,create);
  const controls=el('form');controls.className='form-stack';
  const album=el('select');album.setAttribute('aria-label','查看相册');
  const file=el('input');file.type='file';file.accept='image/jpeg,image/png,image/webp';file.required=true;file.setAttribute('aria-label','上传相册照片');
  const person=el('select');person.setAttribute('aria-label','标记联系人');person.add(new Option('不标记人物',''));
  for(const contact of contacts)person.add(new Option(contact.name,contact.id));
  const vision=el('select');vision.setAttribute('aria-label','人物识别 API');vision.add(new Option('选择人物识别 API',''));
  const automatic=el('input');automatic.type='checkbox';
  const autoLabel=el('label');autoLabel.append(automatic,'上传时自动按联系人的参考图分类');
  const visionKey='emoi-album-vision';
  let preferences={};
  try{preferences=JSON.parse(localStorage.getItem(visionKey)||'{}')}catch{}
  automatic.checked=preferences.automatic===true;
  const identify=el('button','建议照片人物');identify.type='button';identify.className='soft-button';
  void window.EmoiModelConnections?.load().then(rows=>{
   for(const row of rows)vision.add(new Option(row.name+' · '+row.model,row.id));
   vision.value=preferences.route||'';
  }).catch(()=>{});
  const submit=el('button','添加照片');submit.className='soft-button';
  controls.append(album,file,identify,person,submit);
  const savePreferences=()=>{preferences={route:vision.value,automatic:automatic.checked};localStorage.setItem(visionKey,JSON.stringify(preferences))};
  automatic.onchange=()=>{
   if(automatic.checked&&(!vision.value||!confirm('开启后，新照片和联系人的脸部参考图会发给所选视觉 API 进行分类。是否开启？')))automatic.checked=false;
   savePreferences();
  };
  vision.onchange=()=>{automatic.checked=false;savePreferences()};
  let uploaded=null;
  async function uploadSelected(){
   const selected=file.files[0];
   if(!selected)throw Error('请先选择照片');
   if(uploaded?.file===selected)return uploaded.id;
   const id=await upload(selected);uploaded={file:selected,id};return id;
  }
  identify.onclick=async()=>{
   if(!vision.value||!file.files[0]){status.textContent='请选择照片与支持视觉的 API';return}
   if(!confirm('将这张照片和候选联系人的脸部参考图发给所选 API，生成标记建议？'))return;
   identify.disabled=true;submit.disabled=true;status.textContent='正在比对参考图…';
   const current=file.files[0], model_route=vision.value;
   try{
    const id=await uploadSelected();
    const result=await relay.json(path+'/suggest-person','POST',{id,model_route});
    if(current!==file.files[0])return;
    if(result.contact_id&&contacts.some(contact=>contact.id===result.contact_id)){
     person.value=result.contact_id;status.textContent='已填入模型建议，请检查后再保存';
    }else status.textContent='没有找到可信匹配，可手动标记';
   }catch(error){status.textContent=error.message}
   finally{identify.disabled=false;submit.disabled=false}
  };
  const content=el('div');content.className='ep-album-content';
  settings.append(form,vision,autoLabel,controls,status);
  body.append(settings,report,content,tabs);
  let photos=[],albums=[],view='collections',selection=null;
  function openPhoto(photo){
   const dialog=el('dialog');dialog.className='ep-edit-dialog ep-album-photo';dialog.setAttribute('aria-label','查看照片');
   const picture=imageFor(photo);picture.alt='相册照片';
   const actions=el('div');actions.className='settings-actions';
   const close=el('button','关闭');close.className='soft-button';close.onclick=()=>dialog.close();
   const message=el('p');message.setAttribute('role','status');
   const favorite=el('button',photo.favorite?'取消收藏':'收藏');favorite.className='soft-button';
   favorite.onclick=async()=>{
    favorite.disabled=true;
    try{
     const result=await relay.json(path+'/photos/'+encodeURIComponent(photo.id),'PATCH',{favorite:!photo.favorite});
     photo.favorite=result.favorite;favorite.textContent=photo.favorite?'取消收藏':'收藏';
     if(selection?.label==='个人收藏')selection.items=photos.filter(item=>item.favorite);
     paint();
    }catch(error){message.textContent=error.message}
    finally{favorite.disabled=false}
   };
   actions.append(favorite,close);dialog.append(picture,actions,message);document.body.append(dialog);
   dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
  }
  function imageFor(photo){
   const image=el('img');image.alt='';image.loading='lazy';
   if(photo)void relay.media(photo.attachment).then(src=>{image.src=src}).catch(()=>{image.alt='图片暂不可用'});
   return image;
  }
  function tile(label,items){
   const button=el('button');button.type='button';button.className='ep-album-cover';
   button.append(imageFor(items[0]),el('span',label));
   button.onclick=()=>{selection={label,items};paint()};
   return button;
  }
  function section(title,tiles,empty){
   const area=el('section');area.append(el('h2',title));
   const row=el('div');row.className='ep-album-strip';row.append(...tiles);
   area.append(tiles.length?row:el('p',empty));content.append(area);
  }
  function paint(){
   content.replaceChildren();
   library.setAttribute('aria-pressed',String(view==='library'));
   collections.setAttribute('aria-pressed',String(view==='collections'));
   if(view==='library'||selection){
    if(selection){
     const back=el('button','‹ 精选集');back.className='soft-button';back.onclick=()=>{selection=null;paint()};
     content.append(back,el('h2',selection.label));
    }
    const grid=el('div');grid.className='ep-album-grid';
    for(const photo of selection?.items??photos){
     const figure=el('figure'),image=imageFor(photo);
     const caption=contacts.find(contact=>contact.id===photo.contact_id)?.name;
     const open=el('button');open.className='ep-album-thumbnail';open.setAttribute('aria-label',caption?'查看 '+caption+' 的照片':'查看照片');
     open.onclick=()=>openPhoto(photo);open.append(image);
     figure.append(open);if(caption)figure.append(el('figcaption',caption));grid.append(figure);
    }
    content.append(grid.children.length?grid:el('p','还没有照片。可在相册设置里添加。'));
    return;
   }
   section('固定',[tile('个人收藏',photos.filter(item=>item.favorite)),tile('最近保存',photos)],'');
   section('相簿',albums.map(item=>tile(item.name,photos.filter(photo=>photo.album_id===item.id))),'还没有相簿');
   section('人物',contacts.map(contact=>[contact,photos.filter(photo=>photo.contact_id===contact.id)])
     .filter(([,items])=>items.length).map(([contact,items])=>tile(contact.name,items)),'标记人物的照片会自动归在这里');
  }
  library.onclick=()=>{view='library';selection=null;paint()};
  collections.onclick=()=>{view='collections';selection=null;paint()};
  async function refresh(selected=album.value){
   const result=await relay.request(path);photos=result.photos;albums=result.albums;
   album.replaceChildren();
   for(const item of albums)album.add(new Option(item.name,item.id));
   if(albums.some(item=>item.id===selected))album.value=selected;
   controls.hidden=!albums.length;
   selection=null;paint();
  }
  form.onsubmit=async event=>{
   event.preventDefault();create.disabled=true;
   try{const item=await relay.json(path,'POST',{name:name.value});name.value='';await refresh(item.id);status.textContent='相册已创建'}
   catch(error){status.textContent=error.message}finally{create.disabled=false}
  };
  controls.onsubmit=async event=>{
   event.preventDefault();submit.disabled=true;
   const selected=album.value;let contact_id=person.value;
   try{
    const id=await uploadSelected();
    let recognitionFailed=false;
    if(!contact_id&&automatic.checked&&vision.value){
     try{
      const match=await relay.json(path+'/suggest-person','POST',{id,model_route:vision.value});
      contact_id=contacts.some(contact=>contact.id===match.contact_id)?match.contact_id:'';
     }catch{recognitionFailed=true}
    }
    await relay.json(path+'/'+encodeURIComponent(selected)+'/photos','POST',{id,contact_id});
    file.value='';person.value='';uploaded=null;await refresh(selected);
    report.textContent=recognitionFailed?'照片已保存，视觉 API 未能分类':'照片已保存';
   }catch(error){status.textContent=error.message}finally{submit.disabled=false}
  };
  try{await refresh()}catch(error){status.textContent=error.message}
 }
 window.EmoiAlbums={open,uploadFields};
})();
