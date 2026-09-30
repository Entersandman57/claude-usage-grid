import Foundation

/// Dates and numbers as the UI shows them. Grid dates are local "YYYY-MM-DD" strings.
enum Format {
    static let calendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .current
        return calendar
    }()

    static func date(_ iso: String) -> Date? {
        let parts = iso.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        return calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2], hour: 12))
    }

    static func iso(_ date: Date) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    static func monthShort(_ iso: String) -> String {
        date(iso)?.formatted(.dateTime.month(.abbreviated)) ?? ""
    }

    static func dayOfMonth(_ iso: String) -> Int {
        date(iso).map { calendar.component(.day, from: $0) } ?? 0
    }

    static func longDay(_ iso: String) -> String {
        date(iso)?.formatted(.dateTime.weekday(.wide).month(.wide).day().year()) ?? iso
    }

    static func mediumDay(_ iso: String) -> String {
        date(iso)?.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day().year()) ?? iso
    }

    static func time(_ ts: Double) -> String {
        Date(timeIntervalSince1970: ts).formatted(date: .omitted, time: .shortened)
    }

    /// "Today 11:06 AM", "Yesterday 11:55 PM" or "Sep 28, 11:55 PM".
    static func moment(_ ts: Double, now: Date = Date()) -> String {
        let date = Date(timeIntervalSince1970: ts)
        if calendar.isDate(date, inSameDayAs: now) { return "Today " + time(ts) }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now),
           calendar.isDate(date, inSameDayAs: yesterday) { return "Yesterday " + time(ts) }
        return date.formatted(.dateTime.month(.abbreviated).day()) + ", " + time(ts)
    }

    static func percent(_ value: Double) -> String {
        value >= 10 || value == value.rounded() ? String(format: "%.0f%%", value) : String(format: "%.1f%%", value)
    }

    static func sessions(_ n: Int) -> String { n == 1 ? "1 session" : "\(n) sessions" }

    static func surface(_ entrypoint: String) -> String {
        switch entrypoint {
        case "claude-desktop": return "Desktop"
        case "cli": return "Terminal"
        case "claude-vscode": return "VS Code"
        default: return entrypoint
        }
    }
}
