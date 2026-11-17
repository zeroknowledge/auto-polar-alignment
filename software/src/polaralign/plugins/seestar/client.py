"""Minimal JSON-lines client for the Seestar's unofficial control port (TCP 4700) and discovery (UDP 4720).

EXPERIMENTAL and UNVERIFIED.  The framing used here (one JSON object per line, requests carry an integer
``id`` and a ``method``, replies echo the ``id`` and carry ``result``/``code``, asynchronous events have an
``Event`` key) is what the community projects seestar_alp and seestarpy are reported to use, but this code
has never talked to a real telescope.  Firmware updates have broken that interface before (v2.4).
Nothing outside this package imports it unless ``seestar.enabled`` is set.
"""
from __future__ import annotations

import json
import queue
import socket
import threading
import time
from typing import Any


class SeestarError(RuntimeError):
    pass


class SeestarClient:
    def __init__(self, host: str, port: int = 4700, timeout_s: float = 10.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout_s
        self._sock: socket.socket | None = None
        self._id = 1000
        self._pending: dict[int, queue.Queue] = {}
        self.events: queue.Queue = queue.Queue(maxsize=200)
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None

    def connect(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(None)
        self._reader = threading.Thread(target=self._read_loop, name="seestar-reader", daemon=True)
        self._reader.start()

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _read_loop(self) -> None:
        buf = b""
        sock = self._sock
        while sock is not None:
            try:
                chunk = sock.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                mid = msg.get("id")
                if mid in self._pending:
                    self._pending[mid].put(msg)
                elif "Event" in msg:
                    try:
                        self.events.put_nowait(msg)
                    except queue.Full:
                        pass

    def call(self, method: str, params: Any = None, timeout: float | None = None) -> dict:
        if not self._sock:
            raise SeestarError("not connected")
        with self._lock:
            self._id += 1
            mid = self._id
        q: queue.Queue = queue.Queue(maxsize=1)
        self._pending[mid] = q
        msg: dict[str, Any] = {"id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        try:
            self._sock.sendall((json.dumps(msg) + "\r\n").encode())
            reply = q.get(timeout=timeout or self.timeout)
        except queue.Empty as exc:
            raise SeestarError(f"no reply to {method!r} within {timeout or self.timeout} s") from exc
        finally:
            self._pending.pop(mid, None)
        if reply.get("code", 0) not in (0, None):
            raise SeestarError(f"{method!r} failed: code {reply.get('code')} {reply.get('error', '')}")
        return reply


def discover(timeout_s: float = 2.0, port: int = 4720) -> list[str]:
    """UDP broadcast probe; returns the IP addresses that answered (protocol as reported by seestar_alp)."""
    found: list[str] = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.5)
    try:
        s.sendto(json.dumps({"id": 201, "method": "scan_iscope", "name": "iscope", "ver": 1}).encode() + b"\r\n",
                 ("255.255.255.255", port))
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            try:
                _, addr = s.recvfrom(2048)
                if addr[0] not in found:
                    found.append(addr[0])
            except socket.timeout:
                continue
    finally:
        s.close()
    return found
