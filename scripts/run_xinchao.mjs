// Host boundary around the verified, unmodified MIT runtime.
import http from 'node:http';
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
import {createHash,timingSafeEqual} from 'node:crypto';
import path from 'node:path';

process.umask(0o077);
const root=process.env.LUNE_XINCHAO_SOURCE;
const marker=JSON.parse(readFileSync(path.join(path.dirname(root),path.basename(root)+'.lune-verified.json'),'utf8'));
if(marker.revision!=='3acbaf48e92508d678dd5d5a90e13f82d900a370')throw Error('Xinchao revision mismatch');
for(const [file,digest] of Object.entries(marker.files))if(createHash('sha256').update(readFileSync(path.join(root,file))).digest('hex')!==digest)throw Error('Xinchao source verification failed');
const listen=http.Server.prototype.listen;
http.Server.prototype.listen=function(...args){if(args[1]==='0.0.0.0')args[1]='127.0.0.1';return listen.apply(this,args)};
const nativeFetch=globalThis.fetch;
const allowed=new Set([new URL(process.env.OMBRE_MCP_URL).origin,new URL(process.env.LUNE_XINCHAO_PROVIDER).origin]);
globalThis.fetch=async (input,options={})=>{
 const url=new URL(input instanceof Request?input.url:input);
 if(!allowed.has(url.origin))throw Error('This integration has no configured external destination');
 return nativeFetch(input,{...options,redirect:'error'});
};
const {OmbreClient,parseSurfacedDomains}=await import(pathToFileURL(path.join(root,'xinchao/src/ombre-client.js')));
const {StateStore}=await import(pathToFileURL(path.join(root,'xinchao/src/state-store.js')));
const {applyOutputReflux,applyMemoryResonance,topDrives}=await import(pathToFileURL(path.join(root,'xinchao/src/engine.js')));
const {TransitionJournal}=await import(pathToFileURL(path.join(root,'xinchao/src/transition-journal.js')));
let nativeState;
const originalRead=StateStore.prototype.read;
StateStore.prototype.read=function(...args){if(this.path===process.env.STATE_PATH)nativeState=this;return originalRead.apply(this,args)};
const hostJournal=new TransitionJournal(process.env.TRANSITION_JOURNAL_PATH);
const emit=http.Server.prototype.emit;
http.Server.prototype.emit=function(event,...args){
 if(event!=='request'||!args[0].url.startsWith('/lune-host/'))return emit.call(this,event,...args);
 const [request,response]=args;
 (async()=>{
  const expected=Buffer.from('Bearer '+process.env.SERVICE_TOKEN),supplied=Buffer.from(String(request.headers.authorization||''));
  if(supplied.length!==expected.length||!timingSafeEqual(supplied,expected)){response.writeHead(401);return response.end()}
  if(request.method!=='POST'||!['/lune-host/reflux','/lune-host/resonance'].includes(request.url)){response.writeHead(404);return response.end()}
  let raw='';for await(const chunk of request){raw+=chunk;if(raw.length>50000)throw Error('Host projection too large')}
  const input=JSON.parse(raw);
  if(typeof input.id!=='string'||input.id.length>160||typeof input.text!=='string'||input.text.length>24000)throw Error('Invalid host evidence');
  let before,applied=false;
  const now=new Date();
  const after=await nativeState.update(current=>{
   before=structuredClone(current);
   const ids=Array.isArray(current.luneHostReceipts)?current.luneHostReceipts:[];
   if(ids.includes(input.id))return current;
   const result=request.url.endsWith('reflux')
    ?applyOutputReflux(current,topDrives(current)[0]?.key,input.text.slice(0,2000),now,.30)
    :applyMemoryResonance(current,parseSurfacedDomains(input.text),now,{nudge:.02,perCallCap:.06});
   const state=result.state??result;state.luneHostReceipts=[...ids,input.id].slice(-256);applied=true;return state;
  });
  await hostJournal.recordTransition({before,after,type:request.url.endsWith('reflux')?'output_reflux':'memory_resonance',source:'lune-host',eventId:input.id,details:{changed:applied},at:now});
  response.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});response.end(JSON.stringify({applied,revision:after.revision}));
 })().catch(()=>{if(!response.headersSent)response.writeHead(400);response.end(JSON.stringify({error:'Host evidence not applied'}))});
 return true;
};
const originalCall=OmbreClient.prototype.call;
OmbreClient.prototype.call=async function(name,args={},timeout){
 // Keep current Ombre's tool schemas/permissions; the bundled older fork is not started.
 if(!this.luneSchemas)this.luneSchemas=Object.fromEntries((await this.listTools()).map(t=>[t.name,new Set(Object.keys(t.inputSchema?.properties||{}))]));
 if((name==='breath'&&Object.keys(args).length||name==='breath_search'&&('valence'in args||'arousal'in args))&&this.luneSchemas.breath_advanced)name='breath_advanced';
 const fields=this.luneSchemas[name];
 const adapted=fields?Object.fromEntries(Object.entries(args).filter(([key])=>fields.has(key))):args;
 return originalCall.call(this,name,adapted,timeout);
};
async function memory(kind,id=''){
 const url=process.env.LUNE_XINCHAO_PROVIDER+'/memory/'+kind+(id?'?id='+encodeURIComponent(id):'');
 const response=await fetch(url,{headers:{Authorization:'Bearer '+process.env.MODEL_API_KEY}});
 if(!response.ok)throw Error('Existing Ombre memory projection unavailable');
 return response.json();
}
OmbreClient.prototype.fetchBucketMapStructured=()=>memory('map');
// Current vaults are local; fetch the real map directly, including an empty vault.
OmbreClient.prototype.memoryMap=()=>memory('map');
OmbreClient.prototype.memoryBucketPreview=(_id)=>memory('preview',_id);
await import(pathToFileURL(path.join(root,'xinchao/src/server.js')));
