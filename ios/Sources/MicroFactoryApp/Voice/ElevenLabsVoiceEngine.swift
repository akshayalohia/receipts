#if canImport(ElevenLabs)
import Foundation
import Combine
import ElevenLabs

/// ElevenLabs Agents voice session (elevenlabs-swift-sdk 3.4.0; calls as in its README and
/// Documentation/Usage.md).
/// - Started with the conversation token from `POST /voice/token` (private agent).
/// - Client tool `send_to_agent(text)`: posts the text to the order and answers "On it."
/// - Agent messages from SSE go in with `updateContext` (a contextual update) so the voice reads them out.
@MainActor
final class ElevenLabsVoiceEngine: VoiceEngine {
    var onSendToAgent: ((String) async -> Void)?

    private var conversation: Conversation?
    private var cancellables = Set<AnyCancellable>()
    private var handledToolCalls = Set<String>()

    func start(conversationToken: String) async throws {
        let started = try await ElevenLabs.startConversation(conversationToken: conversationToken)
        conversation = started
        started.$pendingToolCalls
            .receive(on: DispatchQueue.main)
            .sink { [weak self] calls in
                guard let self else { return }
                for call in calls {
                    self.handle(call)
                }
            }
            .store(in: &cancellables)
    }

    private func handle(_ call: ClientToolCallEvent) {
        guard !handledToolCalls.contains(call.toolCallId) else { return }
        handledToolCalls.insert(call.toolCallId)
        Task { @MainActor [weak self] in
            await self?.run(call)
        }
    }

    private func run(_ call: ClientToolCallEvent) async {
        guard let conversation else { return }
        guard call.toolName == "send_to_agent" else {
            if call.expectsResponse {
                try? await conversation.sendToolResult(for: call.toolCallId, result: "Unknown tool", isError: true)
            } else {
                conversation.markToolCallCompleted(call.toolCallId)
            }
            return
        }
        var text = ""
        if let parameters = try? call.getParameters(), let value = parameters["text"] as? String {
            text = value
        }
        if !text.isEmpty, let onSendToAgent {
            await onSendToAgent(text)
        }
        if call.expectsResponse {
            try? await conversation.sendToolResult(for: call.toolCallId, result: "On it.")
        } else {
            conversation.markToolCallCompleted(call.toolCallId)
        }
    }

    func setMicOpen(_ open: Bool) async {
        try? await conversation?.setMuted(!open)
    }

    func sendContextualUpdate(_ text: String) async {
        try? await conversation?.updateContext(text)
    }

    func stop() async {
        cancellables.removeAll()
        handledToolCalls.removeAll()
        if let conversation {
            await conversation.endConversation()
        }
        conversation = nil
    }
}
#endif
