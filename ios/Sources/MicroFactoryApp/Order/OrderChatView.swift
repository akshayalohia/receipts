import SwiftUI
import UIKit
import MicroFactoryCore

/// Screen 4: the order chat, laid out like a work order. Agent lines are plain text on the
/// left; customer lines sit in an ink-outlined box. Live agent typing comes from SSE.
struct OrderChatView: View {
    @Environment(AppModel.self) private var app
    let orderId: String

    var body: some View {
        OrderChatContent(model: app.orderModel(for: orderId))
    }
}

private struct OrderChatContent: View {
    @Environment(AppModel.self) private var app
    @Bindable var model: OrderModel

    @State private var showCapture = false
    @State private var showMeasure = false
    @State private var isVisible = false
    @State private var lastSeenDesignVersion: Int?
    @FocusState private var inputFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 18) {
                        header
                        ForEach(model.messages) { message in
                            MessageRow(message: message)
                        }
                        if !model.agentDraft.isEmpty {
                            AgentLine(text: model.agentDraft, typing: true)
                        } else if model.isAgentWorking {
                            WorkingLine()
                        }
                        if let design = model.design {
                            Button {
                                app.pushIfNotTop(.preview(model.orderId))
                            } label: {
                                DesignCard(design: design, api: model.api)
                            }
                            .buttonStyle(CardPressStyle())
                            .accessibilityLabel("Open 3D preview")
                        }
                        if let quote = model.quote, model.orderStatus == .quoted {
                            Button {
                                app.pushIfNotTop(.quote(model.orderId))
                            } label: {
                                StageCard(title: Copy.quoteTitle, detail: Format.price(cents: quote.priceCents))
                            }
                            .buttonStyle(CardPressStyle())
                        }
                        if model.orderStatus?.isPostPayment == true {
                            Button {
                                app.pushIfNotTop(.live(model.orderId))
                            } label: {
                                StageCard(title: liveTitle, detail: nil)
                            }
                            .buttonStyle(CardPressStyle())
                        }
                        Color.clear
                            .frame(height: 1)
                            .id("bottom")
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 12)
                    .padding(.bottom, 8)
                }
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: model.messages.count) { _, _ in
                    scrollToBottom(proxy)
                }
                .onChange(of: model.agentDraft) { _, _ in
                    scrollToBottom(proxy)
                }
                .onChange(of: model.design?.version) { _, _ in
                    scrollToBottom(proxy)
                }
            }

            if let error = model.error {
                ErrorBanner(text: error) {
                    model.error = nil
                    Task { await model.refresh() }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 8)
            }
            if let voiceError = model.voice.lastError {
                ErrorBanner(text: voiceError)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 8)
            }

            Composer(model: model, inputFocused: $inputFocused,
                     colours: app.catalog?.coloursInStock ?? [],
                     onPhotos: { showCapture = true },
                     onMeasure: { showMeasure = true })
        }
        .navigationTitle(app.productTitle(for: model.order?.product))
        .navigationBarTitleDisplayMode(.inline)
        .workshopScreen()
        .sheet(isPresented: $showCapture) {
            CaptureView(model: model)
        }
        .fullScreenCover(isPresented: $showMeasure) {
            MeasureView { chip in
                model.addMeasurement(chip)
            }
        }
        .onAppear {
            isVisible = true
            if lastSeenDesignVersion == nil {
                lastSeenDesignVersion = model.design?.version
            }
        }
        .onDisappear {
            isVisible = false
        }
        .onChange(of: model.design?.version) { _, newVersion in
            // A new design version arrived while the chat is on screen: show it.
            guard let newVersion, newVersion != lastSeenDesignVersion else { return }
            lastSeenDesignVersion = newVersion
            if isVisible {
                app.pushIfNotTop(.preview(model.orderId))
            }
        }
        .task {
            if app.catalog == nil {
                await app.loadCatalog()
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text(model.orderId)
                    .font(Theme.mono(12))
                Text(model.status.replacingOccurrences(of: "_", with: " "))
                    .font(Theme.mono(12, .semibold))
            }
            .foregroundStyle(Theme.muted)
            Hairline()
                .padding(.top, 6)
        }
    }

    private var liveTitle: String {
        switch model.orderStatus {
        case .printing?: return Copy.printing
        case .done?: return Copy.done
        default: return Copy.waiting
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        withAnimation(.easeOut(duration: 0.2)) {
            proxy.scrollTo("bottom", anchor: .bottom)
        }
    }
}

// MARK: - Rows

private struct MessageRow: View {
    let message: ChatMessage

    var body: some View {
        if message.isUser {
            UserLine(text: message.text)
        } else if message.role == "system" {
            Text(message.text)
                .font(Theme.mono(12))
                .foregroundStyle(Theme.muted)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            AgentLine(text: message.text, typing: false)
        }
    }
}

private struct AgentLine: View {
    let text: String
    let typing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Factory")
                .font(Theme.mono(11, .medium))
                .foregroundStyle(Theme.muted)
            (Text(text) + Text(typing ? " ▍" : "").foregroundColor(Theme.accent))
                .font(Theme.sans(16))
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct UserLine: View {
    let text: String

    var body: some View {
        HStack {
            Spacer(minLength: 48)
            VStack(alignment: .leading, spacing: 4) {
                Text("You")
                    .font(Theme.mono(11, .medium))
                    .foregroundStyle(Theme.muted)
                Text(text)
                    .font(Theme.sans(16))
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            .padding(12)
            .overlay(
                RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                    .stroke(Theme.ink, lineWidth: 1)
            )
        }
    }
}

private struct WorkingLine: View {
    var body: some View {
        HStack(spacing: 8) {
            ProgressView()
                .controlSize(.small)
                .tint(Theme.ink)
            Text("Factory")
                .font(Theme.mono(11, .medium))
                .foregroundStyle(Theme.muted)
        }
        .accessibilityLabel("The factory is working on it")
    }
}

/// The latest design inline in the chat: render, version and size.
private struct DesignCard: View {
    let design: DesignArtifact
    let api: APIClient

    var body: some View {
        HStack(spacing: 14) {
            RemoteImage(url: api.resolve(design.png), api: api)
                .frame(width: 84, height: 84)
                .clipShape(RoundedRectangle(cornerRadius: Theme.radius - 2, style: .continuous))
            VStack(alignment: .leading, spacing: 6) {
                Text(design.version.map { "v\($0)" } ?? "v1")
                    .font(Theme.mono(12, .medium))
                    .foregroundStyle(Theme.muted)
                if let bbox = design.bboxMm, !bbox.isEmpty {
                    Text(Format.dimensions(bbox))
                        .font(Theme.mono(14, .medium))
                        .foregroundStyle(Theme.ink)
                }
            }
            Spacer(minLength: 0)
            Image(systemName: "cube")
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(Theme.ink)
        }
        .padding(10)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .stroke(Theme.hairline, lineWidth: 1)
        )
        .contentShape(Rectangle())
    }
}

/// A tappable stage marker in the chat (quote ready, printing).
private struct StageCard: View {
    let title: String
    let detail: String?

    var body: some View {
        HStack {
            Text(title)
                .font(Theme.sans(16, .semibold))
                .foregroundStyle(Theme.ink)
            Spacer()
            if let detail {
                Text(detail)
                    .font(Theme.mono(15, .medium))
                    .foregroundStyle(Theme.ink)
            }
            Image(systemName: "chevron.right")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Theme.ink)
        }
        .padding(14)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .stroke(Theme.accent, lineWidth: 1.5)
        )
        .contentShape(Rectangle())
    }
}

// MARK: - Composer

private struct Composer: View {
    @Bindable var model: OrderModel
    var inputFocused: FocusState<Bool>.Binding
    let colours: [String]
    let onPhotos: () -> Void
    let onMeasure: () -> Void

    @State private var micHeld = false

    var body: some View {
        VStack(spacing: 10) {
            Hairline()
            if !model.pendingPhotos.isEmpty || !model.pendingMeasurements.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(model.pendingPhotos) { photo in
                            ZStack(alignment: .topTrailing) {
                                Image(uiImage: photo.thumbnail)
                                    .resizable()
                                    .scaledToFill()
                                    .frame(width: 44, height: 44)
                                    .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                                Button {
                                    model.removePhoto(photo.id)
                                } label: {
                                    Image(systemName: "xmark")
                                        .font(.system(size: 8, weight: .bold))
                                        .foregroundStyle(Theme.paper)
                                        .frame(width: 16, height: 16)
                                        .background(Circle().fill(Theme.ink))
                                }
                                .offset(x: 5, y: -5)
                                .accessibilityLabel("Remove photo")
                            }
                        }
                        ForEach(model.pendingMeasurements) { chip in
                            MeasurementChipView(chip: chip) {
                                model.removeMeasurement(chip.id)
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 4)
                }
            }

            HStack(spacing: 8) {
                Button(action: onPhotos) {
                    PillLabel(title: photosTitle, systemImage: "camera")
                }
                .buttonStyle(.plain)
                Button(action: onMeasure) {
                    PillLabel(title: Copy.measureTitle, systemImage: "ruler")
                }
                .buttonStyle(.plain)
                if !colours.isEmpty {
                    Menu {
                        ForEach(colours, id: \.self) { name in
                            Button(name.capitalized) {
                                model.colour = name
                            }
                        }
                    } label: {
                        PillLabel(title: model.colour?.capitalized ?? Copy.rowColour, systemImage: "paintpalette",
                                  swatch: model.colour.map { Theme.swatch(for: $0) })
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 16)

            HStack(alignment: .bottom, spacing: 8) {
                TextField("Message", text: $model.draftText,
                          prompt: Text(Copy.chatPlaceholder).foregroundColor(Theme.muted),
                          axis: .vertical)
                    .font(Theme.sans(16))
                    .foregroundStyle(Theme.ink)
                    .lineLimit(1...5)
                    .focused(inputFocused)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 11)
                    .overlay(
                        RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                            .stroke(Theme.ink, lineWidth: 1)
                    )

                if VoiceController.isAvailable {
                    micButton
                }

                Button {
                    Task { await model.send() }
                } label: {
                    ZStack {
                        RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                            .fill(Theme.accent)
                        if model.isSending {
                            ProgressView()
                                .tint(Theme.ink)
                        } else {
                            Image(systemName: "arrow.up")
                                .font(.system(size: 17, weight: .bold))
                                .foregroundStyle(Theme.ink)
                        }
                    }
                    .frame(width: 44, height: 44)
                    .opacity(model.canSend ? 1 : 0.4)
                }
                .disabled(!model.canSend)
                .accessibilityLabel("Send")
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
        }
        .background(Theme.paper)
    }

    private var photosTitle: String {
        model.pendingPhotos.isEmpty ? "Photos" : "Photos \(model.pendingPhotos.count)/\(OrderModel.maxPhotos)"
    }

    /// Hold to talk: finger down opens the mic, finger up mutes it.
    private var micButton: some View {
        let live = model.voice.micOpen || micHeld
        return ZStack {
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .fill(live ? Theme.accent : Color.clear)
            RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                .stroke(Theme.ink, lineWidth: 1)
            if model.voice.phase == .connecting {
                ProgressView()
                    .tint(Theme.ink)
            } else {
                Image(systemName: live ? "mic.fill" : "mic")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Theme.ink)
            }
        }
        .frame(width: 44, height: 44)
        .contentShape(Rectangle())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in
                    guard !micHeld else { return }
                    micHeld = true
                    Task { await model.voicePressBegan() }
                }
                .onEnded { _ in
                    micHeld = false
                    Task { await model.voicePressEnded() }
                }
        )
        .accessibilityLabel("Hold to talk")
        .accessibilityAddTraits(.isButton)
        .accessibilityAction {
            if model.voice.micOpen {
                Task { await model.voicePressEnded() }
            } else {
                Task { await model.voicePressBegan() }
            }
        }
    }
}
