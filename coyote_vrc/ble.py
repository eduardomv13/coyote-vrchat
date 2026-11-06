"""Bluetooth layer: transport (bleak or simulated) and the 100 ms send loop.

On Windows bleak has to run in a thread with its own asyncio loop (the GUI uses the main
thread), which is why `AsyncThread` exists.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable, Optional

from . import protocol
from .control import Controller
from .settings import Settings


# ======================================================================================
# Thread with its own asyncio loop
# ======================================================================================
class AsyncThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="ble-asyncio", daemon=True)
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        try:
            self.loop.run_forever()
        finally:
            try:
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            except Exception:
                pass
            self.loop.close()

    def start_and_wait(self) -> None:
        self.start()
        self._ready.wait(2.0)

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)


# ======================================================================================
# Transports
# ======================================================================================
class BleakTransport:
    """Real transport, via bleak (WinRT on Windows)."""

    def __init__(self) -> None:
        self.client = None
        self._write_response = False

    @property
    def connected(self) -> bool:
        return bool(self.client is not None and self.client.is_connected)

    @staticmethod
    def _bleak():
        try:
            import bleak  # noqa: WPS433 (late import on purpose: the app opens even without bleak)
        except ImportError as exc:
            raise RuntimeError("'bleak' library not installed — run: pip install bleak") from exc
        return bleak

    async def discover(self, timeout: float = 6.0) -> list[dict]:
        bleak = self._bleak()
        found = await bleak.BleakScanner.discover(timeout=timeout, return_adv=True)
        out = []
        for _addr, (dev, adv) in found.items():
            name = (dev.name or adv.local_name or "").strip()
            out.append({"name": name, "address": dev.address, "rssi": adv.rssi})
        out.sort(key=lambda d: (d["name"] != protocol.DEVICE_NAME, d["name"] == "", -(d["rssi"] or -999)))
        return out

    async def connect(self, address: Optional[str], on_disconnect: Callable[[], None],
                      on_notify: Callable[[bytes], None]) -> dict:
        bleak = self._bleak()
        device = None
        if address:
            device = await bleak.BleakScanner.find_device_by_address(address, timeout=8.0)
        if device is None:  # no address, or the saved one did not show up: search by the Coyote 3.0 name
            device = await bleak.BleakScanner.find_device_by_filter(
                lambda d, adv: (d.name or adv.local_name or "").strip() == protocol.DEVICE_NAME,
                timeout=10.0,
            )
        if device is None:
            raise RuntimeError(
                f"Coyote ({protocol.DEVICE_NAME}) not found — turn the device on, keep it near the PC and "
                "close any other app connected to it (the Coyote accepts only one connection at a time)"
            )
        client = bleak.BleakClient(device, disconnected_callback=lambda _c: on_disconnect())
        await client.connect()
        self.client = client
        char = client.services.get_characteristic(protocol.CHAR_WRITE)
        if char is None:
            await client.disconnect()
            raise RuntimeError("characteristic 0x150A not found — this device does not look like a Coyote 3.0")
        self._write_response = "write-without-response" not in char.properties
        await client.start_notify(protocol.CHAR_NOTIFY, lambda _c, data: on_notify(bytes(data)))
        return {"name": device.name or protocol.DEVICE_NAME, "address": device.address}

    async def write(self, data: bytes) -> None:
        await self.client.write_gatt_char(protocol.CHAR_WRITE, data, response=self._write_response)

    async def read_battery(self) -> Optional[int]:
        try:
            raw = await self.client.read_gatt_char(protocol.CHAR_BATTERY)
            return int(raw[0])
        except Exception:
            return None

    async def disconnect(self) -> None:
        client, self.client = self.client, None
        if client is not None and client.is_connected:
            await client.disconnect()


class SimulatedTransport:
    """Fake device: validates commands like the Coyote would and returns B1. Used by the tests and --simulate."""

    def __init__(self) -> None:
        self.connected = False
        self.writes: list[bytes] = []
        self.a = 0
        self.b = 0
        self.soft = [200, 200]
        self.fail_next_connect = False
        self.battery = 87
        self._on_disc: Optional[Callable[[], None]] = None
        self._on_notify: Optional[Callable[[bytes], None]] = None

    async def discover(self, timeout: float = 6.0) -> list[dict]:
        return [{"name": protocol.DEVICE_NAME, "address": "SIM:00:00:00", "rssi": -40}]

    async def connect(self, address, on_disconnect, on_notify) -> dict:
        await asyncio.sleep(0)
        if self.fail_next_connect:
            self.fail_next_connect = False
            raise RuntimeError("simulated connection failure")
        self.connected = True
        self._on_disc, self._on_notify = on_disconnect, on_notify
        return {"name": protocol.DEVICE_NAME + " (simulado)", "address": "SIM:00:00:00"}

    async def write(self, data: bytes) -> None:
        if not self.connected:
            raise ConnectionError("disconnected")
        data = bytes(data)
        self.writes.append(data)
        if data[0] == 0xBF and len(data) == 7:
            self.soft = [data[1] if data[1] <= 200 else self.soft[0], data[2] if data[2] <= 200 else self.soft[1]]
        elif data[0] == 0xB0 and len(data) == 20:
            self._apply_b0(data)

    def _apply_b0(self, d: bytes) -> None:
        seq, interp_a, interp_b = d[1] >> 4, (d[1] >> 2) & 3, d[1] & 3
        before = (self.a, self.b)
        cur = [self.a, self.b]
        for idx, (mode, val) in enumerate(((interp_a, d[2]), (interp_b, d[3]))):
            if mode == protocol.KEEP:
                continue
            new = {protocol.ADD: cur[idx] + val, protocol.SUB: cur[idx] - val, protocol.ABS: val}[mode]
            cur[idx] = max(0, min(200, self.soft[idx], new))
        self.a, self.b = cur
        if (self.a, self.b) != before and self._on_notify:
            self._on_notify(bytes([0xB1, seq, self.a, self.b]))

    async def read_battery(self) -> Optional[int]:
        return self.battery

    async def disconnect(self) -> None:
        self.connected = False

    # test helpers
    def drop(self) -> None:
        """Simulates a link loss (device switched off / out of range)."""
        self.connected = False
        if self._on_disc:
            self._on_disc()


# ======================================================================================
# Intensity sync (doc recommendation: sequence number + wait for B1)
# ======================================================================================
class IntensitySync:
    ACK_TIMEOUT = 0.5

    def __init__(self) -> None:
        self.sent: list[Optional[int]] = [None, None]
        self._seq = 0
        self._pending = 0
        self._pending_at = 0.0

    def reset(self) -> None:
        self.sent = [None, None]
        self._pending = 0

    def next(self, desired: tuple[int, int], now: float) -> tuple[int, int, int, int, int]:
        """-> (seq, interp_a, interp_b, value_a, value_b). Only resends the intensity when it changes."""
        if self._pending and now - self._pending_at > self.ACK_TIMEOUT:
            self._pending = 0
        diff = [self.sent[i] != desired[i] for i in (0, 1)]
        if not any(diff):
            return 0, protocol.KEEP, protocol.KEEP, 0, 0
        decrease = any(
            diff[i] and self.sent[i] is not None and desired[i] < self.sent[i] for i in (0, 1)
        )
        zero_only = all(desired[i] == 0 for i in (0, 1) if diff[i])
        # increases wait for B1; decreases and zeroing (safety) go straight through
        if self._pending and not (decrease or zero_only):
            return 0, protocol.KEEP, protocol.KEEP, 0, 0
        modes = [protocol.ABS if diff[i] else protocol.KEEP for i in (0, 1)]
        vals = [desired[i] if diff[i] else 0 for i in (0, 1)]
        for i in (0, 1):
            if diff[i]:
                self.sent[i] = desired[i]
        if zero_only:
            # zeroing needs no confirmation (seq 0 = "no B1 needed") and must never wait
            return 0, modes[0], modes[1], vals[0], vals[1]
        self._seq = self._seq % 15 + 1
        self._pending, self._pending_at = self._seq, now
        return self._seq, modes[0], modes[1], vals[0], vals[1]

    def on_b1(self, seq: int) -> None:
        if seq and seq == self._pending:
            self._pending = 0


# ======================================================================================
# Connection + send loop
# ======================================================================================
class CoyoteLink:
    PERIOD = 0.1  # the protocol requires a B0 every 100 ms

    def __init__(self, control: Controller, settings: Settings, transport, log: Optional[Callable[[str], None]] = None):
        self.control = control
        self.settings = settings
        self.transport = transport
        self.log = log or control.log
        self.sync = IntensitySync()
        self.bf_dirty = True
        self.state = "disconnected"
        self.name = ""
        self.address = ""
        self.battery: Optional[int] = None
        self.error = ""
        self.n_writes = 0
        self._want = False
        self._lost = False
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._wake = asyncio.Event()

    # ---------------------------------------------------------------- API (coroutines on the BLE loop)
    async def connect(self, address: Optional[str] = None) -> None:
        self._loop = asyncio.get_running_loop()
        self._want = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._supervisor(address))

    async def disconnect(self) -> None:
        self._want = False
        self._wake.set()
        task = self._task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=4.0)
            except (asyncio.TimeoutError, Exception):
                task.cancel()

    async def scan(self, timeout: float = 6.0) -> list[dict]:
        return await self.transport.discover(timeout)

    def poke(self) -> None:
        """Wakes the loop (thread-safe): used by the emergency stop to send immediately."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._wake.set)

    def status(self) -> dict:
        return {
            "state": self.state, "connected": self.state == "connected", "name": self.name,
            "address": self.address, "battery": self.battery, "error": self.error, "writes": self.n_writes,
        }

    # ---------------------------------------------------------------- internals
    def _set_state(self, state: str) -> None:
        self.state = state

    def _on_disc(self) -> None:
        self._lost = True
        self.poke()

    def _on_notify(self, data: bytes) -> None:
        msg = protocol.parse_b1(data)
        if msg is not None:
            self.control.set_actual(msg.a, msg.b)
            self.sync.on_b1(msg.seq)

    async def _supervisor(self, address: Optional[str]) -> None:
        backoff = 1.0
        try:
            while self._want:
                try:
                    target = address or self.settings.device_address or None
                    self._set_state("connecting" if target else "searching")
                    self._lost = False
                    info = await self.transport.connect(target, self._on_disc, self._on_notify)
                    backoff = 1.0
                    self.name, self.address, self.error = info.get("name", ""), info.get("address", ""), ""
                    if self.address:
                        self.settings.device_address = self.address
                    self.sync.reset()
                    self.bf_dirty = True
                    self.control.reset_on_connect()
                    self._set_state("connected")
                    self.log(f"Connected to {self.name} ({self.address})")
                    await self._stream()
                    if self._want:
                        self.log("Bluetooth connection lost")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.error = f"{type(exc).__name__}: {exc}"
                    self.log(f"Bluetooth error: {self.error}")
                finally:
                    await self._goodbye()
                if not self._want or not self.settings.auto_reconnect:
                    break
                self._set_state("reconnecting")
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                self._wake.clear()
                backoff = min(backoff * 2, 10.0)
        finally:
            self._want = False
            self._set_state("disconnected")
            self.log("Bluetooth disconnected")

    async def _goodbye(self) -> None:
        if self.transport.connected:
            try:  # leave the device at zero before exiting
                await self.transport.write(protocol.encode_zero())
            except Exception:
                pass
        try:
            await self.transport.disconnect()
        except Exception:
            pass

    def _bf(self) -> bytes:
        s = self.settings
        return protocol.encode_bf(
            s.channel_ceiling(0), s.channel_ceiling(1),
            s.freq_balance_a, s.freq_balance_b, s.width_balance_a, s.width_balance_b,
        )

    async def _stream(self) -> None:
        loop = asyncio.get_running_loop()
        next_t = last = loop.time()
        battery_at = -1e9
        while self._want and self.transport.connected and not self._lost:
            now = loop.time()
            frame = self.control.step(now - last)
            last = now
            if self.bf_dirty:  # soft limit + balances; the doc says to rewrite on every connection
                await self.transport.write(self._bf())
                self.bf_dirty = False
            seq, ia, ib, sa, sb = self.sync.next(frame.intensity, now)
            await self.transport.write(
                protocol.encode_b0(seq, ia, ib, sa, sb, frame.freq[0], frame.width[0], frame.freq[1], frame.width[1])
            )
            self.n_writes += 1
            if now - battery_at > 60.0:
                battery_at = now
                try:
                    self.battery = await asyncio.wait_for(self.transport.read_battery(), timeout=1.5)
                except Exception:
                    pass
            next_t += self.PERIOD
            delay = next_t - loop.time()
            if delay < -1.0:  # stalled for a long time: restart the cadence instead of "catching up"
                next_t, delay = loop.time(), 0.0
            if delay > 0:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                    self._wake.clear()
                    next_t = loop.time()  # woke early (emergency stop/disconnect): restart the cadence
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(0)
