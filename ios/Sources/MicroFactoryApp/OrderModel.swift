import Foundation
import Observation
import UIKit
import MicroFactoryCore

/// A photo waiting to be uploaded with the next message.
struct PendingPhoto: Identifiable {
    let id = UUID()
    let jpeg: Data
    let thumbnail: UIImage

    /// Downscales to at most 2048 px and re-encodes as JPEG (HEIC/PNG from the library included).
    @MainActor
    static func make(from image: UIImage) -> PendingPhoto? {
        guard let jpeg = resized(image, maxDimension: 2048).jpegData(compressionQuality: 0.85) else { return nil }
        return PendingPhoto(jpeg: jpeg, thumbnail: resized(image, maxDimension: 240))
    }

    @MainActor
    private static func resized(_ image: UIImage, maxDimension: CGFloat) -> UIImage {
        let size = image.size
        let longest = max(size.width, size.height)
        guard longest > 0 else { return image }
        let scale = min(1, maxDimension / longest)
        let target = CGSize(width: (size.width * scale).rounded(), height: (size.height * scale).rounded())
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let renderer = UIGraphicsImageRenderer(size: target, format: format)
        return renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: target))
        }
    }
}

/// One order: its messages, live agent typing, latest design, quote and printer state,
/// all kept current by the order's SSE stream.
@Observable
@MainActor
final class OrderModel {
    static let maxPhotos = 4

    let orderId: String
    let api: APIClient
    let voice = VoiceController()

    var order: Order?
    var messages: [ChatMessage] = []
    /// Agent reply being typed right now (from `agent_delta`).
    var agentDraft = ""
    var awaitingReply = false
    var design: DesignArtifact?
    var quote: Quote?
    var printer: PrinterUpdate?
    var humanTask: String?
    var error: String?
    var isSending = false
    var isAccepting = false

    // Composer
    var draftText = ""
    var pendingPhotos: [PendingPhoto] = []
    var pendingMeasurements: [MeasurementChip] = []
    var colour: String?

    @ObservationIgnored private var streamTask: Task<Void, Never>?

    init(orderId: String, api: APIClient, initial: Order?) {
        self.orderId = orderId
        self.api = api
        self.order = initial
        self.colour = initial?.colour
    }

    var status: String { order?.status ?? OrderStatus.draft.rawValue }
    var orderStatus: OrderStatus? { OrderStatus(rawValue: status) }
    var isAgentWorking: Bool { awaitingReply || orderStatus == .designing }

    var canSend: Bool {
        !isSending && !draftText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var purchaseURL: URL? {
        api.resolve(order?.whopPurchaseUrl ?? quote?.whopPurchaseUrl)
    }

    var variantId: String? {
        quote?.whopVariantId ?? order?.whopVariantId
    }

    // MARK: Lifecycle

    func start() {
        guard streamTask == nil else { return }
        let client = SSEClient(request: api.streamRequest(orderId: orderId))
        streamTask = Task { [weak self] in
            for await item in client.stream() {
                guard let self else { return }
                switch item {
                case .connected:
                    // (Re)connected: catch up on anything missed while offline.
                    Task { await self.refresh() }
                case .event(let raw):
                    if let event = try? OrderEvent.decode(raw) {
                        self.apply(event)
                    }
                }
            }
        }
        Task { await self.refresh() }
    }

    func stop() {
        streamTask?.cancel()
        streamTask = nil
        let voice = self.voice
        Task { await voice.end() }
    }

    func refresh() async {
        do {
            let detail = try await api.order(id: orderId)
            order = detail.order
            if !detail.messages.isEmpty || messages.isEmpty {
                let serverKeys = Set(detail.messages.map { $0.role + "|" + $0.text })
                let unsentLocal = messages.filter { $0.id.hasPrefix("local-") && !serverKeys.contains($0.role + "|" + $0.text) }
                messages = detail.messages + unsentLocal
            }
            if let latest = detail.latestDesign {
                design = latest
            }
            if let latestQuote = detail.effectiveQuote, detail.order.orderStatus != .draft {
                quote = latestQuote
            }
            if colour == nil {
                colour = detail.order.colour
            }
            error = nil
        } catch is CancellationError {
        } catch {
            self.error = userMessage(for: error)
        }
    }

    // MARK: Stream events

    func apply(_ event: OrderEvent) {
        switch event {
        case .message(let message):
            if message.isAgent {
                agentDraft = ""
                awaitingReply = false
                voice.agentSaid(message.text)
            }
            if let index = messages.firstIndex(where: { $0.id.hasPrefix("local-") && $0.role == message.role && $0.text == message.text }) {
                messages[index] = message // server echo of our optimistic message
            } else if !messages.suffix(3).contains(where: { $0.role == message.role && $0.text == message.text }) {
                messages.append(message)
            }
        case .agentDelta(let text):
            agentDraft += text
        case .status(let status):
            if order != nil {
                order?.status = status
            } else {
                Task { await self.refresh() }
            }
            if status == OrderStatus.review.rawValue || status == OrderStatus.quoted.rawValue {
                awaitingReply = false
            }
        case .design(let artifact):
            design = artifact
            awaitingReply = false
        case .quote(let newQuote):
            quote = newQuote
            // The purchase URL lives on the order; fetch it.
            Task { await self.refresh() }
        case .printer(let update):
            printer = update
        case .humanTask(let kind):
            humanTask = kind
        case .unknown:
            break
        }
    }

    // MARK: Actions

    func send() async {
        let text = draftText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isSending else { return }
        let sent = await postUserMessage(text)
        if sent {
            draftText = ""
        }
    }

    /// Called by the voice agent's `send_to_agent` client tool.
    func sendFromVoice(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        _ = await postUserMessage(trimmed)
    }

    /// Uploads pending photos, then posts the message with pending measurements and colour.
    private func postUserMessage(_ text: String) async -> Bool {
        isSending = true
        error = nil
        defer { isSending = false }
        do {
            if !pendingPhotos.isEmpty {
                _ = try await api.uploadPhotos(orderId: orderId, jpegs: pendingPhotos.map { $0.jpeg })
                pendingPhotos = []
            }
            let local = ChatMessage(id: "local-\(UUID().uuidString)", role: "user", text: text)
            messages.append(local)
            let chips = pendingMeasurements
            do {
                try await api.postMessage(orderId: orderId, text: text, measurements: chips, colour: colour)
            } catch {
                messages.removeAll { $0.id == local.id }
                throw error
            }
            pendingMeasurements = []
            awaitingReply = true
            return true
        } catch is CancellationError {
            return false
        } catch {
            self.error = userMessage(for: error)
            return false
        }
    }

    /// "Looks good" → POST /accept. The quote arrives later over SSE.
    func accept() async -> Bool {
        isAccepting = true
        error = nil
        defer { isAccepting = false }
        do {
            try await api.accept(orderId: orderId)
            return true
        } catch {
            self.error = userMessage(for: error)
            return false
        }
    }

    func addPhoto(_ image: UIImage) {
        guard pendingPhotos.count < OrderModel.maxPhotos, let photo = PendingPhoto.make(from: image) else { return }
        pendingPhotos.append(photo)
    }

    func removePhoto(_ id: UUID) {
        pendingPhotos.removeAll { $0.id == id }
    }

    func addMeasurement(_ chip: MeasurementChip) {
        pendingMeasurements.append(chip)
    }

    func removeMeasurement(_ id: UUID) {
        pendingMeasurements.removeAll { $0.id == id }
    }

    // MARK: Voice

    func voicePressBegan() async {
        await voice.pressBegan(orderId: orderId, api: api) { [weak self] text in
            await self?.sendFromVoice(text)
        }
    }

    func voicePressEnded() async {
        await voice.pressEnded()
    }
}
