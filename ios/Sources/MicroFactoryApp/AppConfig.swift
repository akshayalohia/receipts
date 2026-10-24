import Foundation

/// Values from `Config.plist` (bundled resource). Edit that file before building.
struct AppConfig {
    var apiBaseURL: String
    var appKey: String
    var whopCompanyId: String
    var whopIAPKey: String

    static let fallback = AppConfig(apiBaseURL: "http://localhost:8080", appKey: "", whopCompanyId: "", whopIAPKey: "")

    static func loadBundled() -> AppConfig {
        #if SWIFT_PACKAGE
        let bundle = Bundle.module
        #else
        let bundle = Bundle.main
        #endif
        guard let url = bundle.url(forResource: "Config", withExtension: "plist"),
              let data = try? Data(contentsOf: url),
              let plist = try? PropertyListSerialization.propertyList(from: data, options: [], format: nil),
              let dict = plist as? [String: Any] else {
            return fallback
        }
        func value(_ key: String) -> String {
            let raw = dict[key] as? String ?? ""
            return raw.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        let base = value("API_BASE_URL")
        return AppConfig(
            apiBaseURL: base.isEmpty ? fallback.apiBaseURL : base,
            appKey: value("APP_KEY"),
            whopCompanyId: value("WHOP_COMPANY_ID"),
            whopIAPKey: value("WHOP_IAP_KEY")
        )
    }
}
