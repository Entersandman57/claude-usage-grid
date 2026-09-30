import XCTest

final class SharedTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle(for: SharedTests.self).url(forResource: name, withExtension: "json"))
        return try Data(contentsOf: url)
    }

    // MARK: Decoding the aggregator's output

    func testDecodesSnapshotAndDetails() throws {
        let snapshot = try GridJSON.decoder().decode(Snapshot.self, from: fixture("snapshot"))
        XCTAssertEqual(snapshot.today, "2026-09-30")
        XCTAssertEqual(snapshot.days.first?.date, "2025-09-28")  // a Sunday, 52 weeks back
        XCTAssertEqual(snapshot.days.count, 52 * 7 + 4)
        XCTAssertEqual(snapshot.header.week?.usedPct, 12)

        let details = try GridJSON.decoder().decode(Details.self, from: fixture("details"))
        let today = try XCTUnwrap(details.days["2026-09-30"])
        XCTAssertEqual(today.sessionsCode, 2)
        XCTAssertEqual(today.sessionsChat, 1)
        XCTAssertEqual(today.peakFiveHourPct, 31)
        XCTAssertEqual(today.codeSessions.map(\.title), ["Widget layout", "Fix parser"])
        XCTAssertEqual(details.days["2026-09-20"]?.codeSessions.first?.transcriptPresent, false)
        XCTAssertEqual(details.status.chatsImportedThrough, "2026-09-30")
        XCTAssertEqual(details.status.meterLastRun?.trigger, "nightly")
    }

    // MARK: Weeks

    func testWeeksAreSundayFirstAndHideFutureDays() throws {
        let snapshot = try GridJSON.decoder().decode(Snapshot.self, from: fixture("snapshot"))
        let weeks = Week.weeks(from: snapshot.days)
        XCTAssertEqual(weeks.count, 53)
        XCTAssertTrue(weeks.allSatisfy { $0.days.count == 7 })
        let last = try XCTUnwrap(weeks.last)
        XCTAssertEqual(last.days.compactMap { $0?.date }, ["2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"])
        XCTAssertEqual(last.days.filter { $0 == nil }.count, 3)  // Thu-Sat are in the future
        XCTAssertEqual(weeks.first?.monthLabel, nil)              // Sep 28 isn't September's first Sunday
        XCTAssertEqual(weeks[1].monthLabel, "Oct")                // Oct 5 is October's
    }

    // MARK: Layout

    func testMediumFitsOneBandOfAboutFourMonths() {
        let layout = GridLayout.fit(CGSize(width: 316, height: 132), availableWeeks: 53)
        XCTAssertEqual(layout.bands, 1)
        XCTAssertGreaterThanOrEqual(layout.cell, 14)
        XCTAssertEqual(layout.weeks, GridLayout.columns(width: 316, cell: layout.cell, gap: 3))
        XCTAssertGreaterThanOrEqual(layout.weeks, 16)
    }

    func testLargeStacksTwoBands() {
        let layout = GridLayout.fit(CGSize(width: 316, height: 309), availableWeeks: 53)
        XCTAssertEqual(layout.bands, 2)
        XCTAssertGreaterThanOrEqual(layout.cell, 14)
        XCTAssertGreaterThanOrEqual(layout.weeks, 32)
    }

    func testExtraLargeShowsTheWholeYear() {
        let layout = GridLayout.fit(CGSize(width: 684, height: 309), availableWeeks: 53)
        XCTAssertEqual(layout.weeks, 53)
        XCTAssertEqual(layout.bands, 2)
        XCTAssertGreaterThan(layout.cell, 14)  // room to spare goes into bigger cells
    }

    func testFewWeeksUseBigCellsInOneBand() {
        let layout = GridLayout.fit(CGSize(width: 684, height: 309), availableWeeks: 5)
        XCTAssertEqual(layout.weeks, 5)
        XCTAssertEqual(layout.bands, 1)
        XCTAssertEqual(layout.cell, GridLayout.maxCell)
    }

    func testTinySpaceFallsBackBelow14pt() {
        let layout = GridLayout.fit(CGSize(width: 200, height: 60), availableWeeks: 53)
        XCTAssertEqual(layout.bands, 1)
        XCTAssertLessThan(layout.cell, 14)
        XCTAssertGreaterThan(layout.weeks, 0)
    }

    func testBandsPutTheNewestWeeksLast() throws {
        let snapshot = try GridJSON.decoder().decode(Snapshot.self, from: fixture("snapshot"))
        let weeks = Week.weeks(from: snapshot.days)
        let layout = GridLayout(cell: 14, gap: 3, bands: 2, weeksPerBand: 27, weeks: 53)
        let bands = layout.bands(of: weeks)
        XCTAssertEqual(bands.map(\.count), [26, 27])
        XCTAssertEqual(bands.last?.last, weeks.last)
        XCTAssertEqual(bands.flatMap { $0 }, weeks)
    }

    // MARK: Links

    func testResumeLinksEncodeBothValues() {
        let id = "762edcb4-6ae2-4cce-a44a-7660148e7ab7"
        XCTAssertEqual(DeepLink.resumeInTerminal(sessionId: id, cwd: "/Users/me/My Project").absoluteString,
                       "claude-cli://open?cwd=%2FUsers%2Fme%2FMy%20Project&q=%2Fresume%20\(id)")
        XCTAssertEqual(DeepLink.resumeInTerminal(sessionId: id, cwd: "/Users/me/a&b").absoluteString,
                       "claude-cli://open?cwd=%2FUsers%2Fme%2Fa%26b&q=%2Fresume%20\(id)")
        XCTAssertEqual(DeepLink.resumeInTerminal(sessionId: id, cwd: nil).absoluteString,
                       "claude-cli://open?q=%2Fresume%20\(id)")
    }

    func testChatLinks() {
        XCTAssertEqual(DeepLink.chatInBrowser("abc-123").absoluteString, "https://claude.ai/chat/abc-123")
        XCTAssertEqual(DeepLink.chatInDesktop("abc-123").absoluteString, "claude://claude.ai/chat/abc-123")
    }

    func testParsesAppRoutes() {
        XCTAssertEqual(DeepLink.parse(DeepLink.day("2026-09-30")), .day("2026-09-30"))
        XCTAssertEqual(DeepLink.parse(DeepLink.grid), .grid)
        XCTAssertNil(DeepLink.parse(URL(string: "claudeusagegrid://day/../../etc")!))
        XCTAssertNil(DeepLink.parse(URL(string: "https://example.com/day/2026-09-30")!))
    }
}
