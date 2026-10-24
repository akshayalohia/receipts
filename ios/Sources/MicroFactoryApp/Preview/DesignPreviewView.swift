import SwiftUI
import MicroFactoryCore

/// Screen 5: the design, large, on a light grey plinth. Orbit it, see it on your desk in AR,
/// ask for a change, or accept it (→ POST /accept → quote).
struct DesignPreviewView: View {
    @Environment(AppModel.self) private var app
    let orderId: String

    var body: some View {
        DesignPreviewContent(model: app.orderModel(for: orderId))
    }
}

private struct DesignPreviewContent: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    let model: OrderModel

    @State private var localURL: URL?
    @State private var loadFailed = false

    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                ModelSceneView(fileURL: localURL)
                if localURL == nil {
                    if loadFailed {
                        VStack(spacing: 10) {
                            Text(Copy.connectionError)
                                .font(Theme.sans(14))
                                .foregroundStyle(Theme.ink)
                                .multilineTextAlignment(.center)
                            Button("Retry") {
                                Task { await load() }
                            }
                            .font(Theme.sans(15, .semibold))
                            .foregroundStyle(Theme.ink)
                        }
                        .padding(24)
                    } else {
                        ProgressView()
                            .tint(Theme.ink)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    Text(dimensionsText)
                        .font(Theme.mono(17, .medium))
                        .foregroundStyle(Theme.ink)
                    Spacer()
                    if let version = model.design?.version {
                        Text("v\(version)")
                            .font(Theme.mono(13))
                            .foregroundStyle(Theme.muted)
                    }
                }
                Hairline()
                if let error = model.error {
                    ErrorBanner(text: error)
                }
                Button {
                    if let localURL {
                        ARQuickLook.present(fileURL: localURL)
                    }
                } label: {
                    Label(Copy.viewOnDesk, systemImage: "arkit")
                }
                .buttonStyle(SecondaryButtonStyle())
                .disabled(localURL == nil)

                HStack(spacing: 10) {
                    Button(Copy.changeSomething) {
                        dismiss()
                    }
                    .buttonStyle(SecondaryButtonStyle())

                    Button {
                        Task {
                            if await model.accept() {
                                app.replaceTop(with: .quote(model.orderId))
                            }
                        }
                    } label: {
                        if model.isAccepting {
                            ProgressView()
                                .tint(Theme.ink)
                        } else {
                            Text(Copy.looksGood)
                        }
                    }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(model.isAccepting || model.design == nil)
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 16)
            .padding(.bottom, 12)
        }
        .navigationTitle(app.productTitle(for: model.order?.product))
        .navigationBarTitleDisplayMode(.inline)
        .workshopScreen()
        .task(id: model.design?.usdz ?? "") {
            await load()
        }
    }

    private var dimensionsText: String {
        guard let bbox = model.design?.bboxMm, !bbox.isEmpty else { return " " }
        return Format.dimensions(bbox)
    }

    /// Downloads the USDZ to Caches/models/ (once per order + version) and shows it.
    private func load() async {
        guard let design = model.design, let remote = model.api.resolve(design.usdz) else { return }
        loadFailed = false
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        let tag = design.version.map { "v\($0)" } ?? "h\(UInt(bitPattern: remote.absoluteString.hashValue))"
        let destination = caches
            .appendingPathComponent("models", isDirectory: true)
            .appendingPathComponent("\(model.orderId)-\(tag).usdz")
        if FileManager.default.fileExists(atPath: destination.path) {
            localURL = destination
            return
        }
        localURL = nil
        do {
            localURL = try await model.api.download(remote, to: destination)
        } catch is CancellationError {
        } catch {
            loadFailed = true
        }
    }
}
