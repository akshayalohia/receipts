import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public enum SSEError: Error, Equatable {
    case badStatus(Int)
    case unsupportedPlatform
}

/// What the SSE stream yields: a marker each time a connection opens, then events.
public enum SSEStreamItem: Sendable, Equatable {
    case connected
    case event(SSEEvent)
}

/// Reads an SSE endpoint with `URLSession.bytes(for:)` and reconnects with
/// exponential backoff until the consuming task is cancelled.
public final class SSEClient: @unchecked Sendable {
    private let request: URLRequest
    private let session: URLSession
    private let minimumDelay: Double
    private let maximumDelay: Double

    public init(request: URLRequest, session: URLSession = .shared,
                minimumDelay: Double = 1, maximumDelay: Double = 30) {
        self.request = request
        self.session = session
        self.minimumDelay = minimumDelay
        self.maximumDelay = maximumDelay
    }

    /// Delay before reconnect attempt `attempt` (1-based): 1, 2, 4, 8 ... capped.
    public static func backoffDelay(attempt: Int, minimum: Double, maximum: Double) -> Double {
        let exponent = Double(Swift.max(0, attempt - 1))
        return Swift.min(maximum, minimum * pow(2.0, exponent))
    }

    public func stream() -> AsyncStream<SSEStreamItem> {
        AsyncStream { continuation in
            let task = Task {
                await self.run(continuation)
                continuation.finish()
            }
            continuation.onTermination = { _ in
                task.cancel()
            }
        }
    }

    private func run(_ continuation: AsyncStream<SSEStreamItem>.Continuation) async {
        var attempt = 0
        var state = ConnectionState()
        while !Task.isCancelled {
            do {
                try await connectOnce(&state, continuation: continuation)
            } catch {
                if Task.isCancelled { break }
            }
            if Task.isCancelled { break }
            if state.receivedAnything {
                attempt = 0 // the last connection worked: start the backoff again from the bottom
                state.receivedAnything = false
            }
            attempt += 1
            let backoff = SSEClient.backoffDelay(attempt: attempt, minimum: minimumDelay, maximum: maximumDelay)
            var serverRetry: Double = 0
            if let millis = state.retryMilliseconds {
                serverRetry = Double(millis) / 1000
            }
            let delay = Swift.max(serverRetry, backoff)
            do {
                try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            } catch {
                break
            }
        }
    }

    private struct ConnectionState {
        var lastEventId: String? = nil
        var retryMilliseconds: Int? = nil
        var receivedAnything = false
    }

    private func makeRequest(lastEventId: String?) -> URLRequest {
        var req = request
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        req.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        if let lastEventId {
            req.setValue(lastEventId, forHTTPHeaderField: "Last-Event-ID")
        }
        // Idle timeout between bytes; the server sends a heartbeat every 15 s.
        req.timeoutInterval = 60
        return req
    }

    #if canImport(FoundationNetworking)
    private func connectOnce(_ state: inout ConnectionState,
                             continuation: AsyncStream<SSEStreamItem>.Continuation) async throws {
        // swift-corelibs-foundation has no URLSession.bytes(for:). The app only runs on iOS;
        // on Linux this type exists so Core (and its parser tests) still compile.
        throw SSEError.unsupportedPlatform
    }
    #else
    private func connectOnce(_ state: inout ConnectionState,
                             continuation: AsyncStream<SSEStreamItem>.Continuation) async throws {
        let request = makeRequest(lastEventId: state.lastEventId)
        let (bytes, response) = try await session.bytes(for: request)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw SSEError.badStatus(http.statusCode)
        }
        continuation.yield(.connected)
        var splitter = SSELineSplitter()
        var parser = SSEParser()
        for try await byte in bytes {
            state.receivedAnything = true
            if let line = splitter.feed(byte), let event = parser.feed(line: line) {
                if let id = event.id {
                    state.lastEventId = id
                }
                continuation.yield(.event(event))
            }
            if let millis = parser.retryMilliseconds {
                state.retryMilliseconds = millis
            }
        }
    }
    #endif
}
