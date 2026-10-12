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
        XCTAssertEqual(snapshot.sectionsPerCell, 3)
        XCTAssertEqual(snapshot.days.last?.sections, 1)
        XCTAssertFalse(snapshot.days.first { $0.date == "2026-09-27" }!.usageKnown)  // before the first reading
        XCTAssertTrue(snapshot.days.first { $0.date == "2026-09-28" }!.usageKnown)

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

    func testDecodesBatteryRuleAndAfterburner() throws {
        let json = """
        {"battery": {"source": "sessions", "thresholds": [1, 4]},
         "afterburner": {"maxed_pct": 100, "other_pct": 10},
         "day": {"date": "2026-10-10", "usage_pp": 20, "sections": 3, "sessions": 9, "level": 4,
                 "usage_known": true, "afterburner": true},
         "detail": {"usage_pp": 20, "share_fraction": 1.4, "sections": 3, "peak_five_hour_pct": 100,
                    "five_hour_samples": 3, "afterburner": true, "sessions": 9, "sessions_code": 1,
                    "sessions_chat": 8, "inferred_session": false, "level": 4, "code_sessions": [], "chats": [],
                    "five_hour_windows": [{"resets_at": 1791619200, "peak_pct": 100, "samples": 2},
                                          {"resets_at": 1791637200, "peak_pct": 31, "samples": 1}]}}
        """
        struct Parts: Decodable {
            var battery: BatteryRule
            var afterburner: AfterburnerRule
            var day: GridDay
            var detail: DayDetail
        }
        let parts = try GridJSON.decoder().decode(Parts.self, from: Data(json.utf8))
        XCTAssertEqual(parts.battery.sessionLabels, ["0", "1", "2–4", "5+"])
        XCTAssertEqual(parts.afterburner, .standard)
        XCTAssertEqual(parts.day.afterburner, true)
        XCTAssertEqual(parts.detail.fiveHourWindows?.map(\.peakPct), [100, 31])
        XCTAssertEqual(parts.detail.afterburnerText, "Maxed out a 5-hour window, then used 31% of another")

        // A version 2 snapshot (no battery rule, no afterburner) still decodes.
        let old = try GridJSON.decoder().decode(Snapshot.self, from: fixture("snapshot"))
        XCTAssertNil(old.battery)
        XCTAssertTrue(old.days.allSatisfy { $0.afterburner == nil })
    }

    func testSessionLabelsFollowTheThresholds() {
        XCTAssertEqual(BatteryRule(source: "sessions", thresholds: [2, 5]).sessionLabels, ["0", "1–2", "3–5", "6+"])
        XCTAssertEqual(BatteryRule(source: "sessions", thresholds: [1, 2, 3]).sessionLabels, ["0", "1", "2", "3", "4+"])
    }

    func testAfterburnerTextNeedsTheFlag() {
        var detail = try! GridJSON.decoder().decode(Details.self, from: fixture("details")).days["2026-09-30"]!
        detail.fiveHourWindows = [FiveHourWindow(resetsAt: 1, peakPct: 100, samples: 1),
                                  FiveHourWindow(resetsAt: 2, peakPct: 100, samples: 1)]
        XCTAssertNil(detail.afterburnerText)
        detail.afterburner = true
        XCTAssertEqual(detail.afterburnerText, "Maxed out two 5-hour windows")
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

    // MARK: Battery cells

    func testSectionsSplitTheSquareWithOnePointDividers() {
        XCTAssertEqual(CellGeometry.sectionHeight(size: 14, count: 3), 4)       // 4 + 1 + 4 + 1 + 4
        XCTAssertEqual(CellGeometry.sectionHeight(size: 17, count: 3), 5)
        XCTAssertTrue(CellGeometry.isCrisp(14, count: 3))
        XCTAssertTrue(CellGeometry.isCrisp(15.5, count: 3))                      // 4.5 pt sections = 9 px
        XCTAssertFalse(CellGeometry.isCrisp(14.5, count: 3))
        XCTAssertEqual(CellGeometry.crispSize(atMost: 15.4, count: 3), 14)
    }

    func testEveryLayoutUsesCrispCells() {
        for size in [CGSize(width: 320, height: 140), CGSize(width: 320, height: 298), CGSize(width: 680, height: 298),
                     CGSize(width: 1060, height: GridLayout.bandHeight(cell: 15.5, gap: 4)), CGSize(width: 200, height: 60)] {
            let layout = GridLayout.fit(size, availableWeeks: 53)
            XCTAssertTrue(CellGeometry.isCrisp(layout.cell, count: 3), "\(size) -> \(layout.cell)")
        }
    }

    func testSampleCoversEveryCellState() {
        let days = Snapshot.sample(trackedWeeks: 17).days
        XCTAssertTrue(days.contains { !$0.usageKnown })
        for level in 1...4 {
            for sections in 0...3 {
                XCTAssertTrue(days.contains { $0.usageKnown && $0.level == level && $0.sections == sections },
                              "level \(level), \(sections) sections")
            }
        }
        let shown = Array(days.suffix(17 * 7))  // what a 17-week medium widget shows
        XCTAssertTrue(shown.contains { !$0.usageKnown })
        XCTAssertTrue(shown.contains { $0.afterburner == true })
    }

    // MARK: Layout

    // Real sizes: a medium widget is 344x164 pt on this Mac; minus 12 pt padding.
    func testMediumFitsOneBandOfAboutFourMonths() {
        let layout = GridLayout.fit(CGSize(width: 320, height: 140), availableWeeks: 53)
        XCTAssertEqual(layout.bands, 1)
        XCTAssertEqual(layout.cell, 14)
        XCTAssertEqual(layout.gap, 4)
        XCTAssertEqual(layout.weeks, 16)
    }

    func testMacOSDefaultMarginsWouldForceSmallerCells() {
        // With macOS's own 18 pt margins (308x128), 14 pt cells don't fit.
        XCTAssertLessThan(GridLayout.fit(CGSize(width: 308, height: 128), availableWeeks: 53).cell, 14)
    }

    func testLargeStacksTwoBands() {
        let layout = GridLayout.fit(CGSize(width: 320, height: 298), availableWeeks: 53)  // 344x344, header
        XCTAssertEqual(layout.bands, 2)
        XCTAssertGreaterThanOrEqual(layout.cell, 14)
        XCTAssertEqual(layout.weeks, 32)
    }

    func testExtraLargeShowsTheWholeYear() {
        let layout = GridLayout.fit(CGSize(width: 680, height: 298), availableWeeks: 53)  // 704x344, header
        XCTAssertEqual(layout.weeks, 53)
        XCTAssertEqual(layout.bands, 2)
        XCTAssertGreaterThanOrEqual(layout.cell, 14)
    }

    func testFewWeeksUseBigCellsInOneBand() {
        let layout = GridLayout.fit(CGSize(width: 680, height: 298), availableWeeks: 5)
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
        let layout = GridLayout(cell: 14, gap: 4, bands: 2, weeksPerBand: 27, weeks: 53)
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
        XCTAssertEqual(DeepLink.parse(URL(string: "claudeusagegrid://update")!), .update)
        XCTAssertNil(DeepLink.parse(URL(string: "claudeusagegrid://day/../../etc")!))
        XCTAssertNil(DeepLink.parse(URL(string: "https://example.com/day/2026-09-30")!))
    }
}
