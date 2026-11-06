import unittest

from coyote_vrc.control import ControlError, ControlForbidden, Controller, channels_from
from coyote_vrc.settings import Settings


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(**kw):
    clock = Clock()
    s = Settings(**kw).validate()
    return Controller(s, clock), s, clock


class Channels(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(channels_from("A"), (0,))
        self.assertEqual(channels_from("b"), (1,))
        self.assertEqual(channels_from("AB"), (0, 1))
        self.assertEqual(channels_from(0), (0,))
        self.assertEqual(channels_from([1, 0]), (0, 1))

    def test_invalid(self):
        for bad in ("C", True, 2, None, "", [], [0, 5]):
            with self.assertRaises(ControlError, msg=repr(bad)):
                channels_from(bad)


class Mapping(unittest.TestCase):
    def test_osc_full_scale_is_exactly_200(self):
        # avoids the scale bug reported in other modules (100% landing at 50% of the total)
        c, _, _ = make()
        c.set_fraction("A", 1.0, "osc")
        c.set_fraction("B", 0.5, "osc")
        snap = c.snapshot()["channels"]
        self.assertEqual(snap["A"]["target"], 200.0)
        self.assertEqual(snap["B"]["target"], 100.0)

    def test_osc_full_scale_follows_cap(self):
        c, _, _ = make(max_intensity_a=120)
        c.set_fraction("A", 1.0, "osc")
        self.assertEqual(c.snapshot()["channels"]["A"]["target"], 120.0)

    def test_fraction_out_of_range_is_clamped(self):
        c, _, _ = make()
        c.set_fraction("A", 7.0, "osc")
        self.assertEqual(c.snapshot()["channels"]["A"]["target"], 200.0)
        c.set_fraction("A", -3.0, "osc")
        self.assertEqual(c.snapshot()["channels"]["A"]["target"], 0.0)

    def test_gui_clamps_to_cap(self):
        c, _, _ = make()
        r = c.set_intensity("A", 300, "gui")
        self.assertEqual((r["applied"], r["clamped"]), (200.0, True))

    def test_invalid_numbers(self):
        c, _, _ = make()
        for bad in (None, "abc", float("nan"), float("inf"), True):
            with self.assertRaises(ControlError, msg=repr(bad)):
                c.set_intensity("A", bad, "gui")


class PerChannelCeiling(unittest.TestCase):
    def test_each_channel_clamps_to_its_own_ceiling(self):
        c, _, _ = make(max_intensity_a=60, max_intensity_b=120)
        self.assertEqual(c.set_intensity("A", 150, "gui")["applied"], 60.0)
        self.assertEqual(c.set_intensity("B", 150, "gui")["applied"], 120.0)

    def test_ab_reports_the_lowest_and_applies_each(self):
        c, _, _ = make(max_intensity_a=60, max_intensity_b=120)
        r = c.set_intensity("AB", 100, "gui")
        self.assertEqual((r["applied"], r["clamped"], r["limit"]), (60.0, True, 60))
        self.assertEqual(r["per_channel"], {"A": 60.0, "B": 100.0})
        snap = c.snapshot()["channels"]
        self.assertEqual((snap["A"]["target"], snap["B"]["target"]), (60.0, 100.0))

    def test_osc_full_scale_follows_the_channel_ceiling(self):
        c, _, _ = make(max_intensity_a=90)
        c.set_fraction("A", 1.0, "osc")
        c.set_fraction("B", 1.0, "osc")
        snap = c.snapshot()["channels"]
        self.assertEqual((snap["A"]["target"], snap["B"]["target"]), (90.0, 200.0))

    def test_lowering_a_channel_ceiling_cuts_it_at_once(self):
        c, _, clock = make()
        c.set_intensity("AB", 150, "gui")
        for _ in range(30):
            clock.t += 0.1
            c.step(0.1)
        c.configure(max_intensity_b=40)
        snap = c.snapshot()["channels"]
        self.assertEqual((snap["A"]["target"], snap["B"]["target"], snap["B"]["output"]), (150.0, 40.0, 40.0))
        self.assertEqual(c.step(0.1).intensity[1], 40)

    def test_step_never_exceeds_the_channel_ceiling_even_in_a_shock(self):
        c, _, clock = make(max_intensity_a=30)
        c.start_shocks({"A": (100, 5), "B": (100, 5)})
        for _ in range(20):
            clock.t += 0.1
            f = c.step(0.1)
        self.assertEqual(f.intensity, (30, 100))

    def test_configure_clamps_and_snapshot_shows_it(self):
        c, s, _ = make()
        c.configure(max_intensity_a=999, max_intensity_b=-3)
        self.assertEqual((s.max_intensity_a, s.max_intensity_b), (200, 0))
        lim = c.snapshot()["limits"]
        self.assertEqual((lim["max_intensity_a"], lim["max_intensity_b"]), (200, 0))
        self.assertNotIn("max_intensity", lim)   # there is no global ceiling any more

    def test_ai_ceiling_applies_on_top(self):
        c, _, _ = make(max_intensity_a=100, ai_cap=70, ai_enabled=True)
        self.assertEqual(c.set_intensity("A", 150, "ai")["applied"], 70.0)

    def test_the_global_ceiling_is_gone(self):
        c, _, _ = make()
        with self.assertRaises(ControlError):
            c.configure(max_intensity=50)
        with self.assertRaises(TypeError):
            Settings(max_intensity=50)


class IntensityBalance(unittest.TestCase):
    def test_configure_clamps_to_0_255_and_reports_the_change(self):
        c, s, _ = make()
        self.assertEqual(c.configure(width_balance_a=300, width_balance_b=-4), {"width_balance_a", "width_balance_b"})
        self.assertEqual((s.width_balance_a, s.width_balance_b), (255, 0))

    def test_nothing_changed_nothing_reported(self):
        c, s, _ = make()
        self.assertEqual(c.configure(width_balance_a=s.width_balance_a), set())

    def test_a_channel_does_not_move_the_other(self):
        c, s, _ = make()
        before = s.width_balance_b
        c.configure(width_balance_a=180)
        self.assertEqual((s.width_balance_a, s.width_balance_b), (180, before))

    def test_it_does_not_change_the_intensity_or_the_pulse_width(self):
        c, _, _ = make()
        c.set_intensity("A", 40, "gui")
        c.set_width("A", 70, "gui")
        c.configure(width_balance_a=220)
        ch = c.snapshot()["channels"]["A"]
        self.assertEqual((ch["target"], ch["width"]), (40.0, 70.0))


class AiRules(unittest.TestCase):
    def test_disabled_by_default_and_refuses(self):
        c, s, _ = make()
        self.assertFalse(s.ai_enabled)
        for call in (
            lambda: c.set_intensity("A", 10, "ai"),
            lambda: c.set_frequency("A", 10, "ai"),
            lambda: c.set_width("A", 10, "ai"),
            lambda: c.set_pattern("pulse", source="ai"),
        ):
            with self.assertRaises(ControlForbidden):
                call()
        self.assertEqual(c.snapshot()["channels"]["A"]["target"], 0.0)

    def test_enabled_uses_ai_cap(self):
        c, _, _ = make()
        c.configure(ai_enabled=True)
        r = c.set_intensity("AB", 120, "ai")
        self.assertEqual((r["applied"], r["clamped"], r["limit"]), (50.0, True, 50))
        self.assertEqual(c.snapshot()["ai_last_action"], "intensity A+B = 50")

    def test_ai_cannot_exceed_global_cap(self):
        c, _, _ = make(max_intensity_a=30, ai_cap=100)
        c.configure(ai_enabled=True)
        self.assertEqual(c.set_intensity("A", 90, "ai")["applied"], 30.0)

    def test_frequency_and_width_clamped(self):
        c, _, _ = make()
        c.configure(ai_enabled=True)
        self.assertEqual(c.set_frequency("A", 200, "ai")["applied"], 100.0)   # 200 Hz does not exist in V3
        self.assertEqual(c.set_frequency("A", 0, "ai")["applied"], 1.0)
        self.assertEqual(c.set_width("A", 500, "ai")["applied"], 100.0)

    def test_lowering_cap_clamps_what_ai_set(self):
        c, _, _ = make()
        c.configure(ai_enabled=True)
        c.set_intensity("A", 50, "ai")
        c.configure(ai_cap=20)
        self.assertEqual(c.snapshot()["channels"]["A"]["target"], 20.0)

    def test_disabling_ai_zeroes_what_ai_started_but_not_gui(self):
        c, _, _ = make()
        c.configure(ai_enabled=True)
        c.set_intensity("A", 40, "ai")
        c.set_intensity("B", 60, "gui")
        c.configure(ai_enabled=False)
        ch = c.snapshot()["channels"]
        self.assertEqual((ch["A"]["target"], ch["B"]["target"]), (0.0, 60.0))

    def test_ai_cannot_resume(self):
        c, _, _ = make()
        c.emergency_stop("ai")
        with self.assertRaises(ControlForbidden):
            c.resume("ai")
        self.assertTrue(c.estopped)
        c.resume("gui")
        self.assertFalse(c.estopped)


class Safety(unittest.TestCase):
    def test_ramp_limits_rise_but_not_fall(self):
        c, _, _ = make(ramp_up_per_s=100)
        c.set_intensity("A", 200, "gui")
        self.assertEqual(c.step(0.1).intensity[0], 10)
        for _ in range(19):
            f = c.step(0.1)
        self.assertEqual(f.intensity[0], 200)
        c.set_intensity("A", 0, "gui")
        self.assertEqual(c.step(0.1).intensity[0], 0)   # lowering is immediate

    def test_ramp_disabled(self):
        c, _, _ = make(ramp_up_per_s=0)
        c.set_intensity("A", 200, "gui")
        self.assertEqual(c.step(0.1).intensity[0], 200)

    def test_long_pause_does_not_bypass_ramp(self):
        c, _, _ = make(ramp_up_per_s=100)
        c.set_intensity("A", 200, "gui")
        self.assertEqual(c.step(30.0).intensity[0], 50)   # dt limited to 0.5 s

    def test_estop_zeroes_blocks_and_latches(self):
        c, _, _ = make(ramp_up_per_s=0)
        c.set_intensity("AB", 100, "gui")
        c.emergency_stop("gui")
        self.assertEqual(c.step(0.1).intensity, (0, 0))
        with self.assertRaises(ControlForbidden):
            c.set_intensity("A", 10, "gui")
        with self.assertRaises(ControlForbidden):
            c.set_fraction("A", 0.5, "osc")
        c.resume("gui")
        c.set_intensity("A", 10, "gui")
        self.assertEqual(c.step(0.1).intensity[0], 10)

    def test_reset_on_connect(self):
        c, _, _ = make(ramp_up_per_s=0)
        c.set_intensity("AB", 100, "gui")
        c.step(0.1)
        c.reset_on_connect()
        self.assertEqual(c.step(0.1).intensity, (0, 0))

    def test_lowering_max_clamps_everything(self):
        c, _, _ = make(ramp_up_per_s=0)
        c.set_intensity("A", 150, "gui")
        c.step(0.1)
        c.configure(max_intensity_a=80)
        self.assertEqual(c.step(0.1).intensity[0], 80)

    def test_configure_unknown_key_and_clamping(self):
        c, s, _ = make()
        with self.assertRaises(ControlError):
            c.configure(banana=1)
        c.configure(max_intensity_a=999, ai_cap=-5)
        self.assertEqual((s.max_intensity_a, s.ai_cap), (200, 0))

    def test_watchdog_only_zeroes_osc_driven_channels(self):
        c, _, clock = make(osc_timeout_s=5, ramp_up_per_s=0)
        c.note_osc_packet()
        c.set_fraction("A", 0.5, "osc")
        c.set_intensity("B", 50, "gui")
        clock.t = 4.0
        self.assertEqual(c.step(0.1).intensity, (100, 50))
        clock.t = 10.0
        self.assertEqual(c.step(0.1).intensity, (0, 50))

    def test_watchdog_off_by_default(self):
        c, _, clock = make(ramp_up_per_s=0)
        c.note_osc_packet()
        c.set_fraction("A", 0.5, "osc")
        clock.t = 9999.0
        self.assertEqual(c.step(0.1).intensity[0], 100)


class Frames(unittest.TestCase):
    def test_default_const_frame(self):
        c, _, _ = make()
        f = c.step(0.1)
        self.assertEqual(f.freq[0], [20] * 4)      # 50 Hz = 20 ms
        self.assertEqual(f.width[0], [100] * 4)

    def test_frequency_slider_reaches_wire(self):
        c, _, _ = make()
        c.set_frequency("A", 1, "gui")
        c.set_frequency("B", 100, "gui")
        f = c.step(0.1)
        self.assertEqual((f.freq[0][0], f.freq[1][0]), (240, 10))

    def test_pattern_pulse_timeline(self):
        c, _, _ = make()
        c.set_pattern("pulse")
        self.assertEqual(c.step(0.1).width[0], [100] * 4)   # 0..0.075 s: on
        for _ in range(3):
            c.step(0.1)
        self.assertEqual(c.step(0.1).width[0], [0] * 4)     # 0,4 s: desligado

    def test_pattern_speed_scales_clock(self):
        c, _, _ = make()
        c.set_pattern("breathing", speed=2.0)
        c.step(0.1)
        self.assertAlmostEqual(c._pclock, 0.2)

    def test_alternate_offsets_channel_b(self):
        c, _, _ = make()
        c.set_pattern("pulse", alternate=True)
        f = c.step(0.1)
        self.assertEqual(f.width[0], [100] * 4)
        self.assertEqual(f.width[1], [0] * 4)

    def test_pattern_on_one_channel_only(self):
        c, _, _ = make()
        c.set_pattern("pulse", channels="A")
        for _ in range(4):
            c.step(0.1)
        f = c.step(0.1)
        self.assertEqual(f.width[0], [0] * 4)
        self.assertEqual(f.width[1], [100] * 4)   # B segue constante

    def test_const_pattern_restores(self):
        c, _, _ = make()
        c.set_pattern("pulse")
        c.set_pattern("const")
        for _ in range(5):
            f = c.step(0.1)
        self.assertEqual(f.width[0], [100] * 4)

    def test_pattern_validation(self):
        c, _, _ = make()
        with self.assertRaises(ControlError):
            c.set_pattern("does-not-exist")
        with self.assertRaises(ControlError):
            c.set_pattern("pulse", alternate="sim")
        self.assertEqual(c.pattern, "const")   # nada foi aplicado pela metade
        r = c.set_pattern("pulse", speed=99)
        self.assertEqual(r["speed"], 4.0)

    def test_frames_are_always_valid_for_the_device(self):
        c, _, _ = make()
        c.set_frequency("AB", 33.3, "gui")
        for key in ("breathing", "heartbeat", "ramp", "sweep", "random", "staccato", "pulse"):
            c.set_pattern(key, speed=3.0)
            for _ in range(200):
                f = c.step(0.1)
                for ch in (0, 1):
                    self.assertTrue(all(10 <= x <= 240 for x in f.freq[ch]), key)
                    self.assertTrue(all(0 <= x <= 100 for x in f.width[ch]), key)
                self.assertTrue(all(0 <= x <= 200 for x in f.intensity), key)


class Logging(unittest.TestCase):
    def test_log_since(self):
        c, _, _ = make()
        c.log("um")
        c.log("dois")
        n, items = c.log_since(0)
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0].endswith("um"))
        n2, items2 = c.log_since(n)
        self.assertEqual((n2, items2), (n, []))


if __name__ == "__main__":
    unittest.main()
