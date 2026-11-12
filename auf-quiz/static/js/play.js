/* Player phone. Polls the server once a second; re-renders only when something the player can see changes. */
"use strict";
const store = {
  get(k) { try { return localStorage.getItem("aufq." + k) || ""; } catch (e) { return ""; } },
  set(k, v) { try { v ? localStorage.setItem("aufq." + k, v) : localStorage.removeItem("aufq." + k); } catch (e) { /* private mode */ } }
};
let tok = store.get("tok");
let info = null, st = null, lastV = null, sig = "", guestMode = false, joinMsg = "", busy = false, fails = 0;
const clock = makeClock();
const app = $("#app"), headEl = $("#top"), bar = $("#timebar");

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, 3500);
}

function header() {
  const ev = (st && st.event) || (info && info.event) || {title: "University Week Quiz"};
  let chip = "";
  const m = st && st.me;
  const scored = m && m.rank && (m.score > 0 || ["reveal", "leaderboard", "ended", "overall"].includes(st.phase));
  if (scored && ["question", "paused", "reveal", "leaderboard", "ended", "overall"].includes(st.phase)) {
    chip = '<div class="chip"><b>' + fmtNum(m.score) + '</b><span>' + ordinal(m.rank) + " place</span></div>";
  }
  const h = lockupHtml(ev) + chip;
  if (headEl.innerHTML !== h) headEl.innerHTML = h;
}

/* ---------------- join ---------------- */
function formatId(raw, mask) {
  const chars = String(raw).toUpperCase().replace(/[^A-Z0-9]/g, "").split("");
  let out = "";
  for (const m of mask) {
    if (!chars.length) break;
    out += "#A*".includes(m) ? chars.shift() : m;
  }
  return out;
}

function joinView() {
  const J = info.join;
  sig = "join";
  bar.hidden = true;
  const numericMask = J.mode === "mask" && !/[A*]/.test(J.mask);
  let idField = "";
  if (J.mode !== "name") {
    idField = guestMode
      ? '<label class="field"><span>Guest code</span><input class="input code" id="fid" autocomplete="off" maxlength="9" placeholder="G-1234" value="' +
        esc(store.get("guest")) + '"><small>First time? Leave this empty and we\'ll give you a code.</small></label>'
      : '<label class="field"><span>' + esc(J.label) + '</span><input class="input" id="fid" autocomplete="off" ' +
        (numericMask ? 'inputmode="numeric" ' : "") + 'maxlength="' + (J.mode === "mask" ? J.mask.length : 32) + '" placeholder="' +
        esc(J.mode === "mask" ? J.example : "") + '" value="' + esc(store.get("id")) + '"></label>';
  }
  const pinField = J.pin
    ? '<label class="field"><span>4-digit PIN</span><input class="input pin" id="fpin" type="password" inputmode="numeric" ' +
      'autocomplete="off" maxlength="4" pattern="[0-9]*"><small>New here? Choose any 4 digits. Coming back, or on another Wi-Fi? Use the same PIN.</small></label>'
    : "";
  app.innerHTML = '<form class="join" id="joinform" novalidate>' +
    '<h1 class="display">Join the quiz</h1><p class="lede">' + esc(info.event.welcome || "") + "</p>" + idField +
    '<label class="field"><span>Your name</span><input class="input" id="fname" autocomplete="nickname" maxlength="' + J.name_max +
    '" value="' + esc(store.get("name")) + '"><small>This is what shows on the big screen.</small></label>' + pinField +
    '<p class="error-text" id="ferr" role="alert">' + esc(joinMsg) + '</p><button class="btn" id="fgo">Join</button>' +
    (J.mode !== "name" && J.guests ? '<p class="alt"><button type="button" class="link" id="fguest">' +
      (guestMode ? "I have a " + esc(J.label.toLowerCase()) : "No " + esc(J.label.toLowerCase()) + "? Join as a guest") + "</button></p>" : "") +
    (J.privacy ? '<p class="privacy">' + esc(J.privacy) + "</p>" : "") + "</form>";
  const fid = $("#fid");
  if (fid && !guestMode && J.mode === "mask") fid.addEventListener("input", () => { fid.value = formatId(fid.value, J.mask); });
  if ($("#fguest")) $("#fguest").onclick = () => { guestMode = !guestMode; joinMsg = ""; joinView(); };
  $("#joinform").onsubmit = async e => {
    e.preventDefault();
    if (busy) return;
    busy = true; $("#fgo").disabled = true;
    const body = {id: fid ? fid.value.trim() : "", name: $("#fname").value.trim(), pin: $("#fpin") ? $("#fpin").value.trim() : "",
                  guest: guestMode, token: tok};
    try {
      const j = await api("/api/join", body);
      tok = j.token; store.set("tok", tok); store.set("name", j.name);
      if (j.guest) store.set("guest", j.id); else if (!guestMode) store.set("id", j.id);
      joinMsg = ""; sig = ""; lastV = null;
      poll(true);
    } catch (err) {
      $("#ferr").textContent = err.message;
      const need = err.data && err.data.need;
      if (need === "pin" && $("#fpin")) $("#fpin").focus();
      if (need === "name") $("#fname").focus();
    } finally {
      busy = false;
      if ($("#fgo")) $("#fgo").disabled = false;
    }
  };
}

/* ---------------- game screens ---------------- */
function standing(m, label) {
  if (!m.rank) return '<p class="meta">You don\'t have a score in this round yet.</p>';
  return '<div class="standing"><span class="big">' + ordinal(m.rank) + '</span><span><span class="of">of ' + (m.of || st.count || "") + " " +
    esc(label || "players") + '</span><br><span class="pts">' + fmtNum(m.score) + " pts</span></span></div>";
}

function topList(limit, m) {
  const rows = (st.board || []).slice(0, limit);
  if (!rows.length || !limit) return "";
  return '<p class="section-title">Top ' + rows.length + '</p><ol class="sb phone">' + rows.map(r =>
    '<li class="' + (m && r.k === m.k ? "is-me" : "") + '"><span class="rk">' + r.rank + '</span><span class="nm">' + esc(r.name) +
    '</span><span class="sc">' + fmtNum(r.score) + "</span></li>").join("") + "</ol>";
}

function footer(m) {
  return '<div class="foot"><span>Signed in as ' + esc(m.name) + " (" + esc(m.id) + ')</span><button class="link" id="signout" type="button">Sign out</button></div>';
}

function signature() {
  const s = st, m = s.me || {}, q = s.question || {};
  const base = [s.phase, m.name, m.kicked, m.spectator];
  if (s.phase === "question" || s.phase === "paused") return base.concat([q.n, m.choice, q.text]).join("|");
  if (s.phase === "lobby" || s.phase === "idle") return base.concat([s.online, (s.names || []).length]).join("|");
  return base.concat([s.v]).join("|");
}

function render() {
  header();
  const s = st, m = s.me;
  if (!m) {
    if (tok) { tok = ""; store.set("tok", ""); joinMsg = "You were signed out. Join again with your PIN."; }
    if (sig !== "join") joinView();
    return;
  }
  const q = s.question;
  clock.set(q && q.left, q && q.dur, s.phase === "question");
  bar.hidden = !(s.phase === "question" || s.phase === "paused");
  const g = signature();
  if (g === sig) return;
  sig = g;
  const total = s.round ? s.round.total : 0;
  const phoneTop = (s.top && s.top.phone) || 5;
  let h = "";
  if (m.kicked) {
    h = '<div class="wait"><h1 class="display">Removed from this round</h1><p class="lede">The host took you out of this round. You can play the next one.</p></div>';
  } else if (m.spectator && s.phase !== "overall" && s.phase !== "idle") {
    h = '<div class="wait"><h1 class="display">Watching this one</h1><p class="lede">You\'ve already played this quiz, so this round is view-only for you. Follow along on the big screen.</p></div>';
  } else if (s.phase === "idle") {
    h = '<div class="wait"><p class="meta">You\'re signed in as</p><p class="who">' + esc(m.name) + "</p>" + idCard(m) +
      '<p class="lede">No round is running yet. Keep this page open and the next round will appear here.</p><div class="pulse"><i></i><i></i><i></i></div></div>';
  } else if (s.phase === "lobby") {
    h = '<div class="wait"><p class="meta">You\'re in</p><p class="who">' + esc(m.name) + "</p>" + idCard(m) +
      '<p class="lede">' + (s.online || 1) + " player" + (s.online === 1 ? "" : "s") + " ready for " + esc(s.round ? s.round.title : "the next round") +
      '. Watch the big screen; the host starts soon.</p><div class="pulse"><i></i><i></i><i></i></div></div>';
  } else if ((s.phase === "question" || s.phase === "paused") && q) {
    const picked = m.choice;
    h = '<div class="qscreen' + (s.phase === "paused" ? " is-paused" : "") + '"><div class="qhead"><span>Question ' + q.n + " of " + total + '</span><span class="secs" id="secs"></span></div>' +
      (q.points === 2 ? '<span class="double">Double points</span>' : "") + (q.points === 0 ? '<span class="double">Just for fun, no points</span>' : "") +
      '<p class="qtext">' + esc(q.text) + "</p>" + imgHtml(q) +
      (s.phase === "paused" ? '<p class="lede"><b>Paused.</b> The host will continue in a moment.</p>' : "") +
      tilesHtml(q, picked || s.phase === "paused" ? "show" : "pick", {picked}) +
      (picked ? '<p class="locked">Answer locked in. Waiting for everyone else.</p>' : "") + "</div>";
  } else if (s.phase === "reveal" && q) {
    const cls = m.choice ? (m.correct ? "good" : "bad") : "none";
    const verdict = m.choice ? (m.correct ? "Correct" : "Not this time") : "No answer";
    h = '<div class="result ' + cls + '"><p class="verdict">' + verdict + "</p>" +
      (m.correct ? '<p class="gain">+' + fmtNum(m.pts) + "</p>" : "") +
      '<p class="ans">Answer: <b>' + esc(q.options[q.correct] || "") + "</b></p></div>" + standing(m);
  } else if (s.phase === "leaderboard") {
    h = '<h2 class="display">Leaderboard</h2>' + standing(m) + topList(phoneTop, m);
  } else if (s.phase === "ended") {
    h = '<h2 class="display">Final results</h2>' + standing(m) + topList(Math.max(3, phoneTop), m);
  } else if (s.phase === "overall") {
    h = '<h2 class="display">Week standings</h2><p class="meta">' + (s.mode === "sum" ? "Points from every round you played." : "Your best round counts.") + "</p>" +
      standing(m) + topList(Math.max(3, phoneTop), m);
  } else {
    h = '<div class="wait"><p class="lede">Hang on…</p></div>';
  }
  app.innerHTML = h + footer(m);
  $$("button.tile", app).forEach(b => { b.onclick = () => answer(b.dataset.c); });
  $("#signout").onclick = signOut;
}

function idCard(m) {
  if (m.guest) return '<div class="idcard guest">Your guest code <b>' + esc(m.id) + "</b><br><small>Keep it with your PIN to rejoin later.</small></div>";
  return '<div class="idcard"><b>' + esc(m.id) + "</b></div>";
}

async function answer(c) {
  if (!st || !st.me || st.me.choice) return;
  st.me.choice = c; sig = ""; render();
  try {
    const j = await api("/api/answer", {token: tok, choice: c});
    st.me.choice = j.choice;
  } catch (e) {
    toast(e.message);
    if (st && st.me) { st.me.choice = null; sig = ""; render(); }
  }
}

async function signOut() {
  if (!confirm("Sign out on this phone? You can rejoin with your ID and PIN.")) return;
  try { await api("/api/leave", {token: tok}); } catch (e) { /* offline is fine */ }
  tok = ""; store.set("tok", "");
  joinMsg = ""; sig = ""; st = null; lastV = null;
  joinView();
}

/* ---------------- loop ---------------- */
async function poll(now) {
  clearTimeout(poll.t);
  try {
    const j = await api("/api/state?token=" + encodeURIComponent(tok) + (lastV != null && !now ? "&v=" + lastV : ""));
    fails = 0;
    $("#offline") && $("#offline").remove();
    if (!j.same) { st = j; lastV = j.v; render(); }
  } catch (e) {
    if (++fails >= 3 && !$("#offline")) headEl.insertAdjacentHTML("afterend", '<div class="offline" id="offline">Reconnecting to the quiz… stay on the event Wi-Fi.</div>');
  }
  poll.t = setTimeout(poll, 1000);
}

function frame() {
  if (st && (st.phase === "question" || st.phase === "paused") && st.question) {
    const i = $("#timebar i");
    if (i) i.style.transform = "scaleX(" + clock.frac().toFixed(4) + ")";
    const sec = $("#secs");
    if (sec) sec.textContent = Math.ceil(clock.left());
  }
  requestAnimationFrame(frame);
}

document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(true); });

(async function start() {
  for (;;) {
    try { info = await api("/api/info"); break; }
    catch (e) { app.innerHTML = '<p class="lede">' + esc(e.message) + "</p>"; await new Promise(r => setTimeout(r, 2000)); }
  }
  header();
  if (!tok) joinView();
  poll(true);
  frame();
})();
