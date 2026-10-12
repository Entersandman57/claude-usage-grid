# Claude usage grid: Phase 0 findings and plan

Verified on 2026-09-30. You use Claude Code **only in the desktop app's Code tab**, plus claude.ai chat.

## Your machine

| Thing | State |
|---|---|
| macOS | 26.6.2 (Tahoe), arm64, zone America/New_York (DST ends 2026-11-01) |
| Desktop app Claude Code | bundled 2.1.284; the only place you use Claude Code |
| Standalone CLI | **Installed today**: 2.1.285 at `~/.local/bin/claude`, PATH line added to `~/.zshrc`. Signed in with your subscription. Only needed for the meter readings and the `claude-cli://` handler, which is now registered |
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
   - Every session keeps **Resume in Terminal** (`claude-cli://open?cwd=…&q=%2Fresume%20<id>`, from your spec). Confirmed working on Sep 30 with CLI 2.1.285: unlike the desktop app, the terminal CLI runs the pre-filled `/resume` when you press Enter.
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
18. **Chat import (Phase 4).** `import_chats.py` reads `conversations.json` from the export ZIP (any folder depth), an unzipped folder, or the file itself. It keeps uuid, title (`name`) and the local days of each message's `created_at`. Parsing is defensive because the schema isn't documented: alternative keys are accepted (`id`, `title`, `messages`, `create_time`, epoch numbers), conversations without message times fall back to the conversation's own times, and anything unusable is skipped and counted in the printed summary. "Imported through" is the later of the last message day and the export's date. Re-imports merge, keeping chats deleted on claude.ai. The app copies the export into `~/.claude-usage-grid/imports/`, imports, and deletes the copy, so full chat text never stays on disk. A menu bar app has no File menu, so import is drag-and-drop on the grid window plus an Import button and menu item.
19. **Levels never collapse (your call, Phase 4).** With your real history (31 of 40 session days had 1 session), plain quartiles were 1, 1, 1: a 2-session day was the same level 4 as a 10-session day. Each threshold is now at least one session above the previous one (giving 1, 2, 3 today). Days before tracking started stay empty batteries even when they had chats (also your call); those chats show in tooltips and the day view.
20. **Launch at login and uninstall (Phase 5).** Launch at login uses `SMAppService.mainApp`, which works with the free Personal Team. It's turned on the first time the app runs, and the menu's toggle decides after that. A login launch opens no window; opening the app by hand shows the grid. `uninstall.py` mirrors the installer: `plan` writes nothing. `apply` removes only what the installer added to `settings.json`, putting back a wrapped status line and keeping later changes, then checks the result against the pristine backup. It also removes the LaunchAgent, the login item (via the app's `--login-item off`), the app, the widget and the App Group folder, and keeps `~/.claude-usage-grid` unless you pass `--delete-data`. `--exact` restores the pre-install `settings.json` byte-for-byte. The CLI and the `~/.zshrc` PATH line are left alone.
21. **Chat import reminder (Oct 10).** Chats only reach the grid through the export, so the aggregator adds `chats: {imported_through, days_since, remind}` to the snapshot. `remind` is set once the import is more than `chat_reminder_days` (7) old, or if there has never been an import. The widget shows an orange chat bubble in the grid's empty top-left corner (no space taken from the days); the grid window shows a banner and the menu an Import item. The Oct 10 export held only 43 chats (Sep 10 onward), versus 105 in September; the merge kept the 84 older ones.
22. **Orange from the peak 5-hour % (your call, Oct 11).** `level_source: "five_hour"` (the default) colors each day by its highest 5-hour % in fixed quarters of the limit (`five_hour_level_thresholds` [25, 50, 75]); a day with usage but no 5-hour reading is level 1. Session counts no longer affect the color but still show in tooltips, the day view and the header. `"sessions"` brings back the session quartiles. Caveat, shown with your data: with one automatic reading a night, the peak is often the 11:55 PM value after the window reset (Oct 8: 12 points used, peak 2%).
23. **Meter every 3 hours (your call, Oct 11; replaces the once-a-day guard in point 3).** Slots are every `meter_interval_hours` (3, in `~/.claude-usage-grid/config.json`) counting back from 23:55: 02:55 … 20:55, 23:55, plus the pre-reset slot on the weekly reset day. At most one automatic call per slot (`last_auto_slot` in `state/meter.json`; state from the old meter counts its last automatic run). A slot missed while asleep runs on wake until the next slot or midnight; failures still aren't retried. The LaunchAgent is unchanged (hourly at :55). About 8 calls a day, ~$0.006. Side effect: an idle-time call starts a 5-hour window, so windows can start up to 3 hours before you do. A refused call whose rate-limit event names the 5-hour window but carries no utilization is recorded as that window at 100% (untested: no lockout yet).
24. **Battery from sessions, afterburner glow (your call, Oct 11).** `section_source: "sessions"` (default) fills sections by the day's session count (`session_section_thresholds` [1, 4]: 1 → 1, 2–4 → 2, 5+ → 3); `"usage"` brings back the weekly share. "Sessions" are Claude Code sessions plus claude.ai chats, the same count as everywhere else. Days before usage tracking now fill too, with the lightest orange. Afterburner: the day's 5-hour readings are grouped into windows by `resets_at` (within the 1-hour tolerance; readings without one are left out), and a day glows if a window peaked at ≥ `afterburner_maxed_pct` (100) and another window that day went over `afterburner_other_pct` (10). The glow is a pale yellow rim plus an orange shadow, drawn on a flattened cell so it stays outside the battery. Snapshot version 3 adds `battery`, `afterburner` and a per-day `afterburner`; details add `five_hour_windows`. Your closest day so far: Oct 11, windows at 98%, 1% and 8%.
25. **Second afterburner rule (your call, Oct 11).** A day also glows if a window peaked over `afterburner_high_pct` (80) and a later window that day (by `resets_at`) peaked over `afterburner_next_pct` (21); both comparisons are strict. Any later window counts, not only the very next: on Oct 11 a 1% window (started by an Update Now at 3:20 PM) sat between the 98% and 90% windows, and meter calls can start such near-empty windows. Both rules are OR'd. The snapshot's `afterburner` gains `high_pct` and `next_pct` (the app falls back to 80/21 without them).
26. **Chats and usage from the Claude app's local data (your call, Oct 12; you relaxed the local-storage rule for this).** `app_scan.py` (venv Python 3.14 for zstd) runs every 10 minutes from the app. It clones `Cache/Cache_Data` and `plan-usage-history.json` to a temp dir (APFS clone) and deletes it after. From the cache it reads only entries whose key is a `chat_conversations_v2` list or a `chat_conversations/<id>` fetch: chat ID, `name`, the local days of `created_at` and `latest_assistant_output_at` (else `updated_at`), and message `created_at` days. `summary` and message text are dropped. Results merge into `app-chats.json` (IDs dedupe, days accumulate). The aggregator merges it with the export; for chats the export holds, only scanned days after `imported_through` are added. The chat reminder now uses the later of the export date and the last scan that found chats. Usage-history samples (5-hour `fh`, weekly `sd`, no reset times) are appended once each to `readings.jsonl` as source `app_history`; that file stopped being written on Oct 10, so the meter stays. First real scan: 84 chats; Oct 11 went from 1 to 17 sessions; tracking now starts Sep 10. A scan takes about 10 s, mostly cloning ~26k cache files.

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
