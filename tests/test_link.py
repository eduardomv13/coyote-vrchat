import asyncio
import time
import unittest

from coyote_vrc import protocol
from coyote_vrc.ble import CoyoteLink, IntensitySync, SimulatedTransport
from coyote_vrc.control import Controller
from coyote_vrc.settings import Settings


async def until(cond, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return cond()


class SyncTests(unittest.TestCase):
    ABS, KEEP = protocol.ABS, protocol.KEEP

    def test_first_call_is_a_zero_sync_without_ack(self):
        s = IntensitySync()
        self.assertEqual(s.next((0, 0), 0.0), (0, self.ABS, self.ABS, 0, 0))
        self.assertEqual(s.next((0, 0), 0.1), (0, self.KEEP, self.KEEP, 0, 0))

    def test_increase_waits_for_ack(self):
        s = IntensitySync()
        s.next((0, 0), 0.0)
        self.assertEqual(s.next((10, 0), 0.1), (1, self.ABS, self.KEEP, 10, 0))
        self.assertEqual(s.next((20, 0), 0.15), (0, self.KEEP, self.KEEP, 0, 0))   # still no B1
        s.on_b1(1)
        self.assertEqual(s.next((20, 0), 0.2), (2, self.ABS, self.KEEP, 20, 0))

    def test_decrease_and_zero_bypass_pending(self):
        s = IntensitySync()
        s.next((0, 0), 0.0)
        s.next((50, 0), 0.1)                        # pending, no B1
        seq, ia, ib, va, vb = s.next((30, 0), 0.12)  # a decrease goes straight through
        self.assertEqual((ia, va), (self.ABS, 30))
        self.assertNotEqual(seq, 0)
        seq, ia, ib, va, vb = s.next((0, 0), 0.14)   # zeroing goes straight through without requiring an ack
        self.assertEqual((seq, ia, va), (0, self.ABS, 0))

    def test_ack_timeout_releases(self):
        s = IntensitySync()
        s.next((0, 0), 0.0)
        s.next((10, 0), 0.1)
        self.assertEqual(s.next((20, 0), 0.3)[0], 0)
        self.assertEqual(s.next((20, 0), 0.7)[1], self.ABS)

    def test_stale_ack_is_ignored(self):
        s = IntensitySync()
        s.next((0, 0), 0.0)
        s.next((10, 0), 0.1)   # seq 1
        s.on_b1(7)             # ack for a different seq
        self.assertEqual(s.next((20, 0), 0.15)[0], 0)

    def test_sequence_cycles_1_to_15(self):
        s = IntensitySync()
        seqs = []
        for i in range(1, 31):
            seq = s.next((i, 0), float(i))[0]
            seqs.append(seq)
            s.on_b1(seq)
        self.assertEqual(seqs, [((k - 1) % 15) + 1 for k in range(1, 31)])

    def test_only_changed_channel_is_sent(self):
        s = IntensitySync()
        s.next((0, 0), 0.0)
        s.next((10, 0), 0.1)
        s.on_b1(1)
        seq, ia, ib, va, vb = s.next((10, 40), 0.2)
        self.assertEqual((ia, ib, vb), (self.KEEP, self.ABS, 40))


class LinkTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Settings().validate()
        self.settings.ramp_up_per_s = 0
        self.t = SimulatedTransport()
        self.control = Controller(self.settings)
        self.link = CoyoteLink(self.control, self.settings, self.t)

    async def asyncTearDown(self):
        await self.link.disconnect()

    async def connect(self):
        await self.link.connect()
        self.assertTrue(await until(lambda: self.link.state == "connected"))

    def b0s(self):
        return [w for w in self.t.writes if w[0] == 0xB0]

    async def test_connection_sequence_bf_first_then_zero_then_stream(self):
        await self.connect()
        self.assertTrue(await until(lambda: len(self.t.writes) >= 4))
        self.assertEqual(self.t.writes[0][0], 0xBF)                      # BF before everything
        self.assertEqual(list(self.t.writes[0][1:3]), [200, 200])
        self.assertEqual(self.t.writes[1][0], 0xB0)
        self.assertEqual(self.t.writes[1][1], 0x0F)                      # seq 0, A and B absolute
        self.assertEqual(list(self.t.writes[1][2:4]), [0, 0])            # zeroed
        self.assertEqual(self.t.writes[2][1], 0x00)                      # afterwards, wave only (without touching the intensity)
        self.assertIn("simulado", self.link.status()["name"])
        self.assertTrue(await until(lambda: self.link.battery == 87, 1.0))

    async def test_intensity_reaches_device_and_echo_updates_actual(self):
        await self.connect()
        self.control.set_intensity("A", 60, "gui")
        self.assertTrue(await until(lambda: self.t.a == 60))
        self.assertTrue(await until(lambda: self.control.snapshot()["channels"]["A"]["actual"] == 60))
        self.assertTrue(all(w[2] <= 200 and w[3] <= 200 for w in self.b0s()))

    async def test_waveform_and_frequency_reach_the_wire(self):
        await self.connect()
        self.control.set_frequency("A", 10, "gui")      # 100 ms -> byte 100
        self.control.set_width("A", 40, "gui")
        self.assertTrue(await until(lambda: self.b0s()[-1][4:8] == bytes([100] * 4)))
        last = self.b0s()[-1]
        self.assertEqual(last[8:12], bytes([40] * 4))

    async def test_ramp_is_gradual(self):
        self.settings.ramp_up_per_s = 200
        await self.connect()
        self.control.set_intensity("A", 100, "gui")
        await asyncio.sleep(0.25)
        self.assertLess(self.t.a, 100)
        self.assertTrue(await until(lambda: self.t.a == 100, 3.0))

    async def test_cap_goes_to_bf_and_is_enforced(self):
        self.settings.max_intensity_a = self.settings.max_intensity_b = 80
        await self.connect()
        self.assertTrue(await until(lambda: len(self.t.writes) >= 1))
        self.assertEqual(list(self.t.writes[0][1:3]), [80, 80])
        self.control.set_intensity("AB", 200, "gui")
        self.assertTrue(await until(lambda: self.t.a == 80 and self.t.b == 80))
        self.assertEqual(self.t.soft, [80, 80])

    async def test_changing_cap_rewrites_bf(self):
        await self.connect()
        self.assertTrue(await until(lambda: len(self.b0s()) >= 2))
        self.control.configure(max_intensity_a=120, max_intensity_b=120)
        self.link.bf_dirty = True
        self.link.poke()
        self.assertTrue(await until(lambda: self.t.soft == [120, 120]))

    async def test_each_channel_has_its_own_soft_limit_on_the_device(self):
        self.settings.max_intensity_a, self.settings.max_intensity_b = 60, 140
        await self.connect()
        self.assertTrue(await until(lambda: len(self.t.writes) >= 1))
        self.assertEqual(list(self.t.writes[0][1:3]), [60, 140])
        self.control.set_intensity("AB", 200, "gui")
        self.assertTrue(await until(lambda: self.t.a == 60 and self.t.b == 140))
        self.assertEqual(self.t.soft, [60, 140])

    def bfs(self):
        return [w for w in self.t.writes if w[0] == 0xBF]

    async def test_intensity_balance_goes_to_bf_on_connect(self):
        self.settings.width_balance_a, self.settings.width_balance_b = 30, 220
        await self.connect()
        self.assertTrue(await until(lambda: len(self.bfs()) >= 1))
        # 0xBF | soft A, B | frequency balance A, B | intensity balance A, B (the doc's order)
        self.assertEqual(self.bfs()[0], bytes([0xBF, 200, 200, 160, 160, 30, 220]))

    async def test_changing_the_intensity_balance_rewrites_bf(self):
        await self.connect()
        self.assertTrue(await until(lambda: len(self.bfs()) >= 1 and len(self.b0s()) >= 2))
        n = len(self.bfs())
        self.control.configure(width_balance_a=180)
        self.link.bf_dirty = True
        self.link.poke()
        self.assertTrue(await until(lambda: len(self.bfs()) > n))
        self.assertEqual(self.bfs()[-1], bytes([0xBF, 200, 200, 160, 160, 180, 100]))

    async def test_emergency_stop_is_fast_even_with_pending_ack(self):
        await self.connect()
        self.control.set_intensity("A", 150, "gui")
        self.assertTrue(await until(lambda: self.t.a == 150))
        t0 = time.monotonic()
        self.control.emergency_stop("gui")
        self.link.poke()
        self.assertTrue(await until(lambda: self.t.a == 0, 0.6))
        self.assertLess(time.monotonic() - t0, 0.4)

    async def test_stream_cadence_is_100ms(self):
        await self.connect()
        await asyncio.sleep(0.3)
        before = len(self.b0s())
        await asyncio.sleep(1.0)
        n = len(self.b0s()) - before
        self.assertTrue(8 <= n <= 12, n)

    async def test_drop_then_reconnect_rewrites_bf_and_zeroes(self):
        await self.connect()
        self.control.set_intensity("A", 50, "gui")
        self.assertTrue(await until(lambda: self.t.a == 50))
        bf_before = sum(1 for w in self.t.writes if w[0] == 0xBF)
        self.t.drop()
        self.assertTrue(await until(lambda: self.link.state == "connected" and
                                    sum(1 for w in self.t.writes if w[0] == 0xBF) > bf_before, 4.0))
        self.assertTrue(await until(lambda: self.t.a == 0))      # reconnected: the device goes back to zero
        self.assertEqual(self.control.snapshot()["channels"]["A"]["target"], 0.0)

    async def test_no_auto_reconnect(self):
        self.settings.auto_reconnect = False
        await self.connect()
        self.t.drop()
        self.assertTrue(await until(lambda: self.link.state == "disconnected", 2.0))
        await asyncio.sleep(0.3)
        self.assertEqual(self.link.state, "disconnected")

    async def test_connect_failure_is_reported_and_retried(self):
        self.t.fail_next_connect = True
        await self.link.connect()
        self.assertTrue(await until(lambda: "simulated" in self.link.error, 1.5))
        self.assertTrue(await until(lambda: self.link.state == "connected", 4.0))
        self.assertEqual(self.link.error, "")

    async def test_write_error_triggers_reconnect(self):
        await self.connect()
        orig = self.t.write
        calls = {"n": 0}

        async def flaky(data):
            calls["n"] += 1
            if calls["n"] == 3:
                raise ConnectionError("link dropped")
            await orig(data)

        self.t.write = flaky
        self.assertTrue(await until(lambda: "link dropped" in self.link.error, 2.0))
        self.assertTrue(await until(lambda: self.link.state == "connected", 4.0))

    async def test_disconnect_leaves_device_at_zero(self):
        await self.connect()
        self.control.set_intensity("A", 40, "gui")
        self.assertTrue(await until(lambda: self.t.a == 40))
        await self.link.disconnect()
        self.assertFalse(self.t.connected)
        self.assertEqual(self.link.state, "disconnected")
        self.assertEqual((self.t.a, self.t.b), (0, 0))

    async def test_saved_address_is_remembered(self):
        await self.connect()
        self.assertEqual(self.settings.device_address, "SIM:00:00:00")


if __name__ == "__main__":
    unittest.main()
