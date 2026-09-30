import SwiftUI

/// A menu bar app (LSUIElement: no Dock icon) that hosts the widget.
@main
struct ClaudeUsageGridApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var store = DataStore.shared

    var body: some Scene {
        MenuBarExtra {
            MenuContent(store: store)
        } label: {
            Image(systemName: "square.grid.3x3.fill")
        }
        .menuBarExtraStyle(.menu)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        let arguments = CommandLine.arguments
        if let index = arguments.firstIndex(of: "--render-previews"), index + 1 < arguments.count {
            PreviewRenderer.render(to: URL(fileURLWithPath: arguments[index + 1]))
            NSApp.terminate(nil)
            return
        }
        DataStore.shared.start()
    }

    /// claudeusagegrid:// links from the widget (the app is launched first if needed).
    func application(_ application: NSApplication, open urls: [URL]) {
        urls.forEach(WindowManager.shared.handle)
    }
}

struct MenuContent: View {
    @ObservedObject var store: DataStore

    var body: some View {
        Text(store.summary)
        Divider()
        Button("Open Grid…") { WindowManager.shared.showGrid() }
            .keyboardShortcut("g")
        Button("Open Today…") { WindowManager.shared.showDay(Format.iso(Date())) }
            .keyboardShortcut("t")
        Button("Refresh Now") { store.refresh() }
            .keyboardShortcut("r")
        Divider()
        ForEach(store.statusLines, id: \.self) { Text($0) }
        Divider()
        Button("Quit Claude Usage Grid") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }
}
