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
    var chats: ChatImportStatus?
    var header: Header
    var levels: Levels
    var days: [GridDay]

    /// Battery sections per cell (section_thresholds + 1 in the aggregator config).
    var sectionsPerCell: Int { max(1, sectionCount ?? 3) }
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
    var level: Int         // session level 1-4 (0: no sessions)
    var usageKnown: Bool   // false: before tracking started (no data)
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
    var sessions: Int
    var sessionsCode: Int
    var sessionsChat: Int
    var inferredSession: Bool
    var level: Int
    var codeSessions: [CodeSession]
    var chats: [Chat]
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
