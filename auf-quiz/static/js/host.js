/* Host console. Everything the host can change lives here, instead of in config files. */
"use strict";
const H = {tok: "", tab: "live", st: null, lastV: null, info: null, ip: "", ev: null, editor: null, liveSig: "", ctrlSig: "", listSig: "", idleSig: ""};
const clock = makeClock();
try { H.tok = localStorage.getItem("aufq.host") || ""; } catch (e) { /* private mode */ }

function setTok(t) { H.tok = t; try { t ? localStorage.setItem("aufq.host", t) : localStorage.removeItem("aufq.host"); } catch (e) { /* ignore */ } }

async function hapi(path, body) {
  try { return await api(path, body, {headers: {"X-Host-Token": H.tok}}); }
  catch (e) { if (e.status === 401 && !path.endsWith("/login")) showLogin("Your session ended. Sign in again."); throw e; }
}

function toast(msg, bad) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, bad ? 6000 : 3200);
}
const fail = e => toast(e.message || String(e), true);

function dialog(o) {
  return new Promise(res => {
    const d = $("#dlg"), f = $("#dlgform");
    f.innerHTML = "<h2>" + esc(o.title) + "</h2>" + (o.html || "") +
      (o.input ? '<input class="input" id="dlg-in" maxlength="' + (o.input.max || 100) + '" value="' + esc(o.input.value || "") + '">' : "") +
      '<div class="row">' + (o.cancel === false ? "" : '<button type="button" class="btn quiet" id="dlg-no">' + esc(o.cancel || "Cancel") + "</button>") +
      '<button class="btn' + (o.danger ? " danger" : "") + '" id="dlg-ok">' + esc(o.ok || "OK") + "</button></div>";
    const done = v => { if (d.open) d.close(); res(v); };
    f.onsubmit = e => { e.preventDefault(); done(o.input ? $("#dlg-in").value : true); };
    if ($("#dlg-no")) $("#dlg-no").onclick = () => done(null);
    d.oncancel = e => { e.preventDefault(); done(null); };
    d.showModal();
    (o.input ? $("#dlg-in") : $("#dlg-ok")).focus();
  });
}
const confirmBox = (title, html, ok, danger) => dialog({title, html: "<p>" + html + "</p>", ok, danger});

async function download(path) {
  const r = await fetch(path, {headers: {"X-Host-Token": H.tok}, cache: "no-store"});
  if (!r.ok) { let j = {}; try { j = await r.json(); } catch (e) { /* */ } throw new Error(j.error || "Download failed"); }
  const blob = await r.blob();
  const m = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = m ? m[1] : "download";
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
}

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("en-PH", {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
}

/* ======================================================================= sign in */
function showLogin(msg) {
  $("#shell").hidden = true; $("#login").hidden = false;
  $("#loginerr").textContent = msg || "";
  $("#loginlock").innerHTML = lockupHtml(H.ev || {title: "University Week Quiz"});
  setTimeout(() => $("#pw").focus(), 50);
}
$("#loginform").onsubmit = async e => {
  e.preventDefault();
  $("#loginbtn").disabled = true;
  try {
    const j = await api("/api/host/login", {password: $("#pw").value});
    setTok(j.token); $("#pw").value = ""; showShell();
  } catch (err) { $("#loginerr").textContent = err.message; }
  finally { $("#loginbtn").disabled = false; }
};
$("#logout").onclick = async () => {
  try { await hapi("/api/host/logout", {}); } catch (e) { /* */ }
  setTok(""); showLogin("Signed out.");
};

function showShell() {
  $("#login").hidden = true; $("#shell").hidden = false;
  if (H.ev) $("#sidelock").innerHTML = lockupHtml(H.ev);
  const want = (location.hash || "").replace("#", "");
  switchTab(["live", "rounds", "questions", "players", "data", "settings"].includes(want) ? want : H.tab, true);
  loadInfo(); pollLive();
}

/* ======================================================================= tabs */
$$("#nav button").forEach(b => { b.onclick = () => switchTab(b.dataset.tab); });

async function switchTab(name, force) {
  if (!force && H.tab === "questions" && H.editor && H.editor.dirty && name !== "questions") {
    if (!await confirmBox("Leave without saving?", "Your changes to this quiz haven't been saved.", "Leave", true)) return;
    H.editor = null;
  }
  H.tab = name;
  history.replaceState(null, "", "#" + name);
  $$("#nav button").forEach(b => b.setAttribute("aria-current", b.dataset.tab === name ? "page" : "false"));
  $$(".tab").forEach(t => { t.hidden = t.id !== "tab-" + name; });
  if (name === "live") { H.liveSig = H.ctrlSig = H.idleSig = ""; H.listSig = null; buildLive(); if (H.st) renderLive(); }
  if (name === "rounds") renderRounds();
  if (name === "questions") H.editor ? renderEditor() : renderQuizList();
  if (name === "players") renderPlayers();
  if (name === "data") renderData();
  if (name === "settings") renderSettings();
}

addEventListener("beforeunload", e => { if (H.editor && H.editor.dirty) { e.preventDefault(); e.returnValue = ""; } });

/* ======================================================================= live */
const PHASE = {idle: "No round", lobby: "Lobby", question: "Question open", paused: "Paused", reveal: "Answer shown",
  leaderboard: "Leaderboard", ended: "Final results", overall: "Week standings"};

async function loadInfo() {
  try {
    H.info = await hapi("/api/host/info");
    if (!H.ip || !H.info.ips.includes(H.ip)) H.ip = H.info.ip;
    renderJoins();
  } catch (e) { /* */ }
}

function buildLive() {
  $("#tab-live").innerHTML =
    '<div class="page-head"><div><h1>Live game</h1><p id="lv-round"></p></div><div class="actions">' +
    '<a class="btn quiet small" href="/board" target="_blank" rel="noopener">Open projector board</a></div></div>' +
    '<div class="status" id="lv-status"></div>' +
    '<div class="live-grid"><div><div id="lv-stage"></div>' +
    '<div class="primary-row" id="lv-prow"><button class="btn primary" id="lv-primary" type="button"></button>' +
    '<span class="kbd"><kbd>Space</kbd> does the same. <kbd>←</kbd> <kbd>→</kbd> previous and next.</span></div>' +
    '<div class="controls" id="lv-controls"></div></div>' +
    '<div class="side-col"><h2 class="sec">Join codes</h2><p class="sec-help">Also shown on the projector lobby.</p>' +
    '<div class="joins-host" id="lv-joins"></div><div class="ipsel" id="lv-ipsel"></div>' +
    '<h2 class="sec">Players in this round <span id="lv-pcount" class="muted"></span></h2><ul class="plist" id="lv-plist"></ul></div></div>';
  $("#lv-primary").onclick = () => act("advance");
  renderJoins();
}

function renderJoins() {
  const el = $("#lv-joins");
  if (!el || !H.info) return;
  el.innerHTML = joinCards(H.info, H.ip);
  const ips = H.info.ips || [];
  $("#lv-ipsel").innerHTML = ips.length > 1 ? 'Address: <select id="ipsel">' + ips.map(i => "<option" + (i === H.ip ? " selected" : "") + ">" + esc(i) + "</option>").join("") +
    '</select> <span>Pick the one on the event Wi-Fi. Set it permanently in Settings.</span>' : (ips.length ? "" : "No network address found. Is the hotspot on?");
  if ($("#ipsel")) $("#ipsel").onchange = e => { H.ip = e.target.value; renderJoins(); };
}

async function act(action, value) {
  try { await hapi("/api/host/action", {action, value}); H.lastV = null; pollLive(true); }
  catch (e) { fail(e); }
}

function primaryLabel(s) {
  const r = s.round, q = s.q;
  switch (s.phase) {
    case "lobby": return "Start question 1";
    case "question": return "Reveal the answer now";
    case "paused": return "Resume the timer";
    case "reveal": return "Show the leaderboard";
    case "leaderboard": return r && q < r.total - 1 ? "Next: question " + (q + 2) : "Show final results";
    case "ended": return "Show week standings";
    case "overall": return r ? "Back to the round" : "Back to the lobby screen";
    default: return "";
  }
}

const CONTROLS = [
  ["prev", "Previous", s => s.round && s.phase !== "lobby"],
  ["next", "Next", s => s.round && !["ended", "overall"].includes(s.phase)],
  ["pause", "Pause timer", s => s.phase === "question"],
  ["extend", "Add time", s => s.phase === "question" || s.phase === "paused"],
  ["board", "Leaderboard", s => s.round && s.q >= 0 && s.phase !== "leaderboard"],
  ["replay", "Replay question", s => s.round && s.q >= 0, "Replay this question? Answers already given to it are cleared."],
  ["lobby", "Back to lobby", s => s.round && s.phase !== "lobby"],
  ["end", "End round now", s => s.round && !["ended", "overall"].includes(s.phase), "End the round and show the final podium?"],
  ["overall", "Week standings", s => s.phase !== "overall"],
  ["close", "Close round", s => s.round, "Close this round? Its results stay on the Rounds page and you can reopen it later."],
  ["reset", "Reset round scores", s => s.round, "Clear every answer in this round and go back to the lobby? A backup is saved first.", true]
];

function renderLive() {
  const s = H.st;
  if (!s || H.tab !== "live" || !$("#lv-status")) return;
  const r = s.round, q = s.question;
  $("#lv-round").textContent = r ? r.title + (r.quiz_title && r.quiz_title !== r.title ? ", from the quiz " + r.quiz_title : "") : "Start a round to play.";
  clock.set(q && q.left, q && q.dur, s.phase === "question");
  $("#lv-status").innerHTML =
    '<div class="stat phase"><span>Now showing</span><b>' + esc(PHASE[s.phase] || s.phase) + "</b></div>" +
    (r && s.q >= 0 ? '<div class="stat"><span>Question</span><b>' + (s.q + 1) + " / " + r.total + "</b></div>" : "") +
    (q && (s.phase === "question" || s.phase === "paused") ? '<div class="stat timer" id="lv-timer"><span>Seconds left</span><b>–</b></div>' : "") +
    (q ? '<div class="stat"><span>Answered</span><b>' + (s.answered || 0) + " / " + (s.online || 0) + "</b></div>" : "") +
    '<div class="stat"><span>Online now</span><b>' + (r ? s.online : s.online_total) + '</b></div><div class="stat"><span>Registered this week</span><b>' + s.players_total + "</b></div>";

  // stage
  const stageSig = [s.phase, s.q, r && r.id, q && q.text, q && q.correct].join("|") + (q ? JSON.stringify(q.counts) : "");
  if (stageSig !== H.liveSig) {
    H.liveSig = stageSig;
    if (!r) { renderIdle(); }
    else if (q) {
      $("#lv-stage").innerHTML = '<div class="stage-q"><p class="qlabel">Question ' + q.n + ", " + q.time + " seconds" + (q.points === 2 ? ", double points" : q.points === 0 ? ", no points" : "") +
        ". The correct answer is outlined; only you see it before the reveal.</p>" + '<p class="qtext">' + esc(q.text) + "</p>" + imgHtml(q) + tilesHtml(q, "show", {host: true}) + "</div>";
    } else {
      $("#lv-stage").innerHTML = '<div class="empty"><h2>' + (s.phase === "lobby" ? "Lobby is open" : esc(PHASE[s.phase])) + "</h2><p>" +
        (s.phase === "lobby" ? "Players who open the game now join this round. Start when the room is ready." :
         s.phase === "ended" ? "The podium is on the projector." : s.phase === "overall" ? "The week standings are on the projector." : "") + "</p></div>";
    }
  }
  if (r) H.idleSig = "";
  // primary + controls
  const pl = primaryLabel(s);
  $("#lv-prow").hidden = !pl;
  $("#lv-primary").textContent = pl;
  const cs = [s.phase, s.q, r && r.id, r && r.played.join("")].join("|");
  if (cs !== H.ctrlSig) {
    H.ctrlSig = cs;
    const ext = " (+" + ((H.settings && H.settings.game.extend_s) || 5) + "s)";
    let h = CONTROLS.filter(c => c[2](s)).map(c => '<button class="btn small ' + (c[4] ? "danger" : "quiet") + '" data-a="' + c[0] + '" type="button">' +
      esc(c[1]) + (c[0] === "extend" ? ext : "") + "</button>").join("");
    if (r) h += '<select id="lv-jump" aria-label="Jump to a question"><option value="">Jump to question…</option>' + r.titles.map((t, i) =>
      '<option value="' + i + '">' + (i + 1) + ". " + esc(t.length > 48 ? t.slice(0, 47) + "…" : t) + (r.played[i] ? " (played)" : "") + "</option>").join("") + "</select>";
    $("#lv-controls").innerHTML = h;
    $$("#lv-controls button").forEach(b => {
      const c = CONTROLS.find(x => x[0] === b.dataset.a);
      b.onclick = async () => { if (!c[3] || await confirmBox(c[1], esc(c[3]), c[1], c[4])) act(c[0]); };
    });
    if ($("#lv-jump")) $("#lv-jump").onchange = e => { if (e.target.value !== "") act("goto", +e.target.value); };
  }
  // players
  const list = s.list || [];
  $("#lv-pcount").textContent = r ? "(" + list.length + ")" : "";
  const ls = list.map(p => p.id + p.score + p.online + p.ans + p.name).join(",");
  if (ls !== H.listSig) {
    H.listSig = ls;
    $("#lv-plist").innerHTML = !r ? '<li><span></span><span class="muted">No round running.</span></li>' : list.length ? list.map(p =>
      '<li><span class="dot' + (p.online ? " on" : "") + '" title="' + (p.online ? "Online" : "Offline") + '"></span><span class="nm">' + esc(p.name) + "<small>" + esc(p.id) +
      '</small></span><span class="sc">' + fmtNum(p.score) + "</span>" +
      (p.ans ? '<span class="ans tile-' + p.ans + '" title="Answered">' + SHAPES[p.ans] + "</span>" : "<span></span>") +
      '<button class="x" data-id="' + esc(p.id) + '" title="Remove from this round" type="button">✕</button></li>').join("")
      : '<li><span></span><span class="muted">Nobody yet. Players appear when they open the game.</span></li>';
    $$("#lv-plist .x").forEach(b => {
      b.onclick = async () => {
        const p = list.find(x => x.id === b.dataset.id);
        if (await confirmBox("Remove " + p.name + "?", "They're signed out and can't rejoin this round (their answers in it are deleted). To block them for the whole event, use Ban on the Players page.", "Remove", true)) act("kick", p.id);
      };
    });
  }
}

async function renderIdle() {
  if (H.idleSig === "idle") return;
  H.idleSig = "idle";
  $("#lv-stage").innerHTML = '<div class="empty"><h2>No round is running</h2><p>Pick a quiz and start a round. Players who are already signed in join it automatically.</p><div id="lv-quick">Loading quizzes…</div></div>';
  try {
    const j = await hapi("/api/host/rounds");
    const ok = j.quizzes.filter(q => q.count && !q.issues);
    $("#lv-quick").innerHTML = ok.length ? '<div class="inline-form"><label class="field"><span>Quiz</span><select class="input" id="lv-qz">' +
      ok.map(q => '<option value="' + q.id + '">' + esc(q.title) + " (" + q.count + ")</option>").join("") + '</select></label>' +
      '<label class="field"><span>Round name (optional)</span><input class="input" id="lv-rt" maxlength="100" placeholder="e.g. Day 2, 1 PM batch"></label>' +
      '<button class="btn" id="lv-start" type="button">Start round</button></div>'
      : '<p>No ready quizzes yet. <button class="link" id="lv-goq" type="button">Create or import one on the Questions page</button>.</p>';
    if ($("#lv-start")) $("#lv-start").onclick = async () => {
      try { await hapi("/api/host/round/new", {quiz_id: $("#lv-qz").value, title: $("#lv-rt").value}); H.lastV = null; H.liveSig = ""; pollLive(true); }
      catch (e) { fail(e); }
    };
    if ($("#lv-goq")) $("#lv-goq").onclick = () => switchTab("questions");
  } catch (e) { fail(e); }
}

async function pollLive(now) {
  clearTimeout(pollLive.t);
  try {
    const j = await hapi("/api/host/state" + (H.lastV != null && !now ? "?v=" + H.lastV : ""));
    if (!j.same) {
      H.st = j; H.lastV = j.v;
      if (JSON.stringify(j.event) !== JSON.stringify(H.ev)) { H.ev = j.event; $("#sidelock").innerHTML = lockupHtml(j.event); document.title = "Host · " + j.event.title; }
      renderLive();
    }
  } catch (e) { if (e.status === 401) return; }
  pollLive.t = setTimeout(pollLive, 1000);
}

function frame() {
  const t = $("#lv-timer b");
  if (t && H.st) {
    const l = clock.left();
    t.textContent = l.toFixed(1);
    $("#lv-timer").classList.toggle("hot", l <= 5);
  }
  requestAnimationFrame(frame);
}

addEventListener("keydown", e => {
  if (H.tab !== "live" || $("#dlg").open || $("#shell").hidden) return;
  const tag = e.target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if ((tag === "BUTTON" || tag === "A") && (e.key === " " || e.key === "Enter")) return;   // let focused buttons work normally
  if (e.key === " " || e.key === "Enter") { e.preventDefault(); if (H.st && primaryLabel(H.st)) act("advance"); }
  else if (e.key === "ArrowRight") { e.preventDefault(); act("next"); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); act("prev"); }
  else if (e.key.toLowerCase() === "p" && H.st) act(H.st.phase === "paused" ? "resume" : "pause");
});

/* ======================================================================= rounds */
async function renderRounds(detailId) {
  const el = $("#tab-rounds");
  if (detailId) return renderRoundDetail(detailId);
  el.innerHTML = '<div class="page-head"><div><h1>Rounds</h1><p>Each round is one play-through of a quiz. Rounds are kept all week; the week standings combine them.</p></div>' +
    '<div class="actions"><button class="btn quiet small" id="r-overall" type="button">Download week standings (CSV)</button></div></div><div id="r-body">Loading…</div>';
  $("#r-overall").onclick = () => download("/api/host/csv?kind=overall").catch(fail);
  let j;
  try { j = await hapi("/api/host/rounds"); } catch (e) { return fail(e); }
  const ready = j.quizzes.filter(q => q.count && !q.issues);
  $("#r-body").innerHTML = '<h2 class="sec">Start a new round</h2>' +
    (ready.length ? '<div class="inline-form"><label class="field"><span>Quiz</span><select class="input" id="r-qz">' +
      ready.map(q => '<option value="' + q.id + '">' + esc(q.title) + " (" + q.count + " questions)</option>").join("") + "</select></label>" +
      '<label class="field"><span>Round name (optional)</span><input class="input" id="r-title" maxlength="100" placeholder="e.g. CCS booth, Tuesday 10 AM"></label>' +
      '<label class="toggle" style="flex:0 0 auto"><input type="checkbox" id="r-shuf"' + (H.settings && H.settings.game.shuffle ? " checked" : "") + "><span><b>Shuffle questions</b></span></label>" +
      '<button class="btn" id="r-start" type="button">Start round</button></div>'
      : '<p class="sec-help">No quiz is ready yet. Add questions on the Questions page first.</p>') +
    (j.quizzes.length > ready.length ? '<p class="sec-help">' + (j.quizzes.length - ready.length) + " quiz(zes) hidden because they still need fixing.</p>" : "") +
    '<h2 class="sec">All rounds</h2>' +
    (j.rounds.length ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Round</th><th>Quiz</th><th>Started</th><th class="r">Players</th><th>Progress</th><th>Winner</th><th></th></tr></thead><tbody>' +
      j.rounds.map(r => "<tr><td><b>" + esc(r.title) + "</b> " + (r.live ? '<span class="tag live">On screen</span>' : r.status === "done" ? "" : '<span class="tag">Open</span>') +
        '</td><td class="muted">' + esc(r.quiz_title) + '</td><td class="muted">' + when(r.created) + '</td><td class="r">' + r.players + "</td><td>" + r.played + " of " + r.questions +
        "</td><td>" + (r.winner ? '<span class="tag gold">' + esc(r.winner) + "</span>" : "") + '</td><td class="act">' +
        '<button class="btn small quiet" data-a="results" data-id="' + r.id + '" type="button">Results</button>' +
        (r.live ? "" : '<button class="btn small quiet" data-a="open" data-id="' + r.id + '" type="button">Put on screen</button>') +
        '<select class="act-sel" data-id="' + r.id + '" aria-label="More actions"><option value="">More…</option><option value="csv">Download CSV</option><option value="rename">Rename</option><option value="delete">Delete</option></select></td></tr>').join("") +
      "</tbody></table></div>" : '<p class="sec-help">No rounds yet.</p>');
  if ($("#r-start")) $("#r-start").onclick = async () => {
    try {
      await hapi("/api/host/round/new", {quiz_id: $("#r-qz").value, title: $("#r-title").value, shuffle: $("#r-shuf").checked});
      toast("Round started. It's on the projector now."); H.lastV = null; switchTab("live");
    } catch (e) { fail(e); }
  };
  $$("#r-body [data-a]").forEach(b => {
    b.onclick = async () => {
      if (b.dataset.a === "results") return renderRoundDetail(b.dataset.id);
      const live = j.rounds.find(r => r.live);
      if (live && !await confirmBox("Switch rounds?", "“" + esc(live.title) + "” is on screen now. It will be closed (results are kept).", "Switch")) return;
      try { await hapi("/api/host/round/open", {id: b.dataset.id}); H.lastV = null; switchTab("live"); } catch (e) { fail(e); }
    };
  });
  $$("#r-body .act-sel").forEach(sel => {
    sel.onchange = async () => {
      const id = sel.dataset.id, v = sel.value, r = j.rounds.find(x => x.id === id);
      sel.value = "";
      try {
        if (v === "csv") await download("/api/host/csv?kind=round&id=" + id);
        if (v === "rename") {
          const t = await dialog({title: "Rename round", input: {value: r.title, max: 100}, ok: "Rename"});
          if (t) { await hapi("/api/host/round/rename", {id, title: t}); renderRounds(); }
        }
        if (v === "delete" && await confirmBox("Delete “" + esc(r.title) + "”?", "Its scores leave the week standings. A backup is saved first, so you can restore it from the Data page.", "Delete round", true)) {
          await hapi("/api/host/round/delete", {id}); toast("Round deleted."); renderRounds();
        }
      } catch (e) { fail(e); }
    };
  });
}

async function renderRoundDetail(id) {
  const el = $("#tab-rounds");
  let d;
  try { d = await hapi("/api/host/round?id=" + encodeURIComponent(id)); } catch (e) { return fail(e); }
  const r = d.round;
  el.innerHTML = '<div class="page-head"><div><button class="link" id="rd-back" type="button">All rounds</button><h1>' + esc(r.title) + "</h1><p>" + esc(r.quiz_title) + ", started " + when(r.created) +
    ". " + r.players + " players, " + r.played + " of " + r.questions + ' questions played.</p></div><div class="actions"><button class="btn quiet small" id="rd-csv" type="button">Download CSV</button></div></div>' +
    '<h2 class="sec">Standings</h2>' + (d.standings.length ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th class="r">Rank</th><th>Name</th><th>ID</th><th class="r">Correct</th><th class="r">Answered</th><th class="r">Score</th></tr></thead><tbody>' +
      d.standings.map(s => '<tr><td class="r"><b>' + s.rank + "</b></td><td>" + esc(s.name) + '</td><td class="muted">' + esc(s.id) + '</td><td class="r">' + s.correct + '</td><td class="r">' + s.answered +
        '</td><td class="r"><b>' + fmtNum(s.score) + "</b></td></tr>").join("") + "</tbody></table></div>" : '<p class="sec-help">Nobody played this round.</p>') +
    '<h2 class="sec">Questions</h2><p class="sec-help">If an answer key was wrong, pick the right answer here. Everyone who answered is re-scored, and the quiz is fixed for next time.</p>' +
    d.questions.map(q => '<div class="result-q"><span class="n">' + q.n + "</span><div><b>" + esc(q.text) + '</b><div class="muted">' +
      (q.answered ? q.correct_pct + "% correct, " + q.answered + " answered, " + q.avg_s + "s average" : "Not played") + '</div><div class="meter"><i style="width:' + (q.correct_pct || 0) + '%"></i></div></div>' +
      '<select data-q="' + q.id + '" aria-label="Correct answer">' + LETTERS.filter(c => q.options[c]).map(c => '<option value="' + c + '"' + (c === q.answer ? " selected" : "") + ">" +
        SHAPE_NAMES[c] + ": " + esc(q.options[c]) + " (" + q.counts[c] + ")</option>").join("") + "</select></div>").join("");
  $("#rd-back").onclick = () => renderRounds();
  $("#rd-csv").onclick = () => download("/api/host/csv?kind=round&id=" + id).catch(fail);
  $$("#tab-rounds select[data-q]").forEach(sel => {
    const before = sel.value;
    sel.onchange = async () => {
      if (!await confirmBox("Change the correct answer?", "Everyone who answered this question is re-scored.", "Re-score")) { sel.value = before; return; }
      try { await hapi("/api/host/round/regrade", {id, qid: sel.dataset.q, answer: sel.value}); toast("Re-scored."); renderRoundDetail(id); } catch (e) { fail(e); }
    };
  });
}

/* ======================================================================= quizzes */
async function renderQuizList() {
  const el = $("#tab-questions");
  el.innerHTML = '<div class="page-head"><div><h1>Questions</h1><p>Build quizzes here, or import a JSON or CSV file. CSV columns: question, a, b, c, d, answer, time (optional).</p></div>' +
    '<div class="actions"><input type="file" id="qz-file" accept=".json,.csv,application/json,text/csv" hidden><button class="btn quiet small" id="qz-import" type="button">Import file</button>' +
    '<button class="btn small" id="qz-new" type="button">New quiz</button></div></div><div id="qz-body">Loading…</div>';
  $("#qz-new").onclick = () => openEditor(null);
  $("#qz-import").onclick = () => $("#qz-file").click();
  $("#qz-file").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const j = await hapi("/api/host/quiz/import?name=" + encodeURIComponent(f.name), await f.text());
      const n = Object.keys(j.issues).length;
      toast("Imported “" + j.quiz.title + "” with " + j.quiz.questions.length + " questions" + (n ? ". " + n + " need fixing." : "."));
      openEditor(j.quiz.id);
    } catch (err) { fail(err); }
    e.target.value = "";
  };
  let j;
  try { j = await hapi("/api/host/quizzes"); } catch (e) { return fail(e); }
  $("#qz-body").innerHTML = j.quizzes.length ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Quiz</th><th class="r">Questions</th><th>Status</th><th class="r">Rounds played</th><th>Last edited</th><th></th></tr></thead><tbody>' +
    j.quizzes.map(q => "<tr><td><b>" + esc(q.title) + "</b>" + (q.description ? '<br><span class="muted">' + esc(q.description) + "</span>" : "") + '</td><td class="r">' + q.count + "</td><td>" +
      (q.issues ? '<span class="tag warn">' + q.issues + " to fix</span>" : '<span class="tag ok">Ready</span>') + '</td><td class="r">' + q.rounds + '</td><td class="muted">' + when(q.updated) +
      '</td><td class="act"><button class="btn small quiet" data-edit="' + q.id + '" type="button">Edit</button><select class="act-sel" data-id="' + q.id +
      '" aria-label="More actions"><option value="">More…</option><option value="dup">Duplicate</option><option value="export">Download as JSON</option><option value="delete">Delete</option></select></td></tr>').join("") +
    "</tbody></table></div>" : '<div class="empty"><h2>No quizzes yet</h2><p>Create one, or import your old questions.json or a CSV from a spreadsheet.</p></div>';
  $$("#qz-body [data-edit]").forEach(b => { b.onclick = () => openEditor(b.dataset.edit); });
  $$("#qz-body .act-sel").forEach(sel => {
    sel.onchange = async () => {
      const id = sel.dataset.id, v = sel.value, q = j.quizzes.find(x => x.id === id);
      sel.value = "";
      try {
        if (v === "dup") { await hapi("/api/host/quiz/duplicate", {id}); renderQuizList(); }
        if (v === "export") await download("/api/host/quiz/export?id=" + id);
        if (v === "delete" && await confirmBox("Delete “" + esc(q.title) + "”?", "Rounds already played keep their own copy of the questions and scores.", "Delete quiz", true)) {
          await hapi("/api/host/quiz/delete", {id}); renderQuizList();
        }
      } catch (e) { fail(e); }
    };
  });
}

async function openEditor(id) {
  let quiz, issues = {};
  if (id) {
    try { const j = await hapi("/api/host/quiz?id=" + encodeURIComponent(id)); quiz = j.quiz; issues = j.issues; } catch (e) { return fail(e); }
  } else {
    quiz = {title: "", description: "", questions: [blankQuestion()]};
  }
  H.editor = {quiz, issues, dirty: !id};
  renderEditor();
}

function blankQuestion() {
  return {text: "", options: {a: "", b: "", c: "", d: ""}, answer: "", time: (H.settings && H.settings.game.default_time) || 20, points: 1, image: ""};
}

function qCard(q, i, iss) {
  const opts = LETTERS.map(c => '<div class="opt-edit' + (q.answer === c ? " is-correct" : "") + '" data-oc="' + c + '"><span class="sw tile-' + c + '">' + SHAPES[c] + "</span>" +
    '<input type="text" maxlength="120" data-i="' + i + '" data-k="opt-' + c + '" value="' + esc(q.options[c]) + '" placeholder="Answer ' + c.toUpperCase() + (c > "b" ? " (optional)" : "") + '" aria-label="' + SHAPE_NAMES[c] + ' answer">' +
    '<label><input type="radio" name="ans' + i + '" data-i="' + i + '" data-k="answer" value="' + c + '"' + (q.answer === c ? " checked" : "") + "> Correct</label></div>").join("");
  return '<div class="qcard' + (iss ? " has-issue" : "") + '" data-card="' + i + '"><div><span class="qn">' + (i + 1) + '</span><div class="qtools">' +
    '<button type="button" data-tool="up" data-i="' + i + '">Move up</button><button type="button" data-tool="down" data-i="' + i + '">Move down</button>' +
    '<button type="button" data-tool="copy" data-i="' + i + '">Duplicate</button><button type="button" class="del" data-tool="del" data-i="' + i + '">Delete</button></div></div>' +
    '<div><textarea maxlength="300" data-i="' + i + '" data-k="text" placeholder="Type the question" aria-label="Question ' + (i + 1) + '">' + esc(q.text) + "</textarea>" +
    '<div class="opts-edit">' + opts + '</div><div class="qrow"><label>Seconds <input type="number" min="5" max="300" data-i="' + i + '" data-k="time" value="' + q.time + '"></label>' +
    '<label>Points <select data-i="' + i + '" data-k="points"><option value="1"' + (q.points === 1 ? " selected" : "") + '>Standard</option><option value="2"' + (q.points === 2 ? " selected" : "") +
    '>Double</option><option value="0"' + (q.points === 0 ? " selected" : "") + ">No points</option></select></label>" +
    (q.image ? '<img class="thumb" src="/media/' + esc(q.image) + '" alt=""><button class="link" type="button" data-tool="noimg" data-i="' + i + '">Remove image</button>'
             : '<button class="btn small quiet" type="button" data-tool="img" data-i="' + i + '">Add image</button>') + "</div></div>" +
    (iss ? '<p class="qissues">Needs: ' + esc(iss.join(", ")) + "</p>" : "") + "</div>";
}

function renderEditor() {
  const E = H.editor, Q = E.quiz;
  const el = $("#tab-questions");
  el.innerHTML = '<div class="editor-head"><button class="link" id="ed-back" type="button">All quizzes</button><span class="grow"></span><span class="dirty" id="ed-dirty"' +
    (E.dirty ? "" : " hidden") + '>Unsaved changes</span><button class="btn" id="ed-save" type="button">Save quiz</button></div>' +
    '<div class="meta-fields"><label class="field"><span>Quiz title</span><input class="input" id="ed-title" maxlength="80" value="' + esc(Q.title) + '" placeholder="e.g. CCS Trivia, Day 1"></label>' +
    '<label class="field"><span>Description (only you see this)</span><input class="input" id="ed-desc" maxlength="240" value="' + esc(Q.description) + '"></label></div>' +
    '<input type="file" id="ed-file" accept="image/png,image/jpeg,image/gif,image/webp" hidden>' +
    '<div id="ed-list">' + Q.questions.map((q, i) => qCard(q, i, E.issues[String(i)])).join("") + "</div>" +
    '<div class="add-row"><button class="btn quiet" id="ed-add" type="button">Add question</button></div>';
  const dirty = () => { E.dirty = true; $("#ed-dirty").hidden = false; };
  $("#ed-title").oninput = e => { Q.title = e.target.value; dirty(); };
  $("#ed-desc").oninput = e => { Q.description = e.target.value; dirty(); };
  $("#ed-back").onclick = async () => {
    if (E.dirty && !await confirmBox("Leave without saving?", "Your changes to this quiz haven't been saved.", "Leave", true)) return;
    H.editor = null; renderQuizList();
  };
  $("#ed-add").onclick = () => { Q.questions.push(blankQuestion()); dirty(); renderEditor(); const ta = $$("#ed-list textarea"); ta[ta.length - 1].focus(); };
  $("#ed-save").onclick = saveEditor;
  const list = $("#ed-list");
  list.oninput = e => {
    const t = e.target, i = +t.dataset.i, k = t.dataset.k, q = Q.questions[i];
    if (!k || !q) return;
    if (k === "text") q.text = t.value;
    else if (k.startsWith("opt-")) q.options[k.slice(4)] = t.value;
    else if (k === "time") q.time = +t.value;
    dirty();
  };
  list.onchange = e => {
    const t = e.target, i = +t.dataset.i, k = t.dataset.k, q = Q.questions[i];
    if (!q) return;
    if (k === "answer") {
      q.answer = t.value;
      $$('[data-card="' + i + '"] .opt-edit').forEach(o => o.classList.toggle("is-correct", o.dataset.oc === q.answer));
    }
    if (k === "points") q.points = +t.value;
    dirty();
  };
  list.onclick = e => {
    const t = e.target.closest("[data-tool]");
    if (!t) return;
    const i = +t.dataset.i, qs = Q.questions;
    const tool = t.dataset.tool;
    if (tool === "up" && i > 0) [qs[i - 1], qs[i]] = [qs[i], qs[i - 1]];
    else if (tool === "down" && i < qs.length - 1) [qs[i + 1], qs[i]] = [qs[i], qs[i + 1]];
    else if (tool === "copy") { const c = JSON.parse(JSON.stringify(qs[i])); delete c.id; qs.splice(i + 1, 0, c); }
    else if (tool === "del") { qs.splice(i, 1); if (!qs.length) qs.push(blankQuestion()); }
    else if (tool === "noimg") qs[i].image = "";
    else if (tool === "img") { E.imgFor = i; $("#ed-file").click(); return; }
    else return;
    E.issues = {}; dirty(); renderEditor();
  };
  $("#ed-file").onchange = async ev => {
    const f = ev.target.files[0]; ev.target.value = "";
    if (!f) return;
    try {
      toast("Uploading image…");
      const blob = await shrinkImage(f);
      const j = await hapi("/api/host/upload", blob);
      Q.questions[E.imgFor].image = j.id; dirty(); renderEditor(); toast("Image added.");
    } catch (err) { fail(err); }
  };
}

async function saveEditor() {
  const E = H.editor;
  try {
    const j = await hapi("/api/host/quiz", {quiz: E.quiz});
    E.quiz = j.quiz; E.issues = j.issues; E.dirty = false;
    renderEditor();
    const n = Object.keys(j.issues).length;
    n ? toast("Saved. " + n + " question(s) still need fixing before this quiz can be played.", true) : toast("Saved. This quiz is ready to play.");
  } catch (e) { fail(e); }
}

/* Phones on hotspot Wi-Fi download every image at once, so keep images small. */
function shrinkImage(file) {
  return new Promise((resolve, reject) => {
    if (file.size > 20 * 1024 * 1024) return reject(new Error("That image is over 20 MB. Pick a smaller one."));
    if (file.type === "image/gif") return file.size <= 5 * 1024 * 1024 ? resolve(file) : reject(new Error("GIFs must be under 5 MB."));
    const url = URL.createObjectURL(file), img = new Image();
    img.onload = () => {
      const max = 1280, sc = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
      if (sc === 1 && file.size < 350 * 1024 && /png|jpeg|webp/.test(file.type)) { URL.revokeObjectURL(url); return resolve(file); }
      const c = document.createElement("canvas");
      c.width = Math.round(img.naturalWidth * sc); c.height = Math.round(img.naturalHeight * sc);
      const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      c.toBlob(b => b ? resolve(b) : reject(new Error("Couldn't process that image")), "image/jpeg", 0.84);
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("That file isn't an image this browser can read")); };
    img.src = url;
  });
}

/* ======================================================================= players */
async function renderPlayers() {
  const el = $("#tab-players");
  el.innerHTML = '<div class="page-head"><div><h1>Players</h1><p>Everyone who has joined this week. Scores are the week standings.</p></div>' +
    '<div class="actions"><input class="search" id="pl-q" type="search" placeholder="Search name or ID" aria-label="Search players">' +
    '<button class="btn quiet small" id="pl-csv" type="button">Download CSV</button></div></div><div id="pl-body">Loading…</div>';
  $("#pl-csv").onclick = () => download("/api/host/csv?kind=players").catch(fail);
  let j;
  try { j = await hapi("/api/host/players"); } catch (e) { return fail(e); }
  const draw = () => {
    const q = $("#pl-q").value.trim().toLowerCase();
    const rows = j.players.filter(p => !q || p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q));
    $("#pl-body").innerHTML = rows.length ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th class="r">Rank</th><th>Name</th><th>ID</th><th class="r">Rounds</th><th class="r">Week score</th><th>Status</th><th></th></tr></thead><tbody>' +
      rows.slice(0, 1000).map(p => '<tr><td class="r">' + (p.rank || "") + "</td><td><b>" + esc(p.name) + '</b></td><td class="muted">' + esc(p.id) + (p.guest ? ' <span class="tag">Guest</span>' : "") +
        '</td><td class="r">' + p.rounds + '</td><td class="r"><b>' + fmtNum(p.score) + "</b></td><td>" + (p.banned ? '<span class="tag warn">Banned</span> ' : "") +
        (p.online ? '<span class="tag ok">Online</span> ' : "") + (!p.pin ? '<span class="tag">No PIN</span>' : "") + '</td><td class="act"><select class="act-sel" data-id="' + esc(p.id) +
        '" aria-label="Actions"><option value="">Actions…</option><option value="rename">Rename</option><option value="signout">Sign out of their phone</option><option value="resetpin">Reset PIN</option>' +
        (p.banned ? '<option value="unban">Unban</option>' : '<option value="ban">Ban for the event</option>') + '<option value="delete">Delete all their data</option></select></td></tr>').join("") +
      "</tbody></table></div>" + (rows.length > 1000 ? '<p class="sec-help">Showing the first 1000. Search to narrow it down.</p>' : "")
      : '<p class="sec-help">' + (j.players.length ? "No players match." : "Nobody has joined yet.") + "</p>";
    $$("#pl-body .act-sel").forEach(sel => {
      sel.onchange = async () => {
        const id = sel.dataset.id, op = sel.value, p = j.players.find(x => x.id === id);
        sel.value = "";
        try {
          if (op === "rename") {
            const name = await dialog({title: "Rename " + p.name, input: {value: p.name, max: 40}, ok: "Rename"});
            if (!name) return;
            await hapi("/api/host/player", {id, op, name});
          } else if (op === "delete") {
            if (!await confirmBox("Delete " + p.name + "?", "Removes them and every answer they gave, from every round. Use this for data privacy requests. A backup is saved first.", "Delete", true)) return;
            await hapi("/api/host/player", {id, op});
          } else if (op === "ban") {
            if (!await confirmBox("Ban " + p.name + "?", "They're signed out and can't join again until you unban them.", "Ban", true)) return;
            await hapi("/api/host/player", {id, op});
          } else if (op === "resetpin") {
            if (!await confirmBox("Reset " + p.name + "'s PIN?", "They're signed out. The next time they join with their ID, they choose a new PIN.", "Reset PIN")) return;
            await hapi("/api/host/player", {id, op});
          } else if (op) await hapi("/api/host/player", {id, op});
          toast("Done."); renderPlayers();
        } catch (e) { fail(e); }
      };
    });
  };
  $("#pl-q").oninput = draw;
  draw();
}

/* ======================================================================= data */
async function renderData() {
  const el = $("#tab-data");
  el.innerHTML = '<div class="page-head"><div><h1>Data and transfer</h1><p>Everything is saved automatically in the <code>data</code> folder next to server.py. Use an export file to move the whole event to another laptop or network and carry on where you stopped.</p></div></div>' +
    '<div class="data-grid"><div class="data-block"><h2 class="sec">Move to another laptop or Wi-Fi</h2><p class="sec-help">1. Download the event file here. 2. Copy it to the other laptop (USB, chat, email). 3. On that laptop, import it below. Players sign back in with their ID and PIN; a question that was running comes back paused.</p>' +
    '<button class="btn" id="d-export" type="button">Download event file</button></div>' +
    '<div class="data-block"><h2 class="sec">Import an event file</h2><div class="file-pick"><input type="file" id="d-file" accept=".json,.gz,application/json"><span id="d-fname" class="muted"></span></div>' +
    '<div class="radio-row"><label><input type="radio" name="d-mode" value="replace" checked><span><b>Continue from this file</b><small>Replaces what is on this laptop. Use it to pick up where another laptop left off.</small></span></label>' +
    '<label><input type="radio" name="d-mode" value="merge"><span><b>Combine with this laptop</b><small>Adds the other booth\'s players, rounds and quizzes. Use it to build one week standings from several booths.</small></span></label></div>' +
    '<label class="toggle"><input type="checkbox" id="d-keepnet" checked><span><b>Keep this laptop\'s Wi-Fi settings</b><small>Recommended when the new location has a different network.</small></span></label>' +
    '<button class="btn" id="d-import" type="button" disabled>Import</button></div></div>' +
    '<hr class="rule"><div class="data-grid"><div class="data-block"><h2 class="sec">Results for organizers</h2><p class="sec-help">CSV files open in Excel or Google Sheets. Names that look like formulas are made safe.</p>' +
    '<div class="file-pick"><button class="btn quiet small" id="d-overall" type="button">Week standings</button><button class="btn quiet small" id="d-players" type="button">Player list</button></div>' +
    '<p class="sec-help">Per-round results are on the Rounds page.</p></div>' +
    '<div class="data-block"><h2 class="sec">Backups</h2><p class="sec-help">Saved automatically every few minutes, at the end of each round, and before anything is deleted or replaced.</p>' +
    '<button class="btn quiet small" id="d-backup" type="button">Back up now</button><div id="d-backups" style="margin-top:12px">Loading…</div></div></div>' +
    '<div class="danger-zone"><h2 class="sec">Start a new event</h2><p class="sec-help">Clears players and rounds (for example, next year). Settings stay. A backup is saved first.</p>' +
    '<label class="toggle"><input type="checkbox" id="d-keepq" checked><span><b>Keep quizzes</b></span></label>' +
    '<label class="toggle"><input type="checkbox" id="d-keepp"><span><b>Keep registered players and their PINs</b></span></label>' +
    '<button class="btn danger" id="d-new" type="button">Start a new event</button></div>';
  $("#d-export").onclick = () => download("/api/host/export").then(() => toast("Event file downloaded.")).catch(fail);
  $("#d-overall").onclick = () => download("/api/host/csv?kind=overall").catch(fail);
  $("#d-players").onclick = () => download("/api/host/csv?kind=players").catch(fail);
  $("#d-file").onchange = e => { $("#d-import").disabled = !e.target.files[0]; };
  $("#d-import").onclick = async () => {
    const f = $("#d-file").files[0]; if (!f) return;
    const mode = $('input[name="d-mode"]:checked').value;
    const msg = mode === "replace" ? "Everything on this laptop is replaced by the file. A backup of the current data is saved first." : "The file's players, rounds and quizzes are added to this laptop.";
    if (!await confirmBox(mode === "replace" ? "Continue from this file?" : "Combine with this file?", msg, "Import", mode === "replace")) return;
    $("#d-import").disabled = true;
    try {
      const j = await hapi("/api/host/import?mode=" + mode + "&keep_network=" + ($("#d-keepnet").checked ? 1 : 0), await f.arrayBuffer());
      await dialog({title: "Import finished", cancel: false, ok: "Done", html: "<p>" + (mode === "replace"
        ? "Loaded " + j.players + " players, " + j.rounds + " rounds and " + j.quizzes + " quizzes from “" + esc(j.source) + "” (exported " + when(j.exported_at) + ")."
        : "Added " + j.players + " players, " + j.rounds + " rounds, " + j.quizzes + " quizzes and " + j.answers + " answers.") + " Previous data was backed up as " + esc(j.backup) + ".</p>"});
      H.lastV = null; H.liveSig = ""; loadSettings(); renderData();
    } catch (e) { fail(e); $("#d-import").disabled = false; }
  };
  $("#d-backup").onclick = async () => { try { const j = await hapi("/api/host/backup/create", {}); toast("Saved " + j.name); renderBackups(); } catch (e) { fail(e); } };
  $("#d-new").onclick = async () => {
    if (!await confirmBox("Start a new event?", "Players and rounds are cleared" + ($("#d-keepp").checked ? " (players kept)" : "") + ". A backup is saved first.", "Start new event", true)) return;
    try { await hapi("/api/host/newevent", {keep_quizzes: $("#d-keepq").checked, keep_players: $("#d-keepp").checked}); toast("New event started."); H.lastV = null; renderData(); } catch (e) { fail(e); }
  };
  renderBackups();
}

async function renderBackups() {
  let j;
  try { j = await hapi("/api/host/backups"); } catch (e) { return fail(e); }
  const REASON = {auto: "Automatic", manual: "Manual", "round-end": "End of round", "before-import": "Before import", "before-restore": "Before restore",
    "before-reset": "Before reset", "before-new-event": "Before new event", "before-delete-round": "Before deleting a round", "before-delete-player": "Before deleting a player"};
  $("#d-backups").innerHTML = j.backups.length ? '<div class="tbl-wrap"><table class="tbl"><tbody>' + j.backups.slice(0, 25).map(b =>
    "<tr><td>" + when(b.time) + '</td><td class="muted">' + esc(REASON[b.reason] || b.reason) + '</td><td class="r muted">' + Math.max(1, Math.round(b.size / 1024)) + ' KB</td><td class="act">' +
    '<button class="btn small quiet" data-dl="' + esc(b.name) + '" type="button">Download</button><button class="btn small quiet" data-rs="' + esc(b.name) + '" type="button">Restore</button></td></tr>').join("") +
    "</tbody></table></div>" : '<p class="sec-help">No backups yet.</p>';
  $$("#d-backups [data-dl]").forEach(b => { b.onclick = () => download("/api/host/backup/download?name=" + encodeURIComponent(b.dataset.dl)).catch(fail); });
  $$("#d-backups [data-rs]").forEach(b => {
    b.onclick = async () => {
      if (!await confirmBox("Restore this backup?", "The event goes back to how it was at that moment. The current state is backed up first.", "Restore", true)) return;
      try { await hapi("/api/host/backup/restore", {name: b.dataset.rs}); toast("Backup restored."); H.lastV = null; renderBackups(); } catch (e) { fail(e); }
    };
  });
}

/* ======================================================================= settings */
const SET_FORM = [
  {g: "event", t: "Event", d: "Names on the projector and every phone.", f: [
    ["title", "Event title", "text", {help: "For example: University Week Quiz Bee"}],
    ["subtitle", "Institution line", "text", {help: "Small line above the title."}],
    ["organizer", "Organizer", "text", {help: "College or booth running the quiz. Optional."}],
    ["welcome", "Welcome message", "text", {wide: true, help: "One line on the lobby screen and the join page."}]]},
  {g: "brand", t: "Branding", d: "AUF blue and white by default. Enter exact colours from the brand guide, or match your college.", custom: "brand"},
  {g: "network", t: "Wi-Fi and network", d: "Players scan one code to join the Wi-Fi and a second to open the game.", f: [
    ["ssid", "Wi-Fi name (SSID)", "text"],
    ["password", "Wi-Fi password", "text", {help: "Shown on the projector so people can join."}],
    ["security", "Wi-Fi security", "select", {options: [["WPA", "WPA / WPA2 / WPA3"], ["WEP", "WEP"], ["nopass", "Open network, no password"]]}],
    ["show_wifi", "Show the Wi-Fi code", "toggle", {help: "Turn off when players are already on the network, such as campus Wi-Fi."}],
    ["host_ip", "Game address", "text", {help: "Leave empty to detect it automatically. Set it if the game code shows the wrong address."}],
    ["port", "Port", "number", {help: "Applies after restarting the server. 80 keeps the address short."}]]},
  {g: "join", t: "Joining", d: "How students identify themselves. A PIN stops anyone who knows a classmate's student number from playing as them.", f: [
    ["id_mode", "Players identify with", "select", {options: [["mask", "An ID in a fixed format"], ["free", "Any ID (letters and numbers)"], ["name", "Just their name"]]}],
    ["id_label", "What to call the ID", "text", {help: "For example: Student number"}],
    ["id_mask", "ID format", "text", {help: "# is a digit, A is a letter, * is either. AUF student numbers: ##-####-###"}],
    ["require_pin", "Ask for a 4-digit PIN", "toggle", {help: "Players rejoin from another phone or another Wi-Fi with their ID and PIN."}],
    ["allow_guests", "Let guests join without an ID", "toggle", {help: "Visitors get a code like G-4821 to rejoin with."}],
    ["name_max", "Longest name (characters)", "number"],
    ["max_players", "Most players for the event", "number"],
    ["blocked_words", "Blocked words in names", "textarea", {wide: true, help: "One per line. Names containing these are refused, including common swaps like 4 for a."}],
    ["privacy_note", "Privacy note on the join page", "textarea", {wide: true}]]},
  {g: "game", t: "Game and scoring", d: "Defaults match the original booth game: 1000 points, down to 50% for the slowest correct answer.", f: [
    ["default_time", "Default seconds per question", "number"],
    ["points", "Points for a correct answer", "number"],
    ["speed_bonus", "Faster answers earn more", "toggle", {help: "Off: every correct answer earns full points."}],
    ["min_pct", "Slowest correct answer earns (%)", "number"],
    ["grace_ms", "Grace period (milliseconds)", "number", {help: "Accepts answers that arrive just after time runs out on slow Wi-Fi."}],
    ["extend_s", "Add time button adds (seconds)", "number"],
    ["auto_reveal", "Reveal as soon as everyone has answered", "toggle"],
    ["show_counts", "Show how many picked each answer", "toggle"],
    ["board_top", "Rows on the projector leaderboard", "number"],
    ["phone_top", "Rows on phone leaderboards", "number"],
    ["overall_mode", "Week standings count", "select", {options: [["best", "Each player's best round"], ["sum", "Every round added up"]]}],
    ["one_attempt", "One attempt per quiz", "toggle", {help: "When a quiz runs again, players who already played it watch instead of scoring. Useful at booths."}],
    ["shuffle", "Shuffle question order in new rounds", "toggle"]]},
  {g: "data", t: "Backups", d: "Backups live in data/backups.", f: [
    ["backup_minutes", "Automatic backup every (minutes)", "number"],
    ["backup_keep", "Backups to keep", "number"]]}
];
const AUF_COLORS = {primary: "#0B3D91", deep: "#06214F", paper: "#F4F7FC", ink: "#0E1B33", accent: "#F5B700", opt_a: "#D62839", opt_b: "#0E8F84", opt_c: "#D98E04", opt_d: "#6A44B8"};
const COLOR_LABELS = [["primary", "AUF blue"], ["deep", "Projector background"], ["paper", "Page background"], ["ink", "Text"], ["accent", "Highlight (winners, correct)"],
  ["opt_a", "Answer 1 (triangle)"], ["opt_b", "Answer 2 (diamond)"], ["opt_c", "Answer 3 (circle)"], ["opt_d", "Answer 4 (square)"]];

async function loadSettings() {
  try { const j = await hapi("/api/host/settings"); H.settings = j.settings; H.runningPort = j.running_port; return j; } catch (e) { fail(e); return null; }
}

function fieldHtml(g, f, val) {
  const [key, label, type, o] = f, opt = o || {}, id = "s-" + g + "-" + key, path = g + "." + key;
  const help = opt.help ? "<small>" + esc(opt.help) + "</small>" : "";
  const err = '<span class="err" data-err="' + path + '"></span>';
  if (type === "toggle") return '<div class="field' + (opt.wide ? " wide" : "") + '"><label class="toggle"><input type="checkbox" id="' + id + '" data-path="' + path + '" data-type="bool"' +
    (val ? " checked" : "") + "><span><b>" + esc(label) + "</b>" + help + "</span></label>" + err + "</div>";
  let input;
  if (type === "select") input = '<select class="input" id="' + id + '" data-path="' + path + '">' + opt.options.map(x => '<option value="' + x[0] + '"' + (x[0] === val ? " selected" : "") + ">" + esc(x[1]) + "</option>").join("") + "</select>";
  else if (type === "textarea") input = '<textarea class="input" id="' + id + '" data-path="' + path + '"' + (Array.isArray(val) ? ' data-type="list"' : "") + ">" + esc(Array.isArray(val) ? val.join("\n") : val) + "</textarea>";
  else input = '<input class="input" id="' + id + '" data-path="' + path + '"' + (type === "number" ? ' type="number" data-type="int"' : ' type="text"') + ' value="' + esc(val) + '">';
  return '<label class="field' + (opt.wide ? " wide" : "") + '" for="' + id + '"><span>' + esc(label) + "</span>" + input + help + err + "</label>";
}

function brandHtml(b) {
  return '<div class="fields"><div class="field wide"><span>Logo</span><div class="logo-row"><div class="logo-box" id="s-logo-box">' + (b.logo ? '<img src="/media/' + esc(b.logo) + '" alt="">' : "AUF") +
    '</div><div><input type="file" id="s-logo-file" accept="image/png,image/jpeg,image/webp" hidden><button class="btn small quiet" id="s-logo-up" type="button">Upload logo</button> ' +
    (b.logo ? '<button class="link" id="s-logo-rm" type="button">Remove</button>' : "") + '<small>Use the official seal as a PNG with a transparent background. Without one, the screens show “AUF” in type.</small></div></div>' +
    '<input type="hidden" data-path="brand.logo" id="s-logo" value="' + esc(b.logo) + '"><span class="err" data-err="brand.logo"></span></div>' +
    '<div class="field wide"><span>Colours</span><div class="colors">' + COLOR_LABELS.map(([k, l]) => '<label class="color"><input type="color" data-path="brand.' + k + '" value="' + esc(b[k]) + '"><span>' + esc(l) +
    "<br><code>" + esc(b[k]) + "</code></span></label>").join("") + '</div><div class="preview" id="s-preview"></div><p><button class="link" id="s-auf" type="button">Reset to AUF colours</button></p></div></div>';
}

function previewBrand() {
  const get = k => ($('[data-path="brand.' + k + '"]') || {}).value;
  const pv = $("#s-preview");
  if (!pv) return;
  pv.innerHTML = LETTERS.map(c => '<div class="tile tile-' + c + '" style="background:' + get("opt_" + c) + '"><span class="shape">' + SHAPES[c] + '</span><span class="label">Answer ' + c.toUpperCase() + "</span></div>").join("");
  $$('input[type=color]').forEach(i => { i.nextElementSibling.querySelector("code").textContent = i.value.toUpperCase(); });
}

async function renderSettings() {
  const el = $("#tab-settings");
  el.innerHTML = '<div class="page-head"><div><h1>Settings</h1><p>Changes apply to every screen as soon as you save.</p></div></div><div id="s-body">Loading…</div>';
  const j = await loadSettings();
  if (!j) return;
  const S = j.settings;
  $("#s-body").innerHTML = SET_FORM.map(sec => '<section class="settings-grid"><header><h2>' + esc(sec.t) + "</h2><p>" + esc(sec.d) + "</p></header>" +
    (sec.custom === "brand" ? brandHtml(S.brand) : '<div class="fields">' + sec.f.map(f => fieldHtml(sec.g, f, S[sec.g][f[0]])).join("") + "</div>") + "</section>").join("") +
    '<section class="settings-grid"><header><h2>Host password</h2><p>Changing it signs out every other device using the host console.</p></header><div class="fields">' +
    '<label class="field"><span>Current password</span><input class="input" type="password" id="pw-cur" autocomplete="current-password"></label>' +
    '<label class="field"><span>New password (8+ characters)</span><input class="input" type="password" id="pw-new" autocomplete="new-password"></label>' +
    '<div class="field"><span>&nbsp;</span><button class="btn quiet" id="pw-save" type="button">Change password</button></div></div></section>' +
    '<div class="save-bar"><button class="btn" id="s-save" type="button">Save settings</button><span id="s-note" class="muted"></span></div>';
  const note = () => {
    const port = +$('[data-path="network.port"]').value;
    $("#s-note").textContent = port && port !== H.runningPort ? "The server is running on port " + H.runningPort + ". Restart it to use port " + port + "." :
      "Example ID for players: " + maskExample($('[data-path="join.id_mask"]').value);
  };
  $("#s-body").addEventListener("input", e => { if (e.target.type === "color") previewBrand(); note(); });
  previewBrand(); note();
  $("#s-auf").onclick = () => { Object.entries(AUF_COLORS).forEach(([k, v]) => { const i = $('[data-path="brand.' + k + '"]'); if (i) i.value = v; }); previewBrand(); };
  $("#s-logo-up").onclick = () => $("#s-logo-file").click();
  $("#s-logo-file").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const up = await hapi("/api/host/upload", f.size > 1024 * 1024 ? await shrinkImage(f) : f);
      $("#s-logo").value = up.id; $("#s-logo-box").innerHTML = '<img src="' + esc(up.url) + '" alt="">';
      toast("Logo uploaded. Save settings to use it.");
    } catch (err) { fail(err); }
  };
  if ($("#s-logo-rm")) $("#s-logo-rm").onclick = () => { $("#s-logo").value = ""; $("#s-logo-box").textContent = "AUF"; toast("Logo removed. Save settings to apply."); };
  $("#s-save").onclick = saveSettings;
  $("#pw-save").onclick = async () => {
    try { await hapi("/api/host/password", {current: $("#pw-cur").value, new: $("#pw-new").value}); $("#pw-cur").value = $("#pw-new").value = ""; toast("Password changed."); }
    catch (e) { fail(e); }
  };
}

function maskExample(mask) {
  const d = "242156111"; let i = 0, out = "";
  for (const c of mask || "") { if (c === "#") out += d[i++ % d.length]; else if (c === "A") { out += "ABCDEFGH"[i++ % 8]; } else if (c === "*") { out += "X"; i++; } else out += c; }
  return out;
}

async function saveSettings() {
  const out = {};
  $$("#s-body [data-path]").forEach(i => {
    const [g, k] = i.dataset.path.split(".");
    out[g] = out[g] || {};
    let v = i.value;
    if (i.dataset.type === "bool") v = i.checked;
    else if (i.dataset.type === "int") v = i.value === "" ? null : Number(i.value);
    else if (i.dataset.type === "list") v = i.value.split(/[\n,]/).map(x => x.trim()).filter(Boolean);
    out[g][k] = v;
  });
  $$("#s-body [data-err]").forEach(e => { e.textContent = ""; });
  try {
    const j = await hapi("/api/host/settings", {settings: out});
    H.settings = j.settings;
    refreshTheme();
    toast("Settings saved."); H.lastV = null; H.ctrlSig = ""; loadInfo();
  } catch (e) {
    const errs = (e.data && e.data.errors) || {};
    Object.entries(errs).forEach(([p, m]) => { const el = $('[data-err="' + p + '"]'); if (el) el.textContent = m; });
    const first = Object.keys(errs)[0];
    if (first) { const f = $('[data-path="' + first + '"]'); if (f) f.scrollIntoView({block: "center"}); }
    fail(e);
  }
}

function refreshTheme() {
  const l = $('link[href^="/theme.css"]');
  if (l) l.href = "/theme.css?" + Date.now();
}

/* ======================================================================= start */
(async function boot() {
  const m = (location.hash || "").match(/auto=([\w-]+)/);
  if (m) {
    try { const j = await api("/api/host/login", {code: m[1]}); setTok(j.token); } catch (e) { /* not on this laptop */ }
    history.replaceState(null, "", location.pathname + "#live");
  }
  frame();
  if (H.tok) {
    try { await hapi("/api/host/state"); loadSettings(); return showShell(); }
    catch (e) { if (e.status !== 401) { showLogin(e.message); return; } }
  }
  try { const i = await api("/api/info"); H.ev = i.event; } catch (e) { /* */ }
  showLogin();
})();
