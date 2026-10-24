import SwiftUI
import MicroFactoryCore

/// Screen 8: this device's orders (GET /orders). Opens each one where it is in the flow.
struct OrdersView: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text(Copy.ordersTab)
                    .font(Theme.sans(34, .bold))
                    .tracking(-0.6)
                    .foregroundStyle(Theme.ink)
                    .padding(.top, 8)
                    .padding(.bottom, 20)

                if let error = app.ordersError {
                    ErrorBanner(text: error) {
                        Task { await app.loadOrders() }
                    }
                    .padding(.bottom, 16)
                }

                if app.orders.isEmpty {
                    if app.isLoadingOrders {
                        VStack(spacing: 12) {
                            ForEach(0..<3, id: \.self) { _ in
                                SkeletonBlock(height: 64)
                            }
                        }
                    } else if app.ordersError == nil {
                        VStack(alignment: .leading, spacing: 14) {
                            Text("No orders yet.")
                                .font(Theme.sans(16))
                                .foregroundStyle(Theme.muted)
                            Button(Copy.shopTitle) {
                                app.selectedTab = .shop
                            }
                            .buttonStyle(SecondaryButtonStyle())
                        }
                    }
                } else {
                    VStack(spacing: 0) {
                        ForEach(app.orders) { order in
                            Button {
                                app.ordersPath = app.routes(for: order)
                            } label: {
                                OrderRow(title: app.productTitle(for: order.product), order: order)
                            }
                            .buttonStyle(CardPressStyle())
                            Hairline()
                        }
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
        .refreshable {
            await app.loadOrders()
        }
        .task {
            await app.loadOrders()
        }
        .toolbar(.hidden, for: .navigationBar)
        .workshopScreen()
    }
}

private struct OrderRow: View {
    let title: String
    let order: Order

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(Theme.sans(17, .semibold))
                    .foregroundStyle(Theme.ink)
                HStack(spacing: 8) {
                    Text(order.id)
                        .font(Theme.mono(12))
                        .foregroundStyle(Theme.muted)
                    Text(order.status.replacingOccurrences(of: "_", with: " "))
                        .font(Theme.mono(12, .semibold))
                        .foregroundStyle(Theme.ink)
                }
            }
            Spacer()
            if let cents = order.priceCents {
                Text(Format.price(cents: cents))
                    .font(Theme.mono(15, .medium))
                    .foregroundStyle(Theme.ink)
            }
            Image(systemName: "chevron.right")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Theme.muted)
        }
        .padding(.vertical, 14)
        .contentShape(Rectangle())
    }
}
