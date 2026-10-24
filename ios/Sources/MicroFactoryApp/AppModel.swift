import Foundation
import Observation
import MicroFactoryCore

enum AppTab: Hashable {
    case shop
    case orders
}

enum Route: Hashable {
    case order(String)
    case preview(String)
    case quote(String)
    case live(String)
}

/// App-wide state: config, API client, catalog, orders list, navigation and the
/// per-order models (one SSE stream per open order).
@Observable
@MainActor
final class AppModel {
    static let baseURLOverrideKey = "mf.api_base_url"

    let config: AppConfig
    let deviceId: String
    private(set) var baseURLString: String
    private(set) var api: APIClient

    var catalog: Catalog?
    var catalogError: String?
    var isLoadingCatalog = false
    var startingProduct: String?

    var orders: [Order] = []
    var ordersError: String?
    var isLoadingOrders = false

    var selectedTab: AppTab = .shop
    var shopPath: [Route] = []
    var ordersPath: [Route] = []
    var showSettings = false

    @ObservationIgnored private var orderModels: [String: OrderModel] = [:]

    init() {
        let config = AppConfig.loadBundled()
        let deviceId = DeviceID.current()
        var base = config.apiBaseURL
        if let saved = UserDefaults.standard.string(forKey: AppModel.baseURLOverrideKey), !saved.isEmpty {
            base = saved
        }
        self.config = config
        self.deviceId = deviceId
        self.baseURLString = base
        self.api = AppModel.makeClient(base: base, config: config, deviceId: deviceId)
    }

    private static func makeClient(base: String, config: AppConfig, deviceId: String) -> APIClient {
        let fallback = URL(string: AppConfig.fallback.apiBaseURL) ?? URL(fileURLWithPath: "/")
        let url = URL(string: base) ?? fallback
        return APIClient(baseURL: url, appKey: config.appKey, deviceId: deviceId)
    }

    // MARK: Server address

    static func isValidBaseURL(_ text: String) -> Bool {
        guard let url = URL(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https",
              let host = url.host, !host.isEmpty else {
            return false
        }
        return true
    }

    @discardableResult
    func setBaseURL(_ text: String) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard AppModel.isValidBaseURL(trimmed) else { return false }
        UserDefaults.standard.set(trimmed, forKey: AppModel.baseURLOverrideKey)
        applyBaseURL(trimmed)
        return true
    }

    func resetBaseURL() {
        UserDefaults.standard.removeObject(forKey: AppModel.baseURLOverrideKey)
        applyBaseURL(config.apiBaseURL)
    }

    private func applyBaseURL(_ base: String) {
        for model in orderModels.values {
            model.stop()
        }
        orderModels = [:]
        baseURLString = base
        api = AppModel.makeClient(base: base, config: config, deviceId: deviceId)
        shopPath = []
        ordersPath = []
        catalog = nil
        catalogError = nil
        orders = []
        ordersError = nil
        Task { await self.loadCatalog() }
    }

    // MARK: Data

    func loadCatalog() async {
        isLoadingCatalog = true
        defer { isLoadingCatalog = false }
        do {
            catalog = try await api.catalog()
            catalogError = nil
        } catch is CancellationError {
            // view went away
        } catch {
            catalogError = userMessage(for: error)
        }
    }

    func loadOrders() async {
        isLoadingOrders = true
        defer { isLoadingOrders = false }
        do {
            let list = try await api.orders()
            orders = list.sorted { ($0.createdAt ?? "") > ($1.createdAt ?? "") }
            ordersError = nil
        } catch is CancellationError {
        } catch {
            ordersError = userMessage(for: error)
        }
    }

    func startOrder(product: String) async {
        guard startingProduct == nil else { return }
        startingProduct = product
        defer { startingProduct = nil }
        do {
            let order = try await api.createOrder(product: product)
            _ = orderModel(for: order.id, initial: order)
            catalogError = nil
            selectedTab = .shop
            shopPath.append(.order(order.id))
        } catch is CancellationError {
        } catch {
            catalogError = userMessage(for: error)
        }
    }

    /// The shared model for an order; created (and its stream started) on first use.
    func orderModel(for id: String, initial: Order? = nil) -> OrderModel {
        if let existing = orderModels[id] {
            return existing
        }
        let model = OrderModel(orderId: id, api: api, initial: initial)
        orderModels[id] = model
        model.start()
        return model
    }

    func productTitle(for productId: String?) -> String {
        guard let productId, !productId.isEmpty else { return Copy.appName }
        if productId == Copy.customProductId {
            return Copy.somethingElseTitle
        }
        if let product = catalog?.products.first(where: { $0.id == productId }) {
            return product.title
        }
        return productId.replacingOccurrences(of: "_", with: " ").capitalized
    }

    // MARK: Navigation

    var currentPath: [Route] {
        switch selectedTab {
        case .shop: return shopPath
        case .orders: return ordersPath
        }
    }

    func push(_ route: Route) {
        switch selectedTab {
        case .shop: shopPath.append(route)
        case .orders: ordersPath.append(route)
        }
    }

    func pushIfNotTop(_ route: Route) {
        if currentPath.last != route {
            push(route)
        }
    }

    /// Replaces the top screen, e.g. quote → live once payment lands.
    func replaceTop(with route: Route) {
        switch selectedTab {
        case .shop:
            if !shopPath.isEmpty { shopPath.removeLast() }
            shopPath.append(route)
        case .orders:
            if !ordersPath.isEmpty { ordersPath.removeLast() }
            ordersPath.append(route)
        }
    }

    /// Where an order opens from the Orders tab, by status.
    func routes(for order: Order) -> [Route] {
        guard let status = order.orderStatus else { return [.order(order.id)] }
        if status == .quoted {
            return [.order(order.id), .quote(order.id)]
        }
        if status.isPostPayment {
            return [.live(order.id)]
        }
        return [.order(order.id)]
    }
}
