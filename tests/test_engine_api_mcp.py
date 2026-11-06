import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from coyote_vrc import osc
from coyote_vrc.ble import SimulatedTransport
from coyote_vrc.engine import Engine
from coyote_vrc.mcp_server import SUPPORTED_VERSIONS, TOOLS, McpServer
from coyote_vrc.settings import Settings, load_settings, save_settings

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "testtoken"


def wait_for(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class EngineCase(unittest.TestCase):
    osc_on = False

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        s = Settings(osc_enabled=self.osc_on, api_token=TOKEN).validate()
        s.api_port = 0     # ephemeral port (validate() does not accept 0)
        s.osc_port = 0
        s.ramp_up_per_s = 0
        self.settings = s
        self.engine = Engine(settings=s, settings_path=Path(self.tmp.name) / "s.json", transport=SimulatedTransport())
        self.engine.start()
        self.port = self.engine.api.port

    def tearDown(self):
        self.engine.shutdown()
        self.tmp.cleanup()

    def target(self, ch):
        return self.engine.control.snapshot()["channels"][ch]["target"]


class ApiTests(EngineCase):
    def call(self, method, path, body=None, token=TOKEN, host=None, ctype="application/json"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if host:
            headers["Host"] = host
        data = None if body is None else json.dumps(body)
        if data is not None and ctype:
            headers["Content-Type"] = ctype
        conn.request(method, path, body=data, headers=headers)
        r = conn.getresponse()
        payload = json.loads(r.read() or b"{}")
        conn.close()
        return r.status, payload

    def test_auth(self):
        self.assertEqual(self.call("GET", "/status", token=None)[0], 401)
        self.assertEqual(self.call("GET", "/status", token="errado")[0], 401)
        self.assertEqual(self.call("POST", "/stop", {}, token=None)[0], 401)
        status, body = self.call("GET", "/status")
        self.assertEqual(status, 200)
        self.assertIn("ble", body)
        self.assertEqual(body["control"]["limits"]["ai_enabled"], False)

    def test_host_header_must_be_local(self):
        self.assertEqual(self.call("GET", "/status", host="evil.example.com")[0], 403)
        self.assertEqual(self.call("GET", "/status", host=f"localhost:{self.port}")[0], 200)

    def test_ai_disabled_refuses_control(self):
        for path, body in (("/intensity", {"channel": "A", "value": 10}), ("/frequency", {"hz": 20}),
                           ("/width", {"width": 20}), ("/pattern", {"name": "pulse"})):
            status, payload = self.call("POST", path, body)
            self.assertEqual(status, 403, path)
            self.assertIn("AI", payload["error"])
        self.assertEqual(self.target("A"), 0.0)

    def test_ai_enabled_applies_caps(self):
        self.engine.configure(ai_enabled=True)
        status, r = self.call("POST", "/intensity", {"channel": "A", "value": 120})
        self.assertEqual((status, r["applied"], r["clamped"]), (200, 50.0, True))
        self.assertEqual(self.target("A"), 50.0)
        status, r = self.call("POST", "/frequency", {"channel": "B", "hz": 150})
        self.assertEqual((status, r["applied"]), (200, 100.0))
        status, r = self.call("POST", "/width", {"width": 60})
        self.assertEqual((status, r["channels"]), (200, "A+B"))
        status, r = self.call("POST", "/pattern", {"name": "heartbeat", "speed": 1.5, "channels": "AB"})
        self.assertEqual((status, r["name"], r["speed"]), (200, "heartbeat", 1.5))

    def test_validation_errors(self):
        self.engine.configure(ai_enabled=True)
        self.assertEqual(self.call("POST", "/intensity", {"channel": "Z", "value": 5})[0], 400)
        self.assertEqual(self.call("POST", "/intensity", {"channel": "A"})[0], 400)
        self.assertEqual(self.call("POST", "/intensity", {"channel": "A", "value": "alto"})[0], 400)
        self.assertEqual(self.call("POST", "/pattern", {"name": "does-not-exist"})[0], 400)
        self.assertEqual(self.call("GET", "/nada")[0], 404)
        self.assertEqual(self.call("POST", "/resume", {})[0], 404)       # the AI cannot re-enable
        self.assertEqual(self.call("POST", "/intensity", {"value": 5}, ctype="text/plain")[0], 415)

    def test_bad_json_and_body_limits(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/intensity", body="{not json",
                     headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/intensity", body="x" * 20000,
                     headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        self.assertEqual(conn.getresponse().status, 413)
        conn.close()

    def test_stop_works_even_when_ai_disabled_and_latches(self):
        self.engine.control.set_intensity("A", 100, "gui")
        status, r = self.call("POST", "/stop", {})
        self.assertEqual((status, r["estopped"]), (200, True))
        self.assertEqual(self.target("A"), 0.0)
        self.engine.configure(ai_enabled=True)
        status, r = self.call("POST", "/intensity", {"channel": "A", "value": 10})
        self.assertEqual(status, 403)
        self.assertIn("EMERGENCY", r["error"])

    def test_patterns_listing(self):
        status, r = self.call("GET", "/patterns")
        names = [p["name"] for p in r["patterns"]]
        self.assertEqual(status, 200)
        self.assertIn("const", names)
        self.assertIn("breathing", names)

    def test_revoking_ai_stops_what_it_started(self):
        self.engine.configure(ai_enabled=True)
        self.call("POST", "/intensity", {"channel": "B", "value": 40})
        self.assertEqual(self.target("B"), 40.0)
        self.engine.configure(ai_enabled=False)
        self.assertEqual(self.target("B"), 0.0)


class OscIntegration(EngineCase):
    osc_on = True

    def send(self, *msgs):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for m in msgs:
            s.sendto(m, ("127.0.0.1", self.engine.osc.port))
        s.close()

    def test_two_sliders_map_to_two_channels(self):
        self.send(osc.encode_message("/avatar/parameters/CoyoteA", 0.5),
                  osc.encode_message("/avatar/parameters/CoyoteB", 1.0))
        self.assertTrue(wait_for(lambda: self.target("A") == 100.0 and self.target("B") == 200.0))

    def test_cap_applies_to_osc_full_scale(self):
        self.engine.configure(max_intensity_b=150)
        self.send(osc.encode_message("/avatar/parameters/CoyoteB", 1.0))
        self.assertTrue(wait_for(lambda: self.target("B") == 150.0))

    def test_unrelated_parameters_are_ignored_but_count_as_alive(self):
        self.send(osc.encode_message("/avatar/parameters/VelocityX", 0.9),
                  osc.encode_message("/avatar/change", "avtr_123"))
        self.assertTrue(wait_for(lambda: self.engine.control.snapshot()["osc"]["last_packet_age_s"] is not None))
        self.assertEqual((self.target("A"), self.target("B")), (0.0, 0.0))

    def test_int_and_bool_values(self):
        self.send(osc.encode_message("/avatar/parameters/CoyoteA", True))
        self.assertTrue(wait_for(lambda: self.target("A") == 200.0))
        self.send(osc.encode_message("/avatar/parameters/CoyoteA", False))
        self.assertTrue(wait_for(lambda: self.target("A") == 0.0))

    def test_stop_parameter_latches(self):
        self.send(osc.encode_message("/avatar/parameters/CoyoteA", 0.5))
        self.assertTrue(wait_for(lambda: self.target("A") == 100.0))
        self.send(osc.encode_message("/avatar/parameters/CoyoteStop", True))
        self.assertTrue(wait_for(lambda: self.engine.control.estopped))
        self.assertEqual(self.target("A"), 0.0)
        self.send(osc.encode_message("/avatar/parameters/CoyoteA", 0.8))
        time.sleep(0.2)
        self.assertEqual(self.target("A"), 0.0)

    def freq(self, ch):
        return self.engine.control.snapshot()["channels"][ch]["freq_hz"]

    def test_frequency_parameter_sets_both_channels_in_hz(self):
        self.send(osc.encode_message("/avatar/parameters/CoyoteFreq", 70))
        self.assertTrue(wait_for(lambda: self.freq("A") == 70.0 and self.freq("B") == 70.0))
        self.send(osc.encode_message("/avatar/parameters/CoyoteFreq", 100))
        self.assertTrue(wait_for(lambda: self.freq("A") == 100.0 and self.freq("B") == 100.0))

    def test_frequency_parameter_is_clamped_and_ignores_unsafe_values(self):
        self.send(osc.encode_message("/avatar/parameters/CoyoteFreq", 40))
        self.assertTrue(wait_for(lambda: self.freq("A") == 40.0))
        self.send(osc.encode_message("/avatar/parameters/CoyoteFreq", 0),        # parameter not initialized yet
                  osc.encode_message("/avatar/parameters/CoyoteFreq", 0.0),      # float: ignored
                  osc.encode_message("/avatar/parameters/CoyoteFreq", True),     # bool: ignored
                  osc.encode_message("/avatar/parameters/CoyoteFreq", -5))
        time.sleep(0.3)
        self.assertEqual((self.freq("A"), self.freq("B")), (40.0, 40.0))
        self.send(osc.encode_message("/avatar/parameters/CoyoteFreq", 999))
        self.assertTrue(wait_for(lambda: self.freq("A") == 100.0))

    def test_frequency_parameter_works_during_emergency_stop_without_unlocking_intensity(self):
        self.engine.emergency_stop("gui")
        self.send(osc.encode_message("/avatar/parameters/CoyoteFreq", 30),
                  osc.encode_message("/avatar/parameters/CoyoteA", 1.0))
        self.assertTrue(wait_for(lambda: self.freq("A") == 30.0))
        self.assertEqual(self.target("A"), 0.0)

    def test_custom_parameter_names(self):
        self.settings.osc_param_a = "Meu/Slider1"
        self.send(osc.encode_message("/avatar/parameters/Meu/Slider1", 0.25))
        self.assertTrue(wait_for(lambda: self.target("A") == 50.0))

    def test_port_conflict_is_reported_not_fatal(self):
        port = self.engine.osc.port
        self.settings.osc_port = port
        self.engine.osc.stop()
        blocker = osc.OscListener("127.0.0.1", port, lambda *_: None)
        blocker.start()
        try:
            self.engine.start_osc()
            self.assertIn("another OSC program", self.engine.osc_error)
            self.assertFalse(self.engine.osc_status()["listening"])
        finally:
            blocker.stop()


class SettingsTests(unittest.TestCase):
    def test_defaults_token_and_ai_never_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            s = load_settings(path)
            self.assertTrue(len(s.api_token) >= 20)
            s.ai_enabled = True
            save_settings(s, path)
            self.assertFalse(json.loads(path.read_text())["ai_enabled"])
            self.assertFalse(load_settings(path).ai_enabled)
            self.assertEqual(load_settings(path).api_token, s.api_token)    # token is stable across runs

    def test_corrupt_file_falls_back_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            path.write_text("{ this is not json")
            s = load_settings(path)
            self.assertEqual((s.max_intensity_a, s.max_intensity_b), (200, 200))
            self.assertTrue((Path(d) / "s.json.bak").exists())

    def test_validation_clamps(self):
        s = Settings(max_intensity_a=999, max_intensity_b=-1, width_balance_a=999, width_balance_b=-9, ai_cap=-4,
                     osc_port=70000, default_width=500, default_freq_hz=999).validate()
        self.assertEqual((s.max_intensity_a, s.max_intensity_b, s.width_balance_a, s.width_balance_b, s.ai_cap,
                          s.osc_port, s.default_width, s.default_freq_hz),
                         (200, 0, 255, 0, 0, 65535, 100, 100.0))

    def test_unknown_keys_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            path.write_text(json.dumps({"max_intensity_a": 90, "coisa_antiga": 1}))
            self.assertEqual(load_settings(path).max_intensity_a, 90)

    def test_an_old_global_ceiling_is_folded_into_both_channels(self):
        # up to 1.3.0 `max_intensity` capped both channels; dropping it silently would raise the limit back to 200
        cases = (
            ({"max_intensity": 90}, (90, 90)),
            ({"max_intensity": 150, "max_intensity_a": 100, "max_intensity_b": 200}, (100, 150)),
            ({"max_intensity": 200, "max_intensity_a": 140, "max_intensity_b": 140}, (140, 140)),
            ({"max_intensity": "junk", "max_intensity_a": 70}, (70, 200)),
            ({"max_intensity": 60, "max_intensity_a": "junk"}, (60, 60)),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as d:
                path = Path(d) / "s.json"
                path.write_text(json.dumps(raw))
                s = load_settings(path)
                self.assertEqual((s.max_intensity_a, s.max_intensity_b), expected)
                self.assertFalse(hasattr(s, "max_intensity"))
                save_settings(s, path)
                self.assertNotIn("max_intensity", json.loads(path.read_text()))   # not written back

    def test_intensity_balance_is_saved_and_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            s = load_settings(path)
            self.assertEqual((s.width_balance_a, s.width_balance_b), (100, 100))
            s.width_balance_a, s.width_balance_b = 20, 250
            save_settings(s, path)
            loaded = load_settings(path)
            self.assertEqual((loaded.width_balance_a, loaded.width_balance_b), (20, 250))


class McpUnit(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake(method, path, body):
            self.calls.append((method, path, body))
            return (403, {"error": "denied"}) if path == "/intensity" else (200, {"ok": True})

        self.srv = McpServer(fake)

    def req(self, method, params=None, mid=1):
        return self.srv.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})

    def test_initialize_negotiates_version(self):
        r = self.req("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual(r["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", r["result"]["capabilities"])
        r = self.req("initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(r["result"]["protocolVersion"], SUPPORTED_VERSIONS[0])

    def test_notification_has_no_reply(self):
        self.assertIsNone(self.srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools_list_is_well_formed(self):
        names = [t["name"] for t in self.req("tools/list")["result"]["tools"]]
        self.assertEqual(len(names), len(set(names)))
        for need in ("coyote_status", "coyote_set_intensity", "coyote_set_frequency",
                     "coyote_set_pulse_width", "coyote_set_pattern", "coyote_list_patterns", "coyote_stop"):
            self.assertIn(need, names)
        for t in TOOLS:
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_call_maps_to_http_and_flags_errors(self):
        r = self.req("tools/call", {"name": "coyote_set_frequency", "arguments": {"channel": "A", "hz": 20}})
        self.assertFalse(r["result"]["isError"])
        self.assertEqual(self.calls[-1], ("POST", "/frequency", {"channel": "A", "hz": 20}))
        r = self.req("tools/call", {"name": "coyote_set_intensity", "arguments": {"value": 5}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("denied", r["result"]["content"][0]["text"])
        self.req("tools/call", {"name": "coyote_status"})
        self.assertEqual(self.calls[-1], ("GET", "/status", None))

    def test_unknown_tool_and_method(self):
        self.assertEqual(self.req("tools/call", {"name": "x"})["error"]["code"], -32602)
        self.assertEqual(self.req("foo/bar")["error"]["code"], -32601)
        self.assertEqual(self.req("ping")["result"], {})


class McpEndToEnd(EngineCase):
    def test_stdio_process_talks_to_live_api(self):
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "coyote_status", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "coyote_set_intensity", "arguments": {"channel": "A", "value": 30}}},
        ]
        env = dict(os.environ, COYOTE_API_URL=f"http://127.0.0.1:{self.port}", COYOTE_API_TOKEN=TOKEN,
                   PYTHONIOENCODING="utf-8")
        proc = subprocess.run([sys.executable, str(ROOT / "coyote_mcp.py")], input="\n".join(map(json.dumps, lines)) + "\n",
                              capture_output=True, text=True, timeout=20, env=env, cwd=str(ROOT))
        out = [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]
        self.assertEqual([o["id"] for o in out], [1, 2, 3, 4], proc.stderr)
        self.assertEqual(out[0]["result"]["serverInfo"]["name"], "coyote-vrchat")
        self.assertEqual(len(out[1]["result"]["tools"]), 7)
        status = json.loads(out[2]["result"]["content"][0]["text"])
        self.assertIn("control", status)
        self.assertFalse(out[2]["result"]["isError"])
        self.assertTrue(out[3]["result"]["isError"])             # AI still disabled in the GUI
        self.assertEqual(self.target("A"), 0.0)
        # now with the AI enabled
        self.engine.configure(ai_enabled=True)
        proc = subprocess.run([sys.executable, str(ROOT / "coyote_mcp.py")],
                              input=json.dumps(lines[4]) + "\n", capture_output=True, text=True, timeout=20, env=env,
                              cwd=str(ROOT))
        res = json.loads(proc.stdout.splitlines()[0])
        self.assertFalse(res["result"]["isError"])
        self.assertEqual(self.target("A"), 30.0)

    def test_app_not_running_gives_clear_error(self):
        env = dict(os.environ, COYOTE_API_URL="http://127.0.0.1:9", COYOTE_API_TOKEN=TOKEN)
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "coyote_status", "arguments": {}}}
        proc = subprocess.run([sys.executable, str(ROOT / "coyote_mcp.py")], input=json.dumps(req) + "\n",
                              capture_output=True, text=True, timeout=20, env=env, cwd=str(ROOT))
        res = json.loads(proc.stdout.splitlines()[0])
        self.assertTrue(res["result"]["isError"])
        self.assertIn("is not open", res["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
