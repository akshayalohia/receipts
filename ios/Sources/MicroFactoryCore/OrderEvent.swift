import Foundation

/// The `printer` SSE event: `{state, progress_pct, remaining_min}`.
public struct PrinterUpdate: Decodable, Sendable, Equatable {
    public var state: String?
    public var progressPct: Int?
    public var remainingMin: Int?

    enum CodingKeys: String, CodingKey {
        case state
        case progressPct = "progress_pct"
        case remainingMin = "remaining_min"
    }

    public init(state: String?, progressPct: Int?, remainingMin: Int?) {
        self.state = state
        self.progressPct = progressPct
        self.remainingMin = remainingMin
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = c.lossyString(.state)
        progressPct = c.lossyInt(.progressPct)
        remainingMin = c.lossyInt(.remainingMin)
    }
}

/// One event from `GET /orders/{id}/stream`, decoded by its SSE event name.
public enum OrderEvent: Sendable, Equatable {
    case message(ChatMessage)
    case agentDelta(String)
    case status(String)
    case design(DesignArtifact)
    case quote(Quote)
    case printer(PrinterUpdate)
    case humanTask(String)
    case unknown(name: String, data: String)

    public static func decode(_ event: SSEEvent) throws -> OrderEvent {
        let data = Data(event.data.utf8)
        let decoder = JSONDecoder()
        switch event.event {
        case "message":
            return .message(try decoder.decode(ChatMessage.self, from: data))
        case "agent_delta":
            return .agentDelta(try decoder.decode(TextPayload.self, from: data).text)
        case "status":
            return .status(try decoder.decode(StatusPayload.self, from: data).status)
        case "design":
            return .design(try decoder.decode(DesignArtifact.self, from: data))
        case "quote":
            return .quote(try decoder.decode(Quote.self, from: data))
        case "printer":
            return .printer(try decoder.decode(PrinterUpdate.self, from: data))
        case "human_task":
            return .humanTask(try decoder.decode(KindPayload.self, from: data).kind)
        default:
            return .unknown(name: event.event, data: event.data)
        }
    }
}

struct TextPayload: Decodable {
    var text: String
}

struct StatusPayload: Decodable {
    var status: String
}

struct KindPayload: Decodable {
    var kind: String
}
