import SwiftUI
import WidgetKit

/// What a click or hover on a day does.
enum GridInteraction {
    case none
    /// Widget: each day is a Link that opens the day in the app.
    case links
    /// App window: hover shows details, click opens the day.
    case interactive(hovered: Binding<String?>, open: (String) -> Void, tooltip: (GridDay) -> String)
}

/// GitHub-style grid: weeks as columns (oldest left), Sun-Sat rows, month
/// labels on top, Mon/Wed/Fri on the left. Fills whatever size it is given.
struct GridView: View {
    let days: [GridDay]
    var sectionCount = 3
    var style: CellStyle = .color
    var interaction: GridInteraction = .none
    var maxBands = 3
    /// A small chat bubble in the grid's empty top-left corner: chats need importing.
    var showsChatReminder = false

    var body: some View {
        GeometryReader { proxy in
            let weeks = Week.weeks(from: days)
            let layout = GridLayout.fit(proxy.size, availableWeeks: weeks.count, maxBands: maxBands,
                                        sectionCount: sectionCount)
            let block = layout.blockSize
            // Bands share a right edge (today's column). The block is centered on a
            // half-point boundary so the cells' 1 pt dividers stay on whole pixels.
            VStack(alignment: .trailing, spacing: GridLayout.bandSpacing) {
                ForEach(Array(layout.bands(of: weeks).enumerated()), id: \.offset) { index, band in
                    bandView(band, layout: layout, isFirst: index == 0)
                }
            }
            .frame(width: block.width, height: block.height, alignment: .topTrailing)
            .padding(.leading, Self.halfPointFloor((proxy.size.width - block.width) / 2))
            .padding(.top, Self.halfPointFloor((proxy.size.height - block.height) / 2))
            .frame(width: proxy.size.width, height: proxy.size.height, alignment: .topLeading)
        }
    }

    private static func halfPointFloor(_ value: CGFloat) -> CGFloat {
        max(0, (value * 2).rounded(.down) / 2)
    }

    private func bandView(_ weeks: [Week], layout: GridLayout, isFirst: Bool) -> some View {
        let column = layout.cell + layout.gap
        return VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 0) {
                if isFirst && showsChatReminder {
                    Image(systemName: "bubble.left.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(style.fullColor ? Palette.levels[2] : Color.white)
                        .widgetAccentable()
                        .frame(width: GridLayout.dayLabelWidth, height: GridLayout.monthLabelHeight, alignment: .topLeading)
                        .accessibilityLabel("Chats need importing")
                } else {
                    Color.clear.frame(width: GridLayout.dayLabelWidth, height: 1)
                }
                ForEach(weeks) { week in
                    Text(week.monthLabel ?? "")
                        .font(.system(size: 9))
                        .foregroundStyle(style.label)
                        .fixedSize()
                        .frame(width: column, height: GridLayout.monthLabelHeight, alignment: .topLeading)
                }
            }
            HStack(alignment: .top, spacing: 0) {
                VStack(alignment: .leading, spacing: layout.gap) {
                    ForEach(0..<7, id: \.self) { row in
                        Text([1: "Mon", 3: "Wed", 5: "Fri"][row] ?? "")
                            .font(.system(size: 9))
                            .foregroundStyle(style.label)
                            .frame(width: GridLayout.dayLabelWidth, height: layout.cell, alignment: .leading)
                    }
                }
                HStack(alignment: .top, spacing: layout.gap) {
                    ForEach(weeks) { week in
                        VStack(spacing: layout.gap) {
                            ForEach(0..<7, id: \.self) { row in
                                cellView(week.days[row], size: layout.cell)
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func cellView(_ day: GridDay?, size: CGFloat) -> some View {
        if let day {
            let cell = DayCell(day: day, size: size, style: style, sectionCount: sectionCount)
            switch interaction {
            case .none:
                cell
            case .links:
                Link(destination: DeepLink.day(day.date)) { cell }
            case let .interactive(hovered, open, tooltip):
                cell
                    .overlay {
                        if hovered.wrappedValue == day.date {
                            RoundedRectangle(cornerRadius: size * 0.2).strokeBorder(.white.opacity(0.9), lineWidth: 1.5)
                        }
                    }
                    .contentShape(Rectangle())
                    .onHover { inside in
                        if inside { hovered.wrappedValue = day.date }
                        else if hovered.wrappedValue == day.date { hovered.wrappedValue = nil }
                    }
                    .onTapGesture { open(day.date) }
                    .help(tooltip(day))
            }
        } else {
            Color.clear.frame(width: size, height: size)  // a future day: hidden
        }
    }
}

/// "This week 8% · Today 2 sessions · 5h 6%"
struct SummaryLine: View {
    /// Fixed so whatever sits below starts on a whole point.
    static let height: CGFloat = 16

    let snapshot: Snapshot
    var style: CellStyle = .color
    var now = Date()

    var body: some View {
        HStack(spacing: 12) {
            Text("This week \(windowText(snapshot.header.week))")
            Text("Today \(Format.sessions(snapshot.header.todaySessions))")
            Spacer(minLength: 4)
            Text("5h \(windowText(snapshot.header.fiveHour))")
        }
        .font(.system(size: 11, weight: .semibold))
        .foregroundStyle(style.text)
        .lineLimit(1)
        .frame(height: Self.height)
    }

    /// A window's % as of its last reading, or "—" if it has reset since then.
    private func windowText(_ window: UsageWindow?) -> String {
        guard let window else { return "—" }
        if let resetsAt = window.resetsAt, resetsAt < now.timeIntervalSince1970 { return "—" }
        return Format.percent(window.usedPct)
    }
}

/// The widget's content, also rendered by the app for previews.
struct WidgetContent: View {
    /// Padding inside the widget (default content margins are turned off).
    static let padding: CGFloat = 12

    let snapshot: Snapshot?
    var showsHeader: Bool
    var style: CellStyle = .color
    var links = true
    /// Shown instead of the grid when there is no snapshot.
    var message = "Open Claude Usage Grid to build your grid."

    var body: some View {
        if let snapshot {
            VStack(alignment: .leading, spacing: 6) {
                if showsHeader { SummaryLine(snapshot: snapshot, style: style) }
                GridView(days: snapshot.days, sectionCount: snapshot.sectionsPerCell, style: style,
                         interaction: links ? .links : .none,
                         showsChatReminder: snapshot.chats?.remind == true)
            }
        } else {
            VStack(alignment: .leading, spacing: 4) {
                Text("Claude Usage Grid").font(.headline)
                Text(message).font(.caption)
            }
            .foregroundStyle(style.text)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }
}

extension Snapshot {
    /// The widget gallery's preview.
    static let placeholder = sample(trackedWeeks: 17)

    /// Made-up data that shows every cell state. Tracking starts on the
    /// Wednesday `trackedWeeks - 1` weeks before this one (no usage data before
    /// it; batteries still fill with sessions). The four full weeks before this
    /// one hold a key: one column per orange level 1-4 (left to right), with
    /// Sunday-Wednesday filled 0, 1, 2 and 3 sections, and an afterburner on the
    /// last column's Saturday. Other days are random, a few of them afterburners.
    static func sample(trackedWeeks: Int, today: Date = Date()) -> Snapshot {
        let calendar = Format.calendar
        let weekday = calendar.component(.weekday, from: today) - 1  // Sunday = 0
        let totalDays = 52 * 7 + weekday + 1
        let start = calendar.date(byAdding: .day, value: -(totalDays - 1), to: today)!
        let currentWeek = 52
        let firstTracked = (currentWeek - (trackedWeeks - 1)) * 7 + 3
        var seed: UInt32 = 11
        var days: [GridDay] = []
        for offset in 0..<totalDays {
            seed = seed &* 1_103_515_245 &+ 12_345
            let roll = Int((seed >> 16) % 1000)
            let week = offset / 7, row = offset % 7
            var sections = roll % 5 == 0 ? 0 : 1 + roll % 3
            var level = 1 + (roll / 7) % 4
            var afterburner = roll % 29 == 0
            if (currentWeek - 4..<currentWeek).contains(week) {
                if row < 4 {
                    level = week - (currentWeek - 4) + 1
                    sections = row
                }
                afterburner = week == currentWeek - 1 && row == 6
            }
            if afterburner { (level, sections) = (4, 3) }
            let date = calendar.date(byAdding: .day, value: offset, to: start)!
            days.append(GridDay(date: Format.iso(date), usagePp: Double(level) * 4.5, sections: sections,
                                sessions: [0, 1, 3, 6][sections], level: level,
                                usageKnown: offset >= firstTracked, afterburner: afterburner))
        }
        return Snapshot(version: 1, generatedAt: today.timeIntervalSince1970, today: Format.iso(today),
                        usageTrackedSince: days[max(0, min(firstTracked, days.count - 1))].date, sectionCount: 3,
                        battery: BatteryRule(source: "sessions", thresholds: [1, 4]), afterburner: .standard,
                        header: Header(week: UsageWindow(usedPct: 42, resetsAt: nil, asOf: 0, source: nil),
                                       fiveHour: UsageWindow(usedPct: 18, resetsAt: nil, asOf: 0, source: nil),
                                       todayUsagePp: 6, todaySessions: 3),
                        levels: Levels(mode: "five_hour", thresholds: [25, 50, 75], nonzeroDays: 0), days: days)
    }
}
