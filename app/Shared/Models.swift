import Foundation

// Swift mirrors of aggregate.py's output. Decoded with .convertFromSnakeCase,
// so "usage_pp" in the JSON becomes `usagePp` here.

/// out/snapshot.json: everything the widget draws.
struct Snapshot: Codable, Equatable {
    var version: Int
    var generatedAt: Double
    var today: String
    var usageTrackedSince: String?
    var sectionCount: Int?
    var battery: BatteryRule?
    var afterburner: AfterburnerRule?
    var chats: ChatImportStatus?
    var header: Header
    var levels: Levels
    var days: [GridDay]

    /// Battery sections per cell (the battery thresholds + 1).
    var sectionsPerCell: Int { max(1, sectionCount ?? 3) }

    /// True when the sections count sessions (the default); false: the day's share of the week.
    var batteryCountsSessions: Bool { (battery?.source ?? "sessions") == "sessions" }
}

/// What fills a cell's battery: "sessions" (counts) or "usage" (share of the week).
struct BatteryRule: Codable, Equatable {
    var source: String
    var thresholds: [Double]

    /// Session counts per filled-section count, for the legend: ["0", "1", "2–4", "5+"].
    var sessionLabels: [String] {
        let bounds = thresholds.map { Int($0.rounded(.down)) }
        var labels = ["0"]
        var low = 1
        for high in bounds {
            labels.append(high <= low ? "\(high)" : "\(low)–\(high)")
            low = high + 1
        }
        labels.append("\(low)+")
        return labels
    }
}

/// The afterburner glow, on a day whose 5-hour windows show either
/// a window at maxedPct and another above otherPct, or
/// a window above highPct and a later one above nextPct.
struct AfterburnerRule: Codable, Equatable {
    var maxedPct: Double
    var otherPct: Double
    var highPct: Double?  // nil in snapshots from before the second rule
    var nextPct: Double?

    var high: Double { highPct ?? 80 }
    var next: Double { nextPct ?? 21 }

    static let standard = AfterburnerRule(maxedPct: 100, otherPct: 10, highPct: 80, nextPct: 21)
}

/// How current the claude.ai chat import is; `remind` once it's older than
/// chat_reminder_days (or there has never been an import).
struct ChatImportStatus: Codable, Equatable {
    var importedThrough: String?
    var daysSince: Int?
    var remind: Bool

    var reminderText: String {
        guard let through = importedThrough else {
            return "No chats found yet: the Claude app's chat list hasn't been scanned. Open the Claude app, or import your data export."
        }
        let ago = daysSince.map { $0 == 1 ? " (1 day ago)" : " (\($0) days ago)" } ?? ""
        return "Chats are counted through \(Format.mediumDay(through))\(ago). Open the Claude app so its chat list refreshes, or import a newer export."
    }
}

struct Header: Codable, Equatable {
    var week: UsageWindow?
    var fiveHour: UsageWindow?
    var todayUsagePp: Double
    var todaySessions: Int
}

struct UsageWindow: Codable, Equatable {
    var usedPct: Double
    var resetsAt: Double?
    var asOf: Double
    var source: String?
}

struct Levels: Codable, Equatable {
    var mode: String
    var thresholds: [Double]
    var nonzeroDays: Int
}

struct GridDay: Codable, Equatable, Identifiable {
    var date: String
    var usagePp: Double
    var sections: Int      // filled battery sections
    var sessions: Int
    var level: Int         // orange level 1-4 (0: nothing that day)
    var usageKnown: Bool   // false: before tracking started (no usage data)
    var afterburner: Bool? = nil  // maxed out a 5-hour window and kept going in another
    var id: String { date }
}

/// out/details.json: tooltips, the day view and the status panel.
struct Details: Codable {
    var generatedAt: Double
    var today: String
    var levels: Levels
    var header: Header
    var days: [String: DayDetail]
    var status: Status
}

struct DayDetail: Codable {
    var usagePp: Double
    var shareFraction: Double
    var sections: Int
    var peakFiveHourPct: Double?
    var fiveHourSamples: Int
    var fiveHourWindows: [FiveHourWindow]?
    var afterburner: Bool?
    var sessions: Int
    var sessionsCode: Int
    var sessionsChat: Int
    var inferredSession: Bool
    var level: Int
    var codeSessions: [CodeSession]
    var chats: [Chat]
}

/// One 5-hour window read during the day, with its highest reading.
struct FiveHourWindow: Codable, Equatable {
    var resetsAt: Double
    var peakPct: Double
    var samples: Int
}

extension DayDetail {
    /// Why the day glows ("Hit 98% of a 5-hour window, then 90% of a later one"), or nil if it doesn't.
    func afterburnerText(rule: AfterburnerRule) -> String? {
        guard afterburner == true, let windows = fiveHourWindows else { return nil }
        let maxed = windows.filter { $0.peakPct >= rule.maxedPct }
        if maxed.count >= 2 { return "Maxed out two 5-hour windows" }
        if let full = maxed.first, let other = windows.filter({ $0 != full }).map(\.peakPct).max(),
           other > rule.otherPct {
            return "Maxed out a 5-hour window and used \(Format.percent(other)) of another"
        }
        let ordered = windows.sorted { $0.resetsAt < $1.resetsAt }
        for (index, window) in ordered.enumerated() where window.peakPct > rule.high {
            if let later = ordered[(index + 1)...].map(\.peakPct).max(), later > rule.next {
                return "Hit \(Format.percent(window.peakPct)) of a 5-hour window, then \(Format.percent(later)) of a later one"
            }
        }
        return "Kept going past a near-limit 5-hour window"
    }
}

struct CodeSession: Codable, Identifiable {
    var sessionId: String
    var title: String?
    var cwd: String?
    var firstTs: Double
    var lastTs: Double
    var entrypoints: [String]
    var transcriptPresent: Bool?
    var id: String { sessionId }
}

struct Chat: Codable, Identifiable {
    var uuid: String
    var title: String?
    var id: String { uuid }
}

struct Status: Codable {
    var lastReading: LastReading?
    var statuslineLastTs: Double?
    var meterLastRun: MeterRun?
    var meterLastAutoDay: String?
    var sessionsUpdatedAt: Double?
    var hooksFirstTs: Double?
    var chatsImportedThrough: String?
    var chatsImportedAt: Double?
    var appChatsScannedAt: Double?
    var appChatsCount: Int?
}

struct LastReading: Codable {
    var ts: Double
    var source: String?
}

struct MeterRun: Codable {
    var ts: Double?
    var trigger: String?
    var ok: Bool?
    var error: String?
}

enum GridJSON {
    static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}
