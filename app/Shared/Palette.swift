import SwiftUI
import WidgetKit

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
    static let background = Color(hex: 0x17181c)  // also shows through the section dividers
    static let unfilled = Color(hex: 0x2e3037)    // an unfilled battery section (also days with no data)
    static let surface = Color(hex: 0x24262b)     // cards in the app's windows
    /// Orange levels 1-4 (peak 5-hour %): light and whitish for a quiet day, deep and vivid near the limit.
    static let levels = [Color(hex: 0xFDE5D2), Color(hex: 0xFAB27E), Color(hex: 0xF07A2A), Color(hex: 0xCC5500)]
    /// Afterburner: a pale, hot yellow rim with an orange glow around the cell.
    static let afterburnerRim = Color(hex: 0xFFE7A8)
    static let afterburnerGlow = Color(hex: 0xFF9F2E)
}

/// How cells are painted.
///
/// Full color uses the palette. When macOS drains a desktop widget's color
/// (another window in front, or a monochrome or tinted widget style), hue is
/// lost, so brightness carries the meaning: filled sections are clearly
/// brighter than unfilled ones and get brighter with the session level. In the tinted style, filled sections take
/// the tint.
struct CellStyle: Equatable {
    var fullColor: Bool

    static let color = CellStyle(fullColor: true)

    private static let drainedFilled: [Double] = [0.42, 0.58, 0.76, 0.95]

    func filled(level: Int) -> Color {
        let index = min(max(level, 1), 4) - 1  // usage always implies at least one session
        return fullColor ? Palette.levels[index] : Color.white.opacity(Self.drainedFilled[index])
    }

    var unfilled: Color { fullColor ? Palette.unfilled : Color.white.opacity(0.14) }
    var afterburnerRim: Color { fullColor ? Palette.afterburnerRim : Color.white }
    var afterburnerGlow: Color { fullColor ? Palette.afterburnerGlow : Color.white.opacity(0.8) }
    var label: Color { Color.white.opacity(fullColor ? 0.5 : 0.7) }
    var text: Color { Color.white.opacity(0.85) }
}

/// Geometry of a day cell drawn as a battery.
enum CellGeometry {
    /// The gap between sections, showing the background behind the cell.
    static let divider: CGFloat = 1

    static func sectionHeight(size: CGFloat, count: Int) -> CGFloat {
        (size - CGFloat(count - 1) * divider) / CGFloat(count)
    }

    /// True if every section edge lands on a whole pixel at 2x (sections are a
    /// multiple of 0.5 pt), which keeps the 1 pt dividers crisp.
    static func isCrisp(_ size: CGFloat, count: Int) -> Bool {
        let doubled = sectionHeight(size: size, count: count) * 2
        return abs(doubled - doubled.rounded()) < 0.001
    }

    /// The largest crisp size not above `size`.
    static func crispSize(atMost size: CGFloat, count: Int) -> CGFloat {
        var candidate = (size * 2).rounded(.down) / 2
        while candidate > 1, !isCrisp(candidate, count: count) { candidate -= 0.5 }
        return candidate
    }
}

/// A day square drawn as a battery: `sectionCount` full-width sections split by
/// thin gaps, filled bottom-up with the day's sessions (or, with the "usage"
/// battery source, its share of the weekly limit), in the day's orange (its
/// peak 5-hour %). An afterburner day (a 5-hour window maxed out, then real use
/// of another) gets a hot rim and glow.
struct DayCell: View {
    let day: GridDay
    let size: CGFloat
    var style: CellStyle = .color
    var sectionCount = 3

    private var corner: CGFloat { size * 0.2 }

    var body: some View {
        let battery = VStack(spacing: CellGeometry.divider) {
            ForEach((0..<sectionCount).reversed(), id: \.self) { index in
                if index < day.sections {
                    Rectangle().fill(style.filled(level: day.level)).widgetAccentable()
                } else {
                    Rectangle().fill(style.unfilled)
                }
            }
            .frame(height: CellGeometry.sectionHeight(size: size, count: sectionCount))
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: corner, style: .continuous))  // only the outer corners

        if day.afterburner == true {
            let glow = min(5, max(2.5, size * 0.16))
            // Flattened over a solid base so the glow is cast only outside the
            // cell: per-layer shadows would haze the sections and fill the dividers.
            battery
                .overlay {
                    RoundedRectangle(cornerRadius: corner, style: .continuous)
                        .strokeBorder(style.afterburnerRim, lineWidth: size >= 28 ? 2 : 1)
                        .widgetAccentable()
                }
                .background(style.fullColor ? Palette.background : Color(white: 0.1),
                            in: RoundedRectangle(cornerRadius: corner, style: .continuous))
                .compositingGroup()
                .shadow(color: style.afterburnerGlow, radius: glow)
                .shadow(color: style.afterburnerGlow.opacity(0.7), radius: glow / 2.5)
                .accessibilityLabel("Afterburner day")
        } else {
            battery
        }
    }
}
