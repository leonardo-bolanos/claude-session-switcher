# TODO

What's missing, with whatever has already been checked about each item. If you feel like
taking one on, issues and PRs are welcome.

---

## Support Terminal.app

**Status: doable, verified.** The most sensible thing to do next.

Listing already works in any terminal; only the window jump is iTerm2-only. For Terminal.app the
piece that was needed exists: its AppleScript dictionary exposes `tty` per tab, and it has
`selected tab`, `index` and `frontmost` for focusing.

```
$ sdef /System/Applications/Utilities/Terminal.app | grep 'name="tty"'
<property name="tty" description="The tab's TTY device." code="ttty" type="text" access="r">
```

What it involves:

- A `get_terminal_map()` alongside `get_iterm_map()`, and merging both maps. A TTY is unique per
  session, so there's no collision: each one contributes its own.
- Storing which application holds each row, to know where to send the focus AppleScript. Today
  `row["iterm"]` is `(window_id, tab)`; it would have to become `(app, window_id, tab)`.
- Terminal.app addresses tabs by `index` within the window, same as iTerm2, so it inherits the
  same limitation: the index shifts if you close a tab.
- Watch the performance: the `get_iterm_map()` lesson applies here too. Bulk queries, not a loop
  per session, or it's seconds instead of milliseconds.

## Support Windows

**Status: it's a port, not a tweak.**

It isn't that one piece is missing: the whole mechanism is. Worth knowing before you start.

| Piece | On macOS | On Windows |
|---|---|---|
| Interactive panel | `termios` + `tty` in raw mode | **they don't exist**: the script won't even import |
| PID → terminal | `ps -o tty=` | there's no TTY; you'd go through the console/pseudoconsole |
| Focusing the window | AppleScript to iTerm2 | Win32 (`SetForegroundWindow`) or Windows Terminal's tab model |

How it would go:

- Replace `termios`/`tty` with `msvcrt.getwch()` to read keys, behind a `sys.platform` check. The
  rest of the loop (viewport, filter, numbering) is agnostic and can be reused as-is.
- The pure logic is already portable: the whole suite runs on Linux in CI, so `vis`/`clip`,
  `assign_numbers`, `read_transcript` and the filter need no changes.
- Windows Terminal doesn't expose its tabs through a stable public API. The realistic route is
  locating the process's window by PID with Win32 and raising it, accepting that the specific
  **tab** may not be addressable. A window-level jump would already be useful.
- Cheaper alternative to a full port: make only `--list` work on Windows, and have the
  interactive panel say it isn't supported instead of blowing up on import.

## Other terminals

In order of how feasible they look:

- **tmux** — **done.** Sessions running inside a tmux pane are found and focused, and a
  detached session gets attached in a new iTerm tab. See "Sessions inside tmux" in the README.
- **kitty** *(unverified)* — has a remote control protocol (`kitty @ ls` returns windows and tabs
  with their PID), so the mapping would be by PID instead of by TTY.
- **WezTerm** *(unverified)* — `wezterm cli list --format json` includes `pane_id` and the
  process PID.
- **Ghostty, Alacritty** — no remote control that would work for this, as far as is known.

## Smaller things

- **The age column's clock only moves on refresh.** While idle (20 s) it can be that stale. It's
  cosmetic; it would be fixed by repainting without collecting data.
- **The tab index shifts** if you close a tab in the same window between listing and choosing.
  The risk window is seconds and the worst case is focusing the neighbouring tab, but the TTY
  could be revalidated right before focusing.
- **Killing or closing a session from the panel.** Deliberately dropped: a key that kills a
  process one keystroke away from the navigation keys is a bad idea without confirmation, and
  with confirmation it stops being fast.
- **`⌥1..9` needs iTerm2 configured** (*Left Option key: `Esc+`*). Without it, `⌥1` sends `¡` and
  the panel treats it as filter text. Those symbols (`¡™£¢∞§¶•ª`) could be mapped too so it
  worked out of the box, but they depend on the keyboard layout: a Spanish keyboard doesn't
  produce the same ones. Check several layouts before doing it.
- **The note editor's state lives loose inside `interactive()`.** `editando` is touched at four
  points of the loop: entering, initialising, resetting when the filter empties the list,
  painting the prompt and handling keys. One of those already had to be fixed because it had
  drifted. It fits as a small object (`.activo`, `.tecla(k)`, `.pintar()`) without splitting the
  single file. It wasn't done because it touches the heart of the loop and the benefit is
  organisational, not functional — but if one more key gets added to it (cursor with `←`/`→`),
  do it first.
- **The pty harness is duplicated** between `test_panel.py` and `make_demo.py`: fork,
  `TIOCSWINSZ`, bounded draining, with the same justifying comment repeated and already drifting
  (one polls at 0.15 s and the other at 0.1 s, for no reason). It would fit in a
  `pty_harness.py` — they're development files, so it wouldn't break the "one script, no
  dependencies" promise, which is about what gets distributed. It's ~30 hermetic, tested lines,
  so there's no urgency.
- **`test_panel.py` takes ~3 min** because it's ~80 real panel launches, serial and completely
  independent (each with its own pty, subprocess and notes file). They'd parallelise well, but
  that asks for `pytest-xdist` and the project prides itself on zero dependencies; someone would
  have to decide whether a **development-only** dependency is acceptable. **Don't lower the
  waits**: they're tuned against flakiness and they scale with `CCL_TEST_LENTO`.
- **The table view isn't remembered between runs.** `Ctrl-T` switches the view for that panel
  session and `ccl --table` starts in the table, but anyone who prefers it has to set up an
  alias. Storing it in `ccl-notes.json` is five lines; it wasn't done because it opens the
  question of what wins when the flag and the stored value disagree, and inventing a precedence
  rule isn't worth it for a preference an alias solves.
- **The table's columns are fixed-width.** A 40-character name gets clipped even when every other
  one is short and there's room to spare. Fitting them to the actual content (measure the longest
  and share out) looks better, but it makes the table **dance** between refreshes: one session
  with a long name appearing moves every column. The widths would have to be pinned and only
  recomputed when the window is resized.
- **Paused sessions are never pruned**, same as notes. A `sessionId` is a UUID and never comes
  back, so an orphan entry can't pause anyone by mistake; it only piles up bytes. If they're ever
  pruned, it has to be with the list of live sessions at hand — never on save.
