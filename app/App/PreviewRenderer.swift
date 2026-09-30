import AppKit
import SwiftUI

/// `ClaudeUsageGrid --render-previews <dir>` writes PNGs so the look can be
/// checked without a desktop:
///   widget-sample-<size>-<color|drained>.png  made-up data covering every cell state
///   widget-real-<size>-<color|drained>.png    the last aggregator output
///   cells-<color|drained>.png                 every cell state, large and at 14 pt
///   grid-window.png, day-<date>.png           the app's windows with real data
@MainActor
enum PreviewRenderer {
    // Approximate macOS widget sizes in points; the real widget measures itself.
    private static let widgetSizes: [(name: String, size: CGSize, header: Bool)] = [
        ("medium", CGSize(width: 344, height: 160), false),
        ("large", CGSize(width: 344, height: 356), true),
        ("extralarge", CGSize(width: 712, height: 356), true),
    ]
    private static let widgetPadding: CGFloat = 14

    static func render(to directory: URL) {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let store = DataStore.shared
        store.loadLastOutputs()
        for (sizeName, size, header) in widgetSizes {
            // Start the sample's tracking in the oldest column this size shows.
            var grid = CGSize(width: size.width - 2 * widgetPadding, height: size.height - 2 * widgetPadding)
            if header { grid.height -= SummaryLine.height + 6 }
            let weeks = GridLayout.fit(grid, availableWeeks: 53).weeks
            for (name, snapshot) in [("sample", Snapshot.sample(trackedWeeks: weeks)), ("real", store.snapshot)] {
                for fullColor in [true, false] {
                    let view = WidgetContent(snapshot: snapshot, showsHeader: header,
                                             style: CellStyle(fullColor: fullColor), links: false)
                        .padding(widgetPadding)
                        .frame(width: size.width, height: size.height)
                        .background(fullColor ? Palette.background : Color(white: 0.28))
                        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                        .environment(\.colorScheme, .dark)
                    write(view, "widget-\(name)-\(sizeName)-\(fullColor ? "color" : "drained").png", in: directory)
                }
            }
        }
        for fullColor in [true, false] {
            let style = CellStyle(fullColor: fullColor)
            let sheet = VStack(alignment: .leading, spacing: 24) {
                CellKey(size: 41, style: style)  // a crisp size: 13 pt sections
                CellKey(size: 14, style: style)
            }
            .padding(16)
            .background(fullColor ? Palette.background : Color(white: 0.28))
            .environment(\.colorScheme, .dark)
            write(sheet, "cells-\(fullColor ? "color" : "drained").png", in: directory)
        }
        write(GridWindowView(store: store).environment(\.colorScheme, .dark), "grid-window.png", in: directory)
        let today = store.snapshot?.today ?? Format.iso(Date())
        write(DayContent(store: store, date: today).frame(width: 560).background(Palette.background)
                .environment(\.colorScheme, .dark), "day-\(today).png", in: directory)
    }

    private static func write<V: View>(_ view: V, _ name: String, in directory: URL) {
        let renderer = ImageRenderer(content: view)
        renderer.scale = 2
        guard let tiff = renderer.nsImage?.tiffRepresentation,
              let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) else { return }
        try? png.write(to: directory.appendingPathComponent(name))
    }
}

/// Every cell state: rows are 3-0 filled sections, columns session levels 1-4, plus no data.
private struct CellKey: View {
    let size: CGFloat
    let style: CellStyle

    private var column: CGFloat { max(size, 48) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Text("\(Int(size)) pt").frame(width: 64, alignment: .leading)
                ForEach(1...4, id: \.self) { Text("Level \($0)").frame(width: column) }
                Text("No data").frame(width: column)
            }
            .frame(height: 14)
            ForEach((0...3).reversed(), id: \.self) { sections in
                HStack(spacing: 10) {
                    Text("\(sections) of 3").frame(width: 64, alignment: .leading)
                    ForEach(1...4, id: \.self) { level in
                        DayCell(day: GridDay(date: "", usagePp: 0, sections: sections, sessions: level,
                                             level: level, usageKnown: true),
                                size: size, style: style)
                            .frame(width: column)
                    }
                    if sections == 0 {
                        DayCell(day: GridDay(date: "", usagePp: 0, sections: 0, sessions: 0, level: 0,
                                             usageKnown: false),
                                size: size, style: style)
                            .frame(width: column)
                    }
                }
                .frame(height: size)
            }
        }
        .font(.caption)
        .foregroundStyle(style.text)
    }
}
