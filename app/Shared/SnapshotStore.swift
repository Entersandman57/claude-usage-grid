import Foundation

/// The widget's copy of snapshot.json in the App Group container.
///
/// The group ID is "<TeamID>.claudeusagegrid", a macOS-style group that the
/// system authorizes by the signing team, so it works with a free Personal
/// Team. Info.plist carries it as AppGroupID. The app writes; the widget reads.
enum SnapshotStore {
    static let fileName = "snapshot.json"

    static var groupID: String {
        Bundle.main.object(forInfoDictionaryKey: "AppGroupID") as? String ?? ""
    }

    static var fileURL: URL? {
        FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: groupID)?
            .appendingPathComponent(fileName)
    }

    static func load() -> Snapshot? {
        guard let url = fileURL, let data = try? Data(contentsOf: url) else { return nil }
        return try? GridJSON.decoder().decode(Snapshot.self, from: data)
    }

    static func write(_ data: Data) throws {
        guard let url = fileURL else { throw CocoaError(.fileNoSuchFile) }
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        try data.write(to: url, options: .atomic)
    }
}
