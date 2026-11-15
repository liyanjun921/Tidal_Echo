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
  const form=el('form');form.className='form-stack';
  const name=el('input');name.required=true;name.maxLength=80;name.placeholder='相册名称';name.setAttribute('aria-label','相册名称');
  const create=el('button','新建相册');create.className='soft-button';form.append(name,create);
  const controls=el('form');controls.className='form-stack';
  const album=el('select');album.setAttribute('aria-label','查看相册');
  const file=el('input');file.type='file';file.accept='image/jpeg,image/png,image/webp';file.required=true;file.setAttribute('aria-label','上传相册照片');
  const person=el('select');person.setAttribute('aria-label','标记联系人');person.add(new Option('不标记人物',''));
  for(const contact of contacts)person.add(new Option(contact.name,contact.id));
  const vision=el('select');vision.setAttribute('aria-label','人物识别 API');vision.add(new Option('选择人物识别 API',''));
  const identify=el('button','建议照片人物');identify.type='button';identify.className='soft-button';
  void window.EmoiModelConnections?.load().then(rows=>{
   for(const row of rows)vision.add(new Option(row.name+' · '+row.model,row.id));
  }).catch(()=>{});
  const submit=el('button','添加照片');submit.className='soft-button';
  controls.append(album,file,vision,identify,person,submit);
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
  const grid=el('div');grid.className='ep-album-grid';
  body.append(form,controls,status,grid);
  let photos=[];
  function paint(){
   grid.replaceChildren();
   for(const photo of photos.filter(item=>item.album_id===album.value)){
    const figure=el('figure'),image=el('img');image.alt='';image.loading='lazy';
    const caption=contacts.find(contact=>contact.id===photo.contact_id)?.name;
    figure.append(image);if(caption)figure.append(el('figcaption',caption));grid.append(figure);
    void relay.media(photo.attachment).then(src=>{image.src=src}).catch(()=>{image.alt='图片暂不可用'});
   }
  }
  async function refresh(selected=album.value){
   const result=await relay.request(path);photos=result.photos;
   album.replaceChildren();
   for(const item of result.albums)album.add(new Option(item.name,item.id));
   if(result.albums.some(item=>item.id===selected))album.value=selected;
   controls.hidden=!result.albums.length;
   paint();
  }
  album.onchange=paint;
  form.onsubmit=async event=>{
   event.preventDefault();create.disabled=true;
   try{const item=await relay.json(path,'POST',{name:name.value});name.value='';await refresh(item.id);status.textContent='相册已创建'}
   catch(error){status.textContent=error.message}finally{create.disabled=false}
  };
  controls.onsubmit=async event=>{
   event.preventDefault();submit.disabled=true;
   const selected=album.value,contact_id=person.value;
   try{
    const id=await uploadSelected();
    await relay.json(path+'/'+encodeURIComponent(selected)+'/photos','POST',{id,contact_id});
    file.value='';uploaded=null;await refresh(selected);status.textContent='照片已保存';
   }catch(error){status.textContent=error.message}finally{submit.disabled=false}
  };
  try{await refresh()}catch(error){status.textContent=error.message}
 }
 window.EmoiAlbums={open,uploadFields};
})();
