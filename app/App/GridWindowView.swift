import SwiftUI

/// The full year: the same grid as the widget, plus hover details, a legend and status.
struct GridWindowView: View {
    @ObservedObject var store: DataStore
    @State private var hovered: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let snapshot = store.snapshot {
                SummaryLine(snapshot: snapshot)
                GridView(days: snapshot.days, slots: snapshot.slots,
                         interaction: .interactive(hovered: $hovered,
                                                   open: { WindowManager.shared.showDay($0) },
                                                   tooltip: store.tooltip(for:)),
                         maxBands: 1)
                    .frame(height: GridLayout.bandHeight(cell: 15, gap: 3))
                Text(hoverText(snapshot))
                    .font(.callout)
                    .foregroundStyle(hovered == nil ? .secondary : .primary)
                LegendView(slots: snapshot.slots)
                Divider()
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(store.statusLines, id: \.self) { Text($0) }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            } else {
                Text(store.lastError ?? "Building your grid…").foregroundStyle(.secondary)
            }
        }
        .padding(20)
        .frame(minWidth: 1020, minHeight: 340, alignment: .topLeading)
        .background(Palette.background)
    }

    private func hoverText(_ snapshot: Snapshot) -> String {
        guard let hovered, let day = snapshot.days.first(where: { $0.date == hovered }) else {
            return "Hover a day for details. Click it to see its sessions."
        }
        return store.tooltip(for: day)
    }
}

struct LegendView: View {
    let slots: Int

    private func sample(level: Int, bars: Int) -> some View {
        DayCell(day: GridDay(date: "", usagePp: 0, bars: bars, sessions: 0, level: level, usageKnown: true),
                size: 14, style: .color, slots: slots)
    }

    var body: some View {
        HStack(spacing: 18) {
            HStack(spacing: 4) {
                Text("Fewer sessions")
                ForEach(0..<5, id: \.self) { sample(level: $0, bars: 0) }
                Text("More")
            }
            HStack(spacing: 4) {
                Text("Weekly limit used that day")
                ForEach(1...slots, id: \.self) { sample(level: 3, bars: $0) }
                Text("each bar is 1/\(slots) of a day's even share (100% ÷ 7); \(slots) bars = more than \(slots - 1)/\(slots)")
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }
}
