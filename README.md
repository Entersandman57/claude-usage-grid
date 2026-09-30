# Claude usage grid

A macOS desktop widget, styled like GitHub's contribution graph, that charts your daily Claude usage. A menu bar app hosts it, with a full-year grid window and a view of each day's sessions.

Setup, how each number is computed, uninstalling, and known limitations will be written up here in Phase 5. Until then, [PLAN.md](PLAN.md) has the design and every decision.

## Reading the grid

Columns are weeks (oldest on the left, this week on the right), rows run Sunday to Saturday, and future days are hidden.

**Each day is a battery.** The square is split into 3 horizontal sections that fill from the bottom. A section is ⅓ of a day's even share of your weekly limit (100% ÷ 7 ≈ 14.29% of the week).

| The day's usage, as f = usage ÷ 14.29% | The square |
|---|---|
| Before the first usage reading ever recorded | plain dark square, no dividers (no data yet) |
| f = 0 | empty battery: 3 unfilled sections |
| 0 < f ≤ ⅓ | 1 section filled |
| ⅓ < f ≤ ⅔ | 2 sections filled |
| f > ⅔ | 3 sections filled |

**The orange shows how many sessions you had** (Claude Code sessions plus claude.ai chats). Fewer sessions are a light, whitish orange; more are a deep, vivid orange. Levels are quartiles of your own days with sessions over the last year. Until you have 14 such days, fixed buckets are used: 1, 2–3, 4–6, and 7 or more sessions.

| Level | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| Filled section color | `#FDE5D2` | `#FAB27E` | `#F07A2A` | `#CC5500` |

Unfilled sections are `#2e3037`, and the thin dividers show the widget's background (`#17181c`).

**When macOS drains the widget's color** (a window in front, or a monochrome or tinted widget style), the widget keeps its meaning through brightness alone. Filled sections are clearly brighter than unfilled ones, and brighter with more sessions.

The thresholds live in `aggregator/aggregator-config.json`. To override them, copy it to `~/.claude-usage-grid/aggregator-config.json` and edit the copy. `section_thresholds` sets how many sections a day has.
