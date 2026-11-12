#!/usr/bin/env python3
"""
AUF University Week Quiz - a Kahoot-style quiz that runs on a local network.
Python 3.7+, standard library only, works fully offline.

  python server.py                    start (port from Settings, default 80; falls back to 8000)
  python server.py 8080               start on a specific port
  python server.py --no-browser       don't open the host console automatically
  python server.py --data DIR         keep event data in another folder (default: ./data)
  python server.py --reset-password   print a new host password and exit
"""
import base64, csv, gzip, hashlib, hmac, io, json, os, random, re, secrets, socket, sys, threading, time
import traceback, unicodedata, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs

VERSION = "2.0.0"
SCHEMA = 2
EXPORT_FORMAT = "auf-quiz-event"


def _arg(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.realpath(os.path.join(BASE, "static"))
DATA = os.path.abspath(_arg("--data") or os.path.join(BASE, "data"))
DBFILE = os.path.join(DATA, "event.json")
UPLOADS = os.path.join(DATA, "uploads")
BACKUPS = os.path.join(DATA, "backups")

LIMIT_JSON = 256 * 1024          # ordinary API bodies
LIMIT_QUIZ = 4 * 1024 * 1024     # quiz save / quiz import
LIMIT_UPLOAD = 5 * 1024 * 1024   # one image
LIMIT_IMPORT = 120 * 1024 * 1024  # full event file (images are base64 inside)
MAX_QUESTIONS = 300
ONLINE_SECONDS = 6.0
LETTERS = ("a", "b", "c", "d")

# --------------------------------------------------------------------------------------------
# Settings: every value the host can change, with its type, default and limits.
# ("str", default, maxlen) ("int", default, lo, hi) ("bool", default) ("enum", default, [choices])
# ("color", default) ("media", default) ("list", default, max_items, max_len_each) ("text", default, maxlen)
# --------------------------------------------------------------------------------------------
SPEC = {
    "event": {
        "title": ("str", "University Week Quiz", 60),
        "subtitle": ("str", "Angeles University Foundation", 80),
        "organizer": ("str", "", 80),
        "welcome": ("str", "Join the Wi-Fi, scan the game code, and play.", 160),
    },
    "brand": {
        "primary": ("color", "#0B3D91"),
        "deep": ("color", "#06214F"),
        "paper": ("color", "#F4F7FC"),
        "ink": ("color", "#0E1B33"),
        "accent": ("color", "#F5B700"),
        "opt_a": ("color", "#D62839"),
        "opt_b": ("color", "#0E8F84"),
        "opt_c": ("color", "#D98E04"),
        "opt_d": ("color", "#6A44B8"),
        "logo": ("media", ""),
    },
    "network": {
        "ssid": ("str", "", 32),
        "password": ("str", "", 63),
        "security": ("enum", "WPA", ["WPA", "WEP", "nopass"]),
        "show_wifi": ("bool", True),
        "host_ip": ("str", "", 64),
        "port": ("int", 80, 1, 65535),
    },
    "join": {
        "id_mode": ("enum", "mask", ["mask", "free", "name"]),
        "id_label": ("str", "Student number", 30),
        "id_mask": ("str", "##-####-###", 24),
        "allow_guests": ("bool", True),
        "require_pin": ("bool", True),
        "name_max": ("int", 24, 4, 40),
        "max_players": ("int", 1000, 1, 5000),
        "blocked_words": ("list", [], 300, 40),
        "privacy_note": ("text", "Your student number and name are used only to keep score during "
                                 "University Week, in line with the Data Privacy Act of 2012.", 300),
    },
    "game": {
        "default_time": ("int", 20, 5, 300),
        "points": ("int", 1000, 0, 10000),
        "speed_bonus": ("bool", True),
        "min_pct": ("int", 50, 0, 100),
        "grace_ms": ("int", 600, 0, 3000),
        "extend_s": ("int", 5, 1, 120),
        "auto_reveal": ("bool", True),
        "show_counts": ("bool", True),
        "board_top": ("int", 10, 3, 20),
        "phone_top": ("int", 5, 0, 10),
        "overall_mode": ("enum", "best", ["best", "sum"]),
        "one_attempt": ("bool", False),
        "shuffle": ("bool", False),
    },
    "data": {
        "backup_minutes": ("int", 10, 1, 240),
        "backup_keep": ("int", 40, 3, 500),
    },
}

COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
MEDIA_RE = re.compile(r"^[a-f0-9]{24}\.(png|jpg|gif|webp)$")
QID_RE = re.compile(r"^[a-z0-9]{4,24}$")
TOKEN_RE = re.compile(r"^[a-f0-9]{16,64}$")
HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.\-]{1,64}$")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
ASCII_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class ApiError(Exception):
    def __init__(self, code, msg, extra=None):
        Exception.__init__(self, msg)
        self.code, self.msg, self.extra = code, msg, extra or {}


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def new_id(n=5):
    return secrets.token_hex(n)


def clean_text(s, maxlen, multiline=False):
    """Normalise user text: NFC, drop control/format/private-use characters, collapse spaces."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFC", str(s))
    out = []
    for ch in s:
        if ch == "\n" and multiline:
            out.append(ch)
        elif ch in "\t\r\n":
            out.append(" ")
        elif unicodedata.category(ch)[0] != "C":
            out.append(ch)
    s = "".join(out)
    if multiline:
        s = "\n".join(" ".join(line.split()) for line in s.split("\n")).strip()
        s = re.sub(r"\n{3,}", "\n\n", s)
    else:
        s = " ".join(s.split())
    return s[:maxlen]


def defaults(spec=SPEC):
    out = {}
    for k, v in spec.items():
        out[k] = defaults(v) if isinstance(v, dict) else (list(v[1]) if isinstance(v[1], list) else v[1])
    return out


def media_exists(mid):
    return bool(mid) and bool(MEDIA_RE.match(mid)) and os.path.isfile(os.path.join(UPLOADS, mid))


def coerce(spec, val):
    t = spec[0]
    if t in ("str", "text"):
        if not isinstance(val, (str, int, float)) or isinstance(val, bool):
            raise ValueError("must be text")
        return clean_text(val, spec[2], multiline=(t == "text"))
    if t == "bool":
        if isinstance(val, bool):
            return val
        if val in ("true", "1", 1):
            return True
        if val in ("false", "0", 0):
            return False
        raise ValueError("must be on or off")
    if t == "int":
        if isinstance(val, bool):
            raise ValueError("must be a number")
        try:
            n = int(float(val))
        except (TypeError, ValueError):
            raise ValueError("must be a number")
        if n < spec[2] or n > spec[3]:
            raise ValueError("must be between %d and %d" % (spec[2], spec[3]))
        return n
    if t == "enum":
        if val not in spec[2]:
            raise ValueError("must be one of: " + ", ".join(spec[2]))
        return val
    if t == "color":
        if not isinstance(val, str) or not COLOR_RE.match(val.strip()):
            raise ValueError("must be a colour like #0B3D91")
        return val.strip().upper()
    if t == "media":
        if val in ("", None):
            return ""
        if not isinstance(val, str) or not media_exists(val):
            raise ValueError("image not found - upload it again")
        return val
    if t == "list":
        if isinstance(val, str):
            val = re.split(r"[,\n]", val)
        if not isinstance(val, list):
            raise ValueError("must be a list")
        items = []
        for x in val:
            x = clean_text(x, spec[3])
            if x and x.lower() not in [i.lower() for i in items]:
                items.append(x)
        if len(items) > spec[2]:
            raise ValueError("too many entries (max %d)" % spec[2])
        return items
    raise ValueError("unknown setting type")


def mask_ok(mask):
    if not mask or any(c not in "#A* -./_" for c in mask):
        return False
    return 1 <= sum(1 for c in mask if c in "#A*") <= 24


def mask_example(mask):
    digits, letters, out, i = "242156111", "ABCDEFGH", [], 0
    for c in mask:
        if c == "#":
            out.append(digits[i % len(digits)]); i += 1
        elif c == "A":
            out.append(letters[i % len(letters)]); i += 1
        elif c == "*":
            out.append("X"); i += 1
        else:
            out.append(c)
    return "".join(out)


def clean_settings(src, base, strict=True):
    """Merge `src` into a copy of `base`, validating every field. Returns (settings, errors)."""
    errors = {}
    out = json.loads(json.dumps(base))
    if not isinstance(src, dict):
        return out, {"": "settings must be an object"}
    for group, fields in SPEC.items():
        g = src.get(group)
        if not isinstance(g, dict):
            continue
        for key, spec in fields.items():
            if key not in g:
                continue
            try:
                out[group][key] = coerce(spec, g[key])
            except ValueError as e:
                errors[group + "." + key] = str(e)
    if not mask_ok(out["join"]["id_mask"]):
        errors["join.id_mask"] = "use # for a digit, A for a letter, * for either, plus - . / or space"
        out["join"]["id_mask"] = base["join"]["id_mask"] if mask_ok(base["join"]["id_mask"]) else "##-####-###"
    hip = out["network"]["host_ip"]
    if hip and not HOSTNAME_RE.match(hip):
        errors["network.host_ip"] = "use an address like 192.168.137.1, or leave it empty"
        out["network"]["host_ip"] = ""
    if not out["event"]["title"]:
        out["event"]["title"] = "University Week Quiz"
    if not strict:
        errors = {}
    return out, errors


# --------------------------------------------------------------------------------------------
# Quizzes
# --------------------------------------------------------------------------------------------
def clean_question(q, default_time, used_ids):
    if not isinstance(q, dict):
        q = {}
    text = clean_text(q.get("text", q.get("Question", q.get("question", ""))), 300)
    src_opts = q.get("options") if isinstance(q.get("options"), dict) else q
    opts = {}
    for c in LETTERS:
        v = src_opts.get(c, src_opts.get(c.upper(), "")) if isinstance(src_opts, dict) else ""
        opts[c] = clean_text(v, 120)
    ans = str(q.get("answer", q.get("correct", "")) or "").strip().lower()[:1]
    try:
        t = int(float(q.get("time", default_time)))
    except (TypeError, ValueError):
        t = default_time
    t = max(5, min(300, t))
    pts = q.get("points", 1)
    pts = pts if pts in (0, 1, 2) else 1
    img = q.get("image", "")
    img = img if isinstance(img, str) and media_exists(img) else ""
    qid = q.get("id")
    if not (isinstance(qid, str) and QID_RE.match(qid)) or qid in used_ids:
        qid = new_id(4)
        while qid in used_ids:
            qid = new_id(4)
    used_ids.add(qid)
    return {"id": qid, "text": text, "options": opts, "answer": ans, "time": t, "points": pts, "image": img}


def question_issues(q):
    issues = []
    if not q["text"]:
        issues.append("question text is empty")
    filled = [c for c in LETTERS if q["options"][c]]
    if len(filled) < 2:
        issues.append("needs at least two answers")
    if q["answer"] not in filled:
        issues.append("pick the correct answer")
    return issues


def clean_quiz(raw, default_time, keep_id=None):
    if not isinstance(raw, dict):
        raise ApiError(400, "Quiz data must be an object")
    qs = raw.get("questions")
    if not isinstance(qs, list):
        qs = []
    if len(qs) > MAX_QUESTIONS:
        raise ApiError(400, "A quiz can have at most %d questions" % MAX_QUESTIONS)
    used = set()
    questions = [clean_question(q, default_time, used) for q in qs]
    qz = {
        "id": keep_id or (raw.get("id") if isinstance(raw.get("id"), str) and QID_RE.match(raw.get("id")) else new_id()),
        "title": clean_text(raw.get("title"), 80) or "Untitled quiz",
        "description": clean_text(raw.get("description"), 240),
        "questions": questions,
        "created": raw.get("created") if isinstance(raw.get("created"), str) else now_iso(),
        "updated": now_iso(),
    }
    return qz


def quiz_issues(qz):
    out = {}
    for i, q in enumerate(qz["questions"]):
        iss = question_issues(q)
        if iss:
            out[str(i)] = iss
    if not qz["questions"]:
        out["quiz"] = ["add at least one question"]
    return out


def parse_quiz_file(text, filename=""):
    """Accept our JSON format, the old questions.json format, a JSON list, or CSV."""
    text = text.lstrip("\ufeff")
    data = None
    try:
        data = json.loads(text)
    except ValueError:
        pass
    title = os.path.splitext(os.path.basename(filename or "Imported quiz"))[0][:60] or "Imported quiz"
    if isinstance(data, dict) and data.get("format") == EXPORT_FORMAT:
        raise ApiError(400, "That's a full event file. Import it from the Data page instead.")
    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        return data
    if isinstance(data, dict):
        def order(kv):
            n = re.sub(r"\D", "", kv[0])
            return int(n) if n else 0
        items = [v for k, v in sorted(data.items(), key=order) if isinstance(v, dict)]
        return {"title": title, "questions": items}
    if isinstance(data, list):
        return {"title": title, "questions": [x for x in data if isinstance(x, dict)]}
    # CSV
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        raise ApiError(400, "Couldn't read the file. Use JSON or CSV with a header row.")
    if len(rows) < 2:
        raise ApiError(400, "The CSV needs a header row and at least one question")
    head = [h.strip().lower() for h in rows[0]]

    def col(*names):
        for n in names:
            if n in head:
                return head.index(n)
        return -1
    ci = {"text": col("question", "text"), "a": col("a", "option a", "answer a"), "b": col("b", "option b", "answer b"),
          "c": col("c", "option c", "answer c"), "d": col("d", "option d", "answer d"),
          "answer": col("answer", "correct", "correct answer"), "time": col("time", "seconds"), "points": col("points")}
    if ci["text"] < 0 or ci["a"] < 0 or ci["answer"] < 0:
        raise ApiError(400, "CSV header must include: question, a, b, c, d, answer (time is optional)")
    qs = []
    for r in rows[1:]:
        if not any(x.strip() for x in r):
            continue
        g = lambda k: (r[ci[k]] if 0 <= ci[k] < len(r) else "")
        q = {"text": g("text"), "options": {c: g(c) for c in LETTERS}, "answer": g("answer")}
        if g("time").strip():
            q["time"] = g("time")
        p = g("points").strip()
        if p in ("0", "1", "2"):
            q["points"] = int(p)
        qs.append(q)
    return {"title": title, "questions": qs}


# --------------------------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------------------------
lock = threading.RLock()
DB = {}
TOK = {}            # player token -> player id
SEEN = {}           # player id -> monotonic time of last poll (not persisted)
HOSTS = {}          # host session token -> monotonic time of last use
ATTEMPTS = {}       # rate-limit buckets
PUBKEYS = {}
CACHE = {}
SREV = {}           # per-round revision for score caches
REV = 0             # bumps on every visible change
SCORE_REV = 0       # bumps when any score or ranking could change
NAME_REV = 0
DIRTY = False
RUN_START = 0.0     # monotonic time the current question (re)started
PORT = 80
BOOT_CODE = secrets.token_urlsafe(18)
BACKUP_REV = -1


def bump(save=True):
    global REV, DIRTY
    REV += 1
    if save:
        DIRTY = True


def touch(sid=None):
    """Something that affects scores changed."""
    global SCORE_REV
    SCORE_REV += 1
    if sid:
        SREV[sid] = SREV.get(sid, 0) + 1
    bump()


def S():
    return DB["settings"]


def idle_live():
    return {"sid": None, "phase": "idle", "q": -1, "offset": 0.0, "dur": 0.0}


def new_db(settings=None):
    return {"schema": SCHEMA, "event_id": new_id(8), "created": now_iso(), "settings": settings or defaults(),
            "admin": None, "secret": secrets.token_hex(16), "quizzes": {}, "players": {}, "sessions": {},
            "live": idle_live()}


def cur_session():
    sid = DB["live"].get("sid")
    return DB["sessions"].get(sid) if sid else None


def pub(pid):
    k = PUBKEYS.get(pid)
    if not k:
        k = hmac.new(DB["secret"].encode(), pid.encode(), hashlib.sha256).hexdigest()[:12]
        PUBKEYS[pid] = k
    return k


def rebuild_indexes():
    TOK.clear(); PUBKEYS.clear(); CACHE.clear(); SREV.clear()
    for pid, p in DB["players"].items():
        if p.get("tok"):
            TOK[p["tok"]] = pid


def elapsed():
    L = DB["live"]
    if L["phase"] == "question":
        return L["offset"] + (time.monotonic() - RUN_START)
    return L["offset"]


# ------------------------------- sanitising whole databases -------------------------------
def _hexstr(v, lo, hi):
    return isinstance(v, str) and lo <= len(v) <= hi and all(c in "0123456789abcdef" for c in v)


def sanitize_db(d, base_settings=None):
    """Validate a database coming from disk, a backup, or an import. Never trust its shape."""
    if not isinstance(d, dict):
        raise ApiError(400, "The file doesn't contain event data")
    out = new_db()
    out["event_id"] = d["event_id"] if _hexstr(d.get("event_id"), 8, 32) else out["event_id"]
    out["created"] = d.get("created") if isinstance(d.get("created"), str) else now_iso()
    if _hexstr(d.get("secret"), 16, 64):
        out["secret"] = d["secret"]
    s, _ = clean_settings(d.get("settings") or {}, base_settings or defaults(), strict=False)
    out["settings"] = s
    adm = d.get("admin")
    if isinstance(adm, dict) and _hexstr(adm.get("salt"), 16, 64) and _hexstr(adm.get("hash"), 64, 64):
        out["admin"] = {"salt": adm["salt"], "hash": adm["hash"], "iter": int(adm.get("iter", 200000))}
    dt = s["game"]["default_time"]
    for qid, qz in (d.get("quizzes") or {}).items() if isinstance(d.get("quizzes"), dict) else []:
        try:
            c = clean_quiz(qz, dt, keep_id=qid if isinstance(qid, str) and QID_RE.match(qid) else None)
            c["updated"] = qz.get("updated") if isinstance(qz.get("updated"), str) else c["updated"]
            out["quizzes"][c["id"]] = c
        except ApiError:
            pass
    for pid, p in (d.get("players") or {}).items() if isinstance(d.get("players"), dict) else []:
        if not isinstance(pid, str) or not (1 <= len(pid) <= 48) or not isinstance(p, dict):
            continue
        rec = {"name": clean_text(p.get("name"), 40) or "Player", "pin": None, "tok": None,
               "banned": bool(p.get("banned")), "guest": bool(p.get("guest")),
               "created": p.get("created") if isinstance(p.get("created"), str) else now_iso()}
        pin = p.get("pin")
        if isinstance(pin, dict) and _hexstr(pin.get("salt"), 16, 64) and _hexstr(pin.get("hash"), 64, 64):
            rec["pin"] = {"salt": pin["salt"], "hash": pin["hash"]}
        if isinstance(p.get("tok"), str) and TOKEN_RE.match(p["tok"]):
            rec["tok"] = p["tok"]
        out["players"][pid] = rec
    seen_tok = set()
    for pid, p in out["players"].items():          # a token may belong to only one player
        if p["tok"] in seen_tok:
            p["tok"] = None
        elif p["tok"]:
            seen_tok.add(p["tok"])
    for sid, ss in (d.get("sessions") or {}).items() if isinstance(d.get("sessions"), dict) else []:
        if not (isinstance(sid, str) and QID_RE.match(sid) and isinstance(ss, dict)):
            continue
        used = set()
        qs = [clean_question(q, dt, used) for q in (ss.get("questions") or [])[:MAX_QUESTIONS]] \
            if isinstance(ss.get("questions"), list) else []
        qids = {q["id"] for q in qs}
        answers = {}
        for qid, qa in (ss.get("answers") or {}).items() if isinstance(ss.get("answers"), dict) else []:
            if qid not in qids or not isinstance(qa, dict):
                continue
            rows = {}
            for pid, a in qa.items():
                if pid in out["players"] and isinstance(a, list) and len(a) >= 3 and a[0] in LETTERS:
                    try:
                        rows[pid] = [a[0], max(0, int(a[1])), max(0, min(100000, int(a[2])))]
                    except (TypeError, ValueError):
                        pass
            if rows:
                answers[qid] = rows
        qdur = {}
        for qid, v in (ss.get("qdur") or {}).items() if isinstance(ss.get("qdur"), dict) else []:
            if qid in qids and isinstance(v, (int, float)) and not isinstance(v, bool):
                qdur[qid] = max(1000, min(3600000, int(v)))

        def pidmap(m):
            if isinstance(m, list):
                m = {x: now_iso() for x in m if isinstance(x, str)}
            if not isinstance(m, dict):
                return {}
            return {k: (v if isinstance(v, str) else now_iso()) for k, v in m.items() if k in out["players"]}
        out["sessions"][sid] = {
            "id": sid, "title": clean_text(ss.get("title"), 100) or "Round",
            "quiz_id": ss.get("quiz_id") if isinstance(ss.get("quiz_id"), str) else "",
            "quiz_title": clean_text(ss.get("quiz_title"), 80),
            "questions": qs, "answers": answers, "qdur": qdur,
            "joined": pidmap(ss.get("joined")), "kicked": pidmap(ss.get("kicked")),
            "created": ss.get("created") if isinstance(ss.get("created"), str) else now_iso(),
            "ended": ss.get("ended") if isinstance(ss.get("ended"), str) else None,
            "status": ss.get("status") if ss.get("status") in ("live", "done") else "done",
        }
    L = d.get("live") if isinstance(d.get("live"), dict) else {}
    live = idle_live()
    if L.get("sid") in out["sessions"]:
        s = out["sessions"][L["sid"]]
        ph = L.get("phase")
        live["sid"] = L["sid"]
        live["phase"] = ph if ph in ("lobby", "question", "paused", "reveal", "leaderboard", "ended", "overall") else "lobby"
        try:
            live["q"] = max(-1, min(len(s["questions"]) - 1, int(L.get("q", -1))))
            live["offset"] = max(0.0, float(L.get("offset", 0)))
            live["dur"] = max(1.0, min(3600.0, float(L.get("dur", 20))))
        except (TypeError, ValueError):
            live["q"] = -1
        if live["q"] < 0 and live["phase"] not in ("lobby", "ended", "overall"):
            live["phase"] = "lobby"
        if live["phase"] == "question":   # a timer can't survive a restart or a move to another laptop
            live["phase"] = "paused"
        s["status"] = "live" if live["phase"] not in ("ended", "overall") else s["status"]
    elif L.get("phase") == "overall":
        live["phase"] = "overall"
    out["live"] = live
    return out


# ------------------------------- persistence -------------------------------
def write_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    for i in range(20):                  # Windows: antivirus/indexer can briefly lock the target
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.15)
    os.replace(tmp, path)


def dump_db():
    d = DB
    if DB["live"]["phase"] == "question":     # persist how much of the timer has run
        d = dict(DB)
        d["live"] = dict(DB["live"], offset=round(elapsed(), 3))
    return json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def save_now():
    global DIRTY
    with lock:
        data = dump_db()
        DIRTY = False
    write_atomic(DBFILE, data)


def make_backup(reason):
    global BACKUP_REV
    with lock:
        data = dump_db()
        keep = S()["data"]["backup_keep"]
        BACKUP_REV = REV
    reason = re.sub(r"[^a-z0-9-]", "", reason.lower())[:24] or "manual"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = "event-%s-%s.json.gz" % (stamp, reason)
    n = 1
    while os.path.exists(os.path.join(BACKUPS, name)):
        n += 1
        name = "event-%s-%s-%d.json.gz" % (stamp, reason, n)
    write_atomic(os.path.join(BACKUPS, name), gzip.compress(data, 6))
    files = backup_files()
    for f in files[:-keep] if len(files) > keep else []:
        try:
            os.remove(os.path.join(BACKUPS, f))
        except OSError:
            pass
    return name


def backup_files():
    """Backup file names, oldest first (by file time, then name)."""
    fs = [f for f in os.listdir(BACKUPS) if f.startswith("event-") and f.endswith(".json.gz")]
    return sorted(fs, key=lambda f: (os.path.getmtime(os.path.join(BACKUPS, f)), f))


def backup_async(reason):
    threading.Thread(target=lambda: _safe(make_backup, reason), daemon=True).start()


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        traceback.print_exc()


def saver():
    global DIRTY
    last_backup = time.monotonic()
    while True:
        time.sleep(1.0)
        data = None
        with lock:
            if DIRTY:
                data, DIRTY = dump_db(), False
            mins = S()["data"]["backup_minutes"]
            want_backup = REV != BACKUP_REV and time.monotonic() - last_backup >= mins * 60
        if data is not None:
            try:
                write_atomic(DBFILE, data)
            except Exception as e:
                print("  !! Couldn't save event data (%s). Will retry." % e)
                with lock:
                    DIRTY = True
        if want_backup:
            last_backup = time.monotonic()
            _safe(make_backup, "auto")


def load_db():
    global DB
    if os.path.exists(DBFILE):
        try:
            with open(DBFILE, encoding="utf-8") as f:
                DB = sanitize_db(json.load(f))
        except Exception as e:
            bad = os.path.join(DATA, "event.damaged-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
            os.replace(DBFILE, bad)
            print("  !! event.json couldn't be read (%s). Moved it to %s" % (e, os.path.basename(bad)))
            restored = restore_latest_backup()
            if not restored:
                DB = new_db()
    else:
        DB = new_db()
        migrate_legacy()
    rebuild_indexes()
    save_now()


def restore_latest_backup():
    global DB
    files = backup_files() if os.path.isdir(BACKUPS) else []
    for f in reversed(files):
        try:
            with open(os.path.join(BACKUPS, f), "rb") as fh:
                DB = sanitize_db(json.loads(gzip.decompress(fh.read()).decode("utf-8")))
            print("  Restored the most recent backup: " + f)
            return True
        except Exception:
            continue
    return False


def migrate_legacy():
    """First run next to the old version: bring over config.json, questions.json and players."""
    notes = []
    cfgp, qp, dp = (os.path.join(BASE, n) for n in ("config.json", "questions.json", "data.json"))
    if os.path.exists(cfgp):
        try:
            c = json.load(open(cfgp, encoding="utf-8"))
            src = {"event": {"title": c.get("title", "")},
                   "network": {k: c[k] for k in ("ssid", "password", "security", "host_ip", "port") if k in c}}
            DB["settings"], _ = clean_settings(src, DB["settings"], strict=False)
            notes.append("settings from config.json")
        except Exception:
            pass
    if os.path.exists(qp):
        try:
            raw = parse_quiz_file(open(qp, encoding="utf-8").read(), "questions.json")
            raw["title"] = "Imported questions"
            qz = clean_quiz(raw, DB["settings"]["game"]["default_time"])
            DB["quizzes"][qz["id"]] = qz
            notes.append("%d questions from questions.json" % len(qz["questions"]))
        except Exception:
            pass
    if os.path.exists(dp):
        try:
            d = json.load(open(dp, encoding="utf-8"))
            for pid, p in (d.get("players") or {}).items():
                if isinstance(pid, str) and isinstance(p, dict):
                    tok = p.get("token") if isinstance(p.get("token"), str) and TOKEN_RE.match(p.get("token", "")) else None
                    DB["players"][pid[:48]] = {"name": clean_text(p.get("name"), 40) or "Player", "pin": None,
                                               "tok": tok, "banned": False, "guest": False, "created": now_iso()}
            notes.append("%d players from data.json (old scores were not imported: they were stored by "
                         "question position and no longer match questions.json)" % len(DB["players"]))
        except Exception:
            pass
    if notes:
        print("  Migrated from the previous version: " + "; ".join(notes))


# ------------------------------- passwords and pins -------------------------------
def hash_secret(secret, salt=None, iters=200000):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), bytes.fromhex(salt), iters).hex()
    return {"salt": salt, "hash": h, "iter": iters}


def check_secret(secret, rec, iters=None):
    if not rec:
        return False
    h = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), bytes.fromhex(rec["salt"]),
                            iters or rec.get("iter", 200000)).hex()
    return hmac.compare_digest(h, rec["hash"])


PIN_ITERS = 20000


def pin_rec(pin):
    h = hash_secret(pin, iters=PIN_ITERS)
    return {"salt": h["salt"], "hash": h["hash"]}


def gen_password():
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def rate_ok(key, limit, window):
    now = time.monotonic()
    lst = [t for t in ATTEMPTS.get(key, []) if now - t < window]
    ATTEMPTS[key] = lst
    return len(lst) < limit


def rate_hit(key):
    ATTEMPTS.setdefault(key, []).append(time.monotonic())


# --------------------------------------------------------------------------------------------
# Scoring and views
# --------------------------------------------------------------------------------------------
def points_for(Q, choice, el, dur):
    if choice != Q["answer"] or Q.get("points", 1) == 0:
        return 0
    G = S()["game"]
    base = G["points"] * Q.get("points", 1)
    if not G["speed_bonus"]:
        return base
    frac = min(1.0, max(0.0, el / dur)) if dur > 0 else 1.0
    return int(round(base * (1 - (1 - G["min_pct"] / 100.0) * frac)))


def open_qid(s):
    """The question whose points stay hidden (it hasn't been revealed yet)."""
    L = DB["live"]
    if L["sid"] == s["id"] and L["phase"] in ("question", "paused") and 0 <= L["q"] < len(s["questions"]):
        return s["questions"][L["q"]]["id"]
    return None


def round_scores(s):
    hide = open_qid(s)
    key = (SREV.get(s["id"], 0), NAME_REV, hide)
    c = CACHE.get(("r", s["id"]))
    if c and c[0] == key:
        return c[1]
    P = DB["players"]
    tot, cor, ans = {}, {}, {}
    key_of = {q["id"]: q["answer"] for q in s["questions"]}
    for pid in s["joined"]:
        if pid in P:
            tot[pid], cor[pid], ans[pid] = 0, 0, 0
    for qid, qa in s["answers"].items():
        if qid == hide:
            continue
        for pid, a in qa.items():
            if pid in P:
                tot[pid] = tot.get(pid, 0) + a[2]
                cor[pid] = cor.get(pid, 0) + (1 if a[0] == key_of.get(qid) else 0)
                ans[pid] = ans.get(pid, 0) + 1
    rows = [{"pid": pid, "score": sc, "correct": cor.get(pid, 0), "answered": ans.get(pid, 0)} for pid, sc in tot.items()]
    rows.sort(key=lambda r: (-r["score"], P[r["pid"]]["name"].lower(), r["pid"]))
    rank, prev = 0, None
    for i, r in enumerate(rows):          # standard competition ranking: ties share a rank
        if r["score"] != prev:
            rank, prev = i + 1, r["score"]
        r["rank"] = rank
    res = {"rows": rows, "by": {r["pid"]: r for r in rows}}
    CACHE[("r", s["id"])] = (key, res)
    return res


def overall_scores():
    mode = S()["game"]["overall_mode"]
    key = (SCORE_REV, NAME_REV, mode, len(DB["sessions"]))
    c = CACHE.get("overall")
    if c and c[0] == key:
        return c[1]
    agg = {}
    for s in DB["sessions"].values():
        for r in round_scores(s)["rows"]:
            a = agg.setdefault(r["pid"], {"pid": r["pid"], "best": 0, "sum": 0, "rounds": 0})
            a["best"] = max(a["best"], r["score"])
            a["sum"] += r["score"]
            a["rounds"] += 1
    P = DB["players"]
    rows = [dict(a, score=a[mode]) for a in agg.values() if a["pid"] in P]
    rows.sort(key=lambda r: (-r["score"], P[r["pid"]]["name"].lower(), r["pid"]))
    rank, prev = 0, None
    for i, r in enumerate(rows):
        if r["score"] != prev:
            rank, prev = i + 1, r["score"]
        r["rank"] = rank
    res = {"rows": rows, "by": {r["pid"]: r for r in rows}}
    CACHE["overall"] = (key, res)
    return res


def played_elsewhere(s):
    """Players who already answered this quiz in another round (for 'one attempt per quiz')."""
    key = (SCORE_REV,)
    c = CACHE.get(("played", s["id"]))
    if c and c[0] == key:
        return c[1]
    out = set()
    for o in DB["sessions"].values():
        if o["id"] != s["id"] and o["quiz_id"] and o["quiz_id"] == s["quiz_id"]:
            for qa in o["answers"].values():
                out.update(qa.keys())
    CACHE[("played", s["id"])] = (key, out)
    return out


def is_spectator(pid, s):
    return bool(S()["game"]["one_attempt"]) and pid in played_elsewhere(s)


def online_pids():
    now = time.monotonic()
    return [pid for pid, t in SEEN.items() if now - t < ONLINE_SECONDS and pid in DB["players"]]


def eligible_online(s):
    P = DB["players"]
    return [pid for pid in online_pids() if not P[pid]["banned"] and pid not in s["kicked"] and not is_spectator(pid, s)]


def media_url(mid):
    return "/media/" + mid if mid else ""


def event_public():
    e, b = S()["event"], S()["brand"]
    return {"title": e["title"], "subtitle": e["subtitle"], "organizer": e["organizer"], "welcome": e["welcome"],
            "logo": media_url(b["logo"])}


def question_public(Q, n, with_answer, counts=None):
    d = {"n": n, "id": Q["id"], "text": Q["text"], "image": media_url(Q["image"]), "time": Q["time"],
         "points": Q.get("points", 1), "options": {c: Q["options"][c] for c in LETTERS if Q["options"][c]}}
    if with_answer:
        d["correct"] = Q["answer"]
        if counts is not None:
            d["counts"] = counts
    return d


def counts_for(qa):
    return {c: sum(1 for a in qa.values() if a[0] == c) for c in LETTERS}


def board_rows(rows, n):
    P = DB["players"]
    return [{"k": pub(r["pid"]), "name": P[r["pid"]]["name"], "score": r["score"], "rank": r["rank"]} for r in rows[:n]]


def maybe_join(pid, s):
    if pid in s["joined"] or pid in s["kicked"] or DB["players"][pid]["banned"] or is_spectator(pid, s):
        return
    if DB["live"]["phase"] in ("lobby", "question", "paused", "reveal", "leaderboard"):
        s["joined"][pid] = now_iso()
        touch(s["id"])


def public_view(tok=None, v=None):
    pid = TOK.get(tok) if tok else None
    s = cur_session()
    if pid:
        SEEN[pid] = time.monotonic()
        if s:
            maybe_join(pid, s)
    if v is not None and str(v) == str(REV):
        return {"v": REV, "same": 1}
    L, G = DB["live"], S()["game"]
    ph = L["phase"]
    d = {"v": REV, "phase": ph, "event": event_public()}
    if s:
        elig = eligible_online(s)
        d["online"] = len(elig)
        d["round"] = {"title": s["title"], "total": len(s["questions"])}
    else:
        elig = []
        d["online"] = len(online_pids())
    if ph in ("idle", "lobby"):
        P = DB["players"]
        names = [P[x]["name"] for x in (elig if s else online_pids())]
        d["names"] = names[-80:]
    q = L["q"]
    if s and 0 <= q < len(s["questions"]) and ph in ("question", "paused", "reveal", "leaderboard"):
        Q = s["questions"][q]
        qa = s["answers"].get(Q["id"], {})
        revealed = ph in ("reveal", "leaderboard")
        qd = question_public(Q, q + 1, revealed, counts_for(qa) if (revealed and G["show_counts"]) else None)
        if ph in ("question", "paused"):
            qd["left"] = round(max(0.0, L["dur"] - elapsed()), 3)
            qd["dur"] = L["dur"]
        d["question"] = qd
        d["answered"] = len(qa)
    rs = round_scores(s) if s else None
    top = max(G["board_top"], G["phone_top"])
    if s and ph in ("reveal", "leaderboard", "ended"):
        d["board"] = board_rows(rs["rows"], top)
        d["count"] = len(rs["rows"])
    if ph == "overall":
        ov = overall_scores()
        d["board"] = board_rows(ov["rows"], top)
        d["count"] = len(ov["rows"])
        d["mode"] = G["overall_mode"]
    d["top"] = {"board": G["board_top"], "phone": G["phone_top"]}
    if pid:
        P = DB["players"][pid]
        me = {"k": pub(pid), "name": P["name"], "id": pid, "guest": P["guest"]}
        if s:
            r = rs["by"].get(pid)
            me.update(score=r["score"] if r else 0, rank=r["rank"] if r else None, of=len(rs["rows"]),
                      kicked=pid in s["kicked"], spectator=is_spectator(pid, s))
            if 0 <= q < len(s["questions"]) and ph in ("question", "paused", "reveal", "leaderboard"):
                a = s["answers"].get(s["questions"][q]["id"], {}).get(pid)
                me["choice"] = a[0] if a else None
                if ph in ("reveal", "leaderboard"):
                    me["pts"] = a[2] if a else 0
                    me["correct"] = bool(a and a[0] == s["questions"][q]["answer"])
        if ph == "overall":
            o = overall_scores()["by"].get(pid)
            me.update(score=o["score"] if o else 0, rank=o["rank"] if o else None)
        d["me"] = me
    return d


def host_view(v=None):
    if v is not None and str(v) == str(REV):
        return {"v": REV, "same": 1}
    L = DB["live"]
    s = cur_session()
    P = DB["players"]
    d = {"v": REV, "phase": L["phase"], "q": L["q"], "event": event_public(),
         "online_total": len(online_pids()), "players_total": len(P), "round": None}
    if s:
        rs = round_scores(s)
        qs = s["questions"]
        d["round"] = {"id": s["id"], "title": s["title"], "quiz_title": s["quiz_title"], "total": len(qs),
                      "status": s["status"], "titles": [Q["text"][:90] for Q in qs],
                      "played": [bool(s["answers"].get(Q["id"])) for Q in qs]}
        q = L["q"]
        cur = None
        if 0 <= q < len(qs) and L["phase"] in ("question", "paused", "reveal", "leaderboard"):
            Q = qs[q]
            qa = s["answers"].get(Q["id"], {})
            cur = question_public(Q, q + 1, True, counts_for(qa))
            if L["phase"] in ("question", "paused"):
                cur["left"] = round(max(0.0, L["dur"] - elapsed()), 3)
                cur["dur"] = L["dur"]
            d["answered"] = len(qa)
            d["question"] = cur
        elig = set(eligible_online(s))
        d["online"] = len(elig)
        curq = qs[q]["id"] if 0 <= q < len(qs) else None
        qa = s["answers"].get(curq, {}) if curq else {}
        d["list"] = [{"id": r["pid"], "name": P[r["pid"]]["name"], "score": r["score"], "rank": r["rank"],
                      "online": r["pid"] in elig, "ans": (qa.get(r["pid"]) or [None])[0]} for r in rs["rows"][:1500]]
    return d


# --------------------------------------------------------------------------------------------
# Game flow (the same phases and scoring as the original booth game)
# --------------------------------------------------------------------------------------------
def require_round():
    s = cur_session()
    if not s:
        raise ApiError(400, "Start a round first (Rounds page)")
    return s


def open_question(s, i):
    global RUN_START
    Q = s["questions"][i]
    L = DB["live"]
    L.update(phase="question", q=i, offset=0.0, dur=float(Q["time"]))
    RUN_START = time.monotonic()
    s["qdur"][Q["id"]] = int(L["dur"] * 1000)
    touch(s["id"])


def go(s, i):
    qs = s["questions"]
    if not qs:
        raise ApiError(400, "This round has no questions")
    i = max(0, min(len(qs) - 1, int(i)))
    if s["answers"].get(qs[i]["id"]):
        DB["live"].update(phase="reveal", q=i, offset=0.0)     # already played: just show results
        touch(s["id"])
    else:
        open_question(s, i)


def to_reveal(s):
    L = DB["live"]
    L["offset"] = elapsed()
    L["phase"] = "reveal"
    touch(s["id"])


def finish_round(s):
    DB["live"]["phase"] = "ended"
    s["status"] = "done"
    s["ended"] = now_iso()
    touch(s["id"])
    backup_async("round-end")


def host_action(a, v):
    global RUN_START
    L = DB["live"]
    ph, q = L["phase"], L["q"]
    if a == "overall":
        L["phase"] = "overall"
        touch()
        return
    if ph == "overall" and a in ("advance", "back"):   # leave the event standings
        s = cur_session()
        if not s:
            L.update(phase="idle", q=-1)
        elif s["status"] == "done":
            L["phase"] = "ended"
        else:
            L["phase"] = "lobby" if q < 0 else "leaderboard"
        touch()
        return
    if a == "close":
        s = cur_session()
        if s and s["status"] == "live":
            s["status"], s["ended"] = "done", now_iso()
        DB["live"] = idle_live()
        touch()
        return
    s = require_round()
    n = len(s["questions"])
    if a == "advance":                     # the single "do the next obvious thing" button
        if ph == "lobby":
            go(s, 0)
        elif ph == "question":
            to_reveal(s)
        elif ph == "paused":
            host_action("resume", None)
        elif ph == "reveal":
            L["phase"] = "leaderboard"; touch(s["id"])
        elif ph == "leaderboard":
            if q < n - 1:
                go(s, q + 1)
            else:
                finish_round(s)
        elif ph == "ended":
            L["phase"] = "overall"; touch()
    elif a == "next":                      # original behaviour
        if ph == "lobby":
            go(s, 0)
        elif ph not in ("ended", "overall"):
            if q < n - 1:
                go(s, q + 1)
            else:
                finish_round(s)
    elif a == "prev":
        if ph in ("ended", "overall"):
            go(s, n - 1)
        elif q <= 0:
            L.update(phase="lobby", q=-1); touch(s["id"])
        else:
            go(s, q - 1)
    elif a == "reveal" and ph in ("question", "paused"):
        to_reveal(s)
    elif a == "board" and q >= 0:
        L["phase"] = "leaderboard"; touch(s["id"])
    elif a == "replay" and q >= 0:
        s["answers"].pop(s["questions"][q]["id"], None)
        open_question(s, q)
    elif a == "extend" and ph in ("question", "paused"):
        L["dur"] += S()["game"]["extend_s"]
        s["qdur"][s["questions"][q]["id"]] = int(L["dur"] * 1000)
        bump()
    elif a == "pause" and ph == "question":
        L["offset"] = elapsed()
        L["phase"] = "paused"
        bump()
    elif a == "resume" and ph == "paused":
        L["phase"] = "question"
        RUN_START = time.monotonic()
        bump()
    elif a == "goto":
        try:
            go(s, int(v))
        except (TypeError, ValueError):
            raise ApiError(400, "Pick a question")
    elif a == "lobby":
        L.update(phase="lobby", q=-1, offset=0.0); touch(s["id"])
    elif a == "end":
        finish_round(s)
    elif a == "reset":
        make_backup("before-reset")
        s["answers"].clear(); s["qdur"].clear()
        s["status"], s["ended"] = "live", None
        L.update(phase="lobby", q=-1, offset=0.0); touch(s["id"])
    elif a == "kick":
        pid = str(v or "")
        if pid not in DB["players"]:
            raise ApiError(404, "Player not found")
        s["joined"].pop(pid, None)
        s["kicked"][pid] = now_iso()
        for qa in s["answers"].values():
            qa.pop(pid, None)
        revoke(pid)
        touch(s["id"])
    elif a == "unkick":
        s["kicked"].pop(str(v or ""), None); touch(s["id"])
    else:
        raise ApiError(400, "That action isn't available right now")


def revoke(pid):
    p = DB["players"].get(pid)
    if p and p.get("tok"):
        TOK.pop(p["tok"], None)
        p["tok"] = None
    SEEN.pop(pid, None)


def ticker():
    global DIRTY
    tick = 0
    while True:
        time.sleep(0.2)
        tick += 1
        with lock:
            try:
                L = DB["live"]
                if L["phase"] == "question":
                    if tick % 15 == 0:
                        DIRTY = True          # save the running timer every 3 s
                    s = cur_session()
                    if not s:
                        DB["live"] = idle_live(); bump()
                        continue
                    G = S()["game"]
                    if elapsed() >= L["dur"] + G["grace_ms"] / 1000.0:
                        to_reveal(s)
                    elif G["auto_reveal"]:
                        elig = eligible_online(s)
                        qa = s["answers"].get(s["questions"][L["q"]]["id"], {})
                        if elig and all(p in qa for p in elig):
                            to_reveal(s)
                if tick % 150 == 0:          # every 30 s: tidy in-memory tables
                    now = time.monotonic()
                    for k in [k for k, t in HOSTS.items() if now - t > 12 * 3600]:
                        HOSTS.pop(k, None)
                    for k in [k for k, lst in ATTEMPTS.items() if not lst or now - lst[-1] > 900]:
                        ATTEMPTS.pop(k, None)
                    for k in [k for k, t in SEEN.items() if now - t > 3600]:
                        SEEN.pop(k, None)
            except Exception:
                traceback.print_exc()


# --------------------------------------------------------------------------------------------
# Players joining
# --------------------------------------------------------------------------------------------
LEET = str.maketrans("013457@$!", "oieastasi")


def flatten(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().translate(LEET)
    return re.sub(r"[^a-z0-9]", "", s)


def name_blocked(name):
    flat = flatten(name)
    return any(flatten(w) and flatten(w) in flat for w in S()["join"]["blocked_words"])


def normalize_masked(raw, mask):
    chars = [c for c in str(raw or "").upper() if c in ASCII_ALNUM]
    out, i = [], 0
    for m in mask:
        if m in "#A*":
            if i >= len(chars):
                return None
            c = chars[i]; i += 1
            if (m == "#" and c not in "0123456789") or (m == "A" and c not in ASCII_ALNUM[:26]):
                return None
            out.append(c)
        else:
            out.append(m)
    return "".join(out) if i == len(chars) else None


def api_join(b, ip):
    global NAME_REV
    if not rate_ok("join:" + ip, 600, 60):      # generous: a whole hall may share one NAT address
        raise ApiError(429, "Too many tries from this phone. Wait a minute and try again.")
    rate_hit("join:" + ip)
    J = S()["join"]
    name = clean_text(b.get("name"), J["name_max"])
    pin = str(b.get("pin") or "").strip()
    devtok = str(b.get("token") or "")
    guest = bool(b.get("guest")) and J["allow_guests"] and J["id_mode"] != "name"
    raw_id = str(b.get("id") or "").strip()
    new_guest = False
    if J["id_mode"] == "name":
        if not name:
            raise ApiError(400, "Enter your name")
        pid = "N:" + name.casefold()
    elif guest:
        if raw_id:
            g = raw_id.upper().replace(" ", "")
            if not re.match(r"^G-?\d{4,6}$", g):
                raise ApiError(400, "Guest codes look like G-4821. Leave it empty if you're new.")
            pid = "G-" + g.lstrip("G-")
        else:
            new_guest, pid = True, None
    elif J["id_mode"] == "mask":
        pid = normalize_masked(raw_id, J["id_mask"])
        if not pid:
            raise ApiError(400, "Enter your %s like %s" % (J["id_label"].lower(), mask_example(J["id_mask"])))
    else:
        pid = raw_id.upper()
        if not re.match(r"^[A-Z0-9][A-Z0-9._\-]{1,31}$", pid):
            raise ApiError(400, "Enter your %s (letters, numbers and dashes)" % J["id_label"].lower())
    if name and name_blocked(name):
        raise ApiError(400, "Please choose a different name")
    if pin and not re.match(r"^\d{4}$", pin):
        raise ApiError(400, "Your PIN is 4 digits")
    P = DB["players"]
    p = P.get(pid) if pid else None
    if p is None:
        if len(P) >= J["max_players"]:
            raise ApiError(403, "This game is full. Please see the host.")
        if not name:
            raise ApiError(400, "Enter your name", {"need": "name"})
        if J["require_pin"] and not pin:
            raise ApiError(400, "Choose a 4-digit PIN. You'll use it to rejoin later.", {"need": "pin", "new": True})
        if new_guest:
            for _ in range(200):
                pid = "G-%04d" % random.SystemRandom().randint(1000, 9999)
                if pid not in P:
                    break
            else:
                pid = "G-%06d" % random.SystemRandom().randint(100000, 999999)
        p = {"name": name, "pin": pin_rec(pin) if pin else None, "tok": None,
             "banned": False, "guest": bool(guest), "created": now_iso()}
        P[pid] = p
    else:
        if p["banned"]:
            raise ApiError(403, "This ID can't join right now. Please see the host.")
        same_device = bool(devtok) and p.get("tok") == devtok
        if not same_device:
            if p["pin"]:
                key = "pin:" + pid
                if not rate_ok(key, 5, 300):
                    raise ApiError(429, "Too many wrong PINs. Wait 5 minutes or ask the host to reset your PIN.")
                if not pin:
                    raise ApiError(400, "Welcome back! Enter your PIN.", {"need": "pin", "new": False})
                if not check_secret(pin, p["pin"], PIN_ITERS):
                    rate_hit(key)
                    raise ApiError(401, "Wrong PIN. Ask the host to reset it if you forgot.", {"need": "pin", "new": False})
            elif J["require_pin"]:
                if not pin:
                    raise ApiError(400, "Choose a 4-digit PIN. You'll use it to rejoin later.", {"need": "pin", "new": True})
                p["pin"] = pin_rec(pin)
            elif p.get("tok") and time.monotonic() - SEEN.get(pid, -1e9) < 30:
                raise ApiError(409, "This ID is already playing on another phone. Ask the host to sign it out.")
        if name and name != p["name"] and J["id_mode"] != "name":
            p["name"] = name
            NAME_REV += 1
    if not (devtok and p.get("tok") == devtok):
        if p.get("tok"):
            TOK.pop(p["tok"], None)      # one phone per player: the old phone is signed out
        p["tok"] = secrets.token_hex(16)
        TOK[p["tok"]] = pid
    SEEN[pid] = time.monotonic()
    touch()
    return {"token": p["tok"], "id": pid, "name": p["name"], "guest": p["guest"]}


def api_answer(b):
    pid = TOK.get(str(b.get("token") or ""))
    if not pid:
        raise ApiError(401, "Please sign in again")
    p = DB["players"][pid]
    L = DB["live"]
    s = cur_session()
    if p["banned"] or not s or pid in s["kicked"]:
        raise ApiError(403, "You can't answer in this round")
    if L["phase"] != "question":
        raise ApiError(409, "Time's up for this question")
    Q = s["questions"][L["q"]]
    c = str(b.get("choice") or "").lower()
    if c not in LETTERS or not Q["options"][c]:
        raise ApiError(400, "Pick one of the answers")
    el = elapsed()
    if el > L["dur"] + S()["game"]["grace_ms"] / 1000.0:
        raise ApiError(409, "Time's up for this question")
    if is_spectator(pid, s):
        raise ApiError(403, "You've already played this quiz, so you're watching this round")
    qa = s["answers"].setdefault(Q["id"], {})
    if pid not in qa:
        qa[pid] = [c, int(el * 1000), points_for(Q, c, min(el, L["dur"]), L["dur"])]
        if pid not in s["joined"]:
            s["joined"][pid] = now_iso()
            touch(s["id"])
        else:
            bump()
    return {"ok": True, "choice": qa[pid][0]}


# --------------------------------------------------------------------------------------------
# Host: quizzes, rounds, players, data
# --------------------------------------------------------------------------------------------
def quiz_summary(qz):
    iss = quiz_issues(qz)
    return {"id": qz["id"], "title": qz["title"], "description": qz["description"], "count": len(qz["questions"]),
            "issues": len(iss), "updated": qz["updated"],
            "rounds": sum(1 for s in DB["sessions"].values() if s["quiz_id"] == qz["id"])}


def save_quiz(raw):
    dt = S()["game"]["default_time"]
    qid = raw.get("id") if isinstance(raw.get("id"), str) and raw.get("id") in DB["quizzes"] else None
    qz = clean_quiz(raw, dt, keep_id=qid)
    if qid:
        qz["created"] = DB["quizzes"][qid]["created"]
    DB["quizzes"][qz["id"]] = qz
    s = cur_session()                     # a round still waiting in the lobby picks up the edits
    if s and s["quiz_id"] == qz["id"] and not s["answers"] and DB["live"]["phase"] == "lobby" and not quiz_issues(qz):
        s["questions"] = json.loads(json.dumps(qz["questions"]))
        s["quiz_title"] = qz["title"]
        touch(s["id"])
    bump()
    return {"quiz": qz, "issues": quiz_issues(qz)}


def new_round(b):
    qz = DB["quizzes"].get(str(b.get("quiz_id") or ""))
    if not qz:
        raise ApiError(404, "Pick a quiz for this round")
    iss = quiz_issues(qz)
    if iss:
        raise ApiError(400, "Fix the quiz before starting: %d question(s) need attention" % len(iss))
    old = cur_session()
    if old and old["status"] == "live":
        old["status"], old["ended"] = "done", old["ended"] or now_iso()
    qs = json.loads(json.dumps(qz["questions"]))
    shuffle = b.get("shuffle")
    if shuffle if isinstance(shuffle, bool) else S()["game"]["shuffle"]:
        random.SystemRandom().shuffle(qs)
    sid = new_id()
    title = clean_text(b.get("title"), 100) or "%s, %s" % (qz["title"], time.strftime("%b %d %I:%M %p").replace(" 0", " "))
    DB["sessions"][sid] = {"id": sid, "title": title, "quiz_id": qz["id"], "quiz_title": qz["title"], "questions": qs,
                           "answers": {}, "qdur": {}, "joined": {}, "kicked": {}, "created": now_iso(),
                           "ended": None, "status": "live"}
    DB["live"] = {"sid": sid, "phase": "lobby", "q": -1, "offset": 0.0, "dur": 0.0}
    touch(sid)
    return {"id": sid}


def open_round(sid):
    s = DB["sessions"].get(sid)
    if not s:
        raise ApiError(404, "Round not found")
    old = cur_session()
    if old and old["id"] != sid and old["status"] == "live":
        old["status"], old["ended"] = "done", old["ended"] or now_iso()
    played = [i for i, Q in enumerate(s["questions"]) if s["answers"].get(Q["id"])]
    s["status"], s["ended"] = "live", None
    if played:
        DB["live"] = {"sid": sid, "phase": "leaderboard", "q": max(played), "offset": 0.0, "dur": 0.0}
    else:
        DB["live"] = {"sid": sid, "phase": "lobby", "q": -1, "offset": 0.0, "dur": 0.0}
    touch(sid)


def round_summary(s):
    rs = round_scores(s)
    win = rs["rows"][0] if rs["rows"] else None
    return {"id": s["id"], "title": s["title"], "quiz_title": s["quiz_title"], "quiz_id": s["quiz_id"],
            "created": s["created"], "ended": s["ended"], "status": s["status"], "players": len(rs["rows"]),
            "questions": len(s["questions"]), "played": sum(1 for Q in s["questions"] if s["answers"].get(Q["id"])),
            "winner": DB["players"][win["pid"]]["name"] if win and win["score"] > 0 else "",
            "live": DB["live"]["sid"] == s["id"]}


def round_detail(sid):
    s = DB["sessions"].get(sid)
    if not s:
        raise ApiError(404, "Round not found")
    rs = round_scores(s)
    P = DB["players"]
    qs = []
    for i, Q in enumerate(s["questions"]):
        qa = s["answers"].get(Q["id"], {})
        n = len(qa)
        right = sum(1 for a in qa.values() if a[0] == Q["answer"])
        qs.append({"n": i + 1, "id": Q["id"], "text": Q["text"], "options": Q["options"], "answer": Q["answer"],
                   "counts": counts_for(qa), "answered": n, "correct_pct": round(100.0 * right / n) if n else None,
                   "avg_s": round(sum(a[1] for a in qa.values()) / n / 1000.0, 1) if n else None})
    rows = [{"rank": r["rank"], "id": r["pid"], "name": P[r["pid"]]["name"], "score": r["score"],
             "correct": r["correct"], "answered": r["answered"]} for r in rs["rows"]]
    return {"round": round_summary(s), "questions": qs, "standings": rows}


def regrade(b):
    s = DB["sessions"].get(str(b.get("id") or ""))
    if not s:
        raise ApiError(404, "Round not found")
    qid, ans = str(b.get("qid") or ""), str(b.get("answer") or "").lower()
    Q = next((q for q in s["questions"] if q["id"] == qid), None)
    if not Q or ans not in LETTERS or not Q["options"][ans]:
        raise ApiError(400, "Pick a valid answer")
    Q["answer"] = ans
    dur = s["qdur"].get(qid, Q["time"] * 1000) / 1000.0
    for pid, a in s["answers"].get(qid, {}).items():
        a[2] = points_for(Q, a[0], min(a[1] / 1000.0, dur), dur)
    if b.get("also_quiz", True):
        qz = DB["quizzes"].get(s["quiz_id"])
        if qz:
            for q in qz["questions"]:
                if q["id"] == qid and q["options"].get(ans):
                    q["answer"] = ans
                    qz["updated"] = now_iso()
    touch(s["id"])
    return {"ok": True}


def players_list():
    ov = overall_scores()
    P = DB["players"]
    online = set(online_pids())
    rounds = {}
    for s in DB["sessions"].values():
        for pid in s["joined"]:
            rounds[pid] = rounds.get(pid, 0) + 1
    out = []
    for pid, p in P.items():
        o = ov["by"].get(pid)
        out.append({"id": pid, "name": p["name"], "guest": p["guest"], "banned": p["banned"], "pin": bool(p["pin"]),
                    "online": pid in online, "signed_in": bool(p.get("tok")), "rounds": rounds.get(pid, 0),
                    "score": o["score"] if o else 0, "rank": o["rank"] if o else None, "created": p["created"]})
    out.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["name"].lower()))
    return out


def player_op(b):
    global NAME_REV
    pid, op = str(b.get("id") or ""), b.get("op")
    p = DB["players"].get(pid)
    if not p:
        raise ApiError(404, "Player not found")
    if op == "rename":
        name = clean_text(b.get("name"), S()["join"]["name_max"])
        if not name:
            raise ApiError(400, "Enter a name")
        p["name"] = name
        NAME_REV += 1
    elif op == "signout":
        revoke(pid)
    elif op == "resetpin":
        p["pin"] = None
        revoke(pid)
        ATTEMPTS.pop("pin:" + pid, None)
    elif op == "ban":
        p["banned"] = True
        revoke(pid)
    elif op == "unban":
        p["banned"] = False
    elif op == "delete":
        make_backup("before-delete-player")
        revoke(pid)
        for s in DB["sessions"].values():
            s["joined"].pop(pid, None); s["kicked"].pop(pid, None)
            for qa in s["answers"].values():
                qa.pop(pid, None)
            SREV[s["id"]] = SREV.get(s["id"], 0) + 1
        del DB["players"][pid]
        PUBKEYS.pop(pid, None)
    else:
        raise ApiError(400, "Unknown player action")
    touch()
    return {"ok": True}


def csv_safe(v):
    """Stop spreadsheet formula injection from player-supplied names."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def make_csv(rows, header):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([csv_safe(x) for x in r])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")   # BOM so Excel shows ñ and other accents


def csv_export(kind, sid):
    P = DB["players"]
    if kind == "overall":
        ov = overall_scores()
        rows = [[r["rank"], r["pid"], P[r["pid"]]["name"], r["score"], r["best"], r["sum"], r["rounds"]] for r in ov["rows"]]
        return make_csv(rows, ["Rank", "ID", "Name", "Overall score", "Best round", "Total of rounds", "Rounds played"]), "overall-standings"
    if kind == "players":
        rows = [[p["id"], p["name"], "yes" if p["guest"] else "", p["rounds"], p["score"], p["rank"] or "",
                 "yes" if p["banned"] else "", p["created"]] for p in players_list()]
        return make_csv(rows, ["ID", "Name", "Guest", "Rounds", "Overall score", "Overall rank", "Banned", "First joined"]), "players"
    if kind == "round":
        det = round_detail(sid)
        s = DB["sessions"][sid]
        head = ["Rank", "ID", "Name", "Score", "Correct", "Answered"] + ["Q%d" % (i + 1) for i in range(len(s["questions"]))]
        rows = []
        for r in det["standings"]:
            per = []
            for Q in s["questions"]:
                a = s["answers"].get(Q["id"], {}).get(r["id"])
                per.append("%s (%d)" % (a[0].upper(), a[2]) if a else "")
            rows.append([r["rank"], r["id"], r["name"], r["score"], r["correct"], r["answered"]] + per)
        slug = re.sub(r"[^A-Za-z0-9]+", "-", s["title"]).strip("-")[:40] or "round"
        return make_csv(rows, head), "round-" + slug
    raise ApiError(400, "Unknown export")


# ------------------------------- images -------------------------------
def sniff_image(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def store_image(data):
    ext = sniff_image(data)
    if not ext:
        raise ApiError(415, "Use a PNG, JPG, GIF or WebP image (SVG isn't allowed for safety)")
    mid = hashlib.sha256(data).hexdigest()[:24] + "." + ext
    path = os.path.join(UPLOADS, mid)
    if not os.path.exists(path):
        write_atomic(path, data)
    return mid


def referenced_media(db):
    ids = set()
    if db["settings"]["brand"]["logo"]:
        ids.add(db["settings"]["brand"]["logo"])
    for qz in db["quizzes"].values():
        ids.update(q["image"] for q in qz["questions"] if q["image"])
    for s in db["sessions"].values():
        ids.update(q["image"] for q in s["questions"] if q["image"])
    return ids


# ------------------------------- export / import -------------------------------
def checksum(data, media):
    blob = json.dumps({"data": data, "media": media}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_export():
    with lock:
        data = json.loads(dump_db().decode("utf-8"))
    data.pop("admin", None)                # the host password never leaves this laptop
    media = {}
    for mid in sorted(referenced_media(data)):
        p = os.path.join(UPLOADS, mid)
        if os.path.isfile(p):
            with open(p, "rb") as f:
                media[mid] = base64.b64encode(f.read()).decode("ascii")
    doc = {"format": EXPORT_FORMAT, "schema": SCHEMA, "app_version": VERSION, "exported_at": now_iso(),
           "event_id": data["event_id"], "title": data["settings"]["event"]["title"],
           "summary": {"players": len(data["players"]), "rounds": len(data["sessions"]), "quizzes": len(data["quizzes"])},
           "checksum": checksum(data, media), "data": data, "media": media}
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_export(body):
    try:
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        doc = json.loads(body.decode("utf-8-sig"))
    except Exception:
        raise ApiError(400, "That file isn't a quiz event export (couldn't read it)")
    if not isinstance(doc, dict) or doc.get("format") != EXPORT_FORMAT:
        raise ApiError(400, "That file isn't a quiz event export. Quiz files go on the Questions page.")
    if not isinstance(doc.get("schema"), int) or doc["schema"] > SCHEMA:
        raise ApiError(400, "This export was made by a newer version. Update this laptop's copy first.")
    data, media = doc.get("data"), doc.get("media") or {}
    if not isinstance(data, dict) or not isinstance(media, dict):
        raise ApiError(400, "The export file is incomplete")
    if doc.get("checksum") and doc["checksum"] != checksum(data, media):
        raise ApiError(400, "The export file is damaged or was edited (checksum doesn't match). Copy it again.")
    good = {}
    for mid, b64 in media.items():
        if not (isinstance(mid, str) and MEDIA_RE.match(mid) and isinstance(b64, str)):
            continue
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception:
            continue
        if len(raw) <= LIMIT_UPLOAD and sniff_image(raw) == mid.rsplit(".", 1)[1]:
            good[mid] = raw
    for mid, raw in good.items():         # images first, so sanitize_db keeps the references
        path = os.path.join(UPLOADS, mid)
        if not os.path.exists(path):
            write_atomic(path, raw)
    return doc, data


def do_import(body, mode, keep_network):
    global DB
    doc, data = read_export(body)
    with lock:
        incoming = sanitize_db(data, base_settings=S())
        backup = make_backup("before-import")
        if mode == "replace":
            incoming["admin"] = DB["admin"]
            incoming["secret"] = DB["secret"]
            if keep_network:
                incoming["settings"]["network"] = DB["settings"]["network"]
            DB = incoming
            rebuild_indexes()
            summary = {"players": len(DB["players"]), "rounds": len(DB["sessions"]), "quizzes": len(DB["quizzes"])}
        else:
            summary = merge_into(incoming)
        touch()
        bump()
    save_now()
    summary.update(mode=mode, backup=backup, source=doc.get("title", ""), exported_at=doc.get("exported_at", ""))
    return summary


def merge_into(inc):
    added = {"players": 0, "rounds": 0, "quizzes": 0, "answers": 0}
    for qid, qz in inc["quizzes"].items():
        mine = DB["quizzes"].get(qid)
        if not mine:
            DB["quizzes"][qid] = qz; added["quizzes"] += 1
        elif qz["updated"] > mine["updated"]:
            DB["quizzes"][qid] = qz
    for pid, p in inc["players"].items():
        mine = DB["players"].get(pid)
        if not mine:
            if p["tok"] and p["tok"] in TOK:
                p["tok"] = None
            DB["players"][pid] = p
            if p["tok"]:
                TOK[p["tok"]] = pid
            added["players"] += 1
        else:
            if not mine["pin"] and p["pin"]:
                mine["pin"] = p["pin"]
            mine["banned"] = mine["banned"] or p["banned"]
    for sid, s in inc["sessions"].items():
        mine = DB["sessions"].get(sid)
        if not mine:
            if s["status"] == "live":
                s["status"] = "done"
            DB["sessions"][sid] = s; added["rounds"] += 1
        else:
            qids = {q["id"] for q in mine["questions"]}
            for qid, qa in s["answers"].items():
                if qid in qids:
                    tgt = mine["answers"].setdefault(qid, {})
                    for pid, a in qa.items():
                        if pid not in tgt:
                            tgt[pid] = a; added["answers"] += 1
            for pid, t in s["joined"].items():
                mine["joined"].setdefault(pid, t)
            for qid, d in s["qdur"].items():
                mine["qdur"].setdefault(qid, d)
    CACHE.clear(); SREV.clear()
    return added


def list_backups():
    out = []
    for f in reversed(backup_files()):
        if True:
            st = os.stat(os.path.join(BACKUPS, f))
            m = re.match(r"event-(\d{8})-(\d{6})-([a-z0-9-]+?)(?:-\d+)?\.json\.gz$", f)
            out.append({"name": f, "size": st.st_size,
                        "time": "%s-%s-%sT%s:%s:%s" % (m.group(1)[:4], m.group(1)[4:6], m.group(1)[6:], m.group(2)[:2],
                                                        m.group(2)[2:4], m.group(2)[4:]) if m else "",
                        "reason": m.group(3) if m else ""})
    return out


def backup_path(name):
    if not isinstance(name, str) or not re.match(r"^event-[0-9a-z-]+\.json\.gz$", name):
        raise ApiError(400, "Unknown backup")
    p = os.path.join(BACKUPS, name)
    if not os.path.isfile(p):
        raise ApiError(404, "Backup not found")
    return p


def restore_backup(name):
    global DB
    p = backup_path(name)
    try:
        with open(p, "rb") as fh:
            d = json.loads(gzip.decompress(fh.read()).decode("utf-8"))
    except Exception:
        raise ApiError(400, "That backup can't be read")
    with lock:
        incoming = sanitize_db(d, base_settings=S())
        make_backup("before-restore")
        incoming["admin"] = DB["admin"]
        DB = incoming
        rebuild_indexes()
        touch()
    save_now()


def new_event(b):
    global DB
    with lock:
        make_backup("before-new-event")
        fresh = new_db(settings=DB["settings"])
        fresh["admin"] = DB["admin"]
        if b.get("keep_quizzes", True):
            fresh["quizzes"] = DB["quizzes"]
        if b.get("keep_players"):
            fresh["players"] = DB["players"]
        DB = fresh
        rebuild_indexes()
        touch()
    save_now()


# --------------------------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------------------------
def lan_ips():
    ips = set()
    try:
        for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(i[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    ips = [i for i in ips if not i.startswith(("127.", "169.254."))]
    pref = lambda i: (0 if i == "192.168.137.1" else 1 if i.startswith("192.168.") else 2 if i.startswith("10.") else 3, i)
    return sorted(ips, key=pref)


def join_info():
    N = S()["network"]
    ips = lan_ips()
    ip = N["host_ip"] or (ips[0] if ips else "localhost")
    d = {"ssid": N["ssid"], "security": N["security"], "show_wifi": N["show_wifi"] and bool(N["ssid"]),
         "ips": ips, "ip": ip, "port": PORT}
    if d["show_wifi"]:
        d["password"] = N["password"]
    return d


def theme_css():
    b = S()["brand"]
    return (":root{--brand:%s;--deep:%s;--paper:%s;--ink:%s;--accent:%s;--opt-a:%s;--opt-b:%s;--opt-c:%s;--opt-d:%s}"
            % (b["primary"], b["deep"], b["paper"], b["ink"], b["accent"], b["opt_a"], b["opt_b"], b["opt_c"], b["opt_d"])
            ).encode("utf-8")


# --------------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------------
PAGES = {"/": "play.html", "/play": "play.html", "/host": "host.html", "/board": "board.html"}
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"     # keep-alive: phones poll every second
    timeout = 30                      # drop idle / slow connections
    server_version = "AUFQuiz/" + VERSION
    sys_version = ""

    def log_message(self, fmt, *a):
        pass

    def send(self, code, body, ctype, cache="no-store", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                  "application/json; charset=utf-8")

    def download(self, body, filename, ctype):
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", filename)[:100]
        self.send(200, body, ctype, extra={"Content-Disposition": 'attachment; filename="%s"' % safe})

    def body(self, limit):
        cl = self.headers.get("Content-Length")
        if cl is None:
            if self.headers.get("Transfer-Encoding"):
                self.close_connection = True
                raise ApiError(411, "Content-Length required")
            return b""
        try:
            n = int(cl)
        except ValueError:
            self.close_connection = True
            raise ApiError(400, "Bad request")
        if n < 0:
            self.close_connection = True
            raise ApiError(400, "Bad request")
        if n > limit:
            self.close_connection = True
            raise ApiError(413, "That's too large (limit %d MB)" % max(1, limit // (1024 * 1024)))
        data = self.rfile.read(n)
        if len(data) != n:
            self.close_connection = True
            raise ApiError(400, "Upload was cut off")
        return data

    def jbody(self, limit=LIMIT_JSON):
        raw = self.body(limit)
        try:
            b = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "Bad request")
        if not isinstance(b, dict):
            raise ApiError(400, "Bad request")
        return b

    def ip(self):
        return self.client_address[0]

    def host_ok(self):
        t = self.headers.get("X-Host-Token", "")
        with lock:
            if t and t in HOSTS:
                HOSTS[t] = time.monotonic()
                return True
        return False

    def do_GET(self):
        self.route("GET")

    def do_HEAD(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method):
        try:
            self._route(method)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout):
            self.close_connection = True      # phone dropped off the Wi-Fi mid-reply: nothing to do

    def _route(self, method):
        try:
            u = urlsplit(self.path)
            path = u.path
            qs = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
            if path.startswith("/api/"):
                return self.api(method, path, qs)
            if method != "GET":
                raise ApiError(405, "Method not allowed")
            if path == "/theme.css":
                with lock:
                    css = theme_css()
                return self.send(200, css, "text/css; charset=utf-8", cache="no-cache")
            if path.startswith("/media/"):
                return self.media(path[7:])
            if path == "/favicon.ico":
                return self.send(204, b"", "text/plain", cache="max-age=86400")
            return self.static(path)
        except ApiError as e:
            if self.path.startswith("/api/"):
                d = {"error": e.msg}
                d.update(e.extra)
                return self.json(d, e.code)
            return self.send(e.code, ("%d %s" % (e.code, e.msg)).encode(), "text/plain; charset=utf-8")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout):
            raise
        except Exception:
            traceback.print_exc()
            try:
                self.json({"error": "Something went wrong on the server. Check the console window."}, 500)
            except Exception:
                self.close_connection = True

    def static(self, path):
        rel = PAGES.get(path.rstrip("/") or "/", path.lstrip("/"))
        if ".." in rel or not re.match(r"^[A-Za-z0-9_\-/]+\.[a-z0-9]+$", rel):
            raise ApiError(404, "Not found")
        full = os.path.realpath(os.path.join(STATIC, rel))
        ext = os.path.splitext(full)[1]
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full) or ext not in TYPES:
            raise ApiError(404, "Not found")
        st = os.stat(full)
        etag = '"%x-%x"' % (int(st.st_mtime), st.st_size)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        with open(full, "rb") as f:
            data = f.read()
        self.send(200, data, TYPES[ext], cache="no-store" if ext == ".html" else "no-cache", extra={"ETag": etag})

    def media(self, mid):
        if not MEDIA_RE.match(mid):
            raise ApiError(404, "Not found")
        p = os.path.join(UPLOADS, mid)
        if not os.path.isfile(p):
            raise ApiError(404, "Not found")
        with open(p, "rb") as f:
            data = f.read()
        self.send(200, data, MEDIA_TYPES[mid.rsplit(".", 1)[1]], cache="public, max-age=31536000, immutable")

    # ---------------------------------------------------------------- API
    def api(self, method, path, qs):
        if method == "GET":
            if path == "/api/state":
                with lock:
                    return self.json(public_view(qs.get("token"), qs.get("v")))
            if path == "/api/info":
                with lock:
                    d = join_info()
                    d["event"] = event_public()
                    J = S()["join"]
                    d["join"] = {"mode": J["id_mode"], "label": J["id_label"], "mask": J["id_mask"],
                                 "example": mask_example(J["id_mask"]), "guests": J["allow_guests"],
                                 "pin": J["require_pin"], "name_max": J["name_max"], "privacy": J["privacy_note"]}
                return self.json(d)
        if method == "POST":
            if path == "/api/join":
                b = self.jbody()
                with lock:
                    return self.json(api_join(b, self.ip()))
            if path == "/api/answer":
                b = self.jbody()
                with lock:
                    return self.json(api_answer(b))
            if path == "/api/leave":
                b = self.jbody()
                with lock:
                    pid = TOK.get(str(b.get("token") or ""))
                    if pid:
                        revoke(pid)
                        bump()
                return self.json({"ok": True})
            if path == "/api/host/login":
                return self.host_login()
        if path.startswith("/api/host/"):
            if not self.host_ok():
                raise ApiError(401, "Sign in to the host console")
            return self.host_api(method, path[10:], qs)
        raise ApiError(404, "Not found")

    def host_login(self):
        b = self.jbody()
        ip = self.ip()
        if b.get("code"):
            ok = ip in ("127.0.0.1", "::1") and hmac.compare_digest(str(b["code"]), BOOT_CODE)
        else:
            with lock:
                if not rate_ok("host:" + ip, 8, 300):
                    raise ApiError(429, "Too many attempts. Wait 5 minutes.")
                rec = DB["admin"]
            ok = check_secret(str(b.get("password") or ""), rec)   # slow hash: outside the lock
            if not ok:
                with lock:
                    rate_hit("host:" + ip)
        if not ok:
            raise ApiError(401, "That password isn't right")
        t = secrets.token_hex(24)
        with lock:
            HOSTS[t] = time.monotonic()
        return self.json({"token": t})

    def host_api(self, method, ep, qs):
        G = method == "GET"
        if G and ep == "state":
            with lock:
                return self.json(host_view(qs.get("v")))
        if G and ep == "info":
            with lock:
                return self.json(join_info())
        if not G and ep == "action":
            b = self.jbody()
            with lock:
                host_action(b.get("action"), b.get("value"))
                return self.json({"ok": True})
        if not G and ep == "logout":
            with lock:
                HOSTS.pop(self.headers.get("X-Host-Token", ""), None)
            return self.json({"ok": True})
        # settings
        if G and ep == "settings":
            with lock:
                return self.json({"settings": S(), "running_port": PORT, "mask_example": mask_example(S()["join"]["id_mask"])})
        if not G and ep == "settings":
            b = self.jbody()
            with lock:
                new, errors = clean_settings(b.get("settings"), S())
                if errors:
                    raise ApiError(400, "Some settings need fixing", {"errors": errors})
                DB["settings"] = new
                CACHE.clear()
                touch()
                return self.json({"settings": new, "running_port": PORT})
        if not G and ep == "password":
            b = self.jbody()
            with lock:
                rec = DB["admin"]
            if not check_secret(str(b.get("current") or ""), rec):
                raise ApiError(400, "Your current password isn't right")
            new = str(b.get("new") or "")
            if len(new) < 8:
                raise ApiError(400, "Use at least 8 characters")
            h = hash_secret(new)
            cur = self.headers.get("X-Host-Token", "")
            with lock:
                DB["admin"] = h
                bump()
                for k in [k for k in HOSTS if k != cur]:      # sign out every other host device
                    HOSTS.pop(k, None)
            return self.json({"ok": True})
        # quizzes
        if G and ep == "quizzes":
            with lock:
                return self.json({"quizzes": sorted([quiz_summary(q) for q in DB["quizzes"].values()],
                                                    key=lambda q: q["updated"], reverse=True)})
        if G and ep == "quiz":
            with lock:
                qz = DB["quizzes"].get(qs.get("id", ""))
                if not qz:
                    raise ApiError(404, "Quiz not found")
                return self.json({"quiz": qz, "issues": quiz_issues(qz)})
        if not G and ep == "quiz":
            b = self.jbody(LIMIT_QUIZ)
            with lock:
                return self.json(save_quiz(b.get("quiz") or {}))
        if not G and ep == "quiz/delete":
            b = self.jbody()
            with lock:
                if DB["quizzes"].pop(str(b.get("id") or ""), None) is None:
                    raise ApiError(404, "Quiz not found")
                bump()
                return self.json({"ok": True})
        if not G and ep == "quiz/duplicate":
            b = self.jbody()
            with lock:
                qz = DB["quizzes"].get(str(b.get("id") or ""))
                if not qz:
                    raise ApiError(404, "Quiz not found")
                cp = json.loads(json.dumps(qz))
                cp.pop("id", None)
                cp["title"] = (qz["title"] + " (copy)")[:80]
                for q in cp["questions"]:
                    q.pop("id", None)
                return self.json(save_quiz(cp))
        if not G and ep == "quiz/import":
            raw = self.body(LIMIT_QUIZ)
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1252", "replace")
            with lock:
                data = parse_quiz_file(text, qs.get("name", ""))
                data.pop("id", None)
                return self.json(save_quiz(data))
        if G and ep == "quiz/export":
            with lock:
                qz = DB["quizzes"].get(qs.get("id", ""))
                if not qz:
                    raise ApiError(404, "Quiz not found")
                body = json.dumps({"title": qz["title"], "description": qz["description"],
                                   "questions": qz["questions"]}, ensure_ascii=False, indent=2).encode("utf-8")
            return self.download(body, "quiz-%s.json" % re.sub(r"[^A-Za-z0-9]+", "-", qz["title"]).strip("-"), "application/json")
        # rounds
        if G and ep == "rounds":
            with lock:
                return self.json({"rounds": sorted([round_summary(s) for s in DB["sessions"].values()],
                                                   key=lambda r: r["created"], reverse=True),
                                  "quizzes": [quiz_summary(q) for q in DB["quizzes"].values()]})
        if G and ep == "round":
            with lock:
                return self.json(round_detail(qs.get("id", "")))
        if not G and ep == "round/new":
            b = self.jbody()
            with lock:
                return self.json(new_round(b))
        if not G and ep == "round/open":
            b = self.jbody()
            with lock:
                open_round(str(b.get("id") or ""))
                return self.json({"ok": True})
        if not G and ep == "round/rename":
            b = self.jbody()
            with lock:
                s = DB["sessions"].get(str(b.get("id") or ""))
                if not s:
                    raise ApiError(404, "Round not found")
                s["title"] = clean_text(b.get("title"), 100) or s["title"]
                bump()
                return self.json({"ok": True})
        if not G and ep == "round/delete":
            b = self.jbody()
            sid = str(b.get("id") or "")
            make_backup("before-delete-round")
            with lock:
                if DB["sessions"].pop(sid, None) is None:
                    raise ApiError(404, "Round not found")
                if DB["live"]["sid"] == sid:
                    DB["live"] = idle_live()
                CACHE.clear()
                touch()
                return self.json({"ok": True})
        if not G and ep == "round/regrade":
            b = self.jbody()
            with lock:
                return self.json(regrade(b))
        # players
        if G and ep == "players":
            with lock:
                return self.json({"players": players_list()})
        if not G and ep == "player":
            b = self.jbody()
            with lock:
                return self.json(player_op(b))
        # data
        if G and ep == "export":
            body = build_export()
            with lock:
                t = re.sub(r"[^A-Za-z0-9]+", "-", S()["event"]["title"]).strip("-")[:40] or "event"
            return self.download(body, "%s-%s.aufquiz.json" % (t, time.strftime("%Y%m%d-%H%M")), "application/json")
        if not G and ep == "import":
            raw = self.body(LIMIT_IMPORT)
            mode = qs.get("mode", "replace")
            if mode not in ("replace", "merge"):
                raise ApiError(400, "Choose replace or merge")
            return self.json(do_import(raw, mode, qs.get("keep_network", "1") == "1"))
        if G and ep == "backups":
            return self.json({"backups": list_backups()})
        if not G and ep == "backup/create":
            return self.json({"name": make_backup("manual")})
        if not G and ep == "backup/restore":
            b = self.jbody()
            restore_backup(b.get("name"))
            return self.json({"ok": True})
        if G and ep == "backup/download":
            p = backup_path(qs.get("name"))
            with open(p, "rb") as f:
                return self.download(f.read(), os.path.basename(p), "application/gzip")
        if G and ep == "csv":
            with lock:
                body, name = csv_export(qs.get("kind"), qs.get("id", ""))
            return self.download(body, "%s-%s.csv" % (name, time.strftime("%Y%m%d-%H%M")), "text/csv; charset=utf-8")
        if not G and ep == "upload":
            raw = self.body(LIMIT_UPLOAD)
            mid = store_image(raw)
            return self.json({"id": mid, "url": media_url(mid)})
        if not G and ep == "newevent":
            b = self.jbody()
            new_event(b)
            return self.json({"ok": True})
        raise ApiError(404, "Not found")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


# --------------------------------------------------------------------------------------------
def main():
    global PORT
    for d in (DATA, UPLOADS, BACKUPS):
        os.makedirs(d, exist_ok=True)
    with lock:
        load_db()
    if "--reset-password" in sys.argv:
        pw = gen_password()
        with lock:
            DB["admin"] = hash_secret(pw)
        save_now()
        print("\n  New host password:  %s\n" % pw)
        return
    new_pw = None
    if DB["admin"] is None:
        new_pw = gen_password()
        DB["admin"] = hash_secret(new_pw)
        save_now()
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a != _arg("--data")]
    want = int(args[0]) if args and args[0].isdigit() else S()["network"]["port"]
    srv = None
    for p in [want] + [x for x in (8000, 8080, 8888) if x != want]:
        try:
            srv = Server(("0.0.0.0", p), Handler)
            PORT = p
            break
        except OSError:
            print("  (port %d is unavailable)" % p)
    if not srv:
        print("  !! Couldn't open any port. Close other servers and try again.")
        return
    threading.Thread(target=ticker, daemon=True).start()
    threading.Thread(target=saver, daemon=True).start()
    sfx = "" if PORT == 80 else ":%d" % PORT
    ips = lan_ips()
    host_url = "http://localhost%s/host#auto=%s" % (sfx, BOOT_CODE)
    print("\n  AUF QUIZ SERVER %s is running   (data folder: %s)" % (VERSION, DATA))
    print("  " + "-" * 64)
    for ip in ips:
        print("  Players join at:   http://%s%s/" % (ip, sfx))
    if not ips:
        print("  !! No network address found. Is the hotspot or Wi-Fi on?")
    print("  Projector board:   http://localhost%s/board" % sfx)
    print("  Host console:      http://localhost%s/host" % sfx)
    if new_pw:
        print("\n  Host password (shown once, change it in Settings):  %s" % new_pw)
    print("\n  Press Ctrl+C to stop. Progress is saved automatically.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(host_url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("  Saving...")
        try:
            save_now()
        except Exception as e:
            print("  !! Couldn't save on exit: %s" % e)


if __name__ == "__main__":
    main()
