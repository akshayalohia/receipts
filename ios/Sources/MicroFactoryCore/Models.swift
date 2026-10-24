import Foundation

// Models for the HTTP API in SPEC.md. JSON is snake_case; every key is mapped
// explicitly with CodingKeys (no key strategy, so free-form dictionaries keep their keys).
// Decoding is lenient: optional fields may be missing or null, ids may be strings or ints.

// MARK: - Lenient decoding helpers

extension KeyedDecodingContainer {
    func lossyString(_ key: Key) -> String? {
        if let value = try? decodeIfPresent(String.self, forKey: key) { return value }
        if let value = try? decodeIfPresent(Int.self, forKey: key) { return String(value) }
        if let value = try? decodeIfPresent(Double.self, forKey: key) { return String(value) }
        return nil
    }

    func lossyInt(_ key: Key) -> Int? {
        if let value = try? decodeIfPresent(Int.self, forKey: key) { return value }
        if let value = try? decodeIfPresent(Double.self, forKey: key), value.isFinite { return Int(value.rounded()) }
        if let text = try? decodeIfPresent(String.self, forKey: key), let value = Int(text) { return value }
        return nil
    }

    func lossyDouble(_ key: Key) -> Double? {
        if let value = try? decodeIfPresent(Double.self, forKey: key) { return value }
        if let text = try? decodeIfPresent(String.self, forKey: key), let value = Double(text) { return value }
        return nil
    }

    func lossyBool(_ key: Key) -> Bool? {
        if let value = try? decodeIfPresent(Bool.self, forKey: key) { return value }
        if let value = try? decodeIfPresent(Int.self, forKey: key) { return value != 0 }
        if let text = try? decodeIfPresent(String.self, forKey: key) {
            let lower = text.lowercased()
            return lower == "true" || lower == "1" || lower == "yes"
        }
        return nil
    }

    func stringArray(_ key: Key) -> [String] {
        let value: [String]? = try? decodeIfPresent([String].self, forKey: key)
        return value ?? []
    }

    func doubleArray(_ key: Key) -> [Double]? {
        let value: [Double]? = try? decodeIfPresent([Double].self, forKey: key)
        return value
    }
}

// MARK: - Order status

public enum OrderStatus: String, CaseIterable, Sendable {
    case draft
    case designing
    case review
    case quoted
    case paid
    case queued
    case printing
    case done
    case pickedUp = "picked_up"
    case failed
    case refunded
    case cancelled

    /// Statuses after the customer has paid: the live print screen owns these.
    public var isPostPayment: Bool {
        switch self {
        case .paid, .queued, .printing, .done, .pickedUp, .failed, .refunded:
            return true
        case .draft, .designing, .review, .quoted, .cancelled:
            return false
        }
    }
}

// MARK: - GET /health

public struct Health: Decodable, Sendable, Equatable {
    public var ok: Bool
    public var mock: Bool
    public var printerState: String?

    enum CodingKeys: String, CodingKey {
        case ok, mock
        case printerState = "printer_state"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = c.lossyBool(.ok) ?? false
        mock = c.lossyBool(.mock) ?? false
        printerState = c.lossyString(.printerState)
    }
}

// MARK: - GET /catalog

public struct Product: Decodable, Sendable, Identifiable, Hashable {
    public var id: String
    public var title: String
    public var blurb: String
    public var fromPriceCents: Int?
    public var path: String?
    /// Any of "photos", "measurements", "text".
    public var needs: [String]

    enum CodingKeys: String, CodingKey {
        case id, title, blurb, path, needs
        case fromPriceCents = "from_price_cents"
    }

    public init(id: String, title: String, blurb: String, fromPriceCents: Int?, path: String?, needs: [String]) {
        self.id = id
        self.title = title
        self.blurb = blurb
        self.fromPriceCents = fromPriceCents
        self.path = path
        self.needs = needs
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        guard let id = c.lossyString(.id) else {
            throw DecodingError.keyNotFound(CodingKeys.id, .init(codingPath: c.codingPath, debugDescription: "product id missing"))
        }
        self.id = id
        title = c.lossyString(.title) ?? id
        blurb = c.lossyString(.blurb) ?? ""
        fromPriceCents = c.lossyInt(.fromPriceCents)
        path = c.lossyString(.path)
        needs = c.stringArray(.needs)
    }
}

public struct Catalog: Decodable, Sendable, Equatable {
    public var products: [Product]
    public var coloursInStock: [String]
    public var loadedColour: String?

    enum CodingKeys: String, CodingKey {
        case products
        case coloursInStock = "colours_in_stock"
        case loadedColour = "loaded_colour"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        products = try c.decodeIfPresent([Product].self, forKey: .products) ?? []
        coloursInStock = c.stringArray(.coloursInStock)
        loadedColour = c.lossyString(.loadedColour)
    }
}

// MARK: - Orders

public struct ArtifactFiles: Decodable, Sendable, Equatable {
    public var stl: String?
    public var glb: String?
    public var usdz: String?
    public var png: String?
    public var gcode3mf: String?

    enum CodingKeys: String, CodingKey {
        case stl, glb, usdz, png
        case gcode3mf = "gcode_3mf"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        stl = c.lossyString(.stl)
        glb = c.lossyString(.glb)
        usdz = c.lossyString(.usdz)
        png = c.lossyString(.png)
        gcode3mf = c.lossyString(.gcode3mf)
    }
}

public struct Order: Decodable, Sendable, Identifiable, Equatable {
    public var id: String
    public var status: String
    public var product: String?
    public var path: String?
    public var params: JSONValue?
    public var colour: String?
    public var designVersion: Int?
    public var files: ArtifactFiles?
    public var bboxMm: [Double]?
    public var printSeconds: Int?
    public var filamentGrams: Double?
    public var priceCents: Int?
    public var whopVariantId: String?
    public var whopPurchaseUrl: String?
    public var paymentId: String?
    public var queuePosition: Int?
    public var eta: String?
    public var createdAt: String?
    public var updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, status, product, path, params, colour, files, eta
        case designVersion = "design_version"
        case bboxMm = "bbox_mm"
        case printSeconds = "print_seconds"
        case filamentGrams = "filament_grams"
        case priceCents = "price_cents"
        case whopVariantId = "whop_variant_id"
        case whopPurchaseUrl = "whop_purchase_url"
        case paymentId = "payment_id"
        case queuePosition = "queue_position"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        guard let id = c.lossyString(.id) else {
            throw DecodingError.keyNotFound(CodingKeys.id, .init(codingPath: c.codingPath, debugDescription: "order id missing"))
        }
        self.id = id
        status = c.lossyString(.status) ?? OrderStatus.draft.rawValue
        product = c.lossyString(.product)
        path = c.lossyString(.path)
        let decodedParams: JSONValue? = try? c.decodeIfPresent(JSONValue.self, forKey: .params)
        params = decodedParams
        colour = c.lossyString(.colour)
        designVersion = c.lossyInt(.designVersion)
        let decodedFiles: ArtifactFiles? = try? c.decodeIfPresent(ArtifactFiles.self, forKey: .files)
        files = decodedFiles
        bboxMm = c.doubleArray(.bboxMm)
        printSeconds = c.lossyInt(.printSeconds)
        filamentGrams = c.lossyDouble(.filamentGrams)
        priceCents = c.lossyInt(.priceCents)
        whopVariantId = c.lossyString(.whopVariantId)
        whopPurchaseUrl = c.lossyString(.whopPurchaseUrl)
        paymentId = c.lossyString(.paymentId)
        queuePosition = c.lossyInt(.queuePosition)
        eta = c.lossyString(.eta)
        createdAt = c.lossyString(.createdAt)
        updatedAt = c.lossyString(.updatedAt)
    }

    public var orderStatus: OrderStatus? { OrderStatus(rawValue: status) }
}

/// `GET /orders` returns this device's orders: either a bare array or `{"orders": [...]}`.
public struct OrderList: Decodable, Sendable {
    public var orders: [Order]

    enum CodingKeys: String, CodingKey { case orders }

    public init(from decoder: Decoder) throws {
        if let single = try? decoder.singleValueContainer(), let list = try? single.decode([Order].self) {
            orders = list
            return
        }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        orders = try c.decodeIfPresent([Order].self, forKey: .orders) ?? []
    }
}

// MARK: - Messages

public struct ChatMessage: Decodable, Sendable, Identifiable, Equatable {
    public var id: String
    /// "user", "agent" or "system".
    public var role: String
    public var text: String
    public var media: [String]
    public var createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, role, text, media
        case createdAt = "created_at"
    }

    public init(id: String, role: String, text: String, media: [String] = [], createdAt: String? = nil) {
        self.id = id
        self.role = role
        self.text = text
        self.media = media
        self.createdAt = createdAt
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = c.lossyString(.id) ?? UUID().uuidString
        role = c.lossyString(.role) ?? "agent"
        text = c.lossyString(.text) ?? ""
        media = c.stringArray(.media)
        createdAt = c.lossyString(.createdAt)
    }

    public var isUser: Bool { role == "user" }
    public var isAgent: Bool { role == "agent" }
}

// MARK: - Design and quote

/// The `design` SSE event, and the latest artifact URLs on `GET /orders/{id}`.
public struct DesignArtifact: Decodable, Sendable, Equatable {
    public var version: Int?
    public var glb: String?
    public var usdz: String?
    public var png: String?
    public var bboxMm: [Double]?

    enum CodingKeys: String, CodingKey {
        case version, glb, usdz, png
        case bboxMm = "bbox_mm"
    }

    public init(version: Int?, glb: String?, usdz: String?, png: String?, bboxMm: [Double]?) {
        self.version = version
        self.glb = glb
        self.usdz = usdz
        self.png = png
        self.bboxMm = bboxMm
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = c.lossyInt(.version)
        glb = c.lossyString(.glb)
        usdz = c.lossyString(.usdz)
        png = c.lossyString(.png)
        bboxMm = c.doubleArray(.bboxMm)
    }

    public var hasFiles: Bool { usdz != nil || glb != nil || png != nil }
}

/// The `quote` SSE event, and `quote` on `GET /orders/{id}`.
public struct Quote: Decodable, Sendable, Equatable {
    public var priceCents: Int
    public var printSeconds: Int?
    public var filamentGrams: Double?
    public var colour: String?
    public var whopVariantId: String?
    public var whopPurchaseUrl: String?
    public var eta: String?

    enum CodingKeys: String, CodingKey {
        case colour, eta
        case priceCents = "price_cents"
        case printSeconds = "print_seconds"
        case filamentGrams = "filament_grams"
        case whopVariantId = "whop_variant_id"
        case whopPurchaseUrl = "whop_purchase_url"
    }

    public init(priceCents: Int, printSeconds: Int?, filamentGrams: Double?, colour: String?,
                whopVariantId: String?, whopPurchaseUrl: String?, eta: String?) {
        self.priceCents = priceCents
        self.printSeconds = printSeconds
        self.filamentGrams = filamentGrams
        self.colour = colour
        self.whopVariantId = whopVariantId
        self.whopPurchaseUrl = whopPurchaseUrl
        self.eta = eta
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        guard let price = c.lossyInt(.priceCents) else {
            throw DecodingError.keyNotFound(CodingKeys.priceCents, .init(codingPath: c.codingPath, debugDescription: "price_cents missing"))
        }
        priceCents = price
        printSeconds = c.lossyInt(.printSeconds)
        filamentGrams = c.lossyDouble(.filamentGrams)
        colour = c.lossyString(.colour)
        whopVariantId = c.lossyString(.whopVariantId)
        whopPurchaseUrl = c.lossyString(.whopPurchaseUrl)
        eta = c.lossyString(.eta)
    }
}

/// `GET /orders/{id}`: order + messages + latest artifact URLs + quote.
/// Accepts the order nested under `order` or flattened at the top level.
public struct OrderDetail: Decodable, Sendable {
    public var order: Order
    public var messages: [ChatMessage]
    public var artifacts: DesignArtifact?
    public var quote: Quote?

    enum CodingKeys: String, CodingKey {
        case order, messages, artifacts, design, quote
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if c.contains(.order) {
            order = try c.decode(Order.self, forKey: .order)
        } else {
            order = try Order(from: decoder)
        }
        let decodedMessages: [ChatMessage]? = try? c.decodeIfPresent([ChatMessage].self, forKey: .messages)
        messages = decodedMessages ?? []
        let fromArtifacts: DesignArtifact? = try? c.decodeIfPresent(DesignArtifact.self, forKey: .artifacts)
        let fromDesign: DesignArtifact? = try? c.decodeIfPresent(DesignArtifact.self, forKey: .design)
        artifacts = fromArtifacts ?? fromDesign
        let decodedQuote: Quote? = try? c.decodeIfPresent(Quote.self, forKey: .quote)
        quote = decodedQuote
    }

    /// Latest design: explicit artifact URLs if present, else the order's `files`.
    public var latestDesign: DesignArtifact? {
        if let artifacts, artifacts.hasFiles {
            var result = artifacts
            if result.version == nil { result.version = order.designVersion }
            if result.bboxMm == nil { result.bboxMm = order.bboxMm }
            return result
        }
        if let files = order.files, files.usdz != nil || files.glb != nil || files.png != nil {
            return DesignArtifact(version: order.designVersion, glb: files.glb, usdz: files.usdz,
                                  png: files.png, bboxMm: order.bboxMm)
        }
        return nil
    }

    /// The quote, falling back to the priced fields on the order itself.
    public var effectiveQuote: Quote? {
        if var quote {
            if quote.whopPurchaseUrl == nil { quote.whopPurchaseUrl = order.whopPurchaseUrl }
            if quote.whopVariantId == nil { quote.whopVariantId = order.whopVariantId }
            if quote.eta == nil { quote.eta = order.eta }
            return quote
        }
        guard let price = order.priceCents else { return nil }
        return Quote(priceCents: price, printSeconds: order.printSeconds, filamentGrams: order.filamentGrams,
                     colour: order.colour, whopVariantId: order.whopVariantId,
                     whopPurchaseUrl: order.whopPurchaseUrl, eta: order.eta)
    }
}

// MARK: - Small responses

/// `POST /orders/{id}/photos` → `{urls}`.
public struct PhotoUploadResponse: Decodable, Sendable, Equatable {
    public var urls: [String]

    enum CodingKeys: String, CodingKey { case urls }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        urls = c.stringArray(.urls)
    }
}

/// `POST /orders/{id}/messages` → 202 `{message_id}`.
public struct MessageAccepted: Decodable, Sendable, Equatable {
    public var messageId: String?

    enum CodingKeys: String, CodingKey { case messageId = "message_id" }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        messageId = c.lossyString(.messageId)
    }
}

/// `POST /voice/token` → `{conversation_token, agent_id}`.
public struct VoiceToken: Decodable, Sendable, Equatable {
    public var conversationToken: String
    public var agentId: String?

    enum CodingKeys: String, CodingKey {
        case conversationToken = "conversation_token"
        case agentId = "agent_id"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversationToken = try c.decode(String.self, forKey: .conversationToken)
        agentId = c.lossyString(.agentId)
    }
}

// MARK: - Request bodies

public struct CreateOrderRequest: Encodable, Sendable {
    public var product: String
    public init(product: String) { self.product = product }
}

/// A measurement chip `{label, mm}` sent with the next message.
public struct MeasurementChip: Codable, Sendable, Hashable, Identifiable {
    public var id: UUID = UUID()
    public var label: String
    public var mm: Double

    enum CodingKeys: String, CodingKey { case label, mm }

    public init(label: String, mm: Double) {
        self.label = label
        self.mm = mm
    }
}

public struct PostMessageRequest: Encodable, Sendable {
    public var text: String
    public var measurements: [MeasurementChip]?
    public var colour: String?

    public init(text: String, measurements: [MeasurementChip]?, colour: String?) {
        self.text = text
        self.measurements = measurements
        self.colour = colour
    }
}

public struct VoiceTokenRequest: Encodable, Sendable {
    public var orderId: String

    enum CodingKeys: String, CodingKey { case orderId = "order_id" }

    public init(orderId: String) { self.orderId = orderId }
}
