# AUF University Week Quiz

A Kahoot-style quiz for Angeles University Foundation's University Week. One laptop runs the game; players join on their phones over Wi-Fi; a projector or TV shows the questions and scoreboard. It needs **no internet**: Python 3.7 or newer, standard library only.

## Start it

1. Install Python 3 (python.org). On Windows, tick **Add Python to PATH** during setup.
2. Turn on the event Wi-Fi or hotspot and connect the laptop to it.
3. Double-click **start-windows.bat** (Windows) or run `./start-mac-linux.sh` (macOS/Linux). You can also run `python server.py`.
4. The host console opens in the browser automatically. The first time, the server window prints a **host password**. Write it down; you need it to open the host console from any other device.
5. Open **http://localhost/board** in a second browser window and drag it to the projector (press F11 for full screen).

Players scan the two codes on the projector: one joins the Wi-Fi, the other opens the game.

If Windows asks whether to allow Python through the firewall, choose **Allow** for private networks, otherwise phones can't connect.

## Run a round

1. **Questions**: create a quiz, or import a file (`samples/ccs-starter-quiz.json`, your old `questions.json`, or a CSV like `samples/quiz-template.csv`).
2. **Rounds**: pick the quiz and press **Start round**. The projector shows the lobby with the join codes.
3. **Live game**: press the big button (or the Space bar) to move through the game: start, reveal, leaderboard, next question, final podium, week standings. Arrow keys still do previous and next as before. There are also buttons to pause, add time, replay a question, jump, and remove a player.

When a round ends, the next group can play a new round. Players keep their account all week, and **Week standings** combines every round (best round or total, set in Settings).

If an answer key turns out to be wrong, open **Rounds**, then **Results**, and pick the right answer. Everyone who answered is re-scored.

## Move to another laptop or Wi-Fi and carry on

1. On the old laptop: **Data and transfer**, then **Download event file**.
2. Copy the file to the new laptop (USB, chat, email).
3. On the new laptop: start the server, open **Data and transfer**, choose the file, keep **Continue from this file** selected, and press **Import**.

Everything comes across: settings, quizzes, images, players, rounds and scores. A question that was running comes back **paused** with its remaining time; press **Resume the timer**. Players open the new game address and sign in with their **student number and PIN**. Each laptop keeps its own host password and, by default, its own Wi-Fi settings.

To combine several booths into one week standings, import each booth's file with **Combine with this laptop**.

## Players

Students join with their student number (format set in Settings, `##-####-###` by default), their name, and a 4-digit PIN they choose. The PIN stops anyone who knows a classmate's student number from playing as them, and lets students rejoin from another phone or on another network. Visitors without a student number can join as guests and get a code like `G-4821`.

On the **Players** page you can rename, sign out, reset a forgotten PIN, ban for the event, or delete someone's data entirely (for Data Privacy Act requests).

## Settings

Everything that used to be hard-coded is on the **Settings** page: event names, AUF colours and logo, Wi-Fi details, the student-number format, PINs, guests, blocked words in names, points, timing, grace period, leaderboard size, how week standings are counted, one attempt per quiz, and backups. Changes reach every screen within a second or two. Changing the port needs a server restart.

## Your data

Everything lives in the `data` folder next to `server.py`:

- `event.json` holds the whole event and is saved automatically within a second of any change.
- `backups/` keeps automatic copies every 10 minutes, at the end of each round, and before anything is deleted or replaced. Restore them from **Data and transfer**.
- `uploads/` holds question images and the logo.

To upgrade from the old version, put this version's files in a new folder and copy your old `config.json` and `questions.json` (and optionally `data.json`) next to `server.py` before the first start. They're imported automatically. Old scores aren't carried over, because they were stored by question position and no longer matched your questions.

## Network notes

- A **Windows mobile hotspot allows only 8 devices**. For a booth with more players, use a Wi-Fi router or access point and connect the laptop to it.
- If the join code shows the wrong address, pick the right one under the codes on the **Live game** page, or set it under Settings, then **Game address**.
- Port 80 keeps the address short. If it's taken, the server uses 8000 instead and prints the address.

## Command line

```
python server.py                    start (port from Settings)
python server.py 8080               start on a specific port
python server.py --no-browser       don't open the host console automatically
python server.py --data D:\uweek    keep data in another folder
python server.py --reset-password   print a new host password and exit
```

## Credits

Fonts: Atkinson Hyperlegible (Braille Institute) and Big Shoulders Display (Patric King), both SIL Open Font License; see `static/fonts`. QR codes: qrcode-generator by Kazuhiko Arase, MIT License. "QR Code" is a registered trademark of DENSO WAVE INCORPORATED.
