import json
import struct
import time

import pytest

from factory import printer as printer_mod
from factory.printer import (BambuPrinter, MockPrinter, PrinterError, camera_auth_packet, get_printer, merge_report,
                             project_file_payload, read_jpeg_frame, simple_payload, status_from_report)


def wait_for(p, state, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = p.status()
        if st.state == state:
            return st
        time.sleep(0.02)
    raise AssertionError(f"never reached {state}, last {p.status()}")


def test_mock_printer_lifecycle():
    p = MockPrinter(job_seconds=1.0)
    assert p.status().state == "IDLE"
    p.start("x.gcode.3mf", "ord_1")
    st = p.status()
    assert st.state == "PREPARE" and st.job_name == "ord_1" and st.total_layers == 100
    with pytest.raises(PrinterError, match="busy"):
        p.start("y.gcode.3mf", "ord_2")
    run = wait_for(p, "RUNNING")
    assert run.layer >= 1 and 10 <= run.progress_pct < 100
    p.pause()
    paused = p.status()
    assert paused.state == "PAUSE"
    time.sleep(0.3)
    assert p.status().progress_pct == paused.progress_pct  # clock frozen while paused
    p.resume()
    assert p.status().state in ("RUNNING", "FINISH")
    done = wait_for(p, "FINISH")
    assert done.progress_pct == 100 and done.remaining_min == 0 and done.layer == done.total_layers
    assert done.raw["gcode_state"] == "FINISH"
    p.start("y.gcode.3mf", "ord_2")  # next job after FINISH
    assert p.status().job_name == "ord_2"
    p.stop()
    assert p.status().state == "FAILED"


def test_mock_snapshot_changes_with_progress():
    p = MockPrinter(job_seconds=1.0)
    p.start("x", "ord_1")
    first = p.snapshot_jpeg()
    wait_for(p, "FINISH")
    last = p.snapshot_jpeg()
    assert first[:2] == b"\xff\xd8" and last[-2:] == b"\xff\xd9"
    assert first != last


def test_get_printer_is_mock_without_printer_env(monkeypatch):
    monkeypatch.setenv("FACTORY_MOCK", "0")
    p = get_printer()
    assert isinstance(p, MockPrinter) and get_printer() is p


def test_get_printer_bambu_when_configured(monkeypatch):
    monkeypatch.setenv("FACTORY_MOCK", "0")
    for k, v in (("PRINTER_IP", "192.0.2.10"), ("PRINTER_SERIAL", "03919A000000000"), ("PRINTER_ACCESS_CODE", "12345678")):
        monkeypatch.setenv(k, v)
    p = get_printer()
    assert isinstance(p, BambuPrinter) and p._client is None  # constructed without touching the network


def test_project_file_payload():
    pr = project_file_payload("ord_1.gcode.3mf", "ord_1")["print"]
    assert pr["command"] == "project_file"
    assert pr["param"] == "Metadata/plate_1.gcode"
    assert pr["url"] == "ftp:///ord_1.gcode.3mf"
    assert pr["use_ams"] is False and pr["bed_type"] == "textured_plate" and pr["bed_leveling"] is True
    assert pr["subtask_name"] == "ord_1"


def test_simple_payloads():
    for cmd in ("pause", "resume", "stop"):
        assert simple_payload(cmd) == {"print": {"sequence_id": "0", "command": cmd}}
    with pytest.raises(ValueError):
        simple_payload("explode")


def test_report_parsing_merges_partial_updates():
    state = {}
    merge_report(state, {"print": {"command": "push_status", "gcode_state": "RUNNING", "mc_percent": 12,
                                   "mc_remaining_time": 30, "layer_num": 5, "total_layer_num": 80,
                                   "subtask_name": "ord_1"}})
    merge_report(state, {"print": {"command": "push_status", "mc_percent": 13}})
    merge_report(state, {"info": {"command": "get_version"}})  # not a print report: ignored
    st = status_from_report(state)
    assert (st.state, st.progress_pct, st.remaining_min, st.layer, st.total_layers, st.job_name) == \
        ("RUNNING", 13, 30, 5, 80, "ord_1")
    assert status_from_report({"gcode_state": "SLICING"}).state == "PREPARE"
    assert status_from_report({"gcode_state": "WEIRD"}).state == "IDLE"
    assert status_from_report({}).state == "IDLE"


def test_camera_auth_packet_layout():
    pkt = camera_auth_packet("12345678")
    assert len(pkt) == 80
    assert struct.unpack("<IIII", pkt[:16]) == (0x40, 0x3000, 0, 0)
    assert pkt[16:48] == b"bblp".ljust(32, b"\0") and pkt[48:80] == b"12345678".ljust(32, b"\0")


def _stream(data: bytes, chunk=7):
    buf = bytearray(data)

    def recv_exact(n):
        out = bytearray()
        while len(out) < n:  # deliver in small chunks, like a TLS socket
            take = min(chunk, n - len(out))
            out += buf[:take]
            del buf[:take]
        return bytes(out)
    return recv_exact


def test_read_jpeg_frame():
    jpeg = b"\xff\xd8" + b"pixels" * 50 + b"\xff\xd9"
    frame = struct.pack("<IIII", len(jpeg), 0, 1, 0) + jpeg
    assert read_jpeg_frame(_stream(frame)) == jpeg
    bad = b"\x00\x00" + jpeg[2:]
    with pytest.raises(PrinterError):
        read_jpeg_frame(_stream(struct.pack("<IIII", len(bad), 0, 1, 0) + bad))


class FakeMQTT:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, json.loads(payload)))

        class Info:
            rc = 0
        return Info()

    def is_connected(self):
        return True


def test_bambu_printer_with_fake_transport(tmp_path, monkeypatch):
    p = BambuPrinter("192.0.2.10", "SERIAL1", "12345678")
    fake = FakeMQTT()
    p._client = fake
    uploads = []
    monkeypatch.setattr(p, "_upload", lambda local, remote: uploads.append((local, remote)))
    job = tmp_path / "model.gcode.3mf"
    job.write_bytes(b"zip")
    p.start(job, "ord 1/x")
    assert uploads == [(job, "ord_1_x.gcode.3mf")]
    topic, payload = fake.published[0]
    assert topic == "device/SERIAL1/request"
    assert payload["print"]["url"] == "ftp:///ord_1_x.gcode.3mf" and payload["print"]["use_ams"] is False
    p.pause(); p.resume(); p.stop()
    assert [m["print"]["command"] for _, m in fake.published[1:]] == ["pause", "resume", "stop"]
    p._on_report(json.dumps({"print": {"gcode_state": "PAUSE", "mc_percent": 40, "mc_remaining_time": 9}}).encode())
    p._on_report(b"not json")
    st = p.status()
    assert st.state == "PAUSE" and st.progress_pct == 40 and st.remaining_min == 9


def test_bambu_status_offline_when_unreachable(monkeypatch):
    p = BambuPrinter("192.0.2.10", "S", "c")

    def refuse():
        raise ConnectionRefusedError("no route")
    monkeypatch.setattr(p, "_mqtt", refuse)
    assert p.status().state == "OFFLINE"
    assert printer_mod.STATES[-1] == "OFFLINE"
