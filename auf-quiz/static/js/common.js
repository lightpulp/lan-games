/* Shared helpers for the player, board and host pages. No frameworks, works offline. */
"use strict";
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const LETTERS = ["a", "b", "c", "d"];
const SHAPES = {
  a: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3L22.5 21H1.5z"/></svg>',
  b: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1.5L22.5 12 12 22.5 1.5 12z"/></svg>',
  c: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/></svg>',
  d: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2.5" y="2.5" width="19" height="19" rx="1.5"/></svg>'
};
const SHAPE_NAMES = {a: "Triangle", b: "Diamond", c: "Circle", d: "Square"};

async function api(path, body, opts) {
  opts = opts || {};
  const init = {headers: Object.assign({}, opts.headers || {}), cache: "no-store"};
  if (body !== undefined) {
    init.method = "POST";
    if (body instanceof Blob || body instanceof ArrayBuffer || typeof body === "string") init.body = body;
    else { init.body = JSON.stringify(body); init.headers["Content-Type"] = "application/json"; }
  }
  let r;
  try { r = await fetch(path, init); }
  catch (e) { throw Object.assign(new Error("Can't reach the quiz server. Check that you're on the event Wi-Fi."), {offline: true}); }
  let j = {};
  try { j = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) throw Object.assign(new Error(j.error || ("Request failed (" + r.status + ")")), {status: r.status, data: j});
  return j;
}

function qrSvg(text) {
  const q = qrcode(0, "M");
  q.addData(text);
  q.make();
  return q.createSvgTag({cellSize: 6, margin: 12, scalable: true});
}

function wifiString(i) {
  const e = s => String(s || "").replace(/([\\;,:"])/g, "\\$1");
  return i.security === "nopass" || !i.password
    ? "WIFI:T:nopass;S:" + e(i.ssid) + ";;"
    : "WIFI:T:" + (i.security || "WPA") + ";S:" + e(i.ssid) + ";P:" + e(i.password) + ";;";
}

function gameUrl(info, ip) {
  return "http://" + (ip || info.ip) + (Number(info.port) === 80 ? "" : ":" + info.port) + "/";
}

/* Two QR cards: join the Wi-Fi, then open the game. The steps really are a sequence. */
function joinCards(info, ip) {
  const url = gameUrl(info, ip);
  let h = "";
  let n = 1;
  if (info.show_wifi) {
    h += '<div class="qr"><p class="step"><b>' + n++ + '</b> Join the Wi-Fi</p>' + qrSvg(wifiString(info)) +
         '<p class="cap">' + esc(info.ssid) + (info.password ? '<br><span style="font-weight:400">Password: ' + esc(info.password) + "</span>" : "") + "</p></div>";
  }
  h += '<div class="qr"><p class="step"><b>' + n + '</b> Open the game</p>' + qrSvg(url) + '<p class="cap">' + esc(url) + "</p></div>";
  return h;
}

/* Answer tiles. mode: "pick" (player can tap), "show" (display only). */
function tilesHtml(q, mode, opt) {
  opt = opt || {};
  const letters = LETTERS.filter(c => q.options && q.options[c] != null);
  const total = q.counts ? letters.reduce((s, c) => s + (q.counts[c] || 0), 0) : 0;
  return '<div class="tiles' + (letters.length === 2 ? " two" : "") + '">' + letters.map(c => {
    const cls = ["tile", "tile-" + c];
    if (q.correct && opt.host) { if (c === q.correct) cls.push("is-correct"); }
    else if (q.correct) cls.push(c === q.correct ? "is-correct" : "is-dim");
    else if (opt.picked) cls.push(c === opt.picked ? "is-picked" : "is-dim");
    const count = q.counts ? '<span class="count">' + (q.counts[c] || 0) + "</span>" : "";
    const bar = q.counts && total ? '<span class="bar" style="width:' + Math.round(100 * (q.counts[c] || 0) / total) + '%"></span>' : "";
    const tag = mode === "pick" ? "button" : "div";
    return "<" + tag + ' class="' + cls.join(" ") + '" data-c="' + c + '"' + (mode === "pick" ? ' type="button"' : "") +
      ' aria-label="' + SHAPE_NAMES[c] + ": " + esc(q.options[c]) + '"><span class="shape">' + SHAPES[c] + '</span><span class="label">' +
      esc(q.options[c]) + "</span>" + count + bar + "</" + tag + ">";
  }).join("") + "</div>";
}

function imgHtml(q) {
  return q && q.image ? '<img class="qimg" src="' + esc(q.image) + '" alt="">' : "";
}

function lockupHtml(ev) {
  const mark = ev.logo ? '<span class="mark has-logo"><img src="' + esc(ev.logo) + '" alt=""></span>' : '<span class="mark" aria-hidden="true">AUF</span>';
  return '<div class="lockup">' + mark + '<div class="words"><span class="inst">' + esc(ev.subtitle || "Angeles University Foundation") +
         '</span><span class="event">' + esc(ev.title) + "</span></div></div>";
}

/* Smooth countdown driven by the server's "seconds left" plus local elapsed time. */
function makeClock() {
  let left = 0, dur = 1, at = 0, running = false;
  return {
    set(l, d, run) { left = +l || 0; dur = +d || 1; at = performance.now(); running = !!run; },
    stop() { running = false; },
    left() { return Math.max(0, left - (running ? (performance.now() - at) / 1000 : 0)); },
    frac() { return dur ? this.left() / dur : 0; }
  };
}

function ordinal(n) {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function fmtNum(n) { return Number(n || 0).toLocaleString("en-US"); }
