const $=s=>document.querySelector(s);
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(p,b){const r=await fetch(p,b?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}:{});let j={};try{j=await r.json()}catch(e){}
  if(!r.ok)throw Object.assign(new Error(j.error||"error"),{status:r.status});return j}
const LET=["a","b","c","d"],SHAPE={a:"▲",b:"◆",c:"●",d:"■"};
const imgTag=q=>q.image?`<img class="qimg" src="${esc(q.image.startsWith("/")?q.image:"/"+q.image)}" alt="">`:"";
async function joinInfo(el){
  const i=await api("/api/info");
  el.innerHTML=`<small>Network: <b>${esc(i.mode.toUpperCase())}</b> — players open:</small><h2 style="margin:6px 0;word-break:break-all">${esc(i.url)}</h2>`+(i.present?"":`<p style="color:#f77">⚠ ${esc(i.ip)} is not an address on this laptop right now. Found: ${esc(i.others.join(", ")||"none")}. Check the hotspot/router connection or config.json.</p>`);
  return i}
function boardTable(rows,me){return`<table><tr><th>#</th><th>NAME</th><th>SCORE</th></tr>${rows.map(r=>`<tr class="${r.name==me?"me":""}"><td>${r.rank}</td><td>${esc(r.name)}</td><td>${r.score}</td></tr>`).join("")}</table>`}
function optsHtml(q,mode,pick){ // mode: "btn" (players) | "show"
  return`<div class="opts">${LET.map(c=>{const cor=q.correct,dim=cor&&c!=cor||(!cor&&pick&&c!=pick);
    return`<button class="opt ${c} ${dim?"dim":""} ${cor&&c==cor?"ok":""}" data-c="${c}" ${mode=="btn"?"":"disabled"}>${SHAPE[c]} ${esc(q.options[c])}${q.counts?`<small>${q.counts[c]}</small>`:""}</button>`}).join("")}</div>`}
function animBar(getFrac){const f=()=>{const el=$("#bar i");if(el)el.style.width=Math.max(0,100*getFrac())+"%";requestAnimationFrame(f)};f()}