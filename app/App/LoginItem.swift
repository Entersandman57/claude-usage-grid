import ServiceManagement

/// Launch at login via SMAppService (macOS 13+). It works for any signed app,
/// including one signed with a free Personal Team; macOS may ask you to approve
/// it once in System Settings > General > Login Items.
enum LoginItem {
    static var status: SMAppService.Status { SMAppService.mainApp.status }
    static var isEnabled: Bool { status == .enabled }

    static var statusText: String {
        switch status {
        case .enabled: return "Launch at login: on"
        case .requiresApproval: return "Launch at login: waiting for approval in System Settings › General › Login Items"
        case .notRegistered: return "Launch at login: off"
        case .notFound: return "Launch at login: unavailable (the app must be in /Applications)"
        @unknown default: return "Launch at login: unknown"
        }
    }

    static func set(_ enabled: Bool) throws {
        if enabled {
            try SMAppService.mainApp.register()
        } else {
            try SMAppService.mainApp.unregister()
        }
    }

    /// Turned on once, the first time the app runs; after that the menu's toggle decides.
    static func enableOnFirstRun() {
        let key = "LoginItemSetUp"
        guard !UserDefaults.standard.bool(forKey: key) else { return }
        UserDefaults.standard.set(true, forKey: key)
        try? SMAppService.mainApp.register()
    }
}
