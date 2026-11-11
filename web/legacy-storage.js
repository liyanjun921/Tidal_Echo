/* One-time, non-destructive client-side migration for Émoi's former identifiers.
   Keep the source values/databases as rollback copies; do not send them away. */
(()=>{
  'use strict';
  for (const storageType of ['localStorage', 'sessionStorage']) {
    try {
      const store = window[storageType];
      const keys = Array.from({length:store.length}, (_,i)=>store.key(i)).filter(Boolean);
      for (const oldKey of keys) {
        if (!oldKey.startsWith('lune-')) continue;
        const newKey = 'emoi-' + oldKey.slice(5);
        if (store.getItem(newKey) === null) store.setItem(newKey, store.getItem(oldKey));
      }
    } catch (_) { /* private browsing or storage disabled: leave data untouched */ }
  }
  // Retain the safety boundary of prior static preview builds.
  if (window.LUNE_PREVIEW === true) window.EMOI_PREVIEW = true;

  const open = (name) => new Promise((resolve,reject)=>{
    const req=indexedDB.open(name);
    req.onsuccess=()=>resolve(req.result);
    req.onerror=()=>reject(req.error);
    req.onblocked=()=>reject(new Error('IndexedDB busy'));
  });
  const copyStore = async(oldName,newName,store)=>{
    if (!window.indexedDB) return;
    if (typeof indexedDB.databases === 'function') {
      const names=(await indexedDB.databases()).map(x=>x.name);
      if (!names.includes(oldName)) return;
    }
    const older=await open(oldName);
    try {
      if (!older.objectStoreNames.contains(store)) return;
      const rows=await new Promise((resolve,reject)=>{
        const tx=older.transaction(store,'readonly');
        const req=tx.objectStore(store).openCursor();
        const found=[];
        req.onsuccess=()=>{
          const cursor=req.result;
          if (!cursor){resolve(found);return}
          found.push([cursor.key,cursor.value]);cursor.continue();
        };
        req.onerror=()=>reject(req.error);
      });
      if (!rows.length) return;
      const newer=await new Promise((resolve,reject)=>{
        const req=indexedDB.open(newName,1);
        req.onupgradeneeded=()=>{
          if (!req.result.objectStoreNames.contains(store)) req.result.createObjectStore(store);
        };
        req.onsuccess=()=>resolve(req.result);
        req.onerror=()=>reject(req.error);
      });
      try {
        if (!newer.objectStoreNames.contains(store)) return;
        await new Promise((resolve,reject)=>{
          const tx=newer.transaction(store,'readwrite');
          const object=tx.objectStore(store);
          for (const [key,value] of rows){
            const test=object.get(key);
            test.onsuccess=()=>{ if(test.result === undefined) object.put(value,key) };
          }
          tx.oncomplete=()=>resolve();
          tx.onerror=()=>reject(tx.error);
        });
      } finally {newer.close()}
    } finally {older.close()}
  };
  window.EmoiLegacyStorageReady = Promise.all([
    copyStore('lune-ui-assets','emoi-ui-assets','files'),
    copyStore('lune-cloud-cache','emoi-cloud-cache','rooms')
  ]).catch(()=>{/* failure leaves old data accessible for manual recovery */});
})();
