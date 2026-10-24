import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public enum APIError: Error, Equatable, Sendable {
    /// No connection, DNS failure, timeout, TLS failure and the like.
    case unreachable
    case http(status: Int, body: String)
    case decoding(String)
}

/// One file part of a multipart/form-data body.
public struct MultipartFile: Sendable {
    public var field: String
    public var filename: String
    public var mimeType: String
    public var data: Data

    public init(field: String, filename: String, mimeType: String, data: Data) {
        self.field = field
        self.filename = filename
        self.mimeType = mimeType
        self.data = data
    }
}

public enum Multipart {
    public static func body(boundary: String, files: [MultipartFile]) -> Data {
        var body = Data()
        for file in files {
            body.append(Data("--\(boundary)\r\n".utf8))
            body.append(Data("Content-Disposition: form-data; name=\"\(file.field)\"; filename=\"\(file.filename)\"\r\n".utf8))
            body.append(Data("Content-Type: \(file.mimeType)\r\n\r\n".utf8))
            body.append(file.data)
            body.append(Data("\r\n".utf8))
        }
        body.append(Data("--\(boundary)--\r\n".utf8))
        return body
    }
}

/// Persistent per-install customer id (no accounts in the MVP), sent as `X-Device-Id`.
public enum DeviceID {
    public static let defaultsKey = "mf.device_id"

    public static func current(in defaults: UserDefaults = .standard) -> String {
        if let existing = defaults.string(forKey: defaultsKey), !existing.isEmpty {
            return existing
        }
        let created = UUID().uuidString.lowercased()
        defaults.set(created, forKey: defaultsKey)
        return created
    }
}

/// async/await client for the factory HTTP API (SPEC.md "HTTP API").
/// Every request to the factory host carries `X-App-Key` and `X-Device-Id`.
public final class APIClient: @unchecked Sendable {
    public let baseURL: URL
    public let appKey: String
    public let deviceId: String
    private let session: URLSession

    public init(baseURL: URL, appKey: String, deviceId: String, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.appKey = appKey
        self.deviceId = deviceId
        self.session = session
    }

    // MARK: URLs

    /// `path` appended to the base URL (keeps any path prefix on the base URL).
    public func url(_ path: String) -> URL {
        var base = baseURL.absoluteString
        while base.hasSuffix("/") { base.removeLast() }
        var tail = path
        while tail.hasPrefix("/") { tail.removeFirst() }
        return URL(string: base + "/" + tail) ?? baseURL
    }

    /// Absolute URLs pass through; relative ones (e.g. `/files/ord_1/model.usdz`) are joined to the base URL.
    public func resolve(_ string: String?) -> URL? {
        guard let string, !string.isEmpty else { return nil }
        let lower = string.lowercased()
        if lower.hasPrefix("http://") || lower.hasPrefix("https://") {
            return URL(string: string)
        }
        return url(string)
    }

    func isFactoryHost(_ url: URL) -> Bool {
        url.host?.lowercased() == baseURL.host?.lowercased() && url.port == baseURL.port
    }

    static func pathComponent(_ value: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }

    public func makeRequest(_ method: String, url: URL, body: Data? = nil, contentType: String? = nil) -> URLRequest {
        var request = URLRequest(url: url)
        request.httpMethod = method
        if isFactoryHost(url) {
            request.setValue(appKey, forHTTPHeaderField: "X-App-Key")
            request.setValue(deviceId, forHTTPHeaderField: "X-Device-Id")
        }
        if let body {
            request.httpBody = body
        }
        if let contentType {
            request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }
        return request
    }

    // MARK: Transport

    private func perform(_ request: URLRequest) async throws -> (Data, URLResponse) {
        #if canImport(FoundationNetworking)
        return try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<(Data, URLResponse), Error>) in
            let task = session.dataTask(with: request) { data, response, error in
                if let error {
                    continuation.resume(throwing: error)
                } else if let data, let response {
                    continuation.resume(returning: (data, response))
                } else {
                    continuation.resume(throwing: URLError(.badServerResponse))
                }
            }
            task.resume()
        }
        #else
        return try await session.data(for: request)
        #endif
    }

    /// Sends a request and returns the body of a 2xx response.
    public func send(_ request: URLRequest) async throws -> Data {
        let result: (Data, URLResponse)
        do {
            result = try await perform(request)
        } catch let error as URLError {
            if error.code == .cancelled {
                throw CancellationError()
            }
            throw APIError.unreachable
        }
        guard let http = result.1 as? HTTPURLResponse else {
            throw APIError.unreachable
        }
        guard (200..<300).contains(http.statusCode) else {
            let text = String(decoding: result.0.prefix(500), as: UTF8.self)
            throw APIError.http(status: http.statusCode, body: text)
        }
        return result.0
    }

    public static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decoding(String(describing: error))
        }
    }

    private func getJSON<T: Decodable>(_ type: T.Type, _ path: String) async throws -> T {
        let data = try await send(makeRequest("GET", url: url(path)))
        return try APIClient.decode(T.self, from: data)
    }

    private func postJSON<Body: Encodable>(_ path: String, _ body: Body) async throws -> Data {
        let encoded = try JSONEncoder().encode(body)
        return try await send(makeRequest("POST", url: url(path), body: encoded, contentType: "application/json"))
    }

    private func orderPath(_ id: String, _ suffix: String = "") -> String {
        "orders/" + APIClient.pathComponent(id) + suffix
    }

    // MARK: Endpoints

    /// GET /health (no auth needed, headers are sent anyway).
    public func health() async throws -> Health {
        try await getJSON(Health.self, "health")
    }

    /// GET /catalog
    public func catalog() async throws -> Catalog {
        try await getJSON(Catalog.self, "catalog")
    }

    /// POST /orders {product} → order
    public func createOrder(product: String) async throws -> Order {
        let data = try await postJSON("orders", CreateOrderRequest(product: product))
        return try APIClient.decode(Order.self, from: data)
    }

    /// GET /orders → this device's orders
    public func orders() async throws -> [Order] {
        try await getJSON(OrderList.self, "orders").orders
    }

    /// GET /orders/{id} → order + messages + latest artifact URLs + quote
    public func order(id: String) async throws -> OrderDetail {
        try await getJSON(OrderDetail.self, orderPath(id))
    }

    /// POST /orders/{id}/photos, multipart `files[]` (≤4 JPEGs) → {urls}
    public func uploadPhotos(orderId: String, jpegs: [Data]) async throws -> [String] {
        let boundary = "mf-\(UUID().uuidString)"
        var files: [MultipartFile] = []
        for (index, jpeg) in jpegs.prefix(4).enumerated() {
            files.append(MultipartFile(field: "files[]", filename: "photo\(index + 1).jpg", mimeType: "image/jpeg", data: jpeg))
        }
        let body = Multipart.body(boundary: boundary, files: files)
        let request = makeRequest("POST", url: url(orderPath(orderId, "/photos")), body: body,
                                  contentType: "multipart/form-data; boundary=\(boundary)")
        let data = try await send(request)
        return try APIClient.decode(PhotoUploadResponse.self, from: data).urls
    }

    /// POST /orders/{id}/messages {text, measurements?, colour?} → 202 {message_id}
    @discardableResult
    public func postMessage(orderId: String, text: String, measurements: [MeasurementChip], colour: String?) async throws -> String? {
        let body = PostMessageRequest(text: text, measurements: measurements.isEmpty ? nil : measurements, colour: colour)
        let data = try await postJSON(orderPath(orderId, "/messages"), body)
        let accepted: MessageAccepted? = try? APIClient.decode(MessageAccepted.self, from: data)
        return accepted?.messageId
    }

    /// POST /orders/{id}/accept → slice + quote + Whop variant on the server.
    public func accept(orderId: String) async throws {
        _ = try await send(makeRequest("POST", url: url(orderPath(orderId, "/accept"))))
    }

    /// GET /orders/{id}/camera.jpg (only while this order is printing).
    public func cameraSnapshot(orderId: String) async throws -> Data {
        var request = makeRequest("GET", url: url(orderPath(orderId, "/camera.jpg")))
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 10
        return try await send(request)
    }

    /// POST /voice/token {order_id} → {conversation_token, agent_id}
    public func voiceToken(orderId: String) async throws -> VoiceToken {
        let data = try await postJSON("voice/token", VoiceTokenRequest(orderId: orderId))
        return try APIClient.decode(VoiceToken.self, from: data)
    }

    /// GET /orders/{id}/stream request for `SSEClient`.
    public func streamRequest(orderId: String) -> URLRequest {
        makeRequest("GET", url: url(orderPath(orderId, "/stream")))
    }

    /// Authenticated GET of an artifact (`/files/{order_id}/{name}`) or any URL.
    public func data(at url: URL) async throws -> Data {
        try await send(makeRequest("GET", url: url))
    }

    /// Downloads `url` to `destination` (overwriting) and returns `destination`.
    public func download(_ url: URL, to destination: URL) async throws -> URL {
        let data = try await data(at: url)
        let folder = destination.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try data.write(to: destination, options: .atomic)
        return destination
    }
}
