import SwiftUI
import MicroFactoryCore

/// Screen 6: price, colour, print time, material and ETA, then Pay.
/// Pays with the native WhopCheckout sheet when the SDK is linked, else opens
/// `whop_purchase_url` in Safari. The order moves on when the server's webhook marks it paid.
struct QuoteView: View {
    @Environment(AppModel.self) private var app
    let orderId: String

    var body: some View {
        QuoteContent(model: app.orderModel(for: orderId))
    }
}

private struct QuoteContent: View {
    @Environment(AppModel.self) private var app
    let model: OrderModel

    @State private var safari: IdentifiedURL?
    @State private var isPaying = false
    @State private var payError: String?

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text(Copy.quoteTitle)
                        .font(Theme.sans(30, .bold))
                        .tracking(-0.4)
                        .foregroundStyle(Theme.ink)

                    if let png = model.design?.png {
                        RemoteImage(url: model.api.resolve(png), api: model.api)
                            .frame(height: 220)
                            .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
                    }

                    if let quote = model.quote {
                        Text(Format.price(cents: quote.priceCents))
                            .font(Theme.mono(44, .semibold))
                            .foregroundStyle(Theme.ink)
                        VStack(spacing: 0) {
                            row(Copy.rowColour, value: (quote.colour ?? model.order?.colour ?? model.colour)?.capitalized ?? "", swatch: quote.colour ?? model.order?.colour, mono: false)
                            Hairline()
                            row(Copy.rowPrintTime, value: quote.printSeconds.map { Format.duration(seconds: $0) } ?? "", swatch: nil, mono: true)
                            Hairline()
                            row(Copy.rowMaterial, value: Copy.material, swatch: nil, mono: false)
                            if let eta = quote.eta ?? model.order?.eta, !eta.isEmpty {
                                Hairline()
                                row("ETA", value: ETAFormat.display(eta), swatch: nil, mono: true)
                            }
                        }
                        .overlay(
                            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                                .stroke(Theme.hairline, lineWidth: 1)
                        )
                    } else {
                        SkeletonBlock(height: 52)
                            .frame(width: 160)
                        SkeletonBlock(height: 150)
                    }

                    if let message = payError ?? model.error {
                        ErrorBanner(text: message)
                    }
                }
                .padding(20)
            }

            VStack(spacing: 10) {
                Button {
                    Task { await pay() }
                } label: {
                    if isPaying {
                        ProgressView()
                            .tint(Theme.ink)
                    } else {
                        Text(payTitle)
                            .font(Theme.mono(17, .semibold))
                    }
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(model.quote == nil || isPaying)

                if payError != nil, let url = model.purchaseURL {
                    Button("Pay in the browser instead") {
                        safari = IdentifiedURL(url: url)
                    }
                    .font(Theme.sans(15, .medium))
                    .foregroundStyle(Theme.ink)
                    .underline()
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
        }
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .workshopScreen()
        .sheet(item: $safari) { item in
            SafariView(url: item.url) {
                safari = nil
                Task { await afterBrowserCheckout() }
            }
            .ignoresSafeArea()
        }
        .onChange(of: model.status) { _, newStatus in
            if OrderStatus(rawValue: newStatus)?.isPostPayment == true {
                app.replaceTop(with: .live(model.orderId))
            }
        }
    }

    private var payTitle: String {
        guard let quote = model.quote else { return Copy.pay("") }
        return Copy.pay(Format.price(cents: quote.priceCents))
    }

    @ViewBuilder
    private func row(_ title: String, value: String, swatch: String?, mono: Bool) -> some View {
        HStack(spacing: 8) {
            Text(title)
                .font(Theme.sans(16))
                .foregroundStyle(Theme.muted)
            Spacer()
            if let swatch {
                RoundedRectangle(cornerRadius: 3, style: .continuous)
                    .fill(Theme.swatch(for: swatch))
                    .frame(width: 14, height: 14)
                    .overlay(RoundedRectangle(cornerRadius: 3, style: .continuous).stroke(Theme.ink.opacity(0.3), lineWidth: 1))
            }
            Text(value)
                .font(mono ? Theme.mono(16, .medium) : Theme.sans(16, .medium))
                .foregroundStyle(Theme.ink)
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 50)
    }

    private func pay() async {
        payError = nil
        isPaying = true
        defer { isPaying = false }

        #if canImport(WhopCheckout)
        if let variant = model.variantId, !app.config.whopCompanyId.isEmpty, !app.config.whopIAPKey.isEmpty {
            do {
                try await WhopNativeCheckout.purchase(planId: variant, config: app.config)
                app.replaceTop(with: .live(model.orderId))
            } catch {
                payError = "The checkout didn't finish."
            }
            return
        }
        #endif

        if model.purchaseURL == nil {
            await model.refresh()
        }
        if let url = model.purchaseURL {
            safari = IdentifiedURL(url: url)
        } else {
            payError = "No checkout link yet. Try again in a moment."
        }
    }

    private func afterBrowserCheckout() async {
        await model.refresh()
        if model.orderStatus?.isPostPayment == true {
            app.replaceTop(with: .live(model.orderId))
        }
    }
}

/// Shows ISO-8601 ETAs as a local time; anything else is shown as sent.
enum ETAFormat {
    static func display(_ raw: String) -> String {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime]
        var date = parser.date(from: raw)
        if date == nil {
            parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            date = parser.date(from: raw)
        }
        guard let date else { return raw }
        let formatter = DateFormatter()
        formatter.dateStyle = Calendar.current.isDateInToday(date) ? .none : .short
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }
}
