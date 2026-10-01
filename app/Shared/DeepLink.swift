import Foundation

/// URLs in and out of the app.
///
/// In: claudeusagegrid://day/YYYY-MM-DD (widget cells), claudeusagegrid://grid, and
/// claudeusagegrid://update (the same as the Update Now button).
/// Out: documented Claude links. Both query values are percent-encoded with the
/// RFC 3986 unreserved set only, so "/" becomes %2F and a space %20.
enum DeepLink {
    static let scheme = "claudeusagegrid"

    enum Route: Equatable {
        case grid
        case day(String)
        case update
    }

    static var grid: URL { URL(string: "\(scheme)://grid")! }

    static func day(_ date: String) -> URL { URL(string: "\(scheme)://day/\(date)")! }

    static func parse(_ url: URL) -> Route? {
        guard url.scheme == scheme else { return nil }
        switch url.host {
        case "grid": return .grid
        case "update": return .update
        case "day":
            let date = url.pathComponents.dropFirst().first ?? ""
            return date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil ? .day(date) : nil
        default: return nil
        }
    }

    private static let unreserved = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")

    static func encode(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: unreserved) ?? ""
    }

    /// Terminal (the CLI's claude-cli:// handler): opens a terminal with /resume pre-filled.
    static func resumeInTerminal(sessionId: String, cwd: String?) -> URL {
        var query = "q=" + encode("/resume " + sessionId)
        if let cwd, !cwd.isEmpty { query = "cwd=" + encode(cwd) + "&" + query }
        return URL(string: "claude-cli://open?" + query)!
    }

    static func chatInDesktop(_ uuid: String) -> URL { URL(string: "claude://claude.ai/chat/" + encode(uuid))! }

    static func chatInBrowser(_ uuid: String) -> URL { URL(string: "https://claude.ai/chat/" + encode(uuid))! }
}
