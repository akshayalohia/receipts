import Foundation
import MicroFactoryCore

/// Customer-facing strings from the brief, in one place.
enum Copy {
    static let appName = "Micro Factory"
    static let shopTitle = "What should we make?"
    static let somethingElseTitle = "Something else"
    static let somethingElseBlurb = "Describe it. We'll tell you if we can print it."
    /// Product id sent for the "Something else" card (matches the `custom` pricing floor).
    static let customProductId = "custom"

    static let chatPlaceholder = "Describe it, or hold the mic to talk"

    static let measureTitle = "Measure"
    static let measureHint = "Tap two points"
    static let measureAdd = "Add"
    static let measureTypeIt = "Type it instead"

    static let viewOnDesk = "View on your desk"
    static let changeSomething = "Change something"
    static let looksGood = "Looks good"

    static let quoteTitle = "Ready to print"
    static let rowColour = "Colour"
    static let rowPrintTime = "Print time"
    static let rowMaterial = "Material"
    static let material = "PLA"
    static func pay(_ price: String) -> String { "Pay \(price)" }

    static let printing = "Printing"
    static func minutesLeft(_ minutes: Int) -> String { "\(minutes) min left" }
    static let done = "Done. Ready for pickup."
    static let waiting = "Waiting for the printer"

    static let shopTab = "Shop"
    static let ordersTab = "Orders"

    static let connectionError = "Can't reach the factory. Check the server address in settings."
}

/// Turns any error into one line for the customer.
func userMessage(for error: Error) -> String {
    if let apiError = error as? APIError {
        switch apiError {
        case .unreachable:
            return Copy.connectionError
        case .http(let status, _):
            return "The factory returned an error (\(status))."
        case .decoding:
            return "The factory sent a reply this app can't read."
        }
    }
    return Copy.connectionError
}
