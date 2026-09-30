import AppKit
import SwiftUI

/// `ClaudeUsageGrid --render-previews <dir>` writes PNGs of the widget (every
/// size, full color and drained) and of the app's windows, using the last
/// aggregator output. It lets the layout be checked without a desktop.
@MainActor
enum PreviewRenderer {
    // Approximate macOS widget sizes in points; the real widget measures itself.
    private static let widgetSizes: [(name: String, size: CGSize, header: Bool)] = [
        ("medium", CGSize(width: 344, height: 160), false),
        ("large", CGSize(width: 344, height: 356), true),
        ("extralarge", CGSize(width: 712, height: 356), true),
    ]

    static func render(to directory: URL) {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let store = DataStore.shared
        store.loadLastOutputs()
        for (name, snapshot) in [("real", store.snapshot), ("placeholder", Snapshot.placeholder)] {
            for (sizeName, size, header) in widgetSizes {
                for fullColor in [true, false] {
                    let view = WidgetContent(snapshot: snapshot, showsHeader: header,
                                             style: CellStyle(fullColor: fullColor), links: false)
                        .padding(14)
                        .frame(width: size.width, height: size.height)
                        .background(fullColor ? Palette.background : Color(white: 0.28))
                        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                        .environment(\.colorScheme, .dark)
                    write(view, "widget-\(name)-\(sizeName)-\(fullColor ? "color" : "drained").png", in: directory)
                }
            }
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
