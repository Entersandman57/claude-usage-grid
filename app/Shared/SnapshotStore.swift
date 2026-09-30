import Foundation
import os

/// The widget's copy of snapshot.json in the App Group container.
///
/// The group ID is "<TeamID>.claudeusagegrid", a macOS-style group that the
/// system authorizes by the signing team, so it works with a free Personal
/// Team. Info.plist carries it as AppGroupID. The app writes; the widget reads.
enum SnapshotStore {
    static let fileName = "snapshot.json"
    static let log = Logger(subsystem: "com.petesmacintosh.ClaudeUsageGrid", category: "snapshot")

    enum LoadError: Error, CustomStringConvertible {
        case noContainer
        case noFile
        case unreadable(String)

        var description: String {
            switch self {
            case .noContainer: return "App Group container unavailable"
            case .noFile: return "no snapshot yet"
            case let .unreadable(reason): return "unreadable snapshot: \(reason)"
            }
        }

        /// What the widget shows instead of the grid.
        var message: String {
            switch self {
            case .noContainer: return "The widget can't reach the app's data. Reinstall with `make app`."
            case .noFile: return "Open Claude Usage Grid to build your grid."
            case .unreadable: return "The widget and app are out of step. Open Claude Usage Grid to refresh."
            }
        }
    }

    static var groupID: String {
        Bundle.main.object(forInfoDictionaryKey: "AppGroupID") as? String ?? ""
    }

    static var fileURL: URL? {
        FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: groupID)?
            .appendingPathComponent(fileName)
    }

    static func loadResult() -> Result<Snapshot, LoadError> {
        guard let url = fileURL else { return .failure(.noContainer) }
        let data: Data
        do {
            data = try Data(contentsOf: url)
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile {
            return .failure(.noFile)
        } catch {
            return .failure(.unreadable(error.localizedDescription))
        }
        do {
            return .success(try GridJSON.decoder().decode(Snapshot.self, from: data))
        } catch {
            return .failure(.unreadable(String(describing: error)))
        }
    }

    static func load() -> Snapshot? {
        try? loadResult().get()
    }

    static func write(_ data: Data) throws {
        guard let url = fileURL else { throw CocoaError(.fileNoSuchFile) }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        try data.write(to: url, options: .atomic)
    }
}
