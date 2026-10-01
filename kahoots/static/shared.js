const $=s=>document.querySelector(s);
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(p,b){const r=await fetch(p,b?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)}:{});let j={};try{j=await r.json()}catch(e){}
  if(!r.ok)throw Object.assign(new Error(j.error||"error"),{status:r.status});return j}
const LET=["a","b","c","d"],SHAPE={a:"▲",b:"◆",c:"●",d:"■"};
const imgTag=q=>q.image?`<img class="qimg" src="${esc(q.image.startsWith("/")?q.image:"/"+q.image)}" alt="">`:"";
function qrSvg(t){const q=qrcode(0,"M");q.addData(t);q.make();return q.createSvgTag(6,2)}
function wifiStr(i){const e=s=>s.replace(/([\\;,:"])/g,"\\$1");return i.password?`WIFI:T:${i.security||"WPA"};S:${e(i.ssid)};P:${e(i.password)};;`:`WIFI:T:nopass;S:${e(i.ssid)};;`}
async function joinPanel(el,ip){ // two QR codes: join WiFi, then open the game
  const i=await api("/api/info");ip=ip||i.ip;const url=`http://${ip}${i.port==80?"":":"+i.port}/`;
  el.innerHTML=`<div class="qrs"><div><h3>1 · Join WiFi</h3>${qrSvg(wifiStr(i))}<p>${esc(i.ssid)}</p></div><div><h3>2 · Open the game</h3>${qrSvg(url)}<p>${esc(url)}</p></div></div>`;
  return i;
}
function boardTable(rows,me){return`<table><tr><th>#</th><th>NAME</th><th>SCORE</th></tr>${rows.map(r=>`<tr class="${r.name==me?"me":""}"><td>${r.rank}</td><td>${esc(r.name)}</td><td>${r.score}</td></tr>`).join("")}</table>`}
function optsHtml(q,mode,pick){ // mode: "btn" (players) | "show"
  return`<div class="opts">${LET.map(c=>{const cor=q.correct,dim=cor&&c!=cor||(!cor&&pick&&c!=pick);
    return`<button class="opt ${c} ${dim?"dim":""} ${cor&&c==cor?"ok":""}" data-c="${c}" ${mode=="btn"?"":"disabled"}>${SHAPE[c]} ${esc(q.options[c])}${q.counts?`<small>${q.counts[c]}</small>`:""}</button>`}).join("")}</div>`}
function animBar(getFrac){const f=()=>{const el=$("#bar i");if(el)el.style.width=Math.max(0,100*getFrac())+"%";requestAnimationFrame(f)};f()}
