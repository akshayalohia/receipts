import Foundation
import Observation
import MicroFactoryCore

/// A live voice session. The ElevenLabs implementation lives in ElevenLabsVoiceEngine.swift,
/// compiled only when the SDK is linked.
@MainActor
protocol VoiceEngine: AnyObject {
    /// Called when the voice agent uses the `send_to_agent(text)` client tool.
    var onSendToAgent: ((String) async -> Void)? { get set }
    func start(conversationToken: String) async throws
    func setMicOpen(_ open: Bool) async
    func sendContextualUpdate(_ text: String) async
    func stop() async
}

/// Hold-to-talk voice for one order. Without the ElevenLabs SDK, `isAvailable` is false
/// and the chat is text only.
@Observable
@MainActor
final class VoiceController {
    enum Phase: Equatable {
        case off
        case connecting
        case live
    }

    private(set) var phase: Phase = .off
    private(set) var micOpen = false
    var lastError: String?

    @ObservationIgnored private var engine: (any VoiceEngine)?
    @ObservationIgnored private var held = false

    static var isAvailable: Bool {
        #if canImport(ElevenLabs)
        return true
        #else
        return false
        #endif
    }

    private static func makeEngine() -> (any VoiceEngine)? {
        #if canImport(ElevenLabs)
        return ElevenLabsVoiceEngine()
        #else
        return nil
        #endif
    }

    /// Finger down on the mic: start the session if needed, then open the mic.
    func pressBegan(orderId: String, api: APIClient, onSendToAgent: @escaping (String) async -> Void) async {
        held = true
        lastError = nil
        if phase == .connecting {
            return // the connect in flight will open the mic if the finger is still down
        }
        if engine == nil {
            guard let newEngine = VoiceController.makeEngine() else { return }
            phase = .connecting
            do {
                let token = try await api.voiceToken(orderId: orderId)
                newEngine.onSendToAgent = onSendToAgent
                try await newEngine.start(conversationToken: token.conversationToken)
                engine = newEngine
                phase = .live
            } catch {
                phase = .off
                lastError = "Voice isn't available right now. Type instead."
                return
            }
        }
        guard let engine else { return }
        let open = held
        await engine.setMicOpen(open)
        micOpen = open
    }

    /// Finger up: mute, keep the session so the agent can keep talking.
    func pressEnded() async {
        held = false
        guard let engine else { return }
        await engine.setMicOpen(false)
        micOpen = false
    }

    /// An agent message arrived over SSE: hand it to the voice session to read out.
    func agentSaid(_ text: String) {
        guard let engine, phase == .live, !text.isEmpty else { return }
        Task { await engine.sendContextualUpdate(text) }
    }

    func end() async {
        held = false
        micOpen = false
        phase = .off
        let current = engine
        engine = nil
        if let current {
            await current.stop()
        }
    }
}
