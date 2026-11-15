/* Portable backup for data stored in this browser, including binary media. */
(() => {
 'use strict';
 const stores={
  'emoi-ui-assets':'files',
  'emoi-message-media':'files',
  'emoi-ai-avatars-v1':'pictures',
  'emoi-cloud-cache':'rooms'
 };
 const portableKey=key=>/^(?:emoi-|tidal-)/.test(key)&&!['emoi-secret','emoi-connection'].includes(key);
 function open(name,store){
  return new Promise((resolve,reject)=>{
   const request=indexedDB.open(name,1);
   request.onupgradeneeded=()=>request.result.createObjectStore(store);
   request.onsuccess=()=>resolve(request.result);
   request.onerror=()=>reject(request.error);
  });
 }
 async function transaction(name,action,mode='readonly'){
  const db=await open(name,stores[name]);
  try{
   return await new Promise((resolve,reject)=>{
    const tx=db.transaction(stores[name],mode);
    let result;
    tx.oncomplete=()=>resolve(result);
    tx.onabort=()=>reject(tx.error||Error('本机存储操作中止'));
    result=action(tx.objectStore(stores[name]));
   });
  }finally{db.close()}
 }
 function asBase64(blob){
  return new Promise((resolve,reject)=>{
   const reader=new FileReader();
   reader.onload=()=>resolve(reader.result.split(',',2)[1]);
   reader.onerror=()=>reject(reader.error);
   reader.readAsDataURL(blob);
  });
 }
 async function snapshot(){
  await window.EmoiLegacyStorageReady;
  const storage=Object.fromEntries(Object.keys(localStorage).filter(portableKey).map(key=>[key,localStorage.getItem(key)]));
  const records={};
  for(const name of Object.keys(stores)){
   const rows=await transaction(name,store=>{
    const entries=[];
    store.openCursor().onsuccess=event=>{
     const cursor=event.target.result;
     if(cursor){entries.push([cursor.key,cursor.value]);cursor.continue()}
    };
    return entries;
   });
   records[name]=await Promise.all(rows.map(async ([key,value])=>[key,value instanceof Blob
    ?{base64:await asBase64(value),mime:value.type}:{value}]));
  }
  return {format:'emoi-device-v1',exported_at:new Date().toISOString(),storage,records};
 }
 function readRecords(document){
  if(!document.storage||!document.records)throw Error('本机备份不完整');
  const decoded={};
  for(const [name,rows] of Object.entries(document.records)){
   if(!Object.hasOwn(stores,name)||!Array.isArray(rows))throw Error('备份存储格式无效');
   decoded[name]=rows.map(row=>{
    if(!Array.isArray(row)||row.length!==2||typeof row[0]!=='string'||!row[1]||typeof row[1]!=='object')
     throw Error('备份附件格式无效');
    const [key,item]=row;
    if(Object.hasOwn(item,'base64')){
     const raw=atob(item.base64),bytes=Uint8Array.from(raw,char=>char.charCodeAt(0));
     return [key,new Blob([bytes],{type:item.mime||'application/octet-stream'})];
    }
    if(!Object.hasOwn(item,'value'))throw Error('备份记录格式无效');
    return [key,item.value];
   });
  }
  for(const [key,value] of Object.entries(document.storage))
   if(!portableKey(key)||typeof value!=='string')throw Error('备份设置格式无效');
  return decoded;
 }
 async function restore(backup){
  const rows=readRecords(backup);
  for(const [name,entries] of Object.entries(rows)){
   await transaction(name,store=>{
    for(const [key,value] of entries)store.put(value,key);
   },'readwrite');
  }
  for(const [key,value] of Object.entries(backup.storage))localStorage.setItem(key,value);
 }
 window.EmoiDeviceBackup={snapshot,restore};
})();
