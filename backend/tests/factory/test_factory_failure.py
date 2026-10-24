from factory.failure import check_snapshot
from factory.printer import MockPrinter


def test_mock_check_returns_ok():
    jpeg = MockPrinter().snapshot_jpeg()
    assert check_snapshot(jpeg) == {"verdict": "ok", "confidence": 1.0}


def test_missing_key_falls_back_to_mock(monkeypatch):
    monkeypatch.setenv("FACTORY_MOCK", "0")
    assert check_snapshot(b"\xff\xd8\xff\xd9")["verdict"] == "ok"
