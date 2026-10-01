import CoreGraphics

/// One column of the grid: a Sunday-first week. Days after today are nil (hidden).
struct Week: Identifiable, Equatable {
    var id: String { days.compactMap { $0?.date }.first ?? "" }
    var days: [GridDay?]

    /// Short month name when this column holds the month's first Sunday (GitHub-style labels).
    var monthLabel: String? {
        guard let sunday = days.first??.date, Format.dayOfMonth(sunday) <= 7 else { return nil }
        return Format.monthShort(sunday)
    }

    /// Splits the snapshot's days (which start on a Sunday) into weeks of 7.
    static func weeks(from days: [GridDay]) -> [Week] {
        stride(from: 0, to: days.count, by: 7).map { start in
            let chunk: [GridDay?] = Array(days[start..<min(start + 7, days.count)])
            return Week(days: chunk + Array(repeating: nil, count: 7 - chunk.count))
        }
    }
}

/// How many weeks to show and how big to draw them.
///
/// Priority: the most weeks that fit with cells of at least 14 pt, then the
/// biggest cells that still show that many. A tall widget stacks the weeks
/// into two or three bands (older band on top) instead of leaving space empty.
/// Only "crisp" cell sizes are used, whose battery sections land on whole
/// pixels (14, 15.5, 17 ... pt for 3 sections), so the dividers stay sharp.
struct GridLayout: Equatable {
    var cell: CGFloat
    var gap: CGFloat
    var bands: Int
    var weeksPerBand: Int
    var weeks: Int

    static let cellGap: CGFloat = 4
    static let dayLabelWidth: CGFloat = 24
    static let monthLabelHeight: CGFloat = 13
    static let bandSpacing: CGFloat = 8
    static let minCell: CGFloat = 14
    static let maxCell: CGFloat = 26

    static func bandHeight(cell: CGFloat, gap: CGFloat) -> CGFloat {
        monthLabelHeight + 7 * cell + 6 * gap
    }

    static func columns(width: CGFloat, cell: CGFloat, gap: CGFloat) -> Int {
        Int(((width - dayLabelWidth + gap) / (cell + gap)).rounded(.down))
    }

    static func fit(_ size: CGSize, availableWeeks: Int, maxBands: Int = 3, gap: CGFloat = cellGap,
                    sectionCount: Int = 3) -> GridLayout {
        let available = max(availableWeeks, 1)
        var best: GridLayout?
        for bands in 1...max(maxBands, 1) {
            var cell = maxCell
            while cell >= minCell {
                defer { cell -= 0.5 }
                guard CellGeometry.isCrisp(cell, count: sectionCount) else { continue }
                let height = CGFloat(bands) * bandHeight(cell: cell, gap: gap) + CGFloat(bands - 1) * bandSpacing
                let perBand = columns(width: size.width, cell: cell, gap: gap)
                let weeks = min(available, perBand * bands)
                let usesEveryBand = weeks > perBand * (bands - 1)
                if height <= size.height, perBand > 0, usesEveryBand,
                   best == nil || weeks > best!.weeks || (weeks == best!.weeks && cell > best!.cell) {
                    let perBandUsed = Int((Double(weeks) / Double(bands)).rounded(.up))
                    best = GridLayout(cell: cell, gap: gap, bands: bands, weeksPerBand: perBandUsed, weeks: weeks)
                }
            }
        }
        if let best { return best }
        // Too small for 14 pt cells: one band, as large as fits.
        let byHeight = (size.height - monthLabelHeight - 6 * gap) / 7
        let cell = max(2, CellGeometry.crispSize(atMost: min(byHeight, maxCell), count: sectionCount))
        let weeks = max(1, min(available, columns(width: size.width, cell: cell, gap: gap)))
        return GridLayout(cell: cell, gap: gap, bands: 1, weeksPerBand: weeks, weeks: weeks)
    }

    /// Width and height of the whole block of bands (labels included).
    var blockSize: CGSize {
        CGSize(width: Self.dayLabelWidth + CGFloat(weeksPerBand) * (cell + gap),
               height: CGFloat(bands) * Self.bandHeight(cell: cell, gap: gap) + CGFloat(bands - 1) * Self.bandSpacing)
    }

    /// The shown weeks split into bands, newest band last; only the first band may be short.
    func bands(of weeks: [Week]) -> [[Week]] {
        let shown = Array(weeks.suffix(self.weeks))
        var result: [[Week]] = []
        var end = shown.count
        while end > 0 {
            let start = max(0, end - weeksPerBand)
            result.insert(Array(shown[start..<end]), at: 0)
            end = start
        }
        return result
    }
}
