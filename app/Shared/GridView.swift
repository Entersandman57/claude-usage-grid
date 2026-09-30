import SwiftUI

/// A day square: orange by session level, with Nokia-style battery bars that
/// fill bottom-up with the share of the weekly limit used that day.
struct DayCell: View {
    let day: GridDay
    let size: CGFloat
    let style: CellStyle
    var slots = 3

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.2, style: .continuous)
            .fill(style.fill(level: day.level))
            .overlay {
                if day.bars > 0 { BatteryBars(filled: day.bars, slots: slots, size: size, style: style) }
            }
            .frame(width: size, height: size)
    }
}

struct BatteryBars: View {
    let filled: Int
    let slots: Int
    let size: CGFloat
    let style: CellStyle

    var body: some View {
        let inset = max(2, (size * 0.17).rounded())
        let spacing = max(1, (size * 0.08).rounded())
        let inner = size - 2 * inset
        let barHeight = (inner - CGFloat(slots - 1) * spacing) / CGFloat(slots)
        VStack(spacing: spacing) {
            ForEach((0..<slots).reversed(), id: \.self) { index in
                RoundedRectangle(cornerRadius: min(1, barHeight / 2))
                    .fill(index < filled ? style.barFill : style.barSlot)
                    .frame(width: inner * width(of: index), height: barHeight)
            }
        }
        .frame(width: inner, height: inner)
    }

    /// Like the old Nokia battery indicator, bars get longer toward the top.
    private func width(of index: Int) -> CGFloat {
        slots == 1 ? 1 : 0.55 + 0.45 * CGFloat(index) / CGFloat(slots - 1)
    }
}

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
    var slots = 3
    var style: CellStyle = .color
    var interaction: GridInteraction = .none
    var maxBands = 3

    var body: some View {
        GeometryReader { proxy in
            let weeks = Week.weeks(from: days)
            let layout = GridLayout.fit(proxy.size, availableWeeks: weeks.count, maxBands: maxBands)
            // Bands share a right edge (today's column); the block is centered in the space.
            VStack(alignment: .trailing, spacing: GridLayout.bandSpacing) {
                ForEach(Array(layout.bands(of: weeks).enumerated()), id: \.offset) { _, band in
                    bandView(band, layout: layout)
                }
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
    }

    private func bandView(_ weeks: [Week], layout: GridLayout) -> some View {
        let column = layout.cell + layout.gap
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 0) {
                Color.clear.frame(width: GridLayout.dayLabelWidth, height: 1)
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
            let cell = DayCell(day: day, size: size, style: style, slots: slots)
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
    let snapshot: Snapshot?
    var showsHeader: Bool
    var style: CellStyle = .color
    var links = true

    var body: some View {
        if let snapshot {
            VStack(alignment: .leading, spacing: 6) {
                if showsHeader { SummaryLine(snapshot: snapshot, style: style) }
                GridView(days: snapshot.days, slots: snapshot.slots, style: style, interaction: links ? .links : .none)
            }
        } else {
            VStack(alignment: .leading, spacing: 4) {
                Text("Claude Usage Grid").font(.headline)
                Text("Open the app to build your grid.").font(.caption)
            }
            .foregroundStyle(style.text)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }
}

extension Snapshot {
    /// A plausible made-up year for the widget gallery preview.
    static let placeholder: Snapshot = {
        let calendar = Format.calendar
        let today = Date()
        let weekday = calendar.component(.weekday, from: today) - 1  // Sunday = 0
        let start = calendar.date(byAdding: .day, value: -(52 * 7 + weekday), to: today)!
        var days: [GridDay] = []
        var seed: UInt32 = 7
        for offset in 0...(52 * 7 + weekday) {
            seed = seed &* 1_103_515_245 &+ 12_345
            let roll = Int((seed >> 16) % 100)
            let sessions = roll < 35 ? 0 : roll % 9
            let bars = sessions == 0 ? 0 : 1 + roll % 3
            let date = calendar.date(byAdding: .day, value: offset, to: start)!
            days.append(GridDay(date: Format.iso(date), usagePp: Double(bars) * 3, bars: bars,
                                sessions: sessions, level: min(4, (sessions + 1) / 2), usageKnown: true))
        }
        return Snapshot(version: 1, generatedAt: today.timeIntervalSince1970, today: Format.iso(today),
                        usageTrackedSince: days.first?.date, barSlots: 3,
                        header: Header(week: UsageWindow(usedPct: 42, resetsAt: nil, asOf: 0, source: nil),
                                       fiveHour: UsageWindow(usedPct: 18, resetsAt: nil, asOf: 0, source: nil),
                                       todayUsagePp: 6, todaySessions: 3),
                        levels: Levels(mode: "fixed", thresholds: [1, 3, 6], nonzeroDays: 0), days: days)
    }()
}
