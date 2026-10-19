"""Minimal OSC (stdlib only): decoder/encoder and a UDP listener.

VRChat sends avatar parameters as OSC messages to port 9001 (default) at the address
/avatar/parameters/<name>, with float (0..1), int or bool arguments.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from typing import Callable, List, Optional, Tuple

OscMessage = Tuple[str, list]


def _pad4(n: int) -> int:
    return (n + 3) & ~3


def _read_str(data: bytes, i: int) -> Tuple[str, int]:
    end = data.find(b"\x00", i)
    if end < 0:
        raise ValueError("OSC string without terminator")
    return data[i:end].decode("utf-8", "replace"), i + _pad4(end - i + 1)


def parse_message(data: bytes) -> OscMessage:
    address, i = _read_str(data, 0)
    if i >= len(data):
        return address, []
    tags, i = _read_str(data, i)
    if not tags.startswith(","):
        return address, []
    args: list = []
    for tag in tags[1:]:
        if tag == "f":
            args.append(struct.unpack_from(">f", data, i)[0]); i += 4
        elif tag == "i":
            args.append(struct.unpack_from(">i", data, i)[0]); i += 4
        elif tag == "T":
            args.append(True)
        elif tag == "F":
            args.append(False)
        elif tag == "N":
            args.append(None)
        elif tag == "s":
            s, i = _read_str(data, i)
            args.append(s)
        elif tag == "d":
            args.append(struct.unpack_from(">d", data, i)[0]); i += 8
        elif tag == "h":
            args.append(struct.unpack_from(">q", data, i)[0]); i += 8
        elif tag == "b":
            size = struct.unpack_from(">i", data, i)[0]; i += 4
            args.append(bytes(data[i:i + size])); i += _pad4(size)
        else:
            raise ValueError(f"unsupported OSC type: {tag!r}")
    return address, args


def parse_packet(data: bytes) -> List[OscMessage]:
    """Accepts a plain message or a bundle (recursive)."""
    if data.startswith(b"#bundle\x00"):
        out: List[OscMessage] = []
        i = 16  # "#bundle\0" (8) + timetag (8)
        while i + 4 <= len(data):
            size = struct.unpack_from(">i", data, i)[0]
            i += 4
            if size <= 0 or i + size > len(data):
                break
            out.extend(parse_packet(data[i:i + size]))
            i += size
        return out
    return [parse_message(data)]


def _enc_str(s: str) -> bytes:
    raw = s.encode("utf-8") + b"\x00"
    return raw + b"\x00" * (_pad4(len(raw)) - len(raw))


def encode_message(address: str, *args) -> bytes:
    """Encodes a message (bool, int, float, str) — used by the tests."""
    tags = ","
    payload = b""
    for a in args:
        if isinstance(a, bool):
            tags += "T" if a else "F"
        elif isinstance(a, int):
            tags += "i"; payload += struct.pack(">i", a)
        elif isinstance(a, float):
            tags += "f"; payload += struct.pack(">f", a)
        elif isinstance(a, str):
            tags += "s"; payload += _enc_str(a)
        else:
            raise TypeError(f"unsupported type: {type(a)}")
    return _enc_str(address) + _enc_str(tags) + payload


CHATBOX_ADDRESS = "/chatbox/input"
CHATBOX_MAX_CHARS = 144   # VRChat's limit for one chatbox message


class OscSender:
    """Sends OSC messages to VRChat over UDP, fire and forget (VRChat listens for OSC input on port 9000 by default)."""

    def __init__(self) -> None:
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()

    def send(self, host: str, port: int, address: str, *args) -> None:
        """Raises OSError when the host cannot be resolved or the socket fails."""
        data = encode_message(address, *args)
        with self._lock:
            if self._sock is None:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.sendto(data, (host, int(port)))

    def send_chatbox(self, host: str, port: int, text: str, immediate: bool = True, sound: bool = False) -> None:
        """/chatbox/input <text> <send immediately> <notification sound>. `immediate` skips the keyboard."""
        self.send(host, port, CHATBOX_ADDRESS, text[:CHATBOX_MAX_CHARS], bool(immediate), bool(sound))

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None


class OscListener:
    """Listens on UDP and calls handler(address, args) for each message."""

    def __init__(self, host: str, port: int, handler: Callable[[str, list], None]):
        self.host, self.port, self.handler = host, port, handler
        self.packets = 0
        self.last_packet: Optional[float] = None  # time.monotonic()
        self.last_error = ""
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        """Raises OSError if the port is taken (e.g. another controller using 9001)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.host, self.port))  # no SO_REUSEADDR: on Windows it would let two apps "share" the port
        except OSError:
            sock.close()
            raise
        sock.settimeout(0.3)
        self.port = sock.getsockname()[1]  # useful when port 0 is requested (tests)
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="osc-listener", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        sock = self._sock
        while not self._stop.is_set() and sock is not None:
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except ConnectionResetError:
                continue  # Windows: ICMP from earlier sends
            except OSError:
                break
            self.packets += 1
            self.last_packet = time.monotonic()
            try:
                for address, args in parse_packet(data):
                    self.handler(address, args)
            except Exception as exc:  # one bad packet must not take the listener down
                self.last_error = f"{type(exc).__name__}: {exc}"

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        self._sock = None

    @property
    def listening(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
