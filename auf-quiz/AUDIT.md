# Audit of the original booth quiz

What was found in the original `kahoots` project, why it mattered for a university-wide event, and what this version does instead. Each item is covered by an automated test.

## Errors that would have disrupted the game

**Questions 1–5 skipped straight to the answer.** Answers were stored by question position (`"0"`, `"1"`, …). The shipped `data.json` held answers from an older 5-question test set, so pressing Next on questions 1–5 jumped to the reveal and showed stale scores. Editing or reordering `questions.json` mid-week would do the same. *Now:* each round keeps its own copy of the questions, and answers are tied to a question ID.

**The projector page was the phone page.** `board.html` was a copy of `index.html`, so the TV showed a sign-in form. *Now:* a dedicated projector screen.

**Join QR codes never appeared.** `qrcode.js` sat outside the `static` folder the server shares, so it failed to load and the error was swallowed. *Now:* bundled with the pages; QR codes are verified to decode.

**`common.css` was cut off.** The correct answer wasn't highlighted, the timer bar was invisible, and QR panels were unstyled.

**"Everyone answered" never triggered.** It compared answers against every player ever registered. Once anyone left, every question ran its full time. *Now:* it compares against players connected in the last few seconds.

**Answers in the grace period were impossible.** The server accepted answers up to 0.7 s late, but the timer thread closed the question at exactly 0 s. *Now:* the question closes after the grace period (configurable).

**A server restart lost the game position** and dropped back to the lobby. *Now:* the round and question are saved; an open question comes back paused with its remaining time.

**The round leaderboard included everyone registered**, not just who played that round. *Now:* each round lists only its participants; the week standings combine rounds.

**Duplicate names highlighted the wrong row** on phones, because "you" was matched by name. *Now:* matched by an anonymous per-player key.

**Saving after every answer could fail on Windows** (antivirus briefly locking the file) and lose the reply. *Now:* a background saver retries, and writes are atomic.

## Security problems

**Account takeover with a student number.** Signing in with an existing student number returned that player's session and renamed them. Anyone who knew a classmate's number could play as them, or answer wrong on purpose for the leader. *Now:* a 4-digit PIN chosen at first join (hashed), five wrong tries locks that ID for five minutes, and signing in on a new phone signs out the old one.

**Correctness leaked before the reveal.** A player's score rose the moment they answered correctly, visible to anyone nearby. *Now:* scores and points stay hidden until the reveal.

**Invalid answers were accepted.** `c not in "abcd"` let `"ab"` through as a substring. *Now:* exactly one valid letter.

**The server could be stalled.** A huge or negative `Content-Length` hung a worker thread, with no timeout for slow connections. *Now:* size limits per endpoint, rejected bad lengths, and a 30-second socket timeout.

**Spreadsheet formula injection.** A name like `=HYPERLINK(...)` would run when organizers opened results in Excel. *Now:* such cells are neutralised in every CSV.

**The host key was weak to handle.** It travelled in URLs (browser history), changed on every restart, and the host API had no attempt limit. *Now:* a host password (PBKDF2-hashed, rate-limited), session tokens in a request header, and a one-time auto sign-in link that only works from the laptop itself.

**Unsafe uploads.** *Now:* images only (PNG, JPG, GIF, WebP), checked by content; SVG is refused because it can carry scripts.

**No browser protections.** *Now:* Content-Security-Policy (no inline scripts), no-sniff, frame and referrer headers, no directory listings, and a strict static file allow-list.

**Unsanitised names.** Invisible and right-to-left override characters could garble the projector. *Now:* stripped, plus an optional blocked-words list that catches common letter swaps.

**Imported files were trusted.** *Now:* every event file, backup and quiz import is validated field by field, and event files carry a checksum, so a damaged or edited file is refused instead of corrupting the event.

## Data handling

- The shipped `config.json` contained a real Wi-Fi password, and `data.json` contained students' ID numbers. Keep both out of shared copies.
- Exports never include the host password. They do include students' ID numbers and PIN hashes (needed to continue on another laptop), so treat event files as personal data under the Data Privacy Act of 2012.
- The Players page can delete one person's data from every round.
