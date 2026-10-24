import SwiftUI
import MicroFactoryCore

/// Screen 1: products from /catalog plus "Something else".
/// Long-press the wordmark for the hidden settings screen.
struct ShopView: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Wordmark()
                    .padding(.vertical, 6)
                    .contentShape(Rectangle())
                    .onLongPressGesture(minimumDuration: 0.8) {
                        app.showSettings = true
                    }
                    .accessibilityAction(named: "Settings") {
                        app.showSettings = true
                    }

                Text(Copy.shopTitle)
                    .font(Theme.sans(34, .bold))
                    .tracking(-0.6)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 24)
                    .padding(.bottom, 20)

                if let error = app.catalogError {
                    ErrorBanner(text: error) {
                        Task { await app.loadCatalog() }
                    }
                    .padding(.bottom, 16)
                }

                VStack(spacing: 12) {
                    if app.catalog == nil && app.isLoadingCatalog {
                        ForEach(0..<3, id: \.self) { _ in
                            SkeletonBlock(height: 92)
                        }
                    }
                    ForEach(products) { product in
                        productButton(id: product.id, title: product.title, blurb: product.blurb,
                                      price: product.fromPriceCents.map { Format.fromPrice(cents: $0) }, openEnded: false)
                    }
                    productButton(id: Copy.customProductId, title: Copy.somethingElseTitle,
                                  blurb: Copy.somethingElseBlurb, price: nil, openEnded: true)
                }
                .padding(.bottom, 32)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
        }
        .refreshable {
            await app.loadCatalog()
        }
        .task {
            if app.catalog == nil {
                await app.loadCatalog()
            }
        }
        .toolbar(.hidden, for: .navigationBar)
        .workshopScreen()
    }

    /// Catalog products, minus any `custom` entry (that is the "Something else" card).
    private var products: [Product] {
        (app.catalog?.products ?? []).filter { $0.id != Copy.customProductId }
    }

    private func productButton(id: String, title: String, blurb: String, price: String?, openEnded: Bool) -> some View {
        Button {
            Task { await app.startOrder(product: id) }
        } label: {
            ProductCard(title: title, blurb: blurb, price: price, isOpenEnded: openEnded,
                        isStarting: app.startingProduct == id)
        }
        .buttonStyle(CardPressStyle())
        .disabled(app.startingProduct != nil)
    }
}

struct ProductCard: View {
    let title: String
    let blurb: String
    let price: String?
    var isOpenEnded = false
    var isStarting = false

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(Theme.sans(19, .semibold))
                    .foregroundStyle(Theme.ink)
                Text(blurb)
                    .font(Theme.sans(15))
                    .foregroundStyle(Theme.muted)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
            Spacer(minLength: 8)
            if isStarting {
                ProgressView()
                    .tint(Theme.ink)
            } else if let price {
                Text(price)
                    .font(Theme.mono(14, .medium))
                    .foregroundStyle(Theme.ink)
            } else if isOpenEnded {
                Image(systemName: "arrow.right")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Theme.ink)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .fill(isOpenEnded ? Theme.paper : Color.white.opacity(0.55))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .strokeBorder(isOpenEnded ? Theme.ink : Theme.hairline,
                              style: StrokeStyle(lineWidth: 1, dash: isOpenEnded ? [4, 3] : []))
        )
        .contentShape(Rectangle())
    }
}

/// Press feedback for whole-card buttons.
struct CardPressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}
