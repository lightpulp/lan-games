/* Projector board: read-only, no sign-in. Shows the lobby with join codes, questions, results and standings. */
"use strict";
let st = null, info = null, lastV = null, sig = "", infoSig = "";
const clock = makeClock();
const stage = $("#stage"), barEl = $("#bar"), footEl = $("#foot"), line = $("#timeline");

async function loadInfo() {
  try {
    info = await api("/api/info");
    const s = JSON.stringify([info.ip, info.port, info.ssid, info.password, info.show_wifi]);
    if (s !== infoSig) { infoSig = s; sig = ""; if (st) render(); }
  } catch (e) { /* keep the old codes */ }
}

function topBar() {
  const s = st;
  let where = "";
  if (s.round && ["question", "paused", "reveal"].includes(s.phase) && s.question) {
    where = '<div class="where"><span class="rt">' + esc(s.round.title) + '</span><span class="qn">Question ' + s.question.n + " of " + s.round.total + "</span></div>";
  } else if (s.round && s.phase !== "idle") {
    where = '<div class="where"><span class="rt">Round</span><span class="qn">' + esc(s.round.title) + "</span></div>";
  }
  const h = lockupHtml(s.event) + where;
  if (barEl.innerHTML !== h) barEl.innerHTML = h;
}

function footer() {
  const s = st;
  let h = "";
  if (info && ["reveal", "leaderboard", "ended", "overall"].includes(s.phase)) {
    h = "<span>Join the next round at <b>" + esc(gameUrl(info)) + "</b>" + (info.show_wifi ? " on Wi-Fi <b>" + esc(info.ssid) + "</b>" : "") +
        "</span><span>" + (s.online || 0) + " connected</span>";
  }
  if (footEl.innerHTML !== h) footEl.innerHTML = h;
}

function lobby() {
  const s = st;
  const title = s.event.title;
  stage.innerHTML = '<section class="lobby"><div><p class="round-name">' + (s.round ? "Next up: " + esc(s.round.title) : "Get ready for the next round") + "</p>" +
    '<h1 class="title">' + esc(title) + '</h1><p class="welcome">' + esc(s.event.welcome || "") + "</p>" +
    '<div class="count"><b id="count">0</b><span id="countlbl">players in</span></div><div class="names" id="names"></div></div>' +
    '<div class="joins" id="joins">' + (info ? joinCards(info) : "") + "</div></section>";
  lobbyLive();
}

function lobbyLive() {
  const s = st;
  const n = s.online || 0;
  $("#count").textContent = n;
  $("#countlbl").textContent = n === 1 ? "player in" : "players in";
  const names = (s.names || []).slice(-60);
  $("#names").innerHTML = names.map(x => "<span>" + esc(x) + "</span>").join("");
}

function questionView() {
  const s = st, q = s.question;
  const revealed = s.phase === "reveal" || s.phase === "leaderboard";
  let left;
  if (revealed) {
    const total = q.counts ? Object.values(q.counts).reduce((a, b) => a + b, 0) : 0;
    const pct = total && q.counts ? Math.round(100 * (q.counts[q.correct] || 0) / total) : null;
    left = '<div class="clock">' + (pct == null ? '<span class="lbl">Answer</span>' : '<span class="pct">' + pct + '%</span><span class="lbl">got it right</span>') +
           '<span class="ans">' + s.answered + " answered</span></div>";
  } else {
    left = '<div class="clock"><span class="secs" id="secs"></span><span class="lbl">seconds</span><span class="ans" id="answered"></span></div>';
  }
  const badge = q.points === 2 ? '<span class="badge">Double points</span><br>' : q.points === 0 ? '<span class="badge">Just for fun</span><br>' : "";
  stage.innerHTML = '<section class="qlayout">' + left + '<div class="qbody"><div style="flex:1;min-width:0">' + badge + '<p class="qtext">' + esc(q.text) +
    "</p></div>" + imgHtml(q) + "</div>" + tilesHtml(q, "show") + "</section>" +
    (s.phase === "paused" ? '<div class="paused-note"><p>Paused</p></div>' : "");
}

function boardList(rows) {
  return '<ol class="sb">' + rows.map(r => {
    return '<li class="' + (r.rank <= 3 ? "top" : "") + '"><span class="rk">' + r.rank + '</span><span class="nm">' + esc(r.name) +
      '</span><span class="sc">' + fmtNum(r.score) + "</span></li>";
  }).join("") + "</ol>";
}

function scoreboard(title, sub) {
  const rows = (st.board || []).slice(0, (st.top && st.top.board) || 10);
  stage.innerHTML = '<section class="scoreboard"><h2>' + esc(title) + '</h2><p class="sub">' + esc(sub) + "</p>" +
    (rows.length ? boardList(rows) : '<p class="idle-note">No scores yet.</p>') + "</section>";
}

function podium() {
  const rows = st.board || [];
  const p = i => rows[i] || null;
  const col = (r, n) => '<div class="pod p' + n + (r ? "" : " empty") + '"><div class="who">' + (r ? esc(r.name) : "&nbsp;") + '</div><div class="block"><span class="place">' +
    (r ? r.rank : n) + '</span><span class="pts">' + (r ? fmtNum(r.score) : "") + "</span></div></div>";
  const rest = rows.slice(3, (st.top && st.top.board) || 10);
  stage.innerHTML = '<section class="podium-wrap"><h2>Final results</h2><div class="podium">' + col(p(1), 2) + col(p(0), 1) + col(p(2), 3) + "</div>" +
    '<div class="rest">' + (rest.length ? boardList(rest) : "") + "</div></section>";
}

function signature() {
  const s = st, q = s.question || {};
  if (s.phase === "idle" || s.phase === "lobby") return [s.phase, s.round && s.round.title, s.event.title, s.event.welcome, infoSig].join("|");
  if (s.phase === "question" || s.phase === "paused") return [s.phase, q.n, q.text, q.image].join("|");
  return [s.phase, s.v].join("|");
}

function render() {
  const s = st;
  topBar(); footer();
  const q = s.question;
  clock.set(q && q.left, q && q.dur, s.phase === "question");
  line.hidden = !(s.phase === "question" || s.phase === "paused");
  const g = signature();
  if (g !== sig) {
    sig = g;
    if (s.phase === "idle" || s.phase === "lobby") lobby();
    else if ((s.phase === "question" || s.phase === "paused" || s.phase === "reveal") && q) questionView();
    else if (s.phase === "leaderboard") scoreboard("Leaderboard", q ? "After question " + q.n + " of " + (s.round ? s.round.total : "") : "");
    else if (s.phase === "ended") podium();
    else if (s.phase === "overall") scoreboard("Week standings", s.mode === "sum" ? "Points from every round played" : "Each player's best round");
    else stage.innerHTML = '<div class="empty-state"><p>Waiting for the host…</p></div>';
  } else if (s.phase === "idle" || s.phase === "lobby") {
    lobbyLive();
  }
  const a = $("#answered");
  if (a) a.textContent = (s.answered || 0) + " of " + (s.online || 0) + " answered";
}

async function poll() {
  clearTimeout(poll.t);
  try {
    const j = await api("/api/state" + (lastV != null ? "?v=" + lastV : ""));
    if (!j.same) { st = j; lastV = j.v; render(); }
  } catch (e) { /* server restarting: keep the last screen */ }
  poll.t = setTimeout(poll, 1000);
}

function frame() {
  if (st && (st.phase === "question" || st.phase === "paused")) {
    const left = clock.left();
    const sec = $("#secs");
    if (sec) {
      const t = String(Math.ceil(left));
      if (sec.textContent !== t) sec.textContent = t;
      sec.classList.toggle("hot", left <= 5);
    }
    $("#timeline i").style.transform = "scaleX(" + clock.frac().toFixed(4) + ")";
    line.classList.toggle("hot", left <= 5);
  }
  requestAnimationFrame(frame);
}

loadInfo().then(poll);
setInterval(loadInfo, 30000);
frame();
