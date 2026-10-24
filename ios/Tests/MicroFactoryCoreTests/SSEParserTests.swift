import Foundation
import XCTest
@testable import MicroFactoryCore

final class SSEParserTests: XCTestCase {
    func testNamedEventsAndHeartbeat() {
        let body = """
        : heartbeat

        event: status
        data: {"status": "designing"}

        event: agent_delta
        data: {"text": "Hel"}

        : heartbeat

        event: agent_delta
        data: {"text": "lo"}


        """
        let events = SSEParser.events(from: body)
        XCTAssertEqual(events.map { $0.event }, ["status", "agent_delta", "agent_delta"])
        XCTAssertEqual(events[0].data, #"{"status": "designing"}"#)
        XCTAssertEqual(events[2].data, #"{"text": "lo"}"#)
    }

    func testDefaultEventNameIsMessage() {
        let events = SSEParser.events(from: "data: {\"role\": \"agent\", \"text\": \"hi\"}\n\n")
        XCTAssertEqual(events, [SSEEvent(event: "message", data: #"{"role": "agent", "text": "hi"}"#)])
    }

    func testMultiLineDataIsJoinedWithNewline() {
        let events = SSEParser.events(from: "event: message\ndata: line one\ndata: line two\n\n")
        XCTAssertEqual(events.first?.data, "line one\nline two")
    }

    func testCRLFAndCRTerminators() {
        let crlf = SSEParser.events(from: "event: status\r\ndata: {\"status\": \"paid\"}\r\n\r\n")
        XCTAssertEqual(crlf, [SSEEvent(event: "status", data: #"{"status": "paid"}"#)])
        let cr = SSEParser.events(from: "event: status\rdata: x\r\r")
        XCTAssertEqual(cr, [SSEEvent(event: "status", data: "x")])
    }

    func testValueWithoutSpaceAndWithColons() {
        let events = SSEParser.events(from: "data:{\"url\": \"https://x.test/a\"}\n\n")
        XCTAssertEqual(events.first?.data, #"{"url": "https://x.test/a"}"#)
        let spaced = SSEParser.events(from: "data:  two spaces\n\n")
        XCTAssertEqual(spaced.first?.data, " two spaces") // only one leading space is removed
    }

    func testIdAndRetry() {
        var parser = SSEParser()
        XCTAssertNil(parser.feed(line: "id: 41"))
        XCTAssertNil(parser.feed(line: "retry: 2500"))
        XCTAssertNil(parser.feed(line: "event: printer"))
        XCTAssertNil(parser.feed(line: "data: {}"))
        let event = parser.feed(line: "")
        XCTAssertEqual(event, SSEEvent(event: "printer", data: "{}", id: "41"))
        XCTAssertEqual(parser.lastEventId, "41")
        XCTAssertEqual(parser.retryMilliseconds, 2500)
        XCTAssertNil(parser.feed(line: "retry: soon"))
        XCTAssertEqual(parser.retryMilliseconds, 2500)
    }

    func testEventNameResetsAfterDispatch() {
        let events = SSEParser.events(from: "event: status\ndata: a\n\ndata: b\n\n")
        XCTAssertEqual(events.map { $0.event }, ["status", "message"])
    }

    func testBlankLinesWithoutDataDispatchNothing() {
        let events = SSEParser.events(from: "event: status\n\n\n\n")
        XCTAssertTrue(events.isEmpty)
    }

    func testIncompleteTrailingEventIsNotDispatched() {
        let events = SSEParser.events(from: "event: status\ndata: {\"status\": \"done\"}\n")
        XCTAssertTrue(events.isEmpty)
    }

    func testUnknownFieldsAreIgnored() {
        let events = SSEParser.events(from: "foo: bar\nevent: human_task\ndata: {\"kind\": \"bed_clear\"}\n\n")
        XCTAssertEqual(events, [SSEEvent(event: "human_task", data: #"{"kind": "bed_clear"}"#)])
    }

    func testLineSplitterAcrossChunksAndUTF8() {
        var splitter = SSELineSplitter()
        var lines: [String] = []
        for byte in Array("data: 40 × 30 mm\r\n\r\nrest".utf8) {
            if let line = splitter.feed(byte) {
                lines.append(line)
            }
        }
        XCTAssertEqual(lines, ["data: 40 × 30 mm", ""])
        XCTAssertEqual(splitter.finish(), "rest")
        XCTAssertNil(splitter.finish())
    }

    func testEndToEndWithOrderEventDecoding() throws {
        let body = "event: design\ndata: {\"version\": 1, \"usdz\": \"/files/o/v1.usdz\", \"bbox_mm\": [10, 20, 30]}\n\n"
        let events = SSEParser.events(from: body)
        XCTAssertEqual(events.count, 1)
        guard case .design(let design) = try OrderEvent.decode(events[0]) else {
            return XCTFail("expected design")
        }
        XCTAssertEqual(design.version, 1)
        XCTAssertEqual(design.usdz, "/files/o/v1.usdz")
        XCTAssertEqual(design.bboxMm, [10, 20, 30])
    }

    func testBackoffDelay() {
        XCTAssertEqual(SSEClient.backoffDelay(attempt: 1, minimum: 1, maximum: 30), 1)
        XCTAssertEqual(SSEClient.backoffDelay(attempt: 2, minimum: 1, maximum: 30), 2)
        XCTAssertEqual(SSEClient.backoffDelay(attempt: 4, minimum: 1, maximum: 30), 8)
        XCTAssertEqual(SSEClient.backoffDelay(attempt: 10, minimum: 1, maximum: 30), 30)
    }
}
