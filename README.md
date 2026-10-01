# lan-games

Two offline games for a college booth. Players join your WiFi hotspot, open a browser, and play. **No internet needed**: everything runs from your laptop.

| Game | Folder | What it is |
|------|--------|-----------|
| Pac-Man | `pacman-booth/` | 50 levels of rising difficulty, with a leaderboard |
| Quiz (Kahoot-style) | `kahoot-booth/` | Host-controlled live quiz with timed questions and a leaderboard |

## Requirements

- Python 3.7 or newer (check with `python --version`)
- A laptop that can run a WiFi hotspot or access point
- Nothing to install. Both servers use only the Python standard library.

## Folder layout

```

  pacman-booth/
    server.py
    static/            index.html, board.html
 
  kahoot-booth/
    server.py
    questions.json
    config.json
    static/            index.html, host.html, board.html, shared.js, common.css, qrcode.js
    static/images/     q1.svg ... q5.svg
```

Keep the `static/` folders exactly as shown. If they're missing or renamed, the browser shows a **404 File not found** error.

Suggested `.gitignore` (keeps player names and IDs out of git):
```
data.json
data.json.tmp
__pycache__/
```

## Before you start (both games)

1. **Turn on your hotspot.**
   - Windows: Settings → Network & Internet → Mobile hotspot.
   - macOS: System Settings → General → Sharing → Internet Sharing.
   - Or use any router/AP your laptop is connected to.
2. **Allow Python through the firewall** when Windows asks. If you click Cancel, phones can't connect.
3. **Check the address the server prints.** Real addresses look like `192.168.x.x` or `10.x.x.x`. Windows hotspots are usually `192.168.137.1`. If you only see `169.254.x.x`, or nothing, the laptop has no real network address. Make sure the hotspot is actually on.

## Pac-Man

```bash
cd pacman-booth
python server.py          # runs on port 8000
```

The console prints the player and big-screen links:

- **Players:** `http://<your-ip>:8000/`
- **Big-screen leaderboard:** `http://<your-ip>:8000/board`

Use `python server.py 80` to run on port 80. Then players can type just `http://<your-ip>/` with no port. On Windows this may need an admin terminal.

**How it works**
- Players sign in with a student ID (format `24-2156-111`) and a name. The same ID keeps its best score.
- Controls: arrow keys or WASD on a laptop, swipe on a phone.
- Levels 1–50: ghosts get faster and smarter, and power pellets last shorter.
- The leaderboard shows the top 20 by name, level and score.

**Tuning:** open `static/index.html` and edit the `diff()` function and `PSPEED` to make it easier or harder. Change the ID format with `ID_RE` at the top of `server.py`.

## Quiz (Kahoot-style)

**One-time setup:** edit `kahoot-booth/config.json`:

```json
{
  "title": "College Quiz Booth",
  "ssid": "MyHotspot",
  "password": "12345678",
  "security": "WPA",
  "port": 80,
  "host_ip": ""
}
```

`ssid` and `password` must match your hotspot, because they go into the join-WiFi QR code. Use `"security": "nopass"` for an open network. Set `host_ip` only if the server picks the wrong address.

**Run it:**

```bash
cd kahoot-booth
python server.py
```

The host page opens in your browser automatically. Its URL contains a random key that only you have, so players can't use the host controls. If it doesn't open, copy the `Host:` link from the console. If you stop and restart the server, use the new link, because the key changes each run.

Port 80 may need an admin terminal on Windows. If it can't bind, the server falls back to port 8000.

Use `python server.py --no-browser` to skip the auto-open.

### Running a session

1. Open `http://localhost/board` on the booth monitor (or `:8000` if it fell back). The lobby shows two QR codes.
2. Players scan **QR 1** to join the WiFi, then **QR 2** to open the game. One QR can't do both.
3. Players sign in with ID and name and wait in the lobby.
4. On the host page, press **Next ▶** to start question 1.
5. After the timer ends, or when everyone has answered, answers are revealed automatically.
6. Press **Leaderboard** to show standings, then **Next ▶** for the next question.
7. After the last question, **Next ▶** shows the final results.

### Host controls

| Button | What it does |
|--------|--------------|
| Prev / Next (← / → keys) | Move between questions |
| Reveal answer | End the timer early |
| Leaderboard | Show standings on the big screen and phones |
| Replay question | Clear that question's answers and run it again |
| +5 seconds | Extend the running timer |
| Jump to question… | Go straight to any question |
| Back to lobby / Final podium | Jump to either screen |
| Reload questions.json | Pick up question edits without restarting |
| Reset scores | Clear all answers, keep players |
| Wipe players | Remove everyone and all scores |
| ✕ next to a name | Kick one player |

Going back to a question that was already played shows its results. Use **Replay question** to run it again.

### Scoring

- A correct answer gets up to 1000 points: 1000 for an instant answer, dropping to 500 at the last second.
- Wrong or no answer gets 0.
- Timing is measured by the server, so slow phones don't affect fairness.

### Editing the questions

Edit `kahoot-booth/questions.json`:

```json
{
  "question1": {
    "Question": "What is 1 + 1?",
    "a": "2",
    "b": "3",
    "c": "4",
    "d": "5",
    "answer": "A",
    "image": "images/q1.svg",
    "time": 15
  }
}
```

- Questions are ordered by the number in the key (`question1`, `question2`, ...).
- `answer` is `A`, `B`, `C` or `D`.
- `image` is a path inside `static/`. PNG, JPG and SVG all work. Put your pictures in `static/images/`. The image shows on both the question and the answer reveal.
- `time` is optional and defaults to 15 seconds.
- After saving, click **Reload questions.json** on the host page. If the file has a JSON error (a missing comma, say), the reload fails and you'll see an alert.

## Running both at once

They use different default ports (Pac-Man 8000, Quiz 80), so both can run at the same time. Open each in its own terminal.

## Resetting between events

Stop the server and delete `data.json` in that game's folder. The leaderboard and all players start fresh.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| **404 File not found** | Check the `static/` folder layout above. Also make sure no other server (such as an old `python -m http.server`) is using the same port. Close old terminals, or run on another port. |
| Phones can't connect | Check they're on your hotspot, you allowed the firewall prompt, and you're using the IP the server printed, not `localhost`. |
| Server only shows `169.254...` or no address | Your hotspot is off, or the laptop isn't connected to any network. |
| "Port unavailable" or permission error on port 80 | Run as admin, or use `python server.py 8000`. |
| Join-WiFi QR doesn't connect | Check `ssid` and `password` in `config.json`. Some older Android phones can't scan WiFi QR codes. Join manually instead. |
| Quiz shows "Bad host key" | Use the `Host:` link from the current server run. |
| Anyone can open `/host` | They can open the page but can't control it without the key. Keep the host link private. |

## Notes

- Anyone who knows a student ID can play under it. That's fine for a booth but isn't secure.
- Player data is stored in plain `data.json` files on your laptop. Delete them after the event if you don't want to keep names and IDs.