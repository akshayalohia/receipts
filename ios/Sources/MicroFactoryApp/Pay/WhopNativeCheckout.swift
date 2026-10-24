#if canImport(WhopCheckout)
import Foundation
import WhopCheckout

/// Native Whop checkout (WhopCheckout SDK, docs.whop.com checkout reference), purchasing the
/// one-time plan (`plan_...`, the order's `whop_variant_id`) the server created for this quote.
/// Fulfilment happens only from the server's Whop webhook; a successful return here just
/// moves the app to the live screen.
@MainActor
enum WhopNativeCheckout {
    private static var configured = false

    static func purchase(planId: String, config: AppConfig) async throws {
        if !configured {
            // No StoreKit fallback: per-order plans have no App Store product to map to.
            try await Checkout.shared.configure(companyId: config.whopCompanyId,
                                                apiKey: config.whopIAPKey,
                                                planMappings: [])
            configured = true
        }
        _ = try await Checkout.shared.purchase(planId)
    }
}
#endif
