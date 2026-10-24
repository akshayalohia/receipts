import SwiftUI
import UIKit

@main
struct MicroFactoryMain: App {
    @State private var app = AppModel()

    init() {
        let tabBar = UITabBarAppearance()
        tabBar.configureWithOpaqueBackground()
        tabBar.backgroundColor = Theme.paperUI
        UITabBar.appearance().standardAppearance = tabBar
        UITabBar.appearance().scrollEdgeAppearance = tabBar
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(app)
                .tint(Theme.ink)
                .preferredColorScheme(.light)
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        @Bindable var app = app
        TabView(selection: $app.selectedTab) {
            NavigationStack(path: $app.shopPath) {
                ShopView()
                    .navigationDestination(for: Route.self) { route in
                        RouteView(route: route)
                    }
            }
            .tabItem { Label(Copy.shopTab, systemImage: "square.grid.2x2") }
            .tag(AppTab.shop)

            NavigationStack(path: $app.ordersPath) {
                OrdersView()
                    .navigationDestination(for: Route.self) { route in
                        RouteView(route: route)
                    }
            }
            .tabItem { Label(Copy.ordersTab, systemImage: "shippingbox") }
            .tag(AppTab.orders)
        }
        .sheet(isPresented: $app.showSettings) {
            SettingsView()
                .environment(app)
        }
    }
}

struct RouteView: View {
    let route: Route

    var body: some View {
        switch route {
        case .order(let id):
            OrderChatView(orderId: id)
        case .preview(let id):
            DesignPreviewView(orderId: id)
        case .quote(let id):
            QuoteView(orderId: id)
        case .live(let id):
            LivePrintView(orderId: id)
        }
    }
}
