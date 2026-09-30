import Foundation
import WidgetKit

enum GridError: LocalizedError {
    case command(String)
    var errorDescription: String? {
        switch self { case let .command(message): return message }
    }
}

/// Runs the aggregator when the logs change and hands the result to the UI and the widget.
///
/// Every 15 s it compares the modification dates of the collectors' files (a
/// cheap stat, no file watching needed). On a change, or when the date rolls
/// over, it runs aggregate.py. The widget's copy in the App Group is rewritten,
/// and its timeline reloaded, only when the grid itself changed, which keeps
/// well inside WidgetKit's daily reload budget.
@MainActor
final class DataStore: ObservableObject {
    static let shared = DataStore()

    @Published private(set) var snapshot: Snapshot?
    @Published private(set) var details: Details?
    @Published private(set) var lastError: String?
    @Published private(set) var widgetUpdatedAt: Date?

    let dataDir = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".claude-usage-grid")

    private static let watchedFiles = ["readings.jsonl", "activity.jsonl", "sessions.json", "chats.json",
                                       "state/meter.json", "aggregator-config.json"]
    private var timer: Timer?
    private var seenModified: [String: Date?] = [:]
    private var seenDay = Format.iso(Date())
    private var lastBackfill = Date.distantPast
    private var isRefreshing = false
    private var refreshAgain = false

    func start() {
        _ = inputsChanged()
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    private func tick() {
        let today = Format.iso(Date())
        let newDay = today != seenDay
        seenDay = today
        if inputsChanged() || newDay { refresh() }
    }

    private func inputsChanged() -> Bool {
        var changed = false
        for name in Self.watchedFiles {
            let url = dataDir.appendingPathComponent(name)
            let modified = (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate
            if seenModified[name] != .some(modified) {
                seenModified[name] = modified
                changed = true
            }
        }
        return changed
    }

    func refresh() {
        guard !isRefreshing else { refreshAgain = true; return }
        isRefreshing = true
        let dataDir = self.dataDir
        Task.detached(priority: .utility) {
            let result = Result { try DataStore.aggregate(dataDir: dataDir) }
            await MainActor.run { self.finish(result) }
        }
    }

    private func finish(_ result: Result<(Snapshot, Details, Data), Error>) {
        isRefreshing = false
        switch result {
        case let .success((snapshot, details, data)):
            lastError = nil
            let gridChanged = !Self.sameGrid(self.snapshot, snapshot) || SnapshotStore.load() == nil
            self.snapshot = snapshot
            self.details = details
            if gridChanged { publishToWidget(data) }
            backfillIfNeeded(details)
        case let .failure(error):
            lastError = error.localizedDescription
        }
        if refreshAgain {
            refreshAgain = false
            refresh()
        }
    }

    private static func sameGrid(_ old: Snapshot?, _ new: Snapshot) -> Bool {
        guard var old else { return false }
        var new = new
        old.generatedAt = 0
        new.generatedAt = 0
        return old == new
    }

    private func publishToWidget(_ data: Data) {
        do {
            try SnapshotStore.write(data)
            widgetUpdatedAt = Date()
            WidgetCenter.shared.reloadAllTimelines()
        } catch {
            lastError = "Couldn't update the widget: \(error.localizedDescription)"
        }
    }

    /// New sessions get their titles and transcript status from the SDK backfill
    /// (at most every 10 minutes); its sessions.json change triggers a refresh.
    private func backfillIfNeeded(_ details: Details) {
        let unknown = details.days.values.contains { $0.codeSessions.contains { $0.transcriptPresent == nil } }
        guard unknown, Date().timeIntervalSince(lastBackfill) > 600 else { return }
        lastBackfill = Date()
        let dataDir = self.dataDir
        Task.detached(priority: .utility) {
            try? DataStore.run(dataDir.appendingPathComponent("venv/bin/python").path,
                               [dataDir.appendingPathComponent("bin/backfill.py").path])
        }
    }

    // MARK: - Running the Python side

    nonisolated static func run(_ executable: String, _ arguments: [String]) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        let errors = Pipe()
        process.standardError = errors
        process.standardOutput = FileHandle.nullDevice
        try process.run()
        let stderr = errors.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let lastLine = String(decoding: stderr, as: UTF8.self)
                .split(separator: "\n").last.map(String.init) ?? "exit status \(process.terminationStatus)"
            let script = URL(fileURLWithPath: arguments.first ?? executable).lastPathComponent
            throw GridError.command("\(script): \(lastLine)")
        }
    }

    nonisolated static func aggregate(dataDir: URL) throws -> (Snapshot, Details, Data) {
        let script = dataDir.appendingPathComponent("bin/aggregate.py")
        guard FileManager.default.fileExists(atPath: script.path) else {
            throw GridError.command("aggregate.py isn't installed; run `make install` in the repo.")
        }
        try run("/usr/bin/python3", [script.path])
        return try readOutputs(dataDir: dataDir)
    }

    nonisolated static func readOutputs(dataDir: URL) throws -> (Snapshot, Details, Data) {
        let out = dataDir.appendingPathComponent("out")
        let snapshotData = try Data(contentsOf: out.appendingPathComponent("snapshot.json"))
        let decoder = GridJSON.decoder()
        let snapshot = try decoder.decode(Snapshot.self, from: snapshotData)
        let details = try decoder.decode(Details.self, from: Data(contentsOf: out.appendingPathComponent("details.json")))
        return (snapshot, details, snapshotData)
    }

    /// Loads the last aggregator output without running it (used for preview rendering).
    func loadLastOutputs() {
        if let (snapshot, details, _) = try? Self.readOutputs(dataDir: dataDir) {
            self.snapshot = snapshot
            self.details = details
        }
    }

    // MARK: - Text for the menu, tooltips and status

    var summary: String {
        guard let header = snapshot?.header else { return lastError ?? "Building your grid…" }
        let week = header.week.map { Format.percent($0.usedPct) } ?? "—"
        return "This week \(week) · Today \(Format.sessions(header.todaySessions))"
    }

    func tooltip(for day: GridDay) -> String {
        var parts = [Format.mediumDay(day.date)]
        let detail = details?.days[day.date]
        parts.append(day.usageKnown
                     ? "\(Format.percent(day.usagePp)) of week (\(day.bars) of 4 bars)"
                     : "usage not tracked yet")
        if let detail, let peak = detail.peakFiveHourPct {
            parts.append("peak 5h \(Format.percent(peak))" + (detail.fiveHourSamples == 1 ? " (1 reading)" : ""))
        }
        if detail?.inferredSession == true {
            parts.append("1 session (usage, but no session recorded)")
        } else {
            let code = detail?.sessionsCode ?? 0, chats = detail?.sessionsChat ?? 0
            parts.append("\(Format.sessions(day.sessions)): \(code) Code, \(chats) chat\(chats == 1 ? "" : "s")")
        }
        return parts.joined(separator: " · ")
    }

    var statusLines: [String] {
        var lines: [String] = []
        if let status = details?.status {
            if let reading = status.lastReading {
                let source = reading.source == "statusline" ? "status line" : (reading.source ?? "?")
                lines.append("Last reading: \(Format.moment(reading.ts)) (\(source))")
            } else {
                lines.append("Last reading: none yet")
            }
            lines.append(status.statuslineLastTs.map { "Status line readings: last \(Format.moment($0))" }
                         ?? "Status line readings: none (the desktop app doesn't run a status line)")
            if let run = status.meterLastRun, let ts = run.ts {
                let result = run.ok == true ? "OK" : "failed: \(run.error ?? "unknown error")"
                lines.append("Last meter run: \(Format.moment(ts)), \(run.trigger ?? "?"), \(result)")
            } else {
                lines.append("Last meter run: none yet")
            }
            lines.append(status.chatsImportedThrough.map { "Chats imported through \(Format.mediumDay($0))" }
                         ?? "Chats: not imported yet")
        }
        if let at = widgetUpdatedAt { lines.append("Widget updated: \(Format.moment(at.timeIntervalSince1970))") }
        if let lastError { lines.append("Error: \(lastError)") }
        return lines.isEmpty ? ["Building your grid…"] : lines
    }
}
