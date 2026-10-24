import Foundation

/// Number formatting for prices, times and sizes (shown in SF Mono in the app).
public enum Format {
    /// 1200 → "$12.00"
    public static func price(cents: Int) -> String {
        let sign = cents < 0 ? "-" : ""
        let value = abs(cents)
        let dollars = value / 100
        let rest = value % 100
        let restText = rest < 10 ? "0\(rest)" : "\(rest)"
        return "\(sign)$\(dollars).\(restText)"
    }

    /// 1200 → "from $12", 1250 → "from $12.50"
    public static func fromPrice(cents: Int) -> String {
        if cents % 100 == 0 {
            return "from $\(cents / 100)"
        }
        return "from " + price(cents: cents)
    }

    /// 1440 → "24 min", 3900 → "1 h 5 min", 7200 → "2 h". Rounds up to whole minutes.
    public static func duration(seconds: Int) -> String {
        let minutes = Int((Double(Swift.max(0, seconds)) / 60).rounded(.up))
        if minutes < 60 {
            return "\(minutes) min"
        }
        let hours = minutes / 60
        let rest = minutes % 60
        return rest == 0 ? "\(hours) h" : "\(hours) h \(rest) min"
    }

    /// 42 → "42", 31.46 → "31.5"
    public static func number(_ value: Double) -> String {
        let rounded = (value * 10).rounded() / 10
        if rounded == rounded.rounded() {
            return String(Int(rounded))
        }
        return String(format: "%.1f", rounded)
    }

    /// 42.0 → "42 mm"
    public static func mm(_ value: Double) -> String {
        number(value) + " mm"
    }

    /// [40, 31.5, 6] → "40 × 31.5 × 6 mm"
    public static func dimensions(_ bbox: [Double]) -> String {
        guard !bbox.isEmpty else { return "" }
        return bbox.map { number($0) }.joined(separator: " × ") + " mm"
    }
}
