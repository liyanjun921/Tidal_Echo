/* Safe, dependency-free rich text shared by every model room.
   Content becomes DOM text nodes; model HTML is never executed. */
(()=>{'use strict';
function inline(host,text,depth=0){
 if(depth>3){host.append(document.createTextNode(text));return}
 const token=/(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|https?:\/\/[^\s<>]+(?:[^\s<>.,，。！？；：]))/g;
 let last=0;for(const m of text.matchAll(token)){
  host.append(document.createTextNode(text.slice(last,m.index)));const s=m[0];let el;
  if(s.startsWith('`')){el=document.createElement('code');el.textContent=s.slice(1,-1)}
  else if(s.startsWith('**')){el=document.createElement('strong');inline(el,s.slice(2,-2),depth+1)}
  else{el=document.createElement('a');let href=s,label=s;if(s.startsWith('[')){const split=s.indexOf('](');label=s.slice(1,split);href=s.slice(split+2,-1)}
   try{const u=new URL(href);if(!['http:','https:'].includes(u.protocol))throw Error();el.href=u.href;el.target='_blank';el.rel='noopener noreferrer';el.textContent=label;
    if(/(^|\.)(music\.163\.com|open\.spotify\.com)$/.test(u.hostname)){el.className='music-link';el.textContent='♫ '+(label===href?'打开音乐链接':label)}
   }catch{el=document.createTextNode(s)}
  }host.append(el);last=m.index+s.length;
 }host.append(document.createTextNode(text.slice(last)));
}
function render(target,text,stream=false){
 target.replaceChildren();text=String(text||'');if(stream){const p=document.createElement('p');p.textContent=text;target.append(p);return}
 const blocks=text.split(/(^```[^\n]*\n[\s\S]*?^```\s*$)/gm);
 for(const block of blocks){if(!block.trim())continue;
  if(block.startsWith('```')){const first=block.indexOf('\n'),language=block.slice(3,first).trim(),code=block.slice(first+1).replace(/\n```\s*$/,'');
   const head=document.createElement('div');head.className='code-head';const label=document.createElement('span');label.textContent=language||'code';const copy=document.createElement('button');copy.type='button';copy.textContent='复制';copy.onclick=()=>navigator.clipboard.writeText(code).then(()=>copy.textContent='已复制').catch(()=>copy.textContent='请长按复制');head.append(label,copy);const pre=document.createElement('pre'),el=document.createElement('code');el.textContent=code;pre.append(el);target.append(head,pre);continue;
  }
  for(const paragraph of block.trim().replace(/\n(?=\s*(?:[-*] |\d+\. ))/g, '\n\n').replace(/(\n\s*[-*] [^\n]+)\n\n(?=\s*[-*] )/g, '$1\n').split(/\n\s*\n/)){
   const lines=paragraph.split('\n');
   if(lines.every(l=>/^\s*[-*] /.test(l))){const list=document.createElement('ul');for(const l of lines){const li=document.createElement('li');inline(li,l.replace(/^\s*[-*] /,''));list.append(li)}target.append(list)}
   else if(lines.every(l=>/^\s*\d+\. /.test(l))){const list=document.createElement('ol');for(const l of lines){const li=document.createElement('li');inline(li,l.replace(/^\s*\d+\. /,''));list.append(li)}target.append(list)}
   else{const heading=/^#{1,4}\s+/.test(paragraph),quote=/^>\s?/.test(paragraph);const el=document.createElement(heading?'h3':quote?'blockquote':'p');inline(el,paragraph.replace(heading?/^#{1,4}\s+/:quote?/^>\s?/gm:/$^/,''));target.append(el)}
  }
 }
}
window.LuneRich={render};
})();
