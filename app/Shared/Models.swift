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

/// The afterburner glow: a 5-hour window at maxedPct and another above otherPct the same day.
struct AfterburnerRule: Codable, Equatable {
    var maxedPct: Double
    var otherPct: Double

    static let standard = AfterburnerRule(maxedPct: 100, otherPct: 10)
}

/// How current the claude.ai chat import is; `remind` once it's older than
/// chat_reminder_days (or there has never been an import).
struct ChatImportStatus: Codable, Equatable {
    var importedThrough: String?
    var daysSince: Int?
    var remind: Bool

    var reminderText: String {
        guard let through = importedThrough else {
            return "No claude.ai chats imported yet, so chats aren't counted. Import your data export."
        }
        let ago = daysSince.map { $0 == 1 ? " (1 day ago)" : " (\($0) days ago)" } ?? ""
        return "Chats are imported through \(Format.mediumDay(through))\(ago). Newer chats aren't counted until you import a newer export."
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
    /// "Maxed out a 5-hour window, then used 31% of another", or nil if not an afterburner day.
    var afterburnerText: String? {
        guard afterburner == true, let windows = fiveHourWindows,
              let maxed = windows.max(by: { $0.peakPct < $1.peakPct }) else { return nil }
        let others = windows.filter { $0 != maxed }
        if others.contains(where: { $0.peakPct >= maxed.peakPct }) {
            return "Maxed out two 5-hour windows"
        }
        let other = others.map(\.peakPct).max() ?? 0
        return "Maxed out a 5-hour window, then used \(Format.percent(other)) of another"
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
