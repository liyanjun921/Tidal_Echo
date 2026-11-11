/* Émoi private identity pictures. Stored ONLY on this device in IndexedDB.
   Model/API keys and private image data are never sent to GitHub or a connector.
*/
(()=>{
'use strict';
const DB='emoi-ai-avatars-v1',STORE='pictures',MAX=6*1024*1024;
const open=()=>new Promise((resolve,reject)=>{
 const req=indexedDB.open(DB,1);
 req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains(STORE))req.result.createObjectStore(STORE)};
 req.onsuccess=()=>resolve(req.result);
 req.onerror=()=>reject(req.error||new Error('头像库不可用'));
});
async function transaction(id,value,write){
 const db=await open();
 try{
  return await new Promise((resolve,reject)=>{
   const tr=db.transaction(STORE,write?'readwrite':'readonly');
   const req=write?tr.objectStore(STORE).put(value,id):tr.objectStore(STORE).get(id);
   req.onerror=()=>reject(req.error);
   tr.oncomplete=()=>resolve(write?true:req.result);
   tr.onerror=()=>reject(tr.error);
  });
 }finally{db.close()}
}
async function save(id,file){
 if(typeof id!=='string'||!file||!/^image\/(?:png|jpe?g|webp)$/.test(file.type)||file.size>MAX)
   throw Error('头像支持 JPG、PNG、WebP，文件最多 6 MB');
 const bitmap=await createImageBitmap(file);
 const cnv=document.createElement('canvas');cnv.width=256;cnv.height=256;
 const ctx=cnv.getContext('2d');if(!ctx){bitmap.close();throw Error('当前设备无法处理图片')}
 const side=Math.min(bitmap.width,bitmap.height),x=(bitmap.width-side)/2,y=(bitmap.height-side)/2;
 ctx.drawImage(bitmap,x,y,side,side,0,0,256,256);bitmap.close();
 const blob=await new Promise(resolve=>cnv.toBlob(resolve,'image/jpeg',.85));
 if(!blob)throw Error('头像转换失败');
 return transaction(id,blob,true);
}
const painted=new WeakMap();
async function paint(element,id){
 if(!element||!id)return;
 try{
  const blob=await transaction(id,null,false);
  if(!(blob instanceof Blob)||!element.isConnected)return;
  const old=painted.get(element);if(old)URL.revokeObjectURL(old);
  const url=URL.createObjectURL(blob);painted.set(element,url);
  element.textContent='';const img=document.createElement('img');
  img.src=url;img.alt='';img.className='ep-avatar-image';
  element.append(img);
 }catch{}
}
function release(element){
 const url=painted.get(element);if(url){URL.revokeObjectURL(url);painted.delete(element)}
}
window.EmoiAvatars={save,paint,release};
})();
