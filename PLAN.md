# Claude usage grid: Phase 0 findings and plan

Verified on 2026-09-30.

## Your machine, as found

| Thing | Expected | Found |
|---|---|---|
| macOS | — | 26.6.2 (Tahoe), arm64, zone America/New_York (DST ends 2026-11-01) |
| Claude Code CLI in terminal | installed | **Not installed.** No `claude` on PATH, `~/.local/bin`, Homebrew or npm |
| Claude Code in VS Code | extension installed | VS Code is in `~/Applications`, but **the Claude Code extension is not installed** (Copilot and Codex are) |
| Claude Code in desktop app | — | Bundled 2.1.284 in `~/Library/Application Support/Claude/claude-code/`; this session runs on it |
| `~/.claude/settings.json` | may exist | **Does not exist**: no status line, no hooks, `cleanupPeriodDays` at default (30) |
| Session history | ~30 days | **1 session** (this one); `~/.claude` was created today |
| Xcode | installed, Personal Team | **Not installed.** Only Command Line Tools (Swift 6.3.2, macOS 26.5 SDK). `xcodebuild` needs full Xcode |
| Python | 3 | python.org 3.14.3 (~20 ms startup), `/usr/bin/python3` 3.9.6 (~28 ms) |
| Homebrew / XcodeGen | — | brew yes; xcodegen 2.46.0 available, not installed |

## Verification results

### (a) Does `rate_limits` reach a status line? Partly verified

- **Docs confirm the fields.** `rate_limits.five_hour` and `rate_limits.seven_day` each carry `used_percentage` (0–100) and `resets_at` (epoch seconds). They appear only for Pro/Max, only after the first API response, and each window can be absent. A window is dropped once its `resets_at` passes.
- **When it runs.** The status line runs at session start and after each assistant message. It also runs when a window reaches `resets_at`. It's debounced at 300 ms, and an in-flight script is cancelled when a new update arrives. It needs workspace trust.
- **Terminal: not testable yet.** There's no standalone CLI, and the bundled one isn't signed in.
- **VS Code panel: not testable.** The extension isn't installed, and the docs never say the graphical panel runs `statusLine`. I expect it doesn't. Its "Use Terminal" mode runs the real CLI, which should.
- **Desktop Code tab: unknown.** The docs say desktop shares `settings.json` and runs hooks, but they don't mention the status line.
- **Probe ready.** `verify/statusline-probe/` is a folder whose project settings install the status line probe. Open one session in it per surface and send "hi". `verify/out/statusline-probe.jsonl` then records which surface ran it (via `CLAUDE_CODE_ENTRYPOINT`) and what `rate_limits` held.

### (b) Does a tiny `claude -p` run emit `rate_limit_event` for both windows? Blocked: not signed in

- **The command works.** `--model haiku --tools "" --strict-mcp-config --system-prompt "…" --no-session-persistence --output-format stream-json --verbose --max-turns 1` gave a session on `claude-haiku-4-5` with no tools and no MCP servers. I ran it in a clean `env -i` environment, as launchd would.
- **It stopped at sign-in.** It returned `Not logged in · Please run /login` at $0 cost. The desktop app signs in its own sessions, and I won't borrow that.
- **The event is documented after all.** The Python Agent SDK publicly documents `RateLimitEvent` / `RateLimitInfo` with `utilization` as a **0.0–1.0 fraction**, `rate_limit_type` ∈ `five_hour | seven_day | seven_day_opus | seven_day_sonnet | overage`, and `resets_at`.
- **Risks.**
  - Each event covers **one window**.
  - The SDK says it is emitted "when rate limit status changes". A fresh process might emit only one window, or none.
  - `utilization` is optional.
- **Probe ready.** `verify/meter_probe.sh` makes the one call and prints only the rate-limit events and result metadata.
- **Alternatives if `seven_day` utilization is missing**, in order:
  1. **Nightly status-line reading.** Start an interactive `claude` in a pseudo-terminal from launchd, with a `--settings` status line that logs `rate_limits` (a documented field). Send the one-word prompt, then exit. It costs the same, but it's a more fragile TUI automation, and the meter folder needs trust accepted once.
  2. **No nightly meter.** Rely on status-line readings only. Days with only chat or desktop use then land on the next Claude Code day.

  Using the SDK's `query()` instead doesn't help: it parses the same event.

### (c) Does `list_sessions()` work? Yes

- **It works.** `claude-agent-sdk` 0.2.162 in `.venv` (Python 3.14). `list_sessions()` returned this session in about 1 ms, with `session_id, summary, last_modified, file_size, custom_title, first_prompt, git_branch, cwd, tag, created_at`.
- **Desktop sessions are included**, since they live in `~/.claude/projects` too.
- **Privacy catch.** `summary` falls back to *prompt text* (docs: "custom title, most recent prompt, auto-generated summary, or first prompt"). The collector will read **only** `custom_title` (your title or the AI-generated one) and never touch `summary` or `first_prompt`. A session with no title shows as "Untitled session · <folder>".
- **No timestamps per message.** `get_session_messages()` returns raw API message dicts without timestamps. So the backfill knows only each session's first day (`created_at`) and last day (`last_modified`). The days in between aren't knowable, so they aren't counted. The hooks record exact days from install onward.
- **Limited history.** Backfill today covers 1 session, because that's all the history there is.

### (d) Building without the Xcode GUI

The project uses **XcodeGen**. `project.yml` in git generates the `.xcodeproj` (gitignored), and `xcodebuild` builds and signs it. One `make app` target will:
1. Run the generator.
2. Build Release with `-allowProvisioningUpdates DEVELOPMENT_TEAM=<id>`.
3. Copy the app to `/Applications`.
4. Relaunch it.

Steps that need you or the GUI:
1. Install Xcode from the App Store.
2. Run `sudo xcode-select -s /Applications/Xcode.app` and `sudo xcodebuild -license accept`. Both need your password.
3. Xcode → Settings → Accounts → add your Apple ID. This creates the Personal Team.
4. Possibly once: open the project, pick the team under Signing & Capabilities, and build. This is only needed if the command-line build can't create the certificate.
5. Click **Always Allow** on the keychain prompt "codesign wants to access key".
6. Add the widget: right-click the desktop → Edit Widgets.
7. Approve the login item if macOS asks.

## Decisions I made (tell me if you disagree)

1. **Reset = count from zero.** When `used_percentage` drops, or `resets_at` moves by more than an hour, the window restarted. Usage for that interval is the new reading's value, credited to the later reading's day. The more conservative option is to count 0 for that interval.
2. **Status line logging rule.** It appends a reading immediately when either window's value or `resets_at` changes. Otherwise it writes at most one heartbeat per minute, which powers "readings are arriving". State lives in a small file with an atomic rename. Every error is swallowed, and the status line text is always printed.
3. **"Once a day" = once per night slot.** The meter job runs at most once per 23:55 slot. A wake-up catch-up counts as the missed night's run, so it can't also block tonight's run. It's never retried automatically after a failure.
4. **Collectors run on `/usr/bin/python3`** (stdlib only, 3.9-compatible). That path survives python.org upgrades, so a Python update can't break your status line. Only the session backfill uses `.venv` (it needs the SDK).
5. **Aggregator in Python, UI in Swift.** The app runs `aggregate.py` and renders its JSON. This keeps the tested logic in the language you know, and Phase 2 needs no Xcode.
6. **Data lives in `~/.claude-usage-grid/`**: logs, state, and a copy of the collector scripts that `settings.json` points at. Moving the repo then can't break Claude Code.
7. **The hook records the surface.** It logs `CLAUDE_CODE_ENTRYPOINT` (`cli` / `claude-vscode` / `claude-desktop`) with each event. That's a label, not text, and the day view can show where each session ran.

## Architecture

```
Claude Code (terminal/VS Code/desktop)          launchd 23:55
 ├─ statusLine → statusline.py ─┐                 └─ meter.py → claude -p (tagged)
 └─ hooks      → hook.py ───────┤                                   │
                                ▼                                   ▼
                 ~/.claude-usage-grid/  readings.jsonl  activity.jsonl  meter → readings.jsonl
                                        sessions.json (backfill.py via SDK)  chats.json (import)
                                ▼
      Menu bar app (not sandboxed) ── runs aggregate.py ──► snapshot.json + details.json
                                ▼ writes
      App Group container <TEAMID>.claudeusagegrid/snapshot.json ──► Widget (sandboxed)
                                                   Link claudeusagegrid://day/YYYY-MM-DD ──► app day view
```

**Signing and App Group on a free Personal Team.**
- macOS supports *Team-ID-prefixed* app groups (`<TEAMID>.claudeusagegrid`). The system authorizes them by the code signature's team, so they need no registration in the developer portal. iOS-style `group.*` IDs need a provisioning profile that free accounts can't get.
- The widget extension must be sandboxed; it gets the group entitlement and only reads.
- The host app isn't sandboxed, so it can read `~/.claude-usage-grid`. It also carries the group entitlement and is the only writer.
- Unverified: free-team profiles expire after 7 days. These entitlements shouldn't need a profile on macOS, but if the widget ever stops loading, `make app` re-signs it.

## Phases

1. **Collectors.**
   - `statusline.py` (minimal "5h N% · wk N%", since you have no status line).
   - `hook.py` (SessionStart + UserPromptSubmit, `async: true`, prints nothing, skips when `CLAUDE_USAGE_GRID_METER=1`).
   - `meter.py` plus its LaunchAgent plist.
   - `backfill.py`.
   - `install.py`: backs up and diffs `~/.claude/settings.json` (today it doesn't exist, so the diff creates it) and waits for your OK.
   - Fixture tests. The `rate_limit_event` parser gets finalized from the real probe output.
2. **Aggregator and tests.** `aggregate.py` plus `config.json` (bar thresholds, fixed buckets, the 14-day switch). pytest cases:
   - weekly reset mid-day and a manual drop
   - missing windows
   - midnight and DST crossings (including 2026-11-01 in New York)
   - multi-day sessions
   - empty history
   - quartile vs. fixed-bucket levels
   - "usage without a session = 1"
3. **App and widget.** XcodeGen targets:
   - Menu bar app: `MenuBarExtra`, `LSUIElement`, a file watcher that runs the aggregator, then `WidgetCenter.reloadAllTimelines()`. Also a grid window with hover tooltips, a day view with Resume / VS Code / chat links, and a status panel.
   - Widget: medium, large, and extra large; always dark. It supports `widgetRenderingMode`: in accented or vibrant mode, bars and levels are drawn by brightness and opacity instead of hue. Each day is a `Link`.
4. **Chat import.** First look at your real export. Then drag and drop or File → Import. Keep only uuid, title, and message days. Show "chats imported through <date>". Confirm `https://claude.ai/chat/<uuid>` with one real chat.
5. **Polish.** `SMAppService` launch at login, README (setup, formulas, limitations), and `uninstall.py`. The uninstall script restores or removes `settings.json` exactly as it was, and removes the LaunchAgent and data (asking before deleting data).

## Is raising `cleanupPeriodDays` worth it?

Probably, if you want Resume to work across the whole grid. The default of 30 deletes transcripts older than 30 days, so older days would list sessions without Resume. Raising it to 365 keeps transcripts (full chat text, on your disk only), typically well under 1 GB for one person. I won't change it; it's one line you can add yourself.

## What I need from you to finish Phase 0

1. **Install the standalone Claude Code CLI.** I can run the official installer (`curl -fsSL https://claude.ai/install.sh | bash`, which puts `claude` in `~/.local/bin`). Then you run `claude` once and complete `/login` in the browser. This unblocks (a)-terminal, (b), and the `claude-cli://` Resume handler, which registers on your first interactive prompt.
2. **Tell me which surfaces you actually use.** The evidence says the desktop app's Code tab. If you want VS Code covered, install the Claude Code extension.
3. **Install Xcode** (App Store) and add your Apple ID in Xcode. This is needed by Phase 3, not before.
