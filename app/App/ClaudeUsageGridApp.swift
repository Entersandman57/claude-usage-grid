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
        // `--login-item status|off`: report or turn off launch at login (used by uninstall.py).
        if let index = arguments.firstIndex(of: "--login-item"), index + 1 < arguments.count {
            if arguments[index + 1] == "off" { try? LoginItem.set(false) }
            print(LoginItem.statusText)
            NSApp.terminate(nil)
            return
        }
        // `--import <export>`: the Import button's code path, from the command line.
        if let index = arguments.firstIndex(of: "--import"), index + 1 < arguments.count {
            let source = URL(fileURLWithPath: arguments[index + 1])
            let message = (try? DataStore.runImport(source: source, dataDir: DataStore.shared.dataDir))
                ?? "Import failed: couldn't read \(source.lastPathComponent)"
            print(message)
            NSApp.terminate(nil)
            return
        }
        LoginItem.enableOnFirstRun()
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
        if let chats = store.snapshot?.chats, chats.remind {
            Button("Import Chats… (\(chats.importedThrough.map { "last through " + Format.mediumDay($0) } ?? "never imported"))") {
                WindowManager.shared.chooseExport()
            }
        }
        Divider()
        Button("Open Grid…") { WindowManager.shared.showGrid() }
            .keyboardShortcut("g")
        Button("Open Today…") { WindowManager.shared.showDay(Format.iso(Date())) }
            .keyboardShortcut("t")
        Button(store.updating ? "Updating…" : "Update Now") { store.updateNow() }
            .keyboardShortcut("u")
            .disabled(store.updating)
        Button("Import claude.ai Export…") { WindowManager.shared.chooseExport() }
            .keyboardShortcut("i")
            .disabled(store.importing)
        Toggle("Launch at Login", isOn: Binding(get: { store.launchAtLogin },
                                                set: { store.setLaunchAtLogin($0) }))
        Divider()
        ForEach(store.statusLines, id: \.self) { Text($0) }
        Divider()
        Button("Quit Claude Usage Grid") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }
}
