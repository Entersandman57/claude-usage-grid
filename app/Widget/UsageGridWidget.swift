import SwiftUI
import WidgetKit

struct GridEntry: TimelineEntry {
    let date: Date
    let snapshot: Snapshot?
    var problem: String? = nil

    /// The current snapshot, or why it can't be shown (also written to the system log).
    static func current() -> GridEntry {
        switch SnapshotStore.loadResult() {
        case let .success(snapshot):
            SnapshotStore.log.info("widget loaded snapshot for \(snapshot.today, privacy: .public), \(snapshot.days.count) days")
            return GridEntry(date: Date(), snapshot: snapshot)
        case let .failure(error):
            SnapshotStore.log.error("widget can't show the grid: \(error.description, privacy: .public)")
            return GridEntry(date: Date(), snapshot: nil, problem: error.message)
        }
    }
}

/// Reads the snapshot the app wrote to the App Group. The app reloads the
/// timeline whenever the grid changes; the timeline also asks to be refreshed
/// every 30 minutes and just after midnight (macOS may throttle both).
struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> GridEntry {
        GridEntry(date: Date(), snapshot: .placeholder)
    }

    func getSnapshot(in context: Context, completion: @escaping (GridEntry) -> Void) {
        completion(context.isPreview ? GridEntry(date: Date(), snapshot: .placeholder) : .current())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<GridEntry>) -> Void) {
        SnapshotStore.log.info(
            "widget \(String(describing: context.family), privacy: .public) display \(context.displaySize.width)x\(context.displaySize.height)")
        let now = Date()
        let halfHour = now.addingTimeInterval(30 * 60)
        let midnight = Format.calendar.startOfDay(for: now).addingTimeInterval(24 * 3600 + 60)
        completion(Timeline(entries: [.current()], policy: .after(min(halfHour, midnight))))
    }
}

struct UsageGridEntryView: View {
    let entry: GridEntry
    @Environment(\.widgetFamily) private var family
    @Environment(\.widgetRenderingMode) private var renderingMode

    var body: some View {
        WidgetContent(snapshot: entry.snapshot,
                      showsHeader: family != .systemMedium,
                      style: CellStyle(fullColor: renderingMode == .fullColor),
                      message: entry.problem ?? SnapshotStore.LoadError.noFile.message)
            .padding(WidgetContent.padding)
            .widgetURL(DeepLink.grid)
    }
}

struct UsageGridWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "UsageGrid", provider: Provider()) { entry in
            UsageGridEntryView(entry: entry)
                .environment(\.colorScheme, .dark)  // always dark, whatever the system appearance
                .containerBackground(for: .widget) { Palette.background }
        }
        .configurationDisplayName("Claude Usage Grid")
        .description("Each day is a battery: how much of your weekly limit you used. Orange: how many sessions.")
        .supportedFamilies([.systemMedium, .systemLarge, .systemExtraLarge])
        // macOS's default margins are 18 pt a side (a 344x164 medium widget leaves
        // 308x128). Our own 12 pt leaves room for 14 pt cells with 4 pt gaps.
        .contentMarginsDisabled()
    }
}

@main
struct UsageGridWidgetBundle: WidgetBundle {
    var body: some Widget {
        UsageGridWidget()
    }
}
