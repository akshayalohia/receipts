"""Printer control: Bambu Lab A1 over LAN (Developer Mode) or a simulated MockPrinter.

Bambu transport is implemented directly with ftplib + paho-mqtt + ssl rather than `bambulabs_api`:
that library builds its MQTT payloads inside private methods (hard-coded sequence_id, ams_mapping,
calibration flags) so they cannot be unit-tested without a broker, and its pause/resume depend on its
own cached state. Payloads below follow ha-bambulab's pybambu/commands.py.
"""
from __future__ import annotations

import ftplib
import io
import json
import os
import socket
import ssl
import struct
import threading
import time
from pathlib import Path
from typing import Callable, Protocol

from . import is_mock
from .types import PrinterStatus

STATES = ("IDLE", "PREPARE", "RUNNING", "PAUSE", "FINISH", "FAILED", "OFFLINE")


class Printer(Protocol):
    def start(self, gcode_3mf: Path, job_name: str) -> None: ...
    def status(self) -> PrinterStatus: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
    def snapshot_jpeg(self) -> bytes: ...


class PrinterError(Exception):
    pass


# ---------------------------------------------------------------- payloads + report parsing (pure, unit-tested)

def project_file_payload(remote_name: str, job_name: str) -> dict:
    return {"print": {
        "sequence_id": "0",
        "command": "project_file",
        "param": "Metadata/plate_1.gcode",
        "url": f"ftp:///{remote_name}",
        "file": remote_name,
        "subtask_name": job_name,
        "bed_type": "textured_plate",
        "bed_leveling": True,
        "flow_cali": True,
        "vibration_cali": True,
        "layer_inspect": False,
        "timelapse": False,
        "use_ams": False,
        "ams_mapping": [0],
        "profile_id": "0", "project_id": "0", "subtask_id": "0", "task_id": "0",
    }}


def simple_payload(command: str) -> dict:
    if command not in ("pause", "resume", "stop"):
        raise ValueError(command)
    return {"print": {"sequence_id": "0", "command": command}}


PUSHALL = {"pushing": {"sequence_id": "0", "command": "pushall"}}


def merge_report(state: dict, message: dict) -> dict:
    """A1/P1 send partial `print` reports; merge each one into the cached full state."""
    pr = message.get("print")
    if isinstance(pr, dict):
        state.update(pr)
    return state


def status_from_report(state: dict) -> PrinterStatus:
    gs = str(state.get("gcode_state") or "IDLE").upper()
    gs = {"SLICING": "PREPARE", "INIT": "PREPARE", "FINISHED": "FINISH"}.get(gs, gs)
    if gs not in STATES:
        gs = "IDLE"

    def i(key):
        try:
            return int(state.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    return PrinterStatus(state=gs, progress_pct=i("mc_percent"), remaining_min=i("mc_remaining_time"),
                         layer=i("layer_num"), total_layers=i("total_layer_num"),
                         job_name=state.get("subtask_name") or None, raw=dict(state))


def camera_auth_packet(access_code: str, username: str = "bblp") -> bytes:
    """OpenBambuAPI video.md: 0x40, 0x3000, 0, 0, then user and password, 32 bytes each, NUL-padded, LE."""
    return struct.pack("<IIII32s32s", 0x40, 0x3000, 0, 0, username.encode("ascii"), access_code.encode("ascii"))


def read_jpeg_frame(recv_exact: Callable[[int], bytes]) -> bytes:
    """Read one frame: 16-byte header (payload size LE, itrack, flags, 0) then the JPEG bytes."""
    size = struct.unpack("<I", recv_exact(16)[:4])[0]
    if not 0 < size < 16 * 1024 * 1024:
        raise PrinterError(f"bad camera frame size {size}")
    jpeg = recv_exact(size)
    if jpeg[:2] != b"\xff\xd8" or jpeg[-2:] != b"\xff\xd9":
        raise PrinterError("camera frame is not a complete JPEG")
    return jpeg


# ---------------------------------------------------------------- Bambu A1 (LAN-only + Developer Mode)

def _tls_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # printer presents a Bambu-CA self-signed cert on the LAN
    return ctx


class _ImplicitFTPS(ftplib.FTP_TLS):
    """FTPS with implicit TLS (port 990) and TLS session reuse on the data channel, as the A1 requires."""

    def connect(self, host="", port=990, timeout=-999, source_address=None):
        self.host, self.port = host, port
        if timeout != -999:
            self.timeout = timeout
        self.sock = self.context.wrap_socket(socket.create_connection((host, port), self.timeout), server_hostname=host)
        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size

    def store_no_unwrap(self, name: str, data: bytes) -> None:
        # storbinary() can hang in TLS unwrap() on the A1: send, close the socket, then read the 226.
        self.voidcmd("TYPE I")
        conn = self.transfercmd(f"STOR {name}")
        try:
            conn.sendall(data)
        finally:
            conn.close()
        self.voidresp()


class BambuPrinter:
    def __init__(self, ip: str, serial: str, access_code: str):
        self.ip, self.serial, self.access_code = ip, serial, access_code
        self._state: dict = {}
        self._lock = threading.Lock()
        self._client = None  # paho client, connected lazily

    # -- transport
    def _mqtt(self):
        if self._client is None:
            import paho.mqtt.client as mqtt

            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"factory-{os.getpid()}")
            c.username_pw_set("bblp", self.access_code)
            c.tls_set_context(_tls_context())
            def on_connect(cl, *_):
                cl.subscribe(f"device/{self.serial}/report")
                cl.publish(f"device/{self.serial}/request", json.dumps(PUSHALL))  # ask for a full report

            c.on_connect = on_connect
            c.on_message = lambda _c, _u, msg: self._on_report(msg.payload)
            c.connect(self.ip, 8883, keepalive=60)
            c.loop_start()
            self._client = c
        return self._client

    def _on_report(self, payload: bytes) -> None:
        try:
            msg = json.loads(payload)
        except ValueError:
            return
        with self._lock:
            merge_report(self._state, msg)

    def _publish(self, payload: dict) -> None:
        info = self._mqtt().publish(f"device/{self.serial}/request", json.dumps(payload), qos=1)
        if getattr(info, "rc", 0) != 0:
            raise PrinterError(f"MQTT publish failed rc={info.rc}")

    def _upload(self, local: Path, remote_name: str) -> None:
        ftp = _ImplicitFTPS(context=_tls_context(), timeout=30)
        try:
            ftp.connect(self.ip, 990)
            ftp.login("bblp", self.access_code)
            ftp.prot_p()
            ftp.store_no_unwrap(remote_name, Path(local).read_bytes())
        finally:
            try:
                ftp.close()
            except OSError:
                pass

    # -- Printer protocol
    def start(self, gcode_3mf: Path, job_name: str) -> None:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in job_name)[:40] or "job"
        remote = f"{safe}.gcode.3mf"
        self._upload(Path(gcode_3mf), remote)
        self._publish(project_file_payload(remote, job_name))

    def status(self) -> PrinterStatus:
        try:
            client = self._mqtt()
        except OSError:
            return PrinterStatus("OFFLINE", 0, 0, 0, 0, None, {})
        if not client.is_connected():
            return PrinterStatus("OFFLINE", 0, 0, 0, 0, None, dict(self._state))
        with self._lock:
            return status_from_report(self._state)

    def pause(self) -> None:
        self._publish(simple_payload("pause"))

    def resume(self) -> None:
        self._publish(simple_payload("resume"))

    def stop(self) -> None:
        self._publish(simple_payload("stop"))

    def snapshot_jpeg(self) -> bytes:
        raw = socket.create_connection((self.ip, 6000), timeout=10)
        with _tls_context().wrap_socket(raw, server_hostname=self.ip) as s:
            s.sendall(camera_auth_packet(self.access_code))

            def recv_exact(n: int) -> bytes:
                buf = bytearray()
                while len(buf) < n:
                    chunk = s.recv(min(65536, n - len(buf)))
                    if not chunk:
                        raise PrinterError("camera stream closed")
                    buf += chunk
                return bytes(buf)

            return read_jpeg_frame(recv_exact)


# ---------------------------------------------------------------- simulated printer

class MockPrinter:
    """PREPARE (first 10%) -> RUNNING -> FINISH over `job_seconds`; pause freezes the clock."""

    TOTAL_LAYERS = 100

    def __init__(self, job_seconds: float = 60.0):
        self.job_seconds = float(job_seconds)
        self._lock = threading.Lock()
        self._job: str | None = None
        self._elapsed = 0.0
        self._t0: float | None = None  # monotonic time of the last resume/start, None while paused
        self._ended: str | None = None  # "FAILED" after stop

    def _progress(self) -> float:
        run = self._elapsed + (time.monotonic() - self._t0 if self._t0 is not None else 0.0)
        return min(1.0, run / self.job_seconds) if self.job_seconds > 0 else 1.0

    def start(self, gcode_3mf: Path, job_name: str) -> None:
        with self._lock:
            if self._job is not None and self._ended is None and self._progress() < 1.0:
                raise PrinterError("printer is busy")
            self._job, self._elapsed, self._t0, self._ended = job_name, 0.0, time.monotonic(), None

    def status(self) -> PrinterStatus:
        with self._lock:
            if self._job is None:
                return PrinterStatus("IDLE", 0, 0, 0, 0, None, {"gcode_state": "IDLE"})
            p = self._progress()
            if self._ended:
                state = self._ended
            elif p >= 1.0:
                state = "FINISH"
            elif self._t0 is None:
                state = "PAUSE"
            else:
                state = "PREPARE" if p < 0.10 else "RUNNING"
            pct = int(p * 100)
            if p < 0.10:
                layer = 0
            elif p >= 1.0:
                layer = self.TOTAL_LAYERS
            else:
                layer = max(1, int((p - 0.10) / 0.90 * self.TOTAL_LAYERS))
            remaining = int(round((1.0 - p) * self.job_seconds / 60.0))
            raw = {"gcode_state": state, "mc_percent": pct, "mc_remaining_time": remaining,
                   "layer_num": layer, "total_layer_num": self.TOTAL_LAYERS, "subtask_name": self._job, "mock": True}
            return PrinterStatus(state, pct, remaining, layer, self.TOTAL_LAYERS, self._job, raw)

    def pause(self) -> None:
        with self._lock:
            if self._t0 is not None and self._ended is None:
                self._elapsed += time.monotonic() - self._t0
                self._t0 = None

    def resume(self) -> None:
        with self._lock:
            if self._job is not None and self._t0 is None and self._ended is None:
                self._t0 = time.monotonic()

    def stop(self) -> None:
        with self._lock:
            if self._job is not None and self._ended is None and self._progress() < 1.0:
                if self._t0 is not None:  # freeze the clock where it stopped
                    self._elapsed += time.monotonic() - self._t0
                    self._t0 = None
                self._ended = "FAILED"

    def snapshot_jpeg(self) -> bytes:
        from PIL import Image, ImageDraw

        st = self.status()
        img = Image.new("RGB", (640, 360), (28, 30, 34))
        d = ImageDraw.Draw(img)
        d.rectangle((60, 290, 580, 310), fill=(70, 70, 76))  # bed
        h = int(160 * st.progress_pct / 100)
        if h:
            d.rectangle((270, 290 - h, 370, 290), fill=(80, 140, 220))  # the part grows with progress
        d.rectangle((300, 40, 340, 70), fill=(200, 200, 205))  # nozzle carriage
        d.text((16, 12), f"MOCK A1  {st.state}  {st.progress_pct}%  layer {st.layer}/{st.total_layers}", fill=(235, 235, 235))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return buf.getvalue()


_printer: Printer | None = None


def get_printer() -> Printer:
    """MockPrinter when FACTORY_MOCK=1 or PRINTER_IP/SERIAL/ACCESS_CODE are missing; one shared instance."""
    global _printer
    if _printer is None:
        ip, serial, code = (os.environ.get(k, "") for k in ("PRINTER_IP", "PRINTER_SERIAL", "PRINTER_ACCESS_CODE"))
        _printer = MockPrinter() if is_mock() or not (ip and serial and code) else BambuPrinter(ip, serial, code)
    return _printer
