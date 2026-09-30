import AppKit
import SwiftUI

/// One day: its numbers, Claude Code sessions (with Resume) and claude.ai chats.
struct DayView: View {
    @ObservedObject var store: DataStore
    let date: String

    var body: some View {
        ScrollView {
            DayContent(store: store, date: date)
        }
        .frame(minWidth: 560, minHeight: 440)
        .background(Palette.background)
    }
}

struct DayContent: View {
    @ObservedObject var store: DataStore
    let date: String

    private var slots: Int { store.snapshot?.slots ?? 3 }

    var body: some View {
        let detail = store.details?.days[date]
        let day = store.snapshot?.days.first { $0.date == date }
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 12) {
                if let day { DayCell(day: day, size: 34, style: .color, slots: slots) }
                Text(Format.longDay(date)).font(.title2.weight(.semibold))
            }
            stats(detail: detail, day: day)
            codeSessions(detail?.codeSessions ?? [])
            chats(detail?.chats ?? [])
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: Numbers

    private func stats(detail: DayDetail?, day: GridDay?) -> some View {
        let known = day?.usageKnown ?? false
        let usage = detail?.usagePp ?? 0
        return HStack(alignment: .top, spacing: 12) {
            StatTile(title: "Weekly limit used",
                     value: known ? Format.percent(usage) : "—",
                     note: known ? "percentage points of the week" : "not tracked yet")
            StatTile(title: "Bars",
                     value: "\(detail?.bars ?? 0) of \(slots)",
                     note: known ? "\(Int(((detail?.shareFraction ?? 0) * 100).rounded()))% of a day's share" : "")
            StatTile(title: "Peak 5-hour",
                     value: detail?.peakFiveHourPct.map(Format.percent) ?? "—",
                     note: readingsNote(detail?.fiveHourSamples ?? 0))
            StatTile(title: "Sessions",
                     value: "\(detail?.sessions ?? 0)",
                     note: detail?.inferredSession == true
                        ? "usage, but none recorded"
                        : "\(detail?.sessionsCode ?? 0) Code · \(detail?.sessionsChat ?? 0) chats")
        }
    }

    private func readingsNote(_ samples: Int) -> String {
        switch samples {
        case 0: return "no readings"
        case 1: return "from 1 reading"
        default: return "highest of \(samples) readings"
        }
    }

    // MARK: Claude Code

    private func codeSessions(_ sessions: [CodeSession]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Claude Code sessions").font(.headline)
            if sessions.isEmpty {
                Text("None recorded.").foregroundStyle(.secondary)
            }
            ForEach(sessions) { session in
                VStack(alignment: .leading, spacing: 4) {
                    Text(session.title ?? "Untitled session").font(.body.weight(.semibold))
                    if let cwd = session.cwd {
                        Text(abbreviateHome(cwd))
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                    Text(timeLine(session)).font(.caption).foregroundStyle(.secondary)
                    if session.transcriptPresent == false {
                        Text("Claude Code has deleted this transcript (cleanupPeriodDays), so it can't be resumed.")
                            .font(.caption).foregroundStyle(.secondary)
                    } else {
                        // The desktop app has no documented link to an existing session, and it
                        // defuses slash commands that arrive in a link. So desktop sessions get
                        // "Open Claude" (it's in the sidebar under this title); any session can
                        // be resumed in a terminal via the CLI's documented claude-cli:// link.
                        HStack {
                            if session.entrypoints.contains("claude-desktop") {
                                Button("Open Claude") { openClaudeApp() }
                                    .help("Find it in Claude's sidebar under this title.")
                            }
                            Button("Resume in Terminal") {
                                open(DeepLink.resumeInTerminal(sessionId: session.sessionId, cwd: session.cwd))
                            }
                        }
                        .controlSize(.small)
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Palette.emptyCell, in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private func timeLine(_ session: CodeSession) -> String {
        var line = Format.time(session.firstTs)
        if session.lastTs - session.firstTs >= 60 { line += "–" + Format.time(session.lastTs) }
        if !session.entrypoints.isEmpty { line += " · " + session.entrypoints.map(Format.surface).joined(separator: ", ") }
        return line
    }

    private func abbreviateHome(_ path: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return path.hasPrefix(home) ? "~" + path.dropFirst(home.count) : path
    }

    // MARK: claude.ai

    private func chats(_ chats: [Chat]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("claude.ai chats").font(.headline)
            if chats.isEmpty {
                Text(store.details?.status.chatsImportedThrough == nil
                     ? "No chats imported yet."
                     : "None this day.")
                    .foregroundStyle(.secondary)
            }
            ForEach(chats) { chat in
                HStack {
                    Text(chat.title ?? "Untitled chat")
                    Spacer()
                    Button("Open in Claude") { open(DeepLink.chatInDesktop(chat.uuid)) }
                    Button("Open in Browser") { open(DeepLink.chatInBrowser(chat.uuid)) }
                }
                .controlSize(.small)
                .padding(10)
                .background(Palette.emptyCell, in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private func open(_ url: URL) {
        NSWorkspace.shared.open(url)
    }

    private func openClaudeApp() {
        guard let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.anthropic.claudefordesktop")
        else { return }
        NSWorkspace.shared.openApplication(at: app, configuration: NSWorkspace.OpenConfiguration())
    }
}

struct StatTile: View {
    let title: String
    let value: String
    let note: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.title3.weight(.semibold).monospacedDigit())
            Text(note).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
        }
        .padding(10)
        .frame(maxWidth: .infinity, minHeight: 78, alignment: .topLeading)
        .background(Palette.emptyCell, in: RoundedRectangle(cornerRadius: 8))
    }
}
