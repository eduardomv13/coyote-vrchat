"""The shock trigger: a touch on the avatar's ShockOsc/_all contact -> a timed shock at a random power + a chatbox message.

A UDP socket plays the part of VRChat's OSC input (where the chatbox messages go), and the device is the simulated Coyote.
Time is a fake clock, so the durations and the rise limit can be checked exactly.
"""
import json
import random
import socket
import tempfile
import time
import unittest
from pathlib import Path

from coyote_vrc import osc
from coyote_vrc.ble import SimulatedTransport
from coyote_vrc.control import SHOCK_MAX_SECONDS, ControlError, ControlForbidden, Controller
from coyote_vrc.engine import Engine
from coyote_vrc.settings import Settings, load_settings
from coyote_vrc.shock import CHATBOX_MIN_INTERVAL_S, render_text

CONTACT = "/avatar/parameters/ShockOsc/_all"


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class FakeHandle:
    def __init__(self, delay, fn):
        self.delay, self.fn, self.cancelled, self.fired = delay, fn, False, False

    def cancel(self):
        self.cancelled = True

    def fire(self):
        """Runs the callback the way the timer would, unless it was cancelled."""
        if not self.cancelled:
            self.fired = True
            self.fn()


class FakeScheduler:
    """Stands in for threading.Timer: nothing runs until a test fires the handle."""

    def __init__(self):
        self.handles = []

    def __call__(self, delay, fn):
        handle = FakeHandle(delay, fn)
        self.handles.append(handle)
        return handle

    def pending(self):
        return [h for h in self.handles if not h.cancelled and not h.fired]


class ShockCase(unittest.TestCase):
    """A connected (simulated) Coyote, the trigger switched on, a fixed 40% power for 5 s."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        s = Settings(osc_enabled=False, api_token="t").validate()
        s.api_port = 0
        s.osc_port = 0
        s.ramp_up_per_s = 0
        s.shock_enabled = True
        s.shock_min_pct = s.shock_max_pct = 40
        s.shock_seconds = 5
        s.shock_channels = "AB"
        self.vrc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # VRChat's OSC input
        self.vrc.bind(("127.0.0.1", 0))
        self.vrc.settimeout(0.4)
        s.chatbox_port = self.vrc.getsockname()[1]
        self.settings = s
        self.clock = FakeClock()
        self.path = Path(self.tmp.name) / "s.json"
        self.engine = Engine(settings=s, settings_path=self.path, transport=SimulatedTransport())
        self.engine.control._clock = self.clock
        self.engine.shock._clock = self.clock
        self.sched = FakeScheduler()
        self.engine.shock._schedule = self.sched
        self.engine.link.state = "connected"      # as if the Coyote were connected
        self.ctl = self.engine.control

    def tearDown(self):
        self.engine.shutdown()
        self.vrc.close()
        self.tmp.cleanup()

    # ---- helpers
    def touch(self, on=True, address=CONTACT):
        self.engine._on_osc(address, [on])

    def tap(self):
        self.touch(True)
        self.touch(False)

    def out(self):
        self.ctl.step(0.1)
        return self.ctl.ch[0].output, self.ctl.ch[1].output

    def chat(self):
        """The next message that reached the 'VRChat' socket, or None."""
        try:
            data, _ = self.vrc.recvfrom(4096)
        except socket.timeout:
            return None
        return osc.parse_message(data)

    def logged(self, text):
        _, lines = self.ctl.log_since(0)
        return any(text in line for line in lines)


class TouchTests(ShockCase):
    def test_touch_starts_a_shock_and_announces_the_percent(self):
        self.tap()
        self.assertTrue(self.ctl.shock_active())
        self.assertEqual(self.out(), (80.0, 80.0))                 # 40% of the 200 ceiling
        self.assertEqual(self.chat(), ("/chatbox/input", ["Shock 40% for 5 s", True, False]))
        self.assertIsNone(self.chat())                             # one message, not two

    def test_the_shock_lasts_the_configured_seconds_then_the_channels_fall_back(self):
        self.tap()
        self.clock.advance(4.9)
        self.assertEqual(self.out(), (80.0, 80.0))
        self.assertEqual(self.ctl.snapshot()["shock"]["remaining_s"], 0.1)
        self.clock.advance(0.2)
        self.assertEqual(self.out(), (0.0, 0.0))
        self.assertFalse(self.ctl.shock_active())
        self.assertTrue(self.logged("Shock ended"))

    def test_a_contact_that_stays_on_does_not_repeat(self):
        self.touch(True)
        self.clock.advance(60)                                     # the shock is long over
        self.out()
        self.touch(True)                                           # still held: VRChat repeats the same value
        self.assertFalse(self.ctl.shock_active())
        self.touch(False)
        self.touch(True)                                           # a NEW touch
        self.assertTrue(self.ctl.shock_active())

    def test_there_is_no_pause_after_a_shock(self):
        self.tap()
        self.clock.advance(4.9)
        self.tap()                                                 # still running: ignored
        self.assertTrue(self.logged("a shock is already running"))
        self.clock.advance(0.2)                                    # it ended 0.1 s ago
        self.assertEqual(self.out(), (0.0, 0.0))
        self.assertFalse(self.ctl.shock_active())
        self.tap()                                                 # the very next touch fires again: no pause
        self.assertTrue(self.ctl.shock_active())
        self.assertEqual(self.out(), (80.0, 80.0))

    def test_a_touch_during_a_shock_is_ignored_and_does_not_extend_it(self):
        self.tap()
        self.clock.advance(2)
        self.tap()
        self.assertEqual(self.ctl.snapshot()["shock"]["remaining_s"], 3.0)
        self.assertTrue(self.logged("a shock is already running"))

    def test_float_contact_values_and_the_name_case(self):
        self.touch(0.2)                                            # barely there: not a touch
        self.assertFalse(self.ctl.shock_active())
        self.touch(0.0)
        self.touch(0.9)
        self.assertTrue(self.ctl.shock_active())
        self.engine.control.stop_shock("test")
        self.touch(False, "/avatar/parameters/ShockOsc/_All")      # another avatar spells it with a capital A
        self.clock.advance(60)
        self.touch(True, "/avatar/parameters/ShockOsc/_All")
        self.assertTrue(self.ctl.shock_active())

    def test_custom_parameter_name_and_unrelated_parameters(self):
        self.engine.configure_shock(osc_param_shock="Collar/Touch")
        self.touch(True)                                           # the old name does nothing now
        self.assertFalse(self.ctl.shock_active())
        self.touch(False)
        self.touch(True, "/avatar/parameters/Collar/Touch")
        self.assertTrue(self.ctl.shock_active())
        self.engine.configure_shock(osc_param_shock="")            # an empty name switches the contact off
        self.ctl.stop_shock()
        self.clock.advance(60)
        self.touch(False, "/avatar/parameters/Collar/Touch")
        self.touch(True, "/avatar/parameters/Collar/Touch")
        self.assertFalse(self.ctl.shock_active())


class RefusalTests(ShockCase):
    def test_off_by_default_every_start(self):
        self.engine.set_shock_enabled(False)
        self.tap()
        self.assertFalse(self.ctl.shock_active())
        self.assertIsNone(self.chat())
        self.assertTrue(self.logged("the trigger is off"))

    def test_a_contact_already_on_when_the_trigger_is_switched_on_does_not_fire(self):
        self.engine.set_shock_enabled(False)
        self.touch(True)                                           # touched while it was off
        self.engine.set_shock_enabled(True)
        self.touch(True)                                           # VRChat repeats the value: still not a new touch
        self.assertFalse(self.ctl.shock_active())

    def test_emergency_stop_cancels_the_shock_and_blocks_new_ones(self):
        self.tap()
        self.assertEqual(self.out(), (80.0, 80.0))
        self.engine.emergency_stop("gui")
        self.assertEqual(self.out(), (0.0, 0.0))
        self.assertFalse(self.ctl.shock_active())
        self.assertEqual(self.chat()[1][0], "Shock 40% for 5 s")           # the announcement of the first shock...
        self.assertEqual(self.chat(), ("/chatbox/input", ["", True, False]))   # ...and STOP takes it off the screen
        self.clock.advance(60)
        self.tap()
        self.assertEqual(self.out(), (0.0, 0.0))
        self.assertIsNone(self.chat())                             # nothing announced for a shock that did not happen
        self.assertTrue(self.logged("the emergency stop is active"))
        self.engine.resume()
        self.tap()
        self.assertTrue(self.ctl.shock_active())

    def test_not_connected_shows_the_message_but_delivers_no_shock(self):
        self.engine.link.state = "disconnected"
        self.tap()
        self.assertFalse(self.ctl.shock_active())
        self.assertEqual(self.out(), (0.0, 0.0))                   # nothing is delivered, not even later
        self.assertEqual(self.chat(), ("/chatbox/input", ["Shock 40% for 5 s", True, False]))
        self.assertIsNone(self.chat())                             # one message, not two
        self.assertTrue(self.logged("only announced"))
        self.assertIn("chatbox only", self.engine.shock.last)

    def test_the_announced_message_is_cleared_like_a_real_one(self):
        self.engine.link.state = "disconnected"
        self.tap()
        self.chat()
        self.assertEqual([h.delay for h in self.sched.pending()], [3])
        self.sched.pending()[0].fire()
        self.assertEqual(self.chat(), ("/chatbox/input", ["", True, False]))

    def test_the_test_shock_button_does_the_same_without_a_coyote(self):
        self.engine.link.state = "disconnected"
        res = self.engine.test_shock()
        self.assertEqual((res["fired"], res["announced"], res["percent"], res["seconds"]), (False, True, 40, 5.0))
        self.assertIn("no shock was delivered", res["reason"])
        self.assertEqual(self.chat()[1][0], "Shock 40% for 5 s")
        self.assertFalse(self.ctl.shock_active())

    def test_an_announced_touch_counts_as_running_for_the_shock_duration(self):
        self.engine.link.state = "disconnected"
        self.tap()
        self.assertIsNotNone(self.chat())
        self.clock.advance(4.9)                                    # the 5 s are not over: this touch is not announced
        self.tap()
        self.assertIsNone(self.chat())
        self.assertTrue(self.logged("the message of the previous touch is still running"))
        self.clock.advance(0.2)                                    # over now (and VRChat's 1.6 s rule is long past)
        self.tap()
        self.assertEqual(self.chat()[1][0], "Shock 40% for 5 s")
        self.assertEqual(self.engine.shock_status()["announced_count"], 2)

    def test_not_connected_and_the_chatbox_off_means_the_touch_is_ignored(self):
        self.engine.link.state = "disconnected"
        self.engine.configure_shock(chatbox_enabled=False)
        self.tap()
        self.assertIsNone(self.chat())
        st = self.engine.shock_status()
        self.assertEqual((st["announced_count"], st["ignored_count"]), (0, 1))
        self.assertIn("no chatbox message was sent", st["ignored_reason"])
        self.engine.configure_shock(chatbox_enabled=True, chatbox_text="")
        self.tap()
        self.assertIsNone(self.chat())                             # an empty message is not sent either

    def test_not_connected_with_the_emergency_stop_does_nothing_and_says_nothing(self):
        self.engine.link.state = "disconnected"
        self.engine.emergency_stop("gui")
        self.clock.advance(60)
        self.tap()
        self.assertIsNone(self.chat())
        self.assertEqual(self.engine.shock_status()["announced_count"], 0)
        self.assertTrue(self.logged("the emergency stop is active"))

    def test_a_message_that_comes_too_soon_after_another_is_not_sent_and_not_counted(self):
        self.engine.link.state = "disconnected"
        self.engine.configure_shock(shock_seconds=1)
        self.tap()
        self.assertIsNotNone(self.chat())
        self.clock.advance(1.1)                                    # the "shock" is over but VRChat would drop a message now
        self.assertLess(1.1, CHATBOX_MIN_INTERVAL_S)
        self.tap()
        self.assertIsNone(self.chat())
        self.assertEqual(self.engine.shock_status()["announced_count"], 1)
        self.assertIn("no chatbox message was sent", self.engine.shock_status()["ignored_reason"])

    def test_nothing_is_delivered_when_the_coyote_connects_while_the_message_is_showing(self):
        self.engine.link.state = "disconnected"
        self.tap()
        self.engine.link.state = "connected"
        self.assertEqual(self.out(), (0.0, 0.0))
        self.assertFalse(self.ctl.shock_active())

    def test_switching_the_trigger_off_takes_an_announced_message_off_the_screen(self):
        self.engine.link.state = "disconnected"
        self.tap()
        self.assertIsNotNone(self.chat())
        self.engine.set_shock_enabled(False)
        self.assertEqual(self.chat(), ("/chatbox/input", ["", True, False]))

    def test_reconnecting_clears_a_running_shock(self):
        self.tap()
        self.ctl.reset_on_connect()
        self.assertEqual(self.out(), (0.0, 0.0))
        self.assertFalse(self.ctl.shock_active())

    def test_switching_the_trigger_off_stops_a_running_shock(self):
        self.tap()
        self.assertEqual(self.out(), (80.0, 80.0))
        self.engine.set_shock_enabled(False)
        self.assertEqual(self.out(), (0.0, 0.0))
        self.assertTrue(self.logged("Shock stopped"))

    def test_a_zero_ceiling_means_no_shock(self):
        self.engine.configure(max_intensity=0)
        self.tap()
        self.assertFalse(self.ctl.shock_active())
        self.assertIsNone(self.chat())
        self.assertTrue(self.logged("the intensity ceiling is 0"))


class PowerTests(ShockCase):
    def test_the_power_is_random_inside_the_range_and_follows_the_ceiling(self):
        self.engine.configure_shock(shock_min_pct=10, shock_max_pct=12, shock_seconds=1)
        self.engine.configure(max_intensity=100)
        self.engine.shock._rng = random.Random(7)
        seen = set()
        for _ in range(80):
            res = self.engine.shock.fire("test")
            self.assertTrue(res["fired"], res)
            seen.add(res["percent"])
            self.assertEqual(res["level"], float(res["percent"]))   # ceiling 100: 12% = 12 units
            self.clock.advance(1.1)
            self.out()
        self.assertEqual(seen, {10, 11, 12})                       # both ends and the middle, nothing outside

    def test_every_value_in_the_widest_range_stays_inside_the_ceiling(self):
        self.engine.configure_shock(shock_min_pct=1, shock_max_pct=100, shock_seconds=1)
        self.engine.configure(max_intensity=150)
        self.engine.shock._rng = random.Random(3)
        for _ in range(200):
            res = self.engine.shock.fire("test")
            self.assertTrue(res["fired"])
            self.assertLessEqual(res["level"], 150.0)
            self.assertGreaterEqual(res["level"], 1.0)
            self.clock.advance(1.1)
            self.out()

    def test_lowering_the_ceiling_during_a_shock_lowers_the_output(self):
        self.tap()
        self.assertEqual(self.out(), (80.0, 80.0))
        self.engine.configure(max_intensity=50)
        self.assertEqual(self.out(), (50.0, 50.0))

    def test_a_shock_is_a_minimum_and_never_lowers_what_is_already_asked(self):
        self.engine._on_osc("/avatar/parameters/CoyoteA", [0.75])  # the panel asks for A = 75% of the ceiling = 150
        self.tap()
        self.assertEqual(self.out(), (150.0, 80.0))                # A keeps 150, B gets the shock
        self.clock.advance(6)
        self.assertEqual(self.out(), (150.0, 0.0))                 # afterwards A is still the panel's, B is back to 0

    def test_only_the_chosen_channels(self):
        self.engine.configure_shock(shock_channels="A")
        self.tap()
        self.assertEqual(self.out(), (80.0, 0.0))
        self.clock.advance(60)
        self.out()
        self.engine.configure_shock(shock_channels="B")
        self.tap()
        self.assertEqual(self.out(), (0.0, 80.0))

    def test_the_rise_limit_still_applies(self):
        self.engine.configure(ramp_up_per_s=100)
        self.tap()
        first = self.out()
        self.assertEqual(first, (10.0, 10.0))                      # 100 per second * 0.1 s
        for _ in range(7):
            last = self.out()
        self.assertEqual(last, (80.0, 80.0))
        self.clock.advance(6)
        self.assertEqual(self.out(), (0.0, 0.0))                   # lowering is immediate

    def test_the_duration_is_capped_at_30_seconds(self):
        res = self.ctl.start_shock("AB", 50, 999, "test")
        self.assertEqual(res["seconds"], float(SHOCK_MAX_SECONDS))
        self.assertTrue(res["clamped"])


class ChatboxTests(ShockCase):
    def test_template_text_and_the_144_character_limit(self):
        self.assertEqual(render_text("Shock {percent}%", 37, 5), "Shock 37%")
        self.assertEqual(render_text("{percent}% for {seconds} s", 8, 12), "8% for 12 s")
        self.assertEqual(render_text("{percent} {oops}", 5, 1), "5 {oops}")     # a stray brace cannot break it
        self.assertEqual(len(render_text("x" * 500, 1, 1)), 144)
        self.assertEqual(render_text("a\n\n b\t c", 1, 1), "a b c")

    def test_the_default_message_says_the_power_and_how_long(self):
        self.assertEqual(render_text(Settings().chatbox_text, 37, 12), "Shock 37% for 12 s")
        self.assertEqual(render_text(Settings().chatbox_text, 100, 30), "Shock 100% for 30 s")

    def test_custom_text_is_sent(self):
        self.engine.configure_shock(chatbox_text="Zapped at {percent}% for {seconds}s")
        self.tap()
        self.assertEqual(self.chat()[1][0], "Zapped at 40% for 5s")

    def test_chatbox_can_be_switched_off_or_left_empty(self):
        self.engine.configure_shock(chatbox_enabled=False)
        self.tap()
        self.assertTrue(self.ctl.shock_active())
        self.assertIsNone(self.chat())
        self.ctl.stop_shock()
        self.clock.advance(60)
        self.engine.configure_shock(chatbox_enabled=True, chatbox_text="")
        self.tap()
        self.assertTrue(self.ctl.shock_active())
        self.assertIsNone(self.chat())

    def test_messages_that_come_too_fast_are_skipped(self):
        self.engine.configure_shock(shock_seconds=1)
        self.tap()
        self.clock.advance(1.1)
        self.out()
        self.assertLess(1.1, CHATBOX_MIN_INTERVAL_S)
        self.tap()                                                 # a second shock, 1.1 s later
        self.assertTrue(self.ctl.shock_active())
        self.assertIsNotNone(self.chat())
        self.assertIsNone(self.chat())                             # but only the first one was announced
        self.assertTrue(self.logged("message skipped"))

    def test_the_test_button_message_says_it_is_a_test(self):
        self.assertTrue(self.engine.test_chatbox())
        self.assertEqual(self.chat(), ("/chatbox/input", ["Shock 40% for 5 s (test)", True, False]))
        self.assertFalse(self.ctl.shock_active())                  # a chatbox test never shocks
        self.assertEqual([h.delay for h in self.sched.pending()], [3])      # and it is cleared like a real message

    def test_a_failing_send_is_logged_not_raised(self):
        def boom(*args, **kwargs):
            raise OSError(10049, "address not available")
        self.engine.vrc_out.send_chatbox = boom
        self.tap()
        self.assertTrue(self.ctl.shock_active())                   # the shock does not depend on the chatbox
        self.assertTrue(self.logged("could not send"))


class SettingsTests(ShockCase):
    def test_defaults(self):
        d = Settings().validate()
        self.assertEqual((d.osc_param_shock, d.shock_enabled, d.shock_min_pct, d.shock_max_pct, d.shock_seconds),
                         ("ShockOsc/_all", False, 10, 30, 3))
        self.assertEqual((d.shock_channels, d.chatbox_enabled, d.chatbox_port, d.chatbox_text),
                         ("AB", True, 9000, "Shock {percent}% for {seconds} s"))
        self.assertFalse(hasattr(d, "shock_cooldown_s"))           # the pause between shocks does not exist
        self.assertEqual(d.chatbox_clear_s, 3)

    def test_clear_seconds_validation(self):
        for given, expected in ((0, 0), (1, 2), (2, 2), (3, 3), (60, 60), (99, 60), (-4, 0), ("abc", 3)):
            self.assertEqual(Settings(chatbox_clear_s=given).validate().chatbox_clear_s, expected, given)

    def test_validation_clamps_and_orders(self):
        s = Settings(shock_min_pct=80, shock_max_pct=20, shock_seconds=99, shock_channels="ba",
                     chatbox_port=0, chatbox_text=None).validate()
        self.assertEqual((s.shock_min_pct, s.shock_max_pct, s.shock_seconds), (20, 80, 30))
        self.assertEqual((s.shock_channels, s.chatbox_text), ("AB", ""))
        self.assertEqual(Settings(shock_min_pct=0, shock_max_pct=500).validate().shock_min_pct, 1)
        self.assertEqual(Settings(shock_channels="zz").validate().shock_channels, "AB")
        self.assertEqual(Settings(shock_channels="b").validate().shock_channels, "B")

    def test_configure_pushes_the_other_end_of_the_range(self):
        self.engine.configure_shock(shock_min_pct=10, shock_max_pct=30)
        changed = self.engine.configure_shock(shock_min_pct=50)
        self.assertEqual((self.settings.shock_min_pct, self.settings.shock_max_pct), (50, 50))
        self.assertEqual(changed, {"shock_min_pct", "shock_max_pct"})
        self.engine.configure_shock(shock_max_pct=5)
        self.assertEqual((self.settings.shock_min_pct, self.settings.shock_max_pct), (5, 5))
        self.assertEqual(self.engine.configure_shock(shock_min_pct=5), set())      # nothing changed
        with self.assertRaises(ControlError):
            self.engine.configure_shock(shock_enabled=True)       # not changeable this way, on purpose
        with self.assertRaises(ControlError):
            self.engine.configure_shock(nonsense=1)

    def test_a_saved_copy_of_the_old_default_message_takes_the_new_default(self):
        # before 1.2.1 the default said only the power, and every save wrote it into the settings file
        self.path.write_text(json.dumps({"chatbox_text": "Shock {percent}%", "api_token": "t"}), encoding="utf-8")
        self.assertEqual(load_settings(self.path).chatbox_text, "Shock {percent}% for {seconds} s")

    def test_a_message_the_user_wrote_is_kept(self):
        for mine in ("Zap {percent}", "Shock {percent}% !", "", "{percent}% / {seconds} s"):
            self.path.write_text(json.dumps({"chatbox_text": mine, "api_token": "t"}), encoding="utf-8")
            self.assertEqual(load_settings(self.path).chatbox_text, mine)

    def test_an_old_settings_file_with_the_removed_pause_still_loads(self):
        self.path.write_text(json.dumps({"shock_cooldown_s": 30, "shock_min_pct": 15, "api_token": "t"}), encoding="utf-8")
        loaded = load_settings(self.path)
        self.assertEqual(loaded.shock_min_pct, 15)
        self.assertFalse(hasattr(loaded, "shock_cooldown_s"))

    def test_the_enabled_flag_is_never_saved_but_the_rest_is(self):
        self.engine.configure_shock(shock_min_pct=15, shock_max_pct=45, shock_seconds=12, chatbox_text="Zap {percent}")
        self.assertTrue(self.settings.shock_enabled)
        self.engine.save()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIs(data["shock_enabled"], False)
        loaded = load_settings(self.path)
        self.assertFalse(loaded.shock_enabled)                    # always starts off
        self.assertEqual((loaded.shock_min_pct, loaded.shock_max_pct, loaded.shock_seconds), (15, 45, 12))
        self.assertEqual(loaded.chatbox_text, "Zap {percent}")

    def test_status_for_the_window(self):
        st = self.engine.shock_status()
        self.assertEqual((st["enabled"], st["active"], st["connected"], st["estopped"]), (True, False, True, False))
        self.tap()
        st = self.engine.shock_status()
        self.assertTrue(st["active"])
        self.assertEqual(st["level"], {"A": 80.0, "B": 80.0})
        self.assertEqual(st["remaining_s"], 5.0)
        self.assertIn("40%", st["last"])
        self.clock.advance(6)
        st = self.engine.shock_status()
        self.assertFalse(st["active"])
        self.assertNotIn("cooldown_s", st)

    def test_status_reports_touches_and_ignored_touches(self):
        st = self.engine.shock_status()
        self.assertEqual((st["touch_age_s"], st["ignored_age_s"], st["ignored_count"], st["ignored_reason"]),
                         (None, None, 0, ""))
        self.engine.emergency_stop("gui")
        self.clock.advance(5)
        self.tap()                                                 # a touch that cannot do anything
        self.clock.advance(7)
        st = self.engine.shock_status()
        self.assertEqual((st["touch_age_s"], st["ignored_age_s"], st["ignored_count"]), (7.0, 7.0, 1))
        self.assertEqual(st["ignored_reason"], "the emergency stop is active")
        self.assertEqual((st["announced_age_s"], st["announced_count"], st["announced_text"]), (None, 0, ""))

    def test_status_reports_a_touch_that_was_only_announced(self):
        self.engine.link.state = "disconnected"
        self.clock.advance(5)
        self.tap()
        self.clock.advance(7)
        st = self.engine.shock_status()
        self.assertEqual((st["touch_age_s"], st["announced_age_s"], st["announced_count"]), (7.0, 7.0, 1))
        self.assertEqual(st["announced_text"], "40% for 5 s")
        self.assertEqual((st["ignored_count"], st["ignored_reason"]), (0, ""))   # it was not ignored: it reached the chatbox
        self.assertFalse(st["connected"])

    def test_enabling_the_trigger_connects_the_coyote_if_nothing_is_connected(self):
        calls = []
        self.engine.connect = lambda *a, **k: calls.append(1)
        self.engine.set_shock_enabled(False)
        self.engine.link.state = "disconnected"
        self.engine.set_shock_enabled(True)
        self.assertEqual(calls, [1])
        self.assertTrue(self.logged("connecting now"))
        for state in ("connected", "connecting", "searching", "reconnecting"):
            self.engine.set_shock_enabled(False)
            self.engine.link.state = state
            self.engine.set_shock_enabled(True)
        self.assertEqual(calls, [1])                               # it only asks when nothing is connected or on its way

    def test_snapshot_carries_the_shock_for_the_status_api(self):
        self.assertEqual(self.ctl.snapshot()["shock"], {"active": False, "remaining_s": 0.0, "level": {"A": 0.0, "B": 0.0}})


class ChatboxClearTests(ShockCase):
    """The message is removed again a few seconds later (an empty /chatbox/input, which is what chatbox tools do)."""

    def test_the_message_is_cleared_after_the_configured_seconds(self):
        self.tap()
        self.assertEqual(self.chat()[1][0], "Shock 40% for 5 s")
        pending = self.sched.pending()
        self.assertEqual([h.delay for h in pending], [3])
        self.assertIsNone(self.chat())                             # nothing is removed before the time is up
        self.clock.advance(3.0)
        pending[0].fire()
        self.assertEqual(self.chat(), ("/chatbox/input", ["", True, False]))
        self.assertTrue(self.logged("Chatbox: cleared"))
        pending[0].fn()                                            # a second call (a timer race) sends nothing more
        self.assertIsNone(self.chat())

    def test_the_delay_is_configurable_and_zero_means_never(self):
        self.engine.configure_shock(chatbox_clear_s=8)
        self.tap()
        self.assertEqual([h.delay for h in self.sched.pending()], [8])
        first = self.sched.pending()[0]
        self.chat()
        self.ctl.stop_shock()
        self.clock.advance(60)
        self.engine.configure_shock(chatbox_clear_s=0)
        self.tap()
        self.chat()
        self.assertTrue(first.cancelled)                           # the new message replaced the old one...
        self.assertEqual(self.sched.pending(), [])                 # ...and no timer was scheduled for it
        self.engine.emergency_stop("gui")
        self.assertIsNone(self.chat())                             # with clearing off the message is left alone

    def test_a_newer_message_makes_the_older_clear_stale(self):
        self.engine.configure_shock(shock_seconds=1)
        self.tap()
        first = self.sched.pending()[0]
        self.clock.advance(2.0)
        self.out()
        self.tap()                                                 # 2 s later: not too fast, a second message
        self.assertTrue(first.cancelled)
        self.chat()
        self.chat()                                                # the two announcements
        first.fn()                                                 # a timer that had already started: sends nothing
        self.assertIsNone(self.chat())
        self.sched.pending()[0].fire()
        self.assertEqual(self.chat(), ("/chatbox/input", ["", True, False]))

    def test_a_message_skipped_for_speed_leaves_the_pending_clear_alone(self):
        self.engine.configure_shock(shock_seconds=1)
        self.tap()
        first = self.sched.pending()[0]
        self.clock.advance(1.1)
        self.out()
        self.tap()                                                 # too fast: not announced
        self.assertFalse(first.cancelled)
        self.chat()
        first.fire()
        self.assertEqual(self.chat(), ("/chatbox/input", ["", True, False]))

    def test_a_new_shock_right_after_a_clear_is_too_fast_to_announce(self):
        self.engine.configure_shock(shock_seconds=1)
        self.tap()
        handle = self.sched.pending()[0]
        self.chat()
        self.clock.advance(3.0)
        self.out()
        handle.fire()
        self.assertEqual(self.chat(), ("/chatbox/input", ["", True, False]))
        self.clock.advance(0.5)
        self.tap()                                                 # 0.5 s after the clear: VRChat would drop it
        self.assertTrue(self.ctl.shock_active())
        self.assertIsNone(self.chat())
        self.assertTrue(self.logged("message skipped"))

    def test_stop_removes_the_message_at_once_and_cancels_the_timer(self):
        self.tap()
        handle = self.sched.pending()[0]
        self.chat()
        self.engine.emergency_stop("gui")
        self.assertEqual(self.chat(), ("/chatbox/input", ["", True, False]))
        self.assertTrue(handle.cancelled)
        handle.fn()                                                # a timer that had already started does nothing
        self.assertIsNone(self.chat())

    def test_switching_the_trigger_off_during_a_shock_removes_the_message(self):
        self.tap()
        self.chat()
        self.engine.set_shock_enabled(False)
        self.assertEqual(self.chat(), ("/chatbox/input", ["", True, False]))

    def test_closing_the_program_removes_the_message(self):
        self.tap()
        self.chat()
        self.engine.shutdown()
        self.assertEqual(self.chat(), ("/chatbox/input", ["", True, False]))

    def test_a_failing_clear_is_logged_not_raised(self):
        self.tap()
        handle = self.sched.pending()[0]
        self.chat()

        def boom(*args, **kwargs):
            raise OSError(10049, "address not available")
        self.engine.vrc_out.send_chatbox = boom
        handle.fire()
        self.assertTrue(self.logged("could not clear"))


class ControllerTests(unittest.TestCase):
    def test_start_shock_obeys_the_emergency_stop_and_does_not_stack(self):
        c = Controller(Settings().validate())
        c.emergency_stop("gui")
        with self.assertRaises(ControlForbidden):
            c.start_shock("AB", 50, 3)
        c.resume("gui")
        c.start_shock("AB", 50, 3)
        with self.assertRaises(ControlError):
            c.start_shock("AB", 60, 3)
        self.assertTrue(c.stop_shock("test"))
        self.assertFalse(c.stop_shock("again"))

    def test_the_level_is_clamped_to_the_ceiling(self):
        s = Settings(max_intensity=60).validate()
        c = Controller(s)
        res = c.start_shock("A", 200, 2)
        self.assertEqual(res["applied"], 60.0)
        self.assertTrue(res["clamped"])


class OverTheWire(unittest.TestCase):
    """The whole path with real UDP: VRChat's OSC output -> the program -> the chatbox message back to VRChat."""

    def test_touch_over_udp_gives_a_shock_and_a_chatbox_message(self):
        tmp = tempfile.TemporaryDirectory()
        vrc_in = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        vrc_in.bind(("127.0.0.1", 0))
        vrc_in.settimeout(2.0)
        s = Settings(osc_enabled=True, api_token="t").validate()
        s.api_port = 0
        s.osc_port = 0
        s.ramp_up_per_s = 0
        s.shock_enabled = True
        s.shock_min_pct = s.shock_max_pct = 25
        s.shock_seconds = 1
        s.chatbox_clear_s = 2
        s.chatbox_port = vrc_in.getsockname()[1]
        engine = Engine(settings=s, settings_path=Path(tmp.name) / "s.json", transport=SimulatedTransport())
        engine.link.state = "connected"
        engine.start_osc()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.assertTrue(engine.osc_status()["listening"])
            sender.sendto(osc.encode_message(CONTACT, False), ("127.0.0.1", engine.osc.port))
            sender.sendto(osc.encode_message(CONTACT, True), ("127.0.0.1", engine.osc.port))
            data, _ = vrc_in.recvfrom(4096)
            self.assertEqual(osc.parse_message(data), ("/chatbox/input", ["Shock 25% for 1 s", True, False]))
            self.assertTrue(engine.control.shock_active())
            end = time.time() + 3
            while engine.control.shock_active() and time.time() < end:
                time.sleep(0.05)
            self.assertFalse(engine.control.shock_active())       # it ended by itself after 1 s
            vrc_in.settimeout(4.0)
            began = time.time()
            data, _ = vrc_in.recvfrom(4096)                        # and the real timer clears the chatbox after 2 s
            self.assertEqual(osc.parse_message(data), ("/chatbox/input", ["", True, False]))
            self.assertGreaterEqual(time.time() - began, 0.3)
        finally:
            sender.close()
            engine.shutdown()
            vrc_in.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
