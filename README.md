# claude-session-switcher

[![CI](https://github.com/leonardo-bolanos/claude-session-switcher/actions/workflows/ci.yml/badge.svg)](https://github.com/leonardo-bolanos/claude-session-switcher/actions/workflows/ci.yml)
![macOS](https://img.shields.io/badge/macOS-iTerm2-black)
![Python](https://img.shields.io/badge/python-3.7%2B-blue)
![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**One panel for every Claude Code session you have open, and one keystroke to jump to the iTerm2
window that holds it.**

*[Léeme en español](README.es.md)*

Run a dozen Claude Code sessions at once — one per repo, three in the same repo — and you lose
track of which is in which tab, and which one you left half-finished. `ccl` lists them all with
what each was doing, and `Enter` takes you to its window.

![ccl in action](demo.svg)

Every row shows the branch, model, `effort` level and the last prompt you typed, so you can tell
sessions apart without opening them. The number on the left is stable: type it and you jump.

```bash
ccl        # interactive panel
ccl -w     # jump straight to the session that's been waiting on you longest
```

## Why it exists

Claude Code has no built-in way to see all your interactive sessions:

| Alternative | Why it doesn't work |
|---|---|
| `claude agents` (official panel) | Only shows **background** agents. Your terminal sessions aren't there |
| Desktop app | Only sees sessions opened from the app itself |
| Mobile dashboard | Requested in issue [#35607](https://github.com/anthropics/claude-code/issues/35607), **closed as "not planned"** |

The only source that sees all of them is `claude agents --json`, which has no interface.
`ccl` is that source, with an interface, plus the jump to the right window.

## Requirements

- **macOS** and **iTerm2** — the window jump uses AppleScript against iTerm2. In Terminal.app
  the listing works, the jump doesn't.
- **Python 3.7+** (for `datetime.fromisoformat`). No external dependencies.
- **Claude Code** v2.1.139 or newer (when `claude agents` landed).

## Install

```bash
git clone https://github.com/leonardo-bolanos/claude-session-switcher.git
cd claude-session-switcher
./install.sh
```

The installer symlinks `~/.local/bin/ccl` and prints the shell function to add to your `.zshrc`
or `.bashrc`. **It does not touch your shell config on its own.**

<details>
<summary>By hand</summary>

```bash
ln -sf "$PWD/ccl" ~/.local/bin/ccl        # make sure ~/.local/bin is on your PATH
```

</details>

## Usage

```bash
ccl              # interactive panel
ccl --list       # one-shot static listing (handy in scripts)
ccl 7            # jump straight to session number 7
ccl -w           # jump to the session that's been waiting on you longest
ccl -w2          # same, the second one in the WAITING queue
```

### Panel keys

| Key | Action |
|---|---|
| `↑` `↓` | Move selection |
| `PgUp` `PgDn` | Half a page |
| `Enter` | Open that session (focuses its iTerm window and tab) |
| `1` `2` … | Type the session number; `⌫` corrects, `Enter` confirms |
| `⌥1` … `⌥9` | Jump to the 1st, 2nd … **WAITING** session, no confirmation |
| `Ctrl-N` | Write **your own note** on this repo |
| click | Select that session |
| double click | Open it, same as `Enter` |
| wheel | Move the selection |
| any letter | **Filter** by name, repo, branch or account |
| `Ctrl-R` | Force a refresh |
| `?` | **Help** with every shortcut |
| `esc` | Clears the filter; with no filter, quits |
| `q` | Quit (unless you're filtering — then it's just text) |

The panel **refreshes itself** and **does not close when you jump**: you land back on the list
with a confirmation of where you went.

<details>
<summary><b>Jumping to whichever session is waiting on you</b> — including a global shortcut</summary>

`-w` jumps to the Nth session in the **WAITING** group, in the same order the panel paints them
(most recent activity first). It needs no TTY and no panel, so it's meant to hang off a **global
shortcut**. With Hammerspoon:

```lua
-- ⌃⌘1 … ⌃⌘9 : jump to the 1st, 2nd … waiting session, from any app
local ccl = os.getenv("HOME") .. "/.local/bin/ccl"
for n = 1, 9 do
  hs.hotkey.bind({ "ctrl", "cmd" }, tostring(n), function()
    if not hs.fs.attributes(ccl) then
      hs.alert.show("ccl not found at " .. ccl)
      return
    end
    hs.task.new(ccl, nil, { "-w" .. n }):start()
  end)
end
```

`⌃⌘` rather than plain `⌘` because `⌘1..9` already switches tabs in iTerm2, in your browser and
in half a dozen other apps; stealing it everywhere isn't worth it.

**No need to wrap it in a login shell.** A launcher starts the process with launchd's minimal
PATH (`/usr/bin:/bin:/usr/sbin:/sbin`), where `claude` is not — under npm-with-nvm it lives in
`~/.nvm/versions/node/<version>/bin`, a path that also changes when you upgrade Node. `ccl`
finds it on its own in the usual places (see `CLAUDE_EXTRA` in the script), so `hs.task` works
as-is; `zsh -ic` cost ~0.7 s per keypress.

Inside the panel, `⌥1` … `⌥9` do the same thing. `⌥1..9` always counts over the **full list,
ignoring the active filter**: the key means "get me out of here, to the one waiting on me", and
if it counted over filtered rows the same number would lead to different sessions depending on
what you'd typed.

**For `⌥` to reach the program** set **Left Option key: `Esc+`** in iTerm2 (Settings → Profiles →
Keys). Without that, `⌥1` produces a symbol (`¡`) and the panel treats it as filter text.
`⌘1..9` can't be used at all: iTerm2 keeps it for tab switching and it never reaches `ccl` — if
you'd rather have it, map `⌘N` → *Send Escape Sequence* `N` and it works the same, at the cost
of losing tab switching.

</details>

<details>
<summary><b>Your own notes on a session</b></summary>

`Ctrl-N` writes a note on the selected session — a name that means something to *you*, when
`web-app` doesn't say enough:

```
[ 1] web-app-checkout-rework   web-app   12m ago
     ✎ billing backend · main · opus-5 · "check the payment flow…"
```

`Enter` saves, an empty note deletes it, `esc` cancels. `Ctrl-N` starts from the existing text, so
correcting isn't rewriting. **You can also filter by it**, which is half the point: tag a repo
called `web-app` as "billing" and find it by that word.

Notes are stored **per directory** in `~/.claude/ccl-notes.json`, not per session. That's
deliberate: session IDs change every time you restart Claude Code, so a note tied to the session
would go missing exactly when you need it. The trade-off is that two sessions in the same repo
share a note.

Notes for directories that no longer exist are **not** pruned — an unmounted external drive or a
moved repo would silently delete something you typed by hand. The file is a few KB even when it
piles up, and it's plain JSON you can edit yourself.

</details>

<details>
<summary><b>Mouse, and how to select text to copy</b></summary>

Click selects, **double click opens**, the wheel moves the selection. Terminals don't report
double clicks — only individual clicks — so it's synthesised by timing two clicks on the same
row (400 ms).

While the panel is open **the clicks belong to it**, so dragging doesn't select text. Three ways
round it, fastest to most convenient:

| How | When |
|---|---|
| `⌥` + drag, then `⌘C` | Copy something quickly without leaving the panel |
| `CCL_MOUSE=0 ccl` | You're going to copy a lot: starts with no mouse, selection behaves normally |
| `ccl --list` | Best option: no panel, and it stays on screen. `ccl --list \| pbcopy` grabs everything |

`⌥` works because iTerm2 doesn't forward the event to the program while that modifier is held.
And mind the panel: it uses the alternate screen, so **quitting restores whatever was there and
takes the list with it** — copy before you quit. That's why `--list` is usually the better idea:
it writes to the normal screen and stays in your scrollback.

Since `--list` detects it isn't writing to a terminal, piped output carries **no colour codes**,
ready to paste.

</details>

<details>
<summary><b>Filtering</b></summary>

With many sessions, just type to narrow the list: `supp` leaves only `support-agent`. It ignores
case and accents (`migracion` finds `migración`), and multiple terms combine in any order:
`api backend` matches the same as `backend api`.

While filtering, digits are part of the text (so you can search for `v5` or `0042`); with an
empty filter they go back to being number selection.

In small windows the group header **sticks to the top** while scrolling, so you don't lose track
of whether you're in WORKING or WAITING.

</details>

<details>
<summary><b>Multiple Claude Code accounts</b></summary>

It detects `~/.claude` and any `~/.claude-<something>` with a `projects/` directory inside on
its own, so a second account's sessions show up with no configuration. When there's more than
one, a column with the account name appears.

To pin the list by hand:

```bash
export CCL_CONFIG_DIRS=~/.claude:~/.claude-work
```

</details>

<details>
<summary><b>Stable numbering and colours</b></summary>

Each session's number is stored in `~/.claude/ccl-numbers.json` and **doesn't change between
runs**, even as the list reorders itself by activity. You can memorise "7 is the backend". When
a session dies its number is freed and recycled.

| Element | Meaning |
|---|---|
| `✎` note | bold cyan — the only thing on that line you wrote yourself |
| Age | green recent → yellow → grey old |
| Model | blue Opus · green Sonnet · grey Haiku · magenta Fable |
| `effort` | yellow only on `xhigh` / `max` |
| red ⚠ | The session isn't in an iTerm window |

</details>

<details>
<summary><b>How it works</b>, and two performance traps</summary>

1. **Data source**: `claude agents --cwd ~ --json` gives PID, cwd, name and status of every live
   session.
2. **PID → iTerm window**: `ps -o tty=` gives each process's TTY, and one AppleScript call
   returns the iTerm2 window/tab pair for every TTY.
3. **Per-session context**: only the **last 64 KB** of the transcript
   (`~/.claude/projects/*/<sessionId>.jsonl`) is read, for last activity, branch, model, effort
   and last prompt. This is essential: those files get past 100 MB and reading them whole would
   make the command unusable.
4. **Refresh**: on a separate thread, every 4 s while you interact, relaxing to 20 s after two
   minutes without typing. Idle, the panel uses 0 % CPU.

Two things that cost time to find:

- The AppleScript **does not** walk session by session. Resolving the full path
  (`tty of session s of tab t of window w`) costs one IPC round trip per property and took 2.2 s
  with 44 tabs. Two bulk queries plus reconstruction in Python bring it down to ~0.5 s.
- **The transcript's `mtime` is not "last activity"**: it's written in batches and several
  sessions end up with the same stamp. You have to use the last `timestamp` field inside the file.

</details>

## Tests

```bash
python3 test_ccl.py         # pure logic — fast (~2 s)
python3 test_panel.py       # the real panel, over a pty (~1 min)
```

No dependencies, and **neither of them touches iTerm or runs `claude`**.

`test_ccl.py` covers the pure logic: width helpers, stable numbering, AppleScript output parsing,
transcript reading, grouping and ordering, filtering, multi-account, table formatting, the help
screen, key and mouse decoding, and error handling.

`test_panel.py` boots **the whole panel in a pty** and checks what you can only see by running
it: that arrows and wheel move the cursor where they should, that a click lands on the right row,
that a double click opens and two slow clicks don't, that help paginates, and that `--list` comes
out without colours. It's hermetic because it swaps the session list for synthetic data and
leaves the iTerm map empty: **the jump fails gracefully and steals nobody's focus**.

One test is a design guardrail: it checks that **no action hangs off a bare letter**, because any
letter starts filtering. That already bit twice (`r` made it impossible to search for "revisa").

CI runs both suites on Linux (Python 3.9/3.11/3.13) and on macOS, where it also checks the script
degrades with a clear error when Claude Code isn't installed.

<details>
<summary>Regenerating the demo</summary>

```bash
python3 make_demo.py
```

Records the real program in a pty with synthetic sessions and writes `demo.svg`. No dependencies,
no manual recording step, and it exposes none of your actual repos or prompts.

</details>

## Known limitations

- **Undocumented internal format**: `aiTitle` and `lastPrompt` come from Claude Code's
  transcript, which Anthropic doesn't document and may change in any release. They're treated as
  optional — if they vanish, the panel keeps working without that information.
- **Tab indices shift** if you close a tab in the same window between listing and choosing. The
  window is seconds wide and the worst case is focusing the neighbouring tab.
- **iTerm2 only** for the window jump. The listing works in any terminal. Terminal.app would be
  viable (it exposes `tty` over AppleScript) and so would tmux; see [TODO.md](TODO.md).
- **macOS only.** On Windows the script won't even start: the panel uses `termios`/`tty`, which
  don't exist there. Porting it is real work, not a tweak — broken down in [TODO.md](TODO.md).

## What's missing

Terminal.app, Windows, other terminals and some smaller details, with what's already been
researched about each: [TODO.md](TODO.md).

## License

MIT — see [LICENSE](LICENSE).
