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
    private var launchedAsLoginItem = false

    func applicationWillFinishLaunching(_ notification: Notification) {
        let event = NSAppleEventManager.shared().currentAppleEvent
        launchedAsLoginItem = event?.eventID == kAEOpenApplication
            && event?.paramDescriptor(forKeyword: keyAEPropData)?.enumCodeValue == keyAELaunchedAsLogInItem
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let arguments = CommandLine.arguments
        if let index = arguments.firstIndex(of: "--render-previews"), index + 1 < arguments.count {
            PreviewRenderer.render(to: URL(fileURLWithPath: arguments[index + 1]))
            NSApp.terminate(nil)
            return
        }
        DataStore.shared.start()
        // Opened by hand (Finder, Spotlight): show the grid, since the menu bar icon
        // can be hidden on a crowded menu bar. Not at login, not for scripted
        // launches (--no-window), and not when a widget link already opened a day.
        guard !launchedAsLoginItem, !arguments.contains("--no-window") else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            if !WindowManager.shared.hasVisibleWindow { WindowManager.shared.showGrid() }
        }
    }

    /// Opening the app again while it runs (Finder, Spotlight, Dock) brings the grid back.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !WindowManager.shared.hasVisibleWindow { WindowManager.shared.showGrid() }
        return true
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
        Button(store.takingReading ? "Taking Reading…" : "Take Reading Now") { store.takeReading() }
            .disabled(store.takingReading)
        Divider()
        ForEach(store.statusLines, id: \.self) { Text($0) }
        Divider()
        Button("Quit Claude Usage Grid") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }
}
