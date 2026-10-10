import SwiftUI

/// The full year: the same grid as the widget, plus hover details, a legend and status.
struct GridWindowView: View {
    @ObservedObject var store: DataStore
    @State private var hovered: String?
    @State private var dropTargeted = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let snapshot = store.snapshot {
                HStack(spacing: 12) {
                    SummaryLine(snapshot: snapshot)
                    Button("Import claude.ai Export…") { WindowManager.shared.chooseExport() }
                        .disabled(store.importing)
                        .help("Or drop the export ZIP anywhere on this window.")
                    UpdateButton(store: store)
                }
                .frame(height: 24)  // fixed so the grid below starts on a whole point
                if let chats = snapshot.chats, chats.remind {
                    Label(chats.reminderText, systemImage: "bubble.left.fill")
                        .font(.callout)
                        .foregroundStyle(Palette.levels[1])
                        .frame(height: 18)
                }
                GridView(days: snapshot.days, sectionCount: snapshot.sectionsPerCell,
                         interaction: .interactive(hovered: $hovered,
                                                   open: { WindowManager.shared.showDay($0) },
                                                   tooltip: store.tooltip(for:)),
                         maxBands: 1,
                         showsChatReminder: snapshot.chats?.remind == true)
                    .frame(height: GridLayout.bandHeight(cell: 15.5, gap: GridLayout.cellGap))
                Text(hoverText(snapshot))
                    .font(.callout)
                    .foregroundStyle(hovered == nil ? .secondary : .primary)
                    .frame(height: 18)  // fixed heights keep the cells below on whole pixels
                LegendView(sectionCount: snapshot.sectionsPerCell)
                if let message = store.importMessage {
                    Text(message).font(.callout).frame(height: 18)
                }
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
        .frame(minWidth: 1100, minHeight: 356, alignment: .topLeading)
        .background(Palette.background)
        // Drop the claude.ai export (ZIP, conversations.json or its folder) to import it.
        .onDrop(of: [.fileURL], isTargeted: $dropTargeted) { providers in
            guard let provider = providers.first else { return false }
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                guard let url else { return }
                Task { @MainActor in store.importChats(from: url) }
            }
            return true
        }
        .overlay {
            if dropTargeted {
                RoundedRectangle(cornerRadius: 12)
                    .strokeBorder(Palette.levels[2], style: StrokeStyle(lineWidth: 2, dash: [6]))
                    .overlay(Text("Drop your claude.ai export to import its chats").font(.title3.weight(.semibold)))
                    .background(Palette.background.opacity(0.85))
                    .padding(8)
            }
        }
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

    private func cell(sections: Int, level: Int) -> some View {
        DayCell(day: GridDay(date: "", usagePp: 0, sections: sections, sessions: level, level: level, usageKnown: true),
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
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .frame(height: 16)
    }
}

/// Takes a fresh usage reading and refreshes sessions, then redraws the grid and widget.
struct UpdateButton: View {
    @ObservedObject var store: DataStore

    var body: some View {
        HStack(spacing: 8) {
            if let at = store.lastUpdatedAt, !store.updating {
                Text("Updated \(Format.time(at.timeIntervalSince1970))").font(.caption).foregroundStyle(.secondary)
            }
            Button {
                store.updateNow()
            } label: {
                if store.updating {
                    HStack(spacing: 6) { ProgressView().controlSize(.small); Text("Updating…") }
                } else {
                    Label("Update Now", systemImage: "arrow.clockwise")
                }
            }
            .disabled(store.updating)
            .help("Reads your current usage % (one tiny Claude call) and refreshes today's sessions.")
        }
    }
}
