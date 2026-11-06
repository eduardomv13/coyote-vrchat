"""Coyote MCP connection test.

Starts coyote_mcp.py exactly like Claude Code does (stdio, JSON-RPC) and sends, ONLY through the MCP
tools, a sequence of intensities: 50 for 2 s, 100 for 5 s, 200 for 1 s, then zero.

Because it goes through the MCP and the app's API, the same AI safeguards apply: AI control has to be
ticked in the window, the AI ceiling applies, and the rise is gradual (ramp). The script does NOT try
to work around anything: if a value is limited, it shows the limit instead of insisting.

Usage (with the app open and the Coyote connected):
    python mcp_sequence_check.py                 # channel A
    python mcp_sequence_check.py --channel AB    # both channels
    python mcp_sequence_check.py --yes           # no confirmation prompt
Ctrl+C at any time zeroes the channel.
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STEPS = [(50, 2.0), (100, 5.0), (200, 1.0)]   # (intensity, seconds)
SAMPLE_EVERY = 0.25


class McpClient:
    """Minimal MCP client over stdio (one JSON message per line)."""

    def __init__(self, script):
        self.proc = subprocess.Popen(
            [sys.executable, script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )
        self.lines = queue.Queue()
        self._next_id = 0
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def request(self, method, params=None, timeout=15.0):
        self._next_id += 1
        mid = self._next_id
        self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
        end = time.monotonic() + timeout
        while True:
            try:
                line = self.lines.get(timeout=max(0.05, end - time.monotonic()))
            except queue.Empty:
                raise TimeoutError(f"the MCP server did not answer '{method}' within {timeout:.0f} s")
            if line is None:
                raise RuntimeError("the MCP server exited on its own (see the error message above)")
            msg = json.loads(line)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"MCP error in '{method}': {msg['error']}")
                return msg["result"]

    def notify(self, method):
        self._send({"jsonrpc": "2.0", "method": method})

    def tool(self, name, **arguments):
        """Calls a tool; returns (is_error, data)."""
        res = self.request("tools/call", {"name": name, "arguments": arguments})
        text = res["content"][0]["text"]
        try:
            data = json.loads(text)
        except ValueError:
            data = {"text": text}
        return bool(res.get("isError")), data

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()


def channel_names(ch):
    return ["A", "B"] if ch == "AB" else [ch]


def main():
    ap = argparse.ArgumentParser(description="Tests the Coyote MCP with a sequence of intensities")
    ap.add_argument("--channel", default="A", choices=["A", "B", "AB"], help="channel to test (default: A)")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--allow-disconnected", action="store_true",
                    help="run even without the Coyote connected (only tests the MCP -> app path)")
    args = ap.parse_args()
    chans = channel_names(args.channel)

    client = McpClient(os.path.join(HERE, "coyote_mcp.py"))
    try:
        info = client.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "mcp_sequence_check", "version": "1"},
        })
        client.notify("notifications/initialized")
        tools = {t["name"] for t in client.request("tools/list")["tools"]}
        needed = {"coyote_status", "coyote_set_intensity"}
        print(f"[1] MCP ok: server '{info['serverInfo']['name']}', {len(tools)} tools")
        if not needed <= tools:
            print("    missing tools:", needed - tools)
            return 1

        err, st = client.tool("coyote_status")
        if err:
            print("[2] FAILED to talk to the app:", st.get("error", st))
            print("    Is the Coyote x VRChat app open? (the MCP only talks to it)")
            return 1
        ble, ctl = st["ble"], st["control"]
        lim = ctl["limits"]
        print(f"[2] App answered. Bluetooth: {ble['state']}"
              + (f" ({ble['name']}, battery {ble['battery']}%)" if ble.get("name") else ""))
        if ctl["estopped"]:
            print("    EMERGENCY STOP active. Click RE-ENABLE CONTROLS in the window and run again.")
            return 1
        if not lim["ai_enabled"]:
            print("    AI control is OFF. Tick 'Allow an AI to control' in the window and run again.")
            return 1
        if not ble["connected"] and not args.allow_disconnected:
            print("    The Coyote is not connected. Connect it in the window (or use --allow-disconnected).")
            return 1

        ceilings = {c: lim[f"max_intensity_{c.lower()}"] for c in chans}
        cap = min(lim["ai_cap"], *ceilings.values())
        ramp = lim["ramp_up_per_s"]
        print(f"    AI ceiling: {lim['ai_cap']} | channel ceilings: "
              + ", ".join(f"{c} {v}" for c, v in ceilings.items()) + f" | max rise: {ramp or 'unlimited'}/s")
        print(f"\nSequence on channel {args.channel}:")
        for value, secs in DEFAULT_STEPS:
            note = f"  <- will be limited to {cap} by the ceiling" if value > cap else ""
            print(f"    {value:>3} for {secs:g} s{note}")
        if ramp:
            print(f"    (the rise takes ~{max(0, DEFAULT_STEPS[2][0] - DEFAULT_STEPS[1][0]) / ramp:.1f} s from 100 to 200; "
                  "200 is only reached at the end of the last step)")
        if not args.yes:
            input("\nPress Enter to start (Ctrl+C aborts and zeroes)... ")

        report = []
        for value, secs in DEFAULT_STEPS:
            err, res = client.tool("coyote_set_intensity", channel=args.channel, value=value)
            if err:
                print(f"\n[!] The app refused the value {value}: {res.get('error', res)}")
                print("    I will not try to work around it. Adjust the limit in the window if needed.")
                break
            applied = res.get("applied", value)
            print(f"\n>> requested {value} -> applied {applied:g}"
                  + (f" (limited by ceiling {res.get('limit')})" if res.get("clamped") else ""))
            peak_out, peak_dev = 0.0, 0
            t0 = time.monotonic()
            next_print = 0.0
            while True:
                el = time.monotonic() - t0
                if el >= secs:
                    break
                err, st = client.tool("coyote_status")
                if not err:
                    for c in chans:
                        ch = st["control"]["channels"][c]
                        peak_out = max(peak_out, ch["output"])
                        peak_dev = max(peak_dev, ch["actual"] or 0)
                    if el >= next_print:
                        ch = st["control"]["channels"][chans[0]]
                        print(f"   t={el:4.1f}s  output={ch['output']:>5.0f}  device={ch['actual'] if ch['actual'] is not None else '-'}")
                        next_print += 0.5
                time.sleep(SAMPLE_EVERY)
            report.append((value, applied, secs, peak_out, peak_dev))
        else:
            pass

        print("\nSummary (peak values seen in each step):")
        print("   requested  applied  duration  output  device")
        for value, applied, secs, out, dev in report:
            print(f"   {value:>6}  {applied:>8g}  {secs:>5g} s  {out:>5.0f}  {dev:>8}")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted: zeroing.")
        return 130
    finally:
        # Always zeroes what the test touched (does not use coyote_stop, which would lock the window until RE-ENABLE).
        try:
            client.tool("coyote_set_intensity", channel=args.channel, value=0)
            print("Channel zeroed.")
        except Exception as exc:
            print("WARNING: could not confirm the zero through the MCP:", exc,
                  "\nClick STOP ALL in the window if you feel anything.")
        client.close()


if __name__ == "__main__":
    sys.exit(main())
