import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// Opens the grid and day windows. A menu bar app has no main window, so it
/// manages plain NSWindows hosting SwiftUI views and brings itself forward.
@MainActor
final class WindowManager {
    static let shared = WindowManager()

    private var gridWindow: NSWindow?
    private var dayWindow: NSWindow?
    private var dayHost: NSHostingController<DayView>?

    var hasVisibleWindow: Bool {
        [gridWindow, dayWindow].contains { $0?.isVisible == true }
    }

    func handle(_ url: URL) {
        switch DeepLink.parse(url) {
        case let .day(date): showDay(date)
        case .grid: showGrid()
        case .update: DataStore.shared.updateNow()
        case nil: break
        }
    }

    func showGrid() {
        if gridWindow == nil {
            gridWindow = makeWindow(title: "Claude Usage Grid",
                                    controller: NSHostingController(rootView: GridWindowView(store: .shared)))
        }
        present(gridWindow!)
    }

    /// One day window, reused: opening another day swaps its content.
    func showDay(_ date: String) {
        let view = DayView(store: .shared, date: date)
        if let dayHost, let dayWindow {
            dayHost.rootView = view
            dayWindow.title = Format.longDay(date)
        } else {
            let host = NSHostingController(rootView: view)
            dayHost = host
            dayWindow = makeWindow(title: Format.longDay(date), controller: host)
        }
        present(dayWindow!)
    }

    /// Pick a claude.ai data export to import.
    func chooseExport() {
        NSApp.activate()
        let panel = NSOpenPanel()
        panel.title = "Import your claude.ai data export"
        panel.message = "Choose the ZIP from claude.ai › Settings › Privacy › Export data."
        panel.allowedContentTypes = [.zip, .json, .folder]
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        DataStore.shared.importChats(from: url)
        showGrid()
    }

    private func makeWindow(title: String, controller: NSViewController) -> NSWindow {
        let window = NSWindow(contentViewController: controller)
        window.title = title
        window.styleMask.insert(.resizable)
        window.isReleasedWhenClosed = false
        window.appearance = NSAppearance(named: .darkAqua)
        window.center()
        return window
    }

    private func present(_ window: NSWindow) {
        NSApp.activate()
        window.makeKeyAndOrderFront(nil)
    }
}
