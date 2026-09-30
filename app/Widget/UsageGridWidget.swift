import SwiftUI
import WidgetKit

struct GridEntry: TimelineEntry {
    let date: Date
    let snapshot: Snapshot?
}

/// Reads the snapshot the app wrote to the App Group. The app reloads the
/// timeline whenever the grid changes; the timeline also asks to be refreshed
/// every 30 minutes and just after midnight (macOS may throttle both).
struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> GridEntry {
        GridEntry(date: Date(), snapshot: .placeholder)
    }

    func getSnapshot(in context: Context, completion: @escaping (GridEntry) -> Void) {
        let snapshot = context.isPreview ? .placeholder : (SnapshotStore.load() ?? .placeholder)
        completion(GridEntry(date: Date(), snapshot: snapshot))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<GridEntry>) -> Void) {
        let now = Date()
        let halfHour = now.addingTimeInterval(30 * 60)
        let midnight = Format.calendar.startOfDay(for: now).addingTimeInterval(24 * 3600 + 60)
        let entry = GridEntry(date: now, snapshot: SnapshotStore.load())
        completion(Timeline(entries: [entry], policy: .after(min(halfHour, midnight))))
    }
}

struct UsageGridEntryView: View {
    let entry: GridEntry
    @Environment(\.widgetFamily) private var family
    @Environment(\.widgetRenderingMode) private var renderingMode

    var body: some View {
        WidgetContent(snapshot: entry.snapshot,
                      showsHeader: family != .systemMedium,
                      style: CellStyle(fullColor: renderingMode == .fullColor))
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
        .description("Bars: share of your weekly limit used that day. Orange: how many sessions.")
        .supportedFamilies([.systemMedium, .systemLarge, .systemExtraLarge])
    }
}

@main
struct UsageGridWidgetBundle: WidgetBundle {
    var body: some Widget {
        UsageGridWidget()
    }
}
