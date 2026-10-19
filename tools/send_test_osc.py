"""Sends fake VRChat OSC avatar-parameter messages to the program, so you can test it without VRChat.

Examples (run from the project folder, with the program open):
  python tools/send_test_osc.py --a 0.10                # channel A at 10% of the ceiling
  python tools/send_test_osc.py --a 0.05 --b 0.05 --freq 60
  python tools/send_test_osc.py --stop                  # triggers the emergency stop
  python tools/send_test_osc.py --shock                 # touches the ShockOsc/_all contact (a shock, if the trigger is on)
  python tools/send_test_osc.py --a 0 --b 0             # back to zero

Values are the same ones the avatar sends: CoyoteA / CoyoteB are floats 0..1 (1 = the configured ceiling),
CoyoteFreq is an int in Hz (1..100) and CoyoteStop is a bool; --shock sends the bool ShockOsc/_all on and then off,
like someone touching and letting go of the avatar's contact. Start low: this really drives the device.
"""
import argparse
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from coyote_vrc.osc import encode_message  # noqa: E402

PREFIX = "/avatar/parameters/"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Send fake VRChat OSC parameters to the Coyote program")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--a", type=float, help="CoyoteA, float 0..1")
    ap.add_argument("--b", type=float, help="CoyoteB, float 0..1")
    ap.add_argument("--freq", type=int, help="CoyoteFreq, int Hz (1..100)")
    ap.add_argument("--stop", action="store_true", help="CoyoteStop = true (emergency stop)")
    ap.add_argument("--shock", action="store_true", help="touch the ShockOsc/_all contact (on, then off)")
    ap.add_argument("--shock-param", default="ShockOsc/_all", help="name of the contact parameter")
    args = ap.parse_args(argv)

    messages = []
    for name, value in (("CoyoteA", args.a), ("CoyoteB", args.b)):
        if value is not None:
            messages.append((name, float(min(1.0, max(0.0, value)))))
    if args.freq is not None:
        messages.append(("CoyoteFreq", int(args.freq)))
    if args.stop:
        messages.append(("CoyoteStop", True))
    if not messages and not args.shock:
        ap.error("nothing to send: pass --a, --b, --freq, --stop and/or --shock")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for name, value in messages:
        sock.sendto(encode_message(PREFIX + name, value), (args.host, args.port))
        print(f"sent {PREFIX + name} = {value!r} -> {args.host}:{args.port}")
    if args.shock:
        for value in (True, False):
            sock.sendto(encode_message(PREFIX + args.shock_param, value), (args.host, args.port))
            print(f"sent {PREFIX + args.shock_param} = {value!r} -> {args.host}:{args.port}")
            if value:
                time.sleep(0.3)   # like a finger touching and then leaving the contact
    return 0


if __name__ == "__main__":
    sys.exit(main())
