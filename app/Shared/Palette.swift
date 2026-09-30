import SwiftUI

extension Color {
    init(hex: UInt32) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xff) / 255,
                  green: Double((hex >> 8) & 0xff) / 255,
                  blue: Double(hex & 0xff) / 255)
    }
}

/// The grid's fixed dark palette.
enum Palette {
    static let background = Color(hex: 0x17181c)
    static let emptyCell = Color(hex: 0x24262b)
    static let barSlot = Color(hex: 0x2e3037)
    static let barFill = Color(hex: 0xfff1e6)
    static let levels = [Color(hex: 0x5b3a2a), Color(hex: 0x8f5132), Color(hex: 0xc8693c), Color(hex: 0xf0884a)]
}

/// How cells are painted.
///
/// Full color uses the palette. When macOS drains a desktop widget's color
/// (another window in front, or a monochrome widget style), hue is lost, so
/// levels are drawn as rising white opacity and bars as white on dark slots:
/// both still read by brightness alone.
struct CellStyle: Equatable {
    var fullColor: Bool

    static let color = CellStyle(fullColor: true)

    private static let drainedLevels: [Double] = [0.07, 0.18, 0.30, 0.45, 0.62]

    func fill(level: Int) -> Color {
        let level = min(max(level, 0), 4)
        if fullColor { return level == 0 ? Palette.emptyCell : Palette.levels[level - 1] }
        return Color.white.opacity(Self.drainedLevels[level])
    }

    var barSlot: Color { fullColor ? Palette.barSlot : Color.black.opacity(0.5) }
    var barFill: Color { fullColor ? Palette.barFill : Color.white }
    var label: Color { Color.white.opacity(fullColor ? 0.5 : 0.7) }
    var text: Color { Color.white.opacity(0.85) }
}
