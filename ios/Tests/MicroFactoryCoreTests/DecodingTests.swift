import Foundation
import XCTest
@testable import MicroFactoryCore

/// JSON decoding for every response shape in SPEC.md "HTTP API" and every SSE payload.
final class DecodingTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try APIClient.decode(T.self, from: Data(json.utf8))
    }

    private let orderJSON = """
    {
      "id": "ord_abc123",
      "device_id": "dev-1",
      "status": "review",
      "product": "keychain",
      "path": "hybrid",
      "params": {"text": "AKSHAYA", "font_size": 12, "bold": true},
      "colour": "blue",
      "design_version": 2,
      "files": {"stl": "/files/ord_abc123/model.stl", "glb": "/files/ord_abc123/model.glb",
                "usdz": "/files/ord_abc123/model.usdz", "png": "/files/ord_abc123/model.png",
                "gcode_3mf": null},
      "bbox_mm": [40, 31.5, 6],
      "print_seconds": 1440,
      "filament_grams": 7.3,
      "price_cents": 1200,
      "gen_cost_cents": 40,
      "whop_variant_id": "plan_123",
      "whop_purchase_url": "https://whop.com/checkout/plan_123",
      "payment_id": null,
      "queue_position": 1,
      "eta": "2026-10-24T15:30:00Z",
      "created_at": "2026-10-24T14:00:00Z",
      "updated_at": "2026-10-24T14:05:00Z"
    }
    """

    func testHealth() throws {
        let health = try decode(Health.self, #"{"ok": true, "mock": true, "printer_state": "IDLE"}"#)
        XCTAssertTrue(health.ok)
        XCTAssertTrue(health.mock)
        XCTAssertEqual(health.printerState, "IDLE")
    }

    func testCatalog() throws {
        let json = """
        {"products": [
            {"id": "keychain", "title": "Pet keychain", "blurb": "Your pet, 40 mm, on a ring.",
             "from_price_cents": 1200, "path": "hybrid", "needs": ["photos", "text"]},
            {"id": "nametag", "title": "Name tag", "blurb": "Your name, raised.",
             "from_price_cents": 800, "path": "parametric", "needs": ["text"]}
         ],
         "colours_in_stock": ["black", "blue", "red"],
         "loaded_colour": "blue"}
        """
        let catalog = try decode(Catalog.self, json)
        XCTAssertEqual(catalog.products.count, 2)
        XCTAssertEqual(catalog.products[0].id, "keychain")
        XCTAssertEqual(catalog.products[0].title, "Pet keychain")
        XCTAssertEqual(catalog.products[0].blurb, "Your pet, 40 mm, on a ring.")
        XCTAssertEqual(catalog.products[0].fromPriceCents, 1200)
        XCTAssertEqual(catalog.products[0].path, "hybrid")
        XCTAssertEqual(catalog.products[0].needs, ["photos", "text"])
        XCTAssertEqual(catalog.coloursInStock, ["black", "blue", "red"])
        XCTAssertEqual(catalog.loadedColour, "blue")
    }

    func testCatalogToleratesMissingOptionalFields() throws {
        let catalog = try decode(Catalog.self, #"{"products": [{"id": "figurine", "title": "Figurine", "blurb": "60 mm."}]}"#)
        XCTAssertEqual(catalog.products.first?.needs, [])
        XCTAssertNil(catalog.products.first?.fromPriceCents)
        XCTAssertEqual(catalog.coloursInStock, [])
        XCTAssertNil(catalog.loadedColour)
    }

    func testOrder() throws {
        let order = try decode(Order.self, orderJSON)
        XCTAssertEqual(order.id, "ord_abc123")
        XCTAssertEqual(order.status, "review")
        XCTAssertEqual(order.orderStatus, .review)
        XCTAssertEqual(order.product, "keychain")
        XCTAssertEqual(order.path, "hybrid")
        XCTAssertEqual(order.params?["text"], .string("AKSHAYA"))
        XCTAssertEqual(order.params?["font_size"], .number(12))
        XCTAssertEqual(order.params?["bold"], .bool(true))
        XCTAssertEqual(order.colour, "blue")
        XCTAssertEqual(order.designVersion, 2)
        XCTAssertEqual(order.files?.usdz, "/files/ord_abc123/model.usdz")
        XCTAssertEqual(order.files?.png, "/files/ord_abc123/model.png")
        XCTAssertNil(order.files?.gcode3mf)
        XCTAssertEqual(order.bboxMm, [40, 31.5, 6])
        XCTAssertEqual(order.printSeconds, 1440)
        XCTAssertEqual(order.filamentGrams ?? 0, 7.3, accuracy: 0.0001)
        XCTAssertEqual(order.priceCents, 1200)
        XCTAssertEqual(order.whopVariantId, "plan_123")
        XCTAssertEqual(order.whopPurchaseUrl, "https://whop.com/checkout/plan_123")
        XCTAssertNil(order.paymentId)
        XCTAssertEqual(order.queuePosition, 1)
        XCTAssertEqual(order.eta, "2026-10-24T15:30:00Z")
        XCTAssertEqual(order.createdAt, "2026-10-24T14:00:00Z")
    }

    func testFreshDraftOrderFromCreate() throws {
        let order = try decode(Order.self, #"{"id": "ord_new", "status": "draft", "product": "custom"}"#)
        XCTAssertEqual(order.orderStatus, .draft)
        XCTAssertNil(order.files)
        XCTAssertNil(order.priceCents)
    }

    func testOrderListAsArrayAndWrapped() throws {
        let bare = try decode(OrderList.self, "[\(orderJSON)]")
        XCTAssertEqual(bare.orders.map { $0.id }, ["ord_abc123"])
        let wrapped = try decode(OrderList.self, #"{"orders": [\#(orderJSON)]}"#)
        XCTAssertEqual(wrapped.orders.map { $0.id }, ["ord_abc123"])
    }

    func testOrderDetailNested() throws {
        let json = """
        {"order": \(orderJSON),
         "messages": [
            {"id": 1, "order_id": "ord_abc123", "role": "user", "text": "My dog, as a keychain", "media": ["/files/ord_abc123/p1.jpg"], "created_at": "2026-10-24T14:00:00Z"},
            {"id": 2, "order_id": "ord_abc123", "role": "agent", "text": "Here it is.", "media": [], "created_at": "2026-10-24T14:02:00Z"}
         ],
         "artifacts": {"glb": "/files/ord_abc123/v2.glb", "usdz": "/files/ord_abc123/v2.usdz", "png": "/files/ord_abc123/v2.png"},
         "quote": {"price_cents": 1200, "print_seconds": 1440, "filament_grams": 7.3, "colour": "blue", "whop_variant_id": "plan_123"}}
        """
        let detail = try decode(OrderDetail.self, json)
        XCTAssertEqual(detail.order.id, "ord_abc123")
        XCTAssertEqual(detail.messages.count, 2)
        XCTAssertEqual(detail.messages[0].id, "1")
        XCTAssertTrue(detail.messages[0].isUser)
        XCTAssertEqual(detail.messages[0].media, ["/files/ord_abc123/p1.jpg"])
        XCTAssertTrue(detail.messages[1].isAgent)
        XCTAssertEqual(detail.latestDesign?.usdz, "/files/ord_abc123/v2.usdz")
        XCTAssertEqual(detail.latestDesign?.version, 2)
        XCTAssertEqual(detail.latestDesign?.bboxMm, [40, 31.5, 6])
        XCTAssertEqual(detail.effectiveQuote?.priceCents, 1200)
        XCTAssertEqual(detail.effectiveQuote?.whopPurchaseUrl, "https://whop.com/checkout/plan_123")
        XCTAssertEqual(detail.effectiveQuote?.eta, "2026-10-24T15:30:00Z")
    }

    func testOrderDetailFlatWithNullQuote() throws {
        var json = orderJSON.trimmingCharacters(in: .whitespacesAndNewlines)
        XCTAssertEqual(json.last, "}")
        json.removeLast() // drop the closing brace, then flatten messages + quote into the order object
        json += #", "messages": [], "quote": null}"#
        let detail = try decode(OrderDetail.self, json)
        XCTAssertEqual(detail.order.id, "ord_abc123")
        XCTAssertNil(detail.quote)
        XCTAssertEqual(detail.latestDesign?.usdz, "/files/ord_abc123/model.usdz") // from order.files
        XCTAssertEqual(detail.effectiveQuote?.priceCents, 1200) // from order.price_cents
    }

    func testPhotoUpload() throws {
        let response = try decode(PhotoUploadResponse.self, #"{"urls": ["/files/ord_1/p1.jpg", "/files/ord_1/p2.jpg"]}"#)
        XCTAssertEqual(response.urls.count, 2)
    }

    func testMessageAcceptedWithStringOrIntId() throws {
        XCTAssertEqual(try decode(MessageAccepted.self, #"{"message_id": "msg_9"}"#).messageId, "msg_9")
        XCTAssertEqual(try decode(MessageAccepted.self, #"{"message_id": 9}"#).messageId, "9")
    }

    func testVoiceToken() throws {
        let token = try decode(VoiceToken.self, #"{"conversation_token": "tok_fake", "agent_id": "agent_1"}"#)
        XCTAssertEqual(token.conversationToken, "tok_fake")
        XCTAssertEqual(token.agentId, "agent_1")
    }

    func testRequestBodiesAreSnakeCase() throws {
        let message = PostMessageRequest(text: "2 cm taller", measurements: [MeasurementChip(label: "Width", mm: 42)], colour: "red")
        let messageJSON = try XCTUnwrap(try JSONSerialization.jsonObject(with: JSONEncoder().encode(message)) as? [String: Any])
        XCTAssertEqual(messageJSON["text"] as? String, "2 cm taller")
        XCTAssertEqual(messageJSON["colour"] as? String, "red")
        let chips = try XCTUnwrap(messageJSON["measurements"] as? [[String: Any]])
        XCTAssertEqual(chips.first?["label"] as? String, "Width")
        XCTAssertEqual(chips.first?["mm"] as? Double, 42)
        XCTAssertNil(chips.first?["id"])

        let bare = PostMessageRequest(text: "hi", measurements: nil, colour: nil)
        let bareJSON = try XCTUnwrap(try JSONSerialization.jsonObject(with: JSONEncoder().encode(bare)) as? [String: Any])
        XCTAssertEqual(Set(bareJSON.keys), ["text"])

        let voice = try XCTUnwrap(try JSONSerialization.jsonObject(with: JSONEncoder().encode(VoiceTokenRequest(orderId: "ord_1"))) as? [String: Any])
        XCTAssertEqual(voice["order_id"] as? String, "ord_1")

        let create = try XCTUnwrap(try JSONSerialization.jsonObject(with: JSONEncoder().encode(CreateOrderRequest(product: "custom"))) as? [String: Any])
        XCTAssertEqual(create["product"] as? String, "custom")
    }

    // MARK: SSE payloads

    func testStreamEventMessage() throws {
        let event = try OrderEvent.decode(SSEEvent(event: "message", data: #"{"role": "agent", "text": "Printing your design next."}"#))
        guard case .message(let message) = event else { return XCTFail("expected message, got \(event)") }
        XCTAssertEqual(message.role, "agent")
        XCTAssertEqual(message.text, "Printing your design next.")
        XCTAssertFalse(message.id.isEmpty)
    }

    func testStreamEventAgentDelta() throws {
        XCTAssertEqual(try OrderEvent.decode(SSEEvent(event: "agent_delta", data: #"{"text": "Look"}"#)), .agentDelta("Look"))
    }

    func testStreamEventStatus() throws {
        XCTAssertEqual(try OrderEvent.decode(SSEEvent(event: "status", data: #"{"status": "printing"}"#)), .status("printing"))
    }

    func testStreamEventDesign() throws {
        let data = #"{"version": 3, "glb": "/files/o/v3.glb", "usdz": "/files/o/v3.usdz", "png": "/files/o/v3.png", "bbox_mm": [40.2, 30, 8.5]}"#
        let event = try OrderEvent.decode(SSEEvent(event: "design", data: data))
        XCTAssertEqual(event, .design(DesignArtifact(version: 3, glb: "/files/o/v3.glb", usdz: "/files/o/v3.usdz",
                                                     png: "/files/o/v3.png", bboxMm: [40.2, 30, 8.5])))
    }

    func testStreamEventQuote() throws {
        let data = #"{"price_cents": 1450, "print_seconds": 1320, "filament_grams": 9.1, "colour": "red", "whop_variant_id": "plan_9"}"#
        guard case .quote(let quote) = try OrderEvent.decode(SSEEvent(event: "quote", data: data)) else {
            return XCTFail("expected quote")
        }
        XCTAssertEqual(quote.priceCents, 1450)
        XCTAssertEqual(quote.printSeconds, 1320)
        XCTAssertEqual(quote.filamentGrams ?? 0, 9.1, accuracy: 0.0001)
        XCTAssertEqual(quote.colour, "red")
        XCTAssertEqual(quote.whopVariantId, "plan_9")
    }

    func testStreamEventPrinter() throws {
        let event = try OrderEvent.decode(SSEEvent(event: "printer", data: #"{"state": "RUNNING", "progress_pct": 42, "remaining_min": 13}"#))
        XCTAssertEqual(event, .printer(PrinterUpdate(state: "RUNNING", progressPct: 42, remainingMin: 13)))
        let fractional = try OrderEvent.decode(SSEEvent(event: "printer", data: #"{"state": "RUNNING", "progress_pct": 42.6, "remaining_min": 13}"#))
        XCTAssertEqual(fractional, .printer(PrinterUpdate(state: "RUNNING", progressPct: 43, remainingMin: 13)))
    }

    func testStreamEventHumanTask() throws {
        XCTAssertEqual(try OrderEvent.decode(SSEEvent(event: "human_task", data: #"{"kind": "bed_clear"}"#)), .humanTask("bed_clear"))
    }

    func testStreamEventUnknownIsKept() throws {
        XCTAssertEqual(try OrderEvent.decode(SSEEvent(event: "something_new", data: "{}")),
                       .unknown(name: "something_new", data: "{}"))
    }

    func testBadPayloadThrows() {
        XCTAssertThrowsError(try OrderEvent.decode(SSEEvent(event: "quote", data: #"{"colour": "red"}"#)))
    }

    // MARK: Formatting and URLs

    func testFormatting() {
        XCTAssertEqual(Format.price(cents: 1200), "$12.00")
        XCTAssertEqual(Format.price(cents: 805), "$8.05")
        XCTAssertEqual(Format.fromPrice(cents: 800), "from $8")
        XCTAssertEqual(Format.fromPrice(cents: 1250), "from $12.50")
        XCTAssertEqual(Format.duration(seconds: 1440), "24 min")
        XCTAssertEqual(Format.duration(seconds: 1441), "25 min")
        XCTAssertEqual(Format.duration(seconds: 3900), "1 h 5 min")
        XCTAssertEqual(Format.duration(seconds: 7200), "2 h")
        XCTAssertEqual(Format.mm(42), "42 mm")
        XCTAssertEqual(Format.dimensions([40, 31.46, 6]), "40 × 31.5 × 6 mm")
    }

    func testURLResolutionAndHeaders() throws {
        let api = APIClient(baseURL: try XCTUnwrap(URL(string: "https://factory.example.com/")), appKey: "k", deviceId: "d")
        XCTAssertEqual(api.url("/orders").absoluteString, "https://factory.example.com/orders")
        XCTAssertEqual(api.resolve("/files/ord_1/model.usdz")?.absoluteString, "https://factory.example.com/files/ord_1/model.usdz")
        XCTAssertEqual(api.resolve("https://cdn.example.org/x.png")?.absoluteString, "https://cdn.example.org/x.png")
        XCTAssertNil(api.resolve(nil))

        let own = api.makeRequest("GET", url: api.url("catalog"))
        XCTAssertEqual(own.value(forHTTPHeaderField: "X-App-Key"), "k")
        XCTAssertEqual(own.value(forHTTPHeaderField: "X-Device-Id"), "d")
        let other = api.makeRequest("GET", url: try XCTUnwrap(URL(string: "https://cdn.example.org/x.png")))
        XCTAssertNil(other.value(forHTTPHeaderField: "X-App-Key"))

        XCTAssertEqual(api.streamRequest(orderId: "ord_1").url?.absoluteString, "https://factory.example.com/orders/ord_1/stream")
    }

    func testMultipartBody() {
        let body = Multipart.body(boundary: "B", files: [MultipartFile(field: "files[]", filename: "photo1.jpg", mimeType: "image/jpeg", data: Data("JPEG".utf8))])
        let text = String(decoding: body, as: UTF8.self)
        XCTAssertTrue(text.hasPrefix("--B\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"photo1.jpg\"\r\n"))
        XCTAssertTrue(text.contains("Content-Type: image/jpeg\r\n\r\nJPEG\r\n"))
        XCTAssertTrue(text.hasSuffix("--B--\r\n"))
    }

    func testDeviceIdPersists() throws {
        let suite = "mf-tests-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        let first = DeviceID.current(in: defaults)
        XCTAssertFalse(first.isEmpty)
        XCTAssertEqual(DeviceID.current(in: defaults), first)
        defaults.removePersistentDomain(forName: suite)
    }
}
