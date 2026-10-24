import SwiftUI
import UIKit

/// A small, precise workshop: warm off-white, ink, one safety-orange accent, hairlines.
enum Theme {
    static let paper = Color(hex: 0xF4F1EA)
    static let ink = Color(hex: 0x1A1A1A)
    static let accent = Color(hex: 0xFF5A1F)
    static let hairline = Color(hex: 0xD9D4C7)
    /// Secondary text on paper (about 6:1 contrast).
    static let muted = Color(hex: 0x5E5A52)
    /// Light grey surfaces behind models and camera frames.
    static let plinthPanel = Color(hex: 0xE9E7E2)

    static let paperUI = UIColor(hex: 0xF4F1EA)
    static let inkUI = UIColor(hex: 0x1A1A1A)
    static let accentUI = UIColor(hex: 0xFF5A1F)
    static let plinthUI = UIColor(hex: 0xD8D6D1)

    static let radius: CGFloat = 10

    /// SF Mono, for every number: sizes, prices, times.
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }

    /// SF Pro.
    static func sans(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .default)
    }

    /// Best-effort swatch for a colour name from `colours_in_stock`.
    static func swatch(for name: String) -> Color {
        switch name.lowercased() {
        case "black": return Color(hex: 0x1F1F1F)
        case "white": return Color(hex: 0xFAFAFA)
        case "red": return Color(hex: 0xC62828)
        case "blue": return Color(hex: 0x1E5AA8)
        case "green": return Color(hex: 0x2E7D32)
        case "yellow": return Color(hex: 0xF2C200)
        case "orange": return accent
        case "grey", "gray", "silver": return Color(hex: 0x9E9E9E)
        case "purple": return Color(hex: 0x6A3FA0)
        case "pink": return Color(hex: 0xE06B9A)
        case "brown": return Color(hex: 0x6D4C41)
        default: return hairline
        }
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255.0,
                  green: Double((hex >> 8) & 0xFF) / 255.0,
                  blue: Double(hex & 0xFF) / 255.0)
    }
}

extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255.0,
                  green: CGFloat((hex >> 8) & 0xFF) / 255.0,
                  blue: CGFloat(hex & 0xFF) / 255.0,
                  alpha: 1)
    }
}
