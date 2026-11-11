/* Émoi optical liquid glass. Independent implementation guided by user-supplied PDF.
   Shared wallpaper source, position-aware sampling, WebGL refraction, disposal + fallback.
*/
(()=>{
'use strict';
const phone=document.getElementById('emoiPhone');if(!phone)return;
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
const forced=matchMedia('(forced-colors: active)');
const instances=new Map();let bg=null,bgImage=null,bgUrl='',sourceTurn=0,enabled=false,raf=0;
const VS='#version 300 es\nin vec2 position;\nout vec2 uv;\nvoid main(){uv=(position+1.0)*0.5;gl_Position=vec4(position,0.0,1.0);}';
const FS='#version 300 es\nprecision highp float;\nin vec2 uv;\nout vec4 outColor;\nuniform sampler2D source;\nuniform vec2 res;\nuniform float radius;\nuniform float phase;\nfloat rounded(vec2 p,vec2 size,float r){vec2 q=abs(p)-size+r;return length(max(q,0.0))+min(max(q.x,q.y),0.0)-r;}\nvoid main(){vec2 p=uv*res;float d=rounded(p-res*0.5,res*0.5,min(radius,min(res.x,res.y)*0.5));float mask=1.0-smoothstep(-0.9,0.9,d);float edge=1.0-smoothstep(-min(res.x,res.y)*0.43,0.0,d);vec2 q=(p-res*0.5)/res;float w=sin(uv.y*8.0+phase*0.48)*cos(uv.x*6.0-phase*0.29);vec2 refraction=q*0.008*(0.18+edge*0.82)+vec2(w,-w)*0.0006*edge;vec3 back=texture(source,clamp(uv+refraction,vec2(0.0),vec2(1.0))).rgb;float line=exp(-pow((d+0.85)/1.6,2.0));float topLeft=pow(max(0.0,(1.0-uv.x)*(1.0-uv.y)),1.8);float bottomRight=pow(max(0.0,uv.x*uv.y),1.6);float glint=line*(topLeft*0.74+bottomRight*0.32);vec3 color=mix(back,vec3(0.97,0.99,1.0),0.065);color=mix(color,vec3(1.0),clamp(glint*0.61,0.0,0.64));float a=mask*(0.42+glint*0.15);outColor=vec4(color,a);}';
function shader(gl,type,src){
 const sh=gl.createShader(type);gl.shaderSource(sh,src);gl.compileShader(sh);
 if(!gl.getShaderParameter(sh,gl.COMPILE_STATUS)){gl.deleteShader(sh);return null}return sh;
}
function setup(gl){
 const v=shader(gl,gl.VERTEX_SHADER,VS),f=shader(gl,gl.FRAGMENT_SHADER,FS);if(!v||!f)return null;
 const p=gl.createProgram();gl.attachShader(p,v);gl.attachShader(p,f);gl.linkProgram(p);
 gl.deleteShader(v);gl.deleteShader(f);if(!gl.getProgramParameter(p,gl.LINK_STATUS)){gl.deleteProgram(p);return null}
 return p;
}
function currentUrl(){
 let value=getComputedStyle(document.documentElement).getPropertyValue('--emoi-active-wallpaper').trim();
 if(!value||value.includes('var('))value=getComputedStyle(document.documentElement).getPropertyValue('--wallpaper').trim();
 const m=value.match(/url\(\s*['"]?([^'")]+)['"]?\s*\)/);
 return m?m[1]:'';
}
function drawBackground(){
 const rect=phone.getBoundingClientRect();if(rect.width<20||rect.height<20)return;
 bg=bg||document.createElement('canvas');
 bg.width=Math.round(rect.width);bg.height=Math.round(rect.height);
 const ctx=bg.getContext('2d',{alpha:false});if(!ctx)return;
 const grad=ctx.createLinearGradient(0,0,bg.width,bg.height);
 grad.addColorStop(0,'#f0f7fb');grad.addColorStop(0.48,'#c7dbea');grad.addColorStop(1,'#a1bed7');
 ctx.fillStyle=grad;ctx.fillRect(0,0,bg.width,bg.height);
 if(bgImage&&bgImage.complete&&bgImage.naturalWidth>0){
  const scale=Math.max(bg.width/bgImage.naturalWidth,bg.height/bgImage.naturalHeight);
  const width=bgImage.naturalWidth*scale,height=bgImage.naturalHeight*scale;
  ctx.drawImage(bgImage,(bg.width-width)/2,(bg.height-height)/2,width,height);
 }
 ctx.fillStyle='rgba(238,245,252,.11)';ctx.fillRect(0,0,bg.width,bg.height);
}
function loadBackground(){
 const url=currentUrl();if(url===bgUrl&&bg)return;
 bgUrl=url;const turn=++sourceTurn;
 if(!url){bgImage=null;drawBackground();schedule();return}
 const im=new Image();
 im.onload=()=>{if(sourceTurn!==turn)return;bgImage=im;drawBackground();schedule()};
 im.onerror=()=>{if(sourceTurn!==turn)return;bgImage=null;drawBackground();schedule()};
 im.src=url;
 if(!bg){bgImage=null;drawBackground()}
}
function attach(target){
 if(instances.has(target))return;
 const canvas=document.createElement('canvas');canvas.className='ep-optical-canvas';canvas.setAttribute('aria-hidden','true');
 const gl=canvas.getContext('webgl2',{alpha:true,premultipliedAlpha:false,antialias:false,depth:false,stencil:false,powerPreference:'low-power'});
 if(!gl)return;
 const program=setup(gl);if(!program)return;
 const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
 gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
 gl.useProgram(program);const loc=gl.getAttribLocation(program,'position');
 gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
 const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);
 gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
 gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
 gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
 gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
 const uniforms={source:gl.getUniformLocation(program,'source'),res:gl.getUniformLocation(program,'res'),radius:gl.getUniformLocation(program,'radius'),phase:gl.getUniformLocation(program,'phase')};
 const item={target,canvas,gl,program,buffer,texture,uniforms,visible:true};
 target.prepend(canvas);instances.set(target,item);
 item.resize=new ResizeObserver(schedule);item.resize.observe(target);
 item.observer=new IntersectionObserver(e=>{item.visible=!!e[0]?.isIntersecting;schedule()},{threshold:0,root:phone});item.observer.observe(target);
 canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();dispose(item)},{once:true});
 schedule();
}
function dispose(item){
 item.resize?.disconnect();item.observer?.disconnect();
 if(instances.get(item.target)!==item)return;
 instances.delete(item.target);item.target.removeAttribute('data-ep-optics-ready');item.canvas.remove();
 const gl=item.gl;try{gl.deleteTexture(item.texture);gl.deleteBuffer(item.buffer);gl.deleteProgram(item.program)}catch{}
}
function draw(item,now){
 if(!bg||!item.visible||!item.target.isConnected)return;
 const rect=item.target.getBoundingClientRect(),parent=phone.getBoundingClientRect();
 const w=Math.round(rect.width),h=Math.round(rect.height);if(w<16||h<16||w>900||h>900)return;
 const scale=Math.min(devicePixelRatio||1,1.5),cw=Math.round(w*scale),ch=Math.round(h*scale);
 const {canvas,gl,program,texture,uniforms}=item;
 if(canvas.width!==cw||canvas.height!==ch){canvas.width=cw;canvas.height=ch}
 const local=document.createElement('canvas');local.width=cw;local.height=ch;
 const ctx=local.getContext('2d');if(!ctx)return;
 const sx=(rect.left-parent.left)*bg.width/parent.width;
 const sy=(rect.top-parent.top)*bg.height/parent.height;
 ctx.drawImage(bg,sx,sy,w*bg.width/parent.width,h*bg.height/parent.height,0,0,cw,ch);
 gl.viewport(0,0,cw,ch);gl.useProgram(program);gl.bindTexture(gl.TEXTURE_2D,texture);
 gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
 gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,local);
 const radius=parseFloat(getComputedStyle(item.target).borderTopLeftRadius)||22;
 gl.uniform1i(uniforms.source,0);gl.uniform2f(uniforms.res,cw,ch);
 gl.uniform1f(uniforms.radius,Math.min(radius,70)*scale);gl.uniform1f(uniforms.phase,now/1000);
 gl.disable(gl.BLEND);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);gl.drawArrays(gl.TRIANGLES,0,6);
 item.target.setAttribute('data-ep-optics-ready','1');
}
function schedule(){
 if(raf||!enabled||document.hidden)return;
 raf=requestAnimationFrame(t=>{raf=0;for(const item of [...instances.values()]){
  if(!item.target.isConnected){dispose(item);continue}
  draw(item,t);
 }});
}
function refresh(){
 const supported=!!document.createElement('canvas').getContext('webgl2');
 enabled=supported&&!reduced.matches&&!forced.matches&&document.body.dataset.uiMode==='phone'&&document.body.dataset.phoneScreen==='home';
 if(!enabled){for(const item of [...instances.values()])dispose(item);return}
 loadBackground();
 const targets=[...phone.querySelectorAll('[data-ep-optics]')].slice(0,7);
 for(const item of [...instances.values()])if(!targets.includes(item.target))dispose(item);
 for(const target of targets)attach(target);
 schedule();
}
let debounce;
const obs=new MutationObserver(mutations=>{
 // Never spin because our own canvas was added.
 if(mutations.every(m=>m.type==='childList'&&[...m.addedNodes].every(n=>n.nodeName==='CANVAS')))return;
 clearTimeout(debounce);debounce=setTimeout(refresh,30);
});
function init(){
 obs.observe(phone,{childList:true,subtree:true});
 obs.observe(document.documentElement,{attributes:true,attributeFilter:['style']});
 obs.observe(document.body,{attributes:true,attributeFilter:['data-phone-screen','data-ui-mode']});
 window.addEventListener('resize',()=>{drawBackground();refresh()},{passive:true});
 phone.addEventListener('scroll',schedule,{passive:true,capture:true});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
 reduced.addEventListener?.('change',refresh);forced.addEventListener?.('change',refresh);
 refresh();
}
window.EmoiOptics={refresh:()=>{bgUrl='';loadBackground();drawBackground();refresh()},dispose:()=>{obs.disconnect();for(const i of [...instances.values()])dispose(i)}};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
