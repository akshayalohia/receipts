import SwiftUI
import UIKit
import MicroFactoryCore

/// Screen 7: the printer camera (camera.jpg every 2 s while printing), a progress ring,
/// minutes left from `printer` SSE events, and the status timeline.
struct LivePrintView: View {
    @Environment(AppModel.self) private var app
    let orderId: String

    var body: some View {
        LivePrintContent(model: app.orderModel(for: orderId))
    }
}

private struct LivePrintContent: View {
    @Environment(AppModel.self) private var app
    let model: OrderModel

    @State private var snapshot: UIImage?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text(headline)
                    .font(Theme.sans(30, .bold))
                    .tracking(-0.4)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)

                camera

                HStack(spacing: 20) {
                    ProgressRing(progress: progress)
                        .frame(width: 96, height: 96)
                    VStack(alignment: .leading, spacing: 6) {
                        if model.orderStatus == .printing, let minutes = model.printer?.remainingMin {
                            Text(Copy.minutesLeft(minutes))
                                .font(Theme.mono(22, .semibold))
                                .foregroundStyle(Theme.ink)
                        }
                        if let state = model.printer?.state, model.orderStatus == .printing {
                            Text(state)
                                .font(Theme.mono(13))
                                .foregroundStyle(Theme.muted)
                        }
                        if let position = model.order?.queuePosition, model.orderStatus == .queued {
                            Text("#\(position) in queue")
                                .font(Theme.mono(15, .medium))
                                .foregroundStyle(Theme.ink)
                        }
                    }
                    Spacer(minLength: 0)
                }

                Hairline()
                StatusTimeline(status: model.orderStatus)

                if let error = model.error {
                    ErrorBanner(text: error) {
                        Task { await model.refresh() }
                    }
                }
            }
            .padding(20)
        }
        .refreshable {
            await model.refresh()
        }
        .navigationTitle(app.productTitle(for: model.order?.product))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    app.push(.order(model.orderId))
                } label: {
                    Image(systemName: "text.bubble")
                }
                .accessibilityLabel("Order chat")
            }
        }
        .workshopScreen()
        .task(id: model.status) {
            await pollCamera()
        }
    }

    private var headline: String {
        switch model.orderStatus {
        case .printing?: return Copy.printing
        case .done?: return Copy.done
        case .paid?, .queued?: return Copy.waiting
        case .pickedUp?: return "Picked up"
        default: return model.status.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    private var progress: Double {
        switch model.orderStatus {
        case .done?, .pickedUp?: return 1
        case .printing?:
            let pct = Double(model.printer?.progressPct ?? 0)
            return min(1, max(0, pct / 100))
        default: return 0
        }
    }

    private var camera: some View {
        ZStack {
            Theme.plinthPanel
            if let snapshot {
                Image(uiImage: snapshot)
                    .resizable()
                    .scaledToFill()
            } else {
                Image(systemName: model.orderStatus == .printing ? "video" : "printer")
                    .font(.system(size: 28, weight: .light))
                    .foregroundStyle(Theme.muted)
            }
        }
        .aspectRatio(4.0 / 3.0, contentMode: .fit)
        .frame(maxWidth: .infinity)
        .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .stroke(Theme.hairline, lineWidth: 1)
        )
        .accessibilityLabel("Printer camera")
    }

    /// GET /orders/{id}/camera.jpg every 2 s, only while the order is printing.
    private func pollCamera() async {
        while !Task.isCancelled && model.orderStatus == .printing {
            do {
                let data = try await model.api.cameraSnapshot(orderId: model.orderId)
                if let image = UIImage(data: data) {
                    snapshot = image
                }
            } catch is CancellationError {
                return
            } catch {
                // keep the last frame; try again next tick
            }
            do {
                try await Task.sleep(nanoseconds: 2_000_000_000)
            } catch {
                return
            }
        }
    }
}

struct ProgressRing: View {
    var progress: Double

    var body: some View {
        ZStack {
            Circle()
                .stroke(Theme.hairline, lineWidth: 8)
            Circle()
                .trim(from: 0, to: progress)
                .stroke(Theme.accent, style: StrokeStyle(lineWidth: 8, lineCap: .butt))
                .rotationEffect(.degrees(-90))
                .animation(.easeOut(duration: 0.4), value: progress)
            Text("\(Int((progress * 100).rounded()))%")
                .font(Theme.mono(18, .semibold))
                .foregroundStyle(Theme.ink)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Progress \(Int((progress * 100).rounded())) percent")
    }
}

/// Paid → Queued → Printing → Done.
struct StatusTimeline: View {
    let status: OrderStatus?

    private let steps: [(OrderStatus, String)] = [
        (.paid, "Paid"),
        (.queued, "Queued"),
        (.printing, "Printing"),
        (.done, "Done"),
    ]

    private var currentIndex: Int {
        switch status {
        case .paid?: return 0
        case .queued?: return 1
        case .printing?: return 2
        case .done?, .pickedUp?: return 3
        default: return -1
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                HStack(spacing: 12) {
                    marker(for: index)
                    Text(step.1)
                        .font(Theme.sans(16, index == currentIndex ? .semibold : .regular))
                        .foregroundStyle(index <= currentIndex ? Theme.ink : Theme.muted)
                    Spacer()
                }
                .frame(height: 40)
            }
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private func marker(for index: Int) -> some View {
        let shape = RoundedRectangle(cornerRadius: 3, style: .continuous)
        if index < currentIndex || (index == currentIndex && status == .done) || status == .pickedUp {
            shape.fill(Theme.ink)
                .frame(width: 14, height: 14)
                .overlay(
                    Image(systemName: "checkmark")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(Theme.paper)
                )
        } else if index == currentIndex {
            shape.fill(Theme.accent)
                .frame(width: 14, height: 14)
        } else {
            shape.stroke(Theme.hairline, lineWidth: 1.5)
                .frame(width: 14, height: 14)
        }
    }
}
