#!/usr/bin/env python3
"""Kahoot-style booth quiz. Python 3.7+, standard library only, fully offline.
  python server.py [port]        (port defaults to config.json -> 80, falls back to 8000)
  python server.py --no-browser  (don't auto-open the host page)
"""
import json, os, re, sys, socket, threading, time, secrets, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT, QFILE, CFILE, DB = (os.path.join(BASE, p) for p in ("static", "questions.json", "config.json", "data.json"))
ID_RE = re.compile(r"^\d{2}-\d{4}-\d{3}$")   # e.g. 24-2156-111
cfg = {"title": "Quiz Booth", "ssid": "MyHotspot", "password": "12345678", "security": "WPA", "port": 80, "host_ip": ""}
if os.path.exists(CFILE):
    cfg.update(json.load(open(CFILE, encoding="utf-8")))
else:
    json.dump(cfg, open(CFILE, "w"), indent=2)
HOST_KEY = secrets.token_urlsafe(6)
lock = threading.RLock()


def load_questions():
    raw = json.load(open(QFILE, encoding="utf-8"))
    out = []
    for k, v in sorted(raw.items(), key=lambda kv: int(re.sub(r"\D", "", kv[0]) or 0)):
        out.append({"text": v.get("Question") or v.get("question", ""),
                    "options": {c: str(v.get(c, v.get(c.upper(), ""))) for c in "abcd"},
                    "answer": str(v.get("answer", "a")).strip().lower()[:1],
                    "image": v.get("image", "") or "",
                    "time": float(v.get("time", 15))})
    return out


questions = load_questions()
S = {"phase": "lobby", "q": -1, "start": 0.0, "dur": 15.0}   # lobby|question|reveal|leaderboard|ended
players, answers = {}, {}                                      # players[id]={name,token}; answers[q][id]=[choice,ms,pts]
if os.path.exists(DB):
    d = json.load(open(DB))
    players, answers = d.get("players", {}), d.get("answers", {})


def save():
    with open(DB + ".tmp", "w") as f:
        json.dump({"players": players, "answers": answers}, f)
    os.replace(DB + ".tmp", DB)


def totals():
    t = {}
    for qa in answers.values():
        for pid, a in qa.items():
            t[pid] = t.get(pid, 0) + a[2]
    rows = [{"id": i, "name": p["name"], "score": t.get(i, 0)} for i, p in players.items()]
    rows.sort(key=lambda r: (-r["score"], r["name"].lower()))
    for n, r in enumerate(rows):
        r["rank"] = n + 1
    return rows


def go(q):
    q = max(0, min(len(questions) - 1, q))
    S["q"] = q
    if answers.get(str(q)):
        S["phase"] = "reveal"                      # already played -> just show results
    else:
        S.update(phase="question", start=time.time(), dur=questions[q]["time"])


def view(tok=None, host=False):
    now, ph, q, rows = time.time(), S["phase"], S["q"], totals()
    d = {"phase": ph, "q": q, "total": len(questions), "players": len(players), "title": cfg["title"],
         "board": [{"name": r["name"], "score": r["score"], "rank": r["rank"]} for r in rows[:10]]}
    if ph == "lobby":
        d["names"] = [p["name"] for p in players.values()][-40:]
    if ph != "ended" and 0 <= q < len(questions):
        Q, qa = questions[q], answers.get(str(q), {})
        qd = {"text": Q["text"], "options": Q["options"], "image": Q["image"], "time": Q["time"]}
        if ph == "question":
            qd.update(left=max(0, S["dur"] - (now - S["start"])), dur=S["dur"])
        if host or ph != "question":
            qd["correct"] = Q["answer"]
            qd["counts"] = {c: sum(1 for a in qa.values() if a[0] == c) for c in "abcd"}
        d["question"], d["answered"] = qd, len(qa)
    pid = next((i for i, p in players.items() if tok and p["token"] == tok), None)
    if pid:
        r = next(r for r in rows if r["id"] == pid)
        a = answers.get(str(q), {}).get(pid)
        d["me"] = {"name": r["name"], "score": r["score"], "rank": r["rank"],
                   "choice": a[0] if a else None, "pts": a[2] if a else 0}
    if host:
        d["list"] = [{"id": r["id"], "name": r["name"], "score": r["score"]} for r in rows]
        d["titles"] = [Q["text"] for Q in questions]
    return d


def host_action(a, v):
    global questions
    ph, q, n = S["phase"], S["q"], len(questions)
    if a == "next":
        if ph == "lobby": go(0)
        elif ph != "ended": go(q + 1) if q < n - 1 else S.update(phase="ended")
    elif a == "prev":
        if ph == "ended": go(n - 1)
        elif q <= 0: S.update(phase="lobby", q=-1)
        else: go(q - 1)
    elif a == "reveal" and ph == "question": S["phase"] = "reveal"
    elif a == "board" and q >= 0: S["phase"] = "leaderboard"
    elif a == "replay" and q >= 0:
        answers.pop(str(q), None); S.update(phase="question", start=time.time(), dur=questions[q]["time"])
    elif a == "extend" and ph == "question": S["dur"] += 5
    elif a == "goto": go(int(v))
    elif a == "lobby": S.update(phase="lobby", q=-1)
    elif a == "end": S["phase"] = "ended"
    elif a == "reset": answers.clear(); S.update(phase="lobby", q=-1)
    elif a == "wipe": answers.clear(); players.clear(); S.update(phase="lobby", q=-1)
    elif a == "kick":
        players.pop(v, None)
        for qa in answers.values(): qa.pop(v, None)
    elif a == "reload":
        questions = load_questions()
    save()


def ticker():
    while True:
        time.sleep(0.2)
        with lock:
            if S["phase"] == "question":
                qa = answers.get(str(S["q"]), {})
                if time.time() - S["start"] >= S["dur"] or (players and len(qa) >= len(players)):
                    S["phase"] = "reveal"


def lan_ips():
    ips = set()
    try:
        for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(i[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1)); ips.add(s.getsockname()[0]); s.close()
    except Exception:
        pass
    ips = [i for i in ips if not i.startswith(("127.", "169.254."))]   # 169.254 = no real network
    pref = lambda i: (0 if i == "192.168.137.1" else 1 if i.startswith("192.168.") else 2 if i.startswith("10.") else 3, i)
    return sorted(ips, key=pref)


PAGES = {"/": "/index.html", "/host": "/host.html", "/board": "/board.html"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a): pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def reply(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        arg = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        with lock:
            if path == "/api/state":
                return self.reply(view(arg.get("token")))
            if path == "/api/host/state":
                return self.reply(view(host=True)) if arg.get("key") == HOST_KEY else self.reply({"error": "bad key"}, 403)
            if path == "/api/info":
                ips = lan_ips()
                return self.reply({"ssid": cfg["ssid"], "password": cfg["password"], "security": cfg["security"],
                                   "ips": ips, "ip": cfg["host_ip"] or (ips[0] if ips else "localhost"), "port": PORT})
        self.path = PAGES.get(path.rstrip("/") or "/", path)
        super().do_GET()

    def do_POST(self):
        try:
            b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except Exception:
            return self.reply({"error": "bad request"}, 400)
        with lock:
            if self.path == "/api/login":
                sid, name = str(b.get("id", "")).strip(), " ".join(str(b.get("name", "")).split())[:24]
                if not ID_RE.match(sid): return self.reply({"error": "ID must look like 24-2156-111"}, 400)
                if not name: return self.reply({"error": "Please enter your name"}, 400)
                p = players.setdefault(sid, {"token": secrets.token_hex(8)})
                p["name"] = name; save()
                return self.reply({"token": p["token"]})
            if self.path == "/api/answer":
                pid = next((i for i, p in players.items() if p["token"] == b.get("token")), None)
                if not pid: return self.reply({"error": "sign in again"}, 401)
                el = time.time() - S["start"]
                c = str(b.get("choice", "")).lower()
                if S["phase"] != "question" or el > S["dur"] + 0.7 or c not in "abcd" or not c:
                    return self.reply({"error": "too late"}, 400)
                qa = answers.setdefault(str(S["q"]), {})
                if pid not in qa:
                    ok = c == questions[S["q"]]["answer"]
                    qa[pid] = [c, int(el * 1000), round(1000 * (1 - 0.5 * min(1, el / S["dur"]))) if ok else 0]
                    save()
                return self.reply({"ok": True})
            if self.path == "/api/host":
                if b.get("key") != HOST_KEY: return self.reply({"error": "bad key"}, 403)
                try:
                    host_action(b.get("action"), b.get("value"))
                except Exception as e:
                    return self.reply({"error": str(e)}, 400)
                return self.reply({"ok": True})
        self.reply({"error": "not found"}, 404)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    PORT = int(args[0]) if args else int(cfg["port"])
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError:
        print(f"  (port {PORT} unavailable, using 8000)"); PORT = 8000
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=ticker, daemon=True).start()
    sfx = "" if PORT == 80 else f":{PORT}"
    ips = lan_ips()
    print(f"\n  QUIZ SERVER RUNNING  ({len(questions)} questions)")
    for ip in ips: print(f"  Players:      http://{ip}{sfx}/")
    if not ips: print("  !! No network address found - is your hotspot on?")
    host_url = f"http://localhost{sfx}/host?key={HOST_KEY}"
    print(f"  Host:         {host_url}\n  Leaderboard:  http://localhost{sfx}/board\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(host_url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
