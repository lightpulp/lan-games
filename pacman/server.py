#!/usr/bin/env python3
"""Pacman booth server. Python 3.7+, standard library only, no internet needed.
Run:  python server.py        (port 8000)
      python server.py 80     (port 80 -> players type just http://<ip>/, may need admin/sudo)
Reset leaderboard: stop server, delete data.json.
"""
import json, os, re, sys, socket, threading, time, secrets
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, "static")
DB = os.path.join(BASE, "data.json")
ID_RE = re.compile(r"^\d{2}-\d{4}-\d{3}$")   # e.g. 24-2156-111  (edit if your IDs differ)
TOP_N = 20

lock = threading.Lock()
tokens = {}  # token -> student id
players = json.load(open(DB)) if os.path.exists(DB) else {}


def save():
    tmp = DB + ".tmp"
    with open(tmp, "w") as f:
        json.dump(players, f)
    os.replace(tmp, DB)


def ranked():
    return sorted(players.items(), key=lambda kv: (-kv[1]["score"], kv[1]["t"]))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def log_message(self, *a):
        pass

    def reply(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/leaderboard"):
            with lock:
                rows = [{"name": p["name"], "score": p["score"], "level": p["level"]}
                        for _, p in ranked()[:TOP_N]]
            return self.reply(rows)
        if self.path.split("?")[0] in ("/board", "/board/"):
            self.path = "/board.html"
        super().do_GET()

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except Exception:
            return self.reply({"error": "bad request"}, 400)

        if self.path == "/api/login":
            sid = str(body.get("id", "")).strip()
            name = " ".join(str(body.get("name", "")).split())[:24]
            if not ID_RE.match(sid):
                return self.reply({"error": "ID must look like 24-2156-111"}, 400)
            if not name:
                return self.reply({"error": "Please enter your name"}, 400)
            with lock:
                p = players.setdefault(sid, {"score": 0, "level": 0, "t": time.time()})
                p["name"] = name
                tok = secrets.token_hex(8)
                tokens[tok] = sid
                save()
                return self.reply({"token": tok, "name": name, "best": p["score"], "level": p["level"]})

        if self.path == "/api/score":
            with lock:
                sid = tokens.get(body.get("token"))
                if not sid:
                    return self.reply({"error": "please sign in again"}, 401)
                p = players[sid]
                score = max(0, int(body.get("score", 0)))
                level = min(50, max(0, int(body.get("level", 0))))
                if score > p["score"]:
                    p["score"], p["t"] = score, time.time()
                p["level"] = max(p["level"], level)
                save()
                rank = [k for k, _ in ranked()].index(sid) + 1
                return self.reply({"best": p["score"], "rank": rank, "total": len(players)})

        self.reply({"error": "not found"}, 404)


def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packets sent; just picks the active interface
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    suffix = "" if port == 80 else f":{port}"
    print("\n  PACMAN BOOTH SERVER RUNNING")
    for ip in lan_ips():
        print(f"  Players:      http://{ip}{suffix}/")
        print(f"  Big screen:   http://{ip}{suffix}/board")
    print("  (Ctrl+C to stop)\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
