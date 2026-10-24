import Foundation

/// One dispatched Server-Sent Event.
public struct SSEEvent: Sendable, Equatable {
    /// The `event:` field, or "message" when the server sent none.
    public var event: String
    /// All `data:` lines joined with "\n".
    public var data: String
    /// The last `id:` seen on the stream, if any.
    public var id: String?

    public init(event: String, data: String, id: String? = nil) {
        self.event = event
        self.data = data
        self.id = id
    }
}

/// Splits a byte stream into lines. Accepts "\n", "\r\n" and "\r" terminators.
/// (Used instead of `AsyncBytes.lines`, which drops the blank lines SSE needs.)
public struct SSELineSplitter: Sendable {
    private var buffer: [UInt8] = []
    private var lastWasCarriageReturn = false

    public init() {}

    /// Feeds one byte. Returns a completed line (without its terminator) when one ends.
    public mutating func feed(_ byte: UInt8) -> String? {
        if byte == 0x0A {
            if lastWasCarriageReturn {
                lastWasCarriageReturn = false
                return nil
            }
            return flush()
        }
        lastWasCarriageReturn = false
        if byte == 0x0D {
            lastWasCarriageReturn = true
            return flush()
        }
        buffer.append(byte)
        return nil
    }

    /// Returns any unterminated trailing text.
    public mutating func finish() -> String? {
        if buffer.isEmpty { return nil }
        return flush()
    }

    private mutating func flush() -> String {
        let line = String(decoding: buffer, as: UTF8.self)
        buffer.removeAll(keepingCapacity: true)
        return line
    }
}

/// The SSE field parser from the WHATWG spec, one line at a time.
public struct SSEParser: Sendable {
    private var eventName = ""
    private var dataLines: [String] = []
    public private(set) var lastEventId: String?
    /// Reconnect delay requested by the server with `retry:`, in milliseconds.
    public private(set) var retryMilliseconds: Int?

    public init() {}

    /// Feeds one line (no terminator). Returns an event when a blank line dispatches one.
    public mutating func feed(line: String) -> SSEEvent? {
        if line.isEmpty {
            return dispatch()
        }
        if line.hasPrefix(":") {
            return nil // comment, e.g. the 15 s heartbeat
        }
        let field: String
        var value: String
        if let colon = line.firstIndex(of: ":") {
            field = String(line[line.startIndex..<colon])
            value = String(line[line.index(after: colon)...])
            if value.hasPrefix(" ") {
                value.removeFirst()
            }
        } else {
            field = line
            value = ""
        }
        switch field {
        case "event":
            eventName = value
        case "data":
            dataLines.append(value)
        case "id":
            if !value.contains("\u{0}") {
                lastEventId = value
            }
        case "retry":
            if !value.isEmpty, value.allSatisfy({ $0.isASCII && $0.isNumber }), let millis = Int(value) {
                retryMilliseconds = millis
            }
        default:
            break
        }
        return nil
    }

    private mutating func dispatch() -> SSEEvent? {
        let name = eventName.isEmpty ? "message" : eventName
        let lines = dataLines
        eventName = ""
        dataLines = []
        if lines.isEmpty {
            return nil
        }
        return SSEEvent(event: name, data: lines.joined(separator: "\n"), id: lastEventId)
    }

    /// Parses a complete SSE text body. Handy for tests and fixtures.
    public static func events(from text: String) -> [SSEEvent] {
        var splitter = SSELineSplitter()
        var parser = SSEParser()
        var result: [SSEEvent] = []
        for byte in Array(text.utf8) {
            if let line = splitter.feed(byte), let event = parser.feed(line: line) {
                result.append(event)
            }
        }
        return result
    }
}
