# Claude usage grid: Phase 0 findings and plan

Verified on 2026-09-30. You use Claude Code **only in the desktop app's Code tab**, plus claude.ai chat.

## Your machine

| Thing | State |
|---|---|
| macOS | 26.6.2 (Tahoe), arm64, zone America/New_York (DST ends 2026-11-01) |
| Desktop app Claude Code | bundled 2.1.284; the only place you use Claude Code |
| Standalone CLI | **Installed today**: 2.1.285 at `~/.local/bin/claude`, PATH line added to `~/.zshrc`. Signed in with your subscription. Only needed for the nightly meter reading and the `claude-cli://` handler, which is now registered |
| `~/.claude/settings.json` | Created by the CLI's first run and contains only `{"theme": "dark"}`. No status line, no hooks, `cleanupPeriodDays` at default (30) |
| Session history | 2 sessions: this desktop session and the terminal probe session |
| Xcode | Installing (you). Command Line Tools present (Swift 6.3.2, macOS 26.5 SDK) |
| XcodeGen | **Installed**: 2.46.0 (Homebrew) |
| Python | `/usr/bin/python3` 3.9.6 for collectors; python.org 3.14.3 in `.venv` with `claude-agent-sdk` 0.2.162 |

## Verification results

### (a) `rate_limits` in the status line

- **Terminal: yes.** The probe recorded both windows after the first response:
  - `five_hour`: `used_percentage` 12, resets Wed Sep 30 08:30.
  - `seven_day`: `used_percentage` 5, resets **Sun Oct 4 21:00**.

  The session-start run had no `rate_limits`, as documented. Values arrived as whole numbers.
- **Desktop Code tab: probably not.** A project-local status line was in place in this desktop session for about 15 replies, and it never ran. Every probe entry came from `cli`. The docs don't mention the status line for desktop. This isn't fully conclusive, because the session may only read project settings at start. To settle it, start a new desktop Code session in `verify/statusline-probe/` and send one message.
- **VS Code panel: not applicable.** You don't use it.

### (b) Headless `rate_limit_event`

- **Yes, both windows in one event.** Output:

  ```
  {"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1790771400,"rateLimitType":"five_hour",
   "overageStatus":"rejected","overageDisabledReason":"org_level_disabled","isUsingOverage":false,
   "unifiedWindows":{"five_hour":{"utilization":0.13,"resetsAt":1790771400},"seven_day":{"utilization":0.05,"resetsAt":1791162000}}}, ...}
  ```

- **Scale confirmed.** `utilization` is a 0–1 fraction; ×100 matches the status line (13 vs 12 after one more message, 5 vs 5). `resetsAt` matches `resets_at` exactly.
- **Caveat: undocumented field.** Both windows come only from **`unifiedWindows`**, which the SDK doesn't model (it would land in `RateLimitInfo.raw`). The documented top-level `utilization` was absent. The parser will:
  1. Read `unifiedWindows` first.
  2. Fall back to the top-level `rateLimitType` + `utilization`.
  3. Otherwise log "no utilization" and never guess.
- **Cost and hygiene.**
  - About $0.0007 (client-side estimate) and 2 seconds.
  - `--no-session-persistence` works: the run isn't in `list_sessions()`.
  - It works in a clean `env -i` environment, as launchd will run it.

### (c) `list_sessions()`

- **It works**, and desktop sessions are included.
- **Titles only.** It reads only `custom_title` and never `summary` or `first_prompt`, which can contain prompt text.
- **Backfill limits.** There are no per-message timestamps, so the backfill credits each session's first and last day only; hooks record exact days from now on.
- **Untitled sessions.** The terminal probe session has no title yet, so it shows as "Untitled session · claude-usage-grid".

### (d) Build

- **Tooling.** XcodeGen is installed. `make app` will:
  1. Generate the project.
  2. Run `xcodebuild -allowProvisioningUpdates DEVELOPMENT_TEAM=<id>`.
  3. Copy the app to `/Applications`.
  4. Relaunch it.
- **Steps for you.**
  1. Finish installing Xcode.
  2. Run `sudo xcode-select -s /Applications/Xcode.app` and `sudo xcodebuild -license accept`.
  3. Add your Apple ID in Xcode → Settings → Accounts.
  4. Possibly one GUI build to create the signing certificate.
  5. Click **Always Allow** on the keychain prompt.
  6. Add the widget to the desktop.
  7. Approve the login item if macOS asks.

## What desktop-only use changes

1. **The meter is the main source of plan usage.** The status line is probably desktop-silent, so most readings come from the scheduled meter. The status-line collector is still installed; it's free and covers any terminal use.
2. **Weekly reset vs. 11:55 PM (decision needed).** Your weekly window resets Sunday 21:00, before 23:55. With count-from-zero, one reading at 23:55 would credit Sunday with only its post-reset usage. Everything from Saturday 23:55 to Sunday 21:00 would be lost.
   - **Recommendation:** still **one run per day**, but on the day the weekly window resets, take it ~5 minutes *before* `resets_at` instead of at 23:55. The post-reset evening then lands on Monday's reading.
   - **How:** launchd wakes the script hourly at :55, which is cheap and makes no `claude` call. The script runs the meter only for today's chosen slot, guarded to once per day. The slot follows `resets_at` automatically, including after DST, when it becomes 20:00 EST if Anthropic keeps it fixed in UTC.
3. **Peak 5-hour % is mostly a single sample.** With only one reading a day it's the value at reading time, not a true peak. The tooltip will say "5h at last reading" unless several readings exist that day.
4. **Session counts are unaffected.** Hooks run in desktop (documented; confirmed live in Phase 1), and desktop sessions are in `list_sessions()`.
5. **Resume: tested in Phase 3, so the desktop gets "Open Claude".** Desktop resume via `claude://code/new?folder=…&q=%2Fresume%20<id>` doesn't work. The desktop app turns a link's leading `/` into a full-width `／`, so slash commands from links never run, and there's no documented route to an existing Code session.
   - Desktop sessions get **Open Claude**, which brings the app forward so you can find the session in its sidebar by title.
   - Every session keeps **Resume in Terminal** (`claude-cli://open?cwd=…&q=%2Fresume%20<id>`, from your spec; that handler is registered).
   - Chats open with `claude://claude.ai/chat/<uuid>` (documented), with https as a fallback.
   - The VS Code link is dropped.

## Decisions I made (tell me if you disagree)

1. **Reset = count from zero.** When `used_percentage` drops, or `resets_at` moves by more than an hour, the window restarted. That interval's usage is the new reading's value, credited to the later reading's day.
2. **Status line logging rule.** Log immediately when a window's value or `resets_at` changes; otherwise write at most one heartbeat per minute. All errors are swallowed and the status text is always printed.
3. **Meter guard.** At most one automatic run per local day, at the slot from point 2 above. It's never retried automatically after a failure.
4. **Collectors on `/usr/bin/python3`**, stdlib only. Only the session backfill uses `.venv`.
5. **Aggregator in Python** (pytest); Swift only renders.
6. **Data in `~/.claude-usage-grid/`**, with installed copies of the collector scripts.
7. **Hooks record the surface.** They log `CLAUDE_CODE_ENTRYPOINT` (e.g. `claude-desktop`), a label, never text.
8. **Merge, don't overwrite.** Phase 1 merges into your existing `settings.json`, keeping `"theme": "dark"`, and shows the diff first.
9. **Small drops are noise, not resets (Phase 2).** Only a drop of at least `reset_drop_threshold_pp` (3) counts as a manual reset. The meter (e.g. 13.0 from 0.13) and the status line (e.g. 12) round differently, and a 1-point dip must not re-count the whole value. A high-water mark keeps the same points from being counted twice. Cost: a genuine manual reset from under 3% is missed, undercounting by at most 3 points.
10. **Backfill days only before the hooks start.** `list_sessions()` gives only start and last-change times, and a transcript can change without new activity. So those times count only for moments before the first hook event; after that, hooks and status-line readings decide which days a session was active.
11. **The first tracked day is partial.** The first-ever reading is only a baseline, so usage before it is unknown. Days before it get `usage_known: false`, which lets the UI say "not tracked yet" instead of "0%".
12. **Tall widgets stack bands (Phase 3).** Layout picks the most weeks that fit with cells of at least 14 pt, then the biggest cells that still show them. Medium shows one band of about 17 weeks. Large stacks two bands (about 34 weeks), and extra large shows all 53 weeks in two bands. Each band is GitHub-style, older on top, with today's column at the right edge.
13. **Signing needs no provisioning profile.** With the free Personal Team, Xcode signs with your Apple Development certificate and embeds no profile, because a Team-ID-prefixed App Group and the sandbox aren't restricted entitlements on macOS. So nothing expires after 7 days; only the certificate does, yearly, and `make app` renews it.
14. **The widget reloads only when the grid changes.** The app checks the logs' modification times every 15 s and re-runs the aggregator on a change or at midnight. It rewrites the App Group snapshot and calls `reloadAllTimelines()` only if the grid or header differ, which keeps well under WidgetKit's daily reload budget.
15. **Each day is a battery (your redesign after Phase 3).** The square is split into 3 full-width sections by two 1 pt gaps that show the background, and it fills bottom-up. Filled sections take the day's session-level orange: level 1 `#FDE5D2`, level 2 `#FAB27E`, level 3 `#F07A2A`, level 4 `#CC5500`, from fewer to more sessions. Unfilled sections are `#2e3037`. With f = the day's usage ÷ (100% ÷ 7): f = 0 is an empty battery, f ≤ ⅓ fills 1 section, f ≤ ⅔ fills 2, and more fills 3. A day before the first reading ever recorded looks exactly like an empty battery (your call); tooltips and the day view still say "no data yet". Cells are 4 pt apart. `section_thresholds` in `aggregator-config.json` sets the section count, and the snapshot carries it as `section_count`. Only cell sizes whose sections land on whole pixels are used (14, 15.5, 17 … pt), so the dividers stay crisp. When macOS drains the widget's color, filled sections are drawn brighter than unfilled ones, and brighter with more sessions.
16. **Update Now.** The grid window's button (also ⌘U in the menu, and `claudeusagegrid://update`) runs `meter.py --now`, one tiny Haiku call, then the session backfill, then rebuilds the grid and widget. Manual readings don't use up the day's automatic run; the once-a-day limit only applies to automatic runs.
17. **Our own widget padding.** macOS's default widget margins are 18 pt a side: a 344×164 medium widget leaves 308×128, too short for seven 14 pt rows. The widget turns them off and uses 12 pt, leaving 320×140: one band of 16 weeks at 14 pt with 4 pt gaps. The widget logs its real size (`/usr/bin/log show --info --predicate 'subsystem == "com.petesmacintosh.ClaudeUsageGrid"'`).

## Architecture

```
Desktop Code tab / CLI                          launchd (hourly :55 wake-up; one meter run per day)
 ├─ hooks      → hook.py ───────┐                 └─ meter.py → claude -p --model haiku (tagged, no tools)
 └─ statusLine → statusline.py ─┤  (CLI only)                       │
                                ▼                                   ▼
             ~/.claude-usage-grid/  activity.jsonl  readings.jsonl ◄┘  sessions.json (backfill.py, SDK)
                                                                       chats.json (export import)
                                ▼
      Menu bar app (not sandboxed) ── runs aggregate.py ──► snapshot.json + details.json
                                ▼ writes
      App Group <TEAMID>.claudeusagegrid/snapshot.json ──► Widget (sandboxed, read-only)
                                   Link claudeusagegrid://day/YYYY-MM-DD ──► app day view
```

**Signing on a free Personal Team.**
- **App Group.** Use a Team-ID-prefixed macOS app group (`<TEAMID>.claudeusagegrid`). macOS authorizes it by the signing team, so no portal registration is needed.
- **Widget.** Sandboxed, with the group entitlement; it only reads.
- **App.** Not sandboxed, so it can read `~/.claude-usage-grid`, and it's the only writer.
- **Unverified.** Whether the 7-day free-profile expiry matters. If it does, `make app` re-signs.

## Phases

1. **Collectors.**
   - `hook.py`: SessionStart + UserPromptSubmit, `async: true`, prints nothing, skips when `CLAUDE_USAGE_GRID_METER=1`.
   - `statusline.py`: minimal "5h N% · wk N%".
   - `meter.py` plus its LaunchAgent, with the reset-aware slot.
   - `backfill.py`.
   - `install.py`: backup, diff, wait for your OK, merge.

   Fixture tests, including the real `unifiedWindows` event above.
2. **Aggregator and tests.** Resets (weekly mid-day, manual drop), missing windows, midnight and DST (2026-11-01), multi-day sessions, empty history, quartile vs. fixed levels, "usage without a session = 1".
3. **App and widget.** Menu bar app, grid window with tooltips, day view with desktop Resume, status panel. Widget in medium, large, and extra large; always dark; rendering-mode aware; each day a `Link`.
4. **Chat import.** Inspect a real export first. Keep uuid, title, and message days. Links: `claude://claude.ai/chat/<uuid>` (desktop) with `https://claude.ai/chat/<uuid>` as a fallback; one confirmed with a real chat.
5. **Polish.** Launch at login, README, and an uninstall script that restores `settings.json` to `{"theme": "dark"}` and removes the LaunchAgent (asking before deleting data).

## `cleanupPeriodDays`

Worth raising, to around 365, if you want Resume to work for older days on the grid. At the default of 30, older sessions are listed without Resume. Transcripts stay on your disk only, typically well under 1 GB a year. I won't change it.
