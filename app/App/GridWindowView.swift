import SwiftUI

/// The full year: the same grid as the widget, plus hover details, a legend and status.
struct GridWindowView: View {
    @ObservedObject var store: DataStore
    @State private var hovered: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let snapshot = store.snapshot {
                SummaryLine(snapshot: snapshot)
                GridView(days: snapshot.days, sectionCount: snapshot.sectionsPerCell,
                         interaction: .interactive(hovered: $hovered,
                                                   open: { WindowManager.shared.showDay($0) },
                                                   tooltip: store.tooltip(for:)),
                         maxBands: 1)
                    .frame(height: GridLayout.bandHeight(cell: 15.5, gap: 3))
                Text(hoverText(snapshot))
                    .font(.callout)
                    .foregroundStyle(hovered == nil ? .secondary : .primary)
                    .frame(height: 18)  // fixed heights keep the cells below on whole pixels
                LegendView(sectionCount: snapshot.sectionsPerCell)
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
        .frame(minWidth: 1045, minHeight: 350, alignment: .topLeading)
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
    let sectionCount: Int

    private func cell(sections: Int, level: Int, known: Bool = true) -> some View {
        DayCell(day: GridDay(date: "", usagePp: 0, sections: sections, sessions: level, level: level, usageKnown: known),
                size: 14, style: .color, sectionCount: sectionCount)
    }

    var body: some View {
        HStack(spacing: 20) {
            HStack(spacing: 4) {
                Text("Sessions: fewer")
                ForEach(1...4, id: \.self) { cell(sections: sectionCount, level: $0) }
                Text("more")
            }
            HStack(spacing: 4) {
                Text("Weekly limit used that day:")
                ForEach(0...sectionCount, id: \.self) { cell(sections: $0, level: 3) }
                Text("each section = 1/\(sectionCount) of a day's even share (100% ÷ 7)")
            }
            HStack(spacing: 4) {
                cell(sections: 0, level: 0, known: false)
                Text("no data yet")
            }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .frame(height: 16)
    }
}
