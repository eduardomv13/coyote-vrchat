"""Offline simulation of the Coyote panel FX controller, with VRChat semantics as we understand them:
one transition per layer per frame, parameter drivers run when a state is entered, a transition with no
condition and no exit time never fires (the avatar build strips it).

Usage: python simulate_controller.py [ctrl.json]
The JSON comes from  Tools > Coyote Panel > Developer > Export FX controller JSON.
This checks the LOGIC of the controller. It does not test VRChat, PhysBones, Modular Avatar or the look of the panel.
"""
import json
import sys

J = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "ctrl.json", encoding="utf-8"))
BAR_X0, BAR_X1 = -0.12, 0.08


class Sim:
    def __init__(self):
        self.p = {}
        for x in J["params"]:
            self.p[x["n"]] = float(x["d"])
        self.layers = []
        for L in J["layers"]:
            st = {s["name"]: s for s in L["states"]}
            dfl = next(s for s in L["states"] if s["default"])
            self.layers.append({"name": L["layer"], "states": st, "cur": None, "dfl": dfl, "t": 0.0})
        self.first = True
        self.touched_remote = []

    # --- drivers
    def run_drivers(self, s):
        for d in s["drivers"]:
            t, n = d["type"], d["name"]
            if t == "Set":
                self.p[n] = d["value"]
            elif t == "Add":
                self.p[n] = self.p.get(n, 0) + d["value"]
            elif t == "Copy":
                v = self.p.get(d["src"], 0)
                if d["conv"]:
                    sMin, sMax, dMin, dMax = d["sMin"], d["sMax"], d["dMin"], d["dMax"]
                    tt = 0 if sMax == sMin else (v - sMin) / (sMax - sMin)
                    tt = max(0.0, min(1.0, tt))
                    v = dMin + (dMax - dMin) * tt
                self.p[n] = v
            # Int params: VRChat guarda inteiros
            if self.is_int(n):
                self.p[n] = float(int(round(self.p[n])))

    def is_int(self, n):
        return any(x["n"] == n and x["t"] == "Int" for x in J["params"])

    @staticmethod
    def cond_ok(c, v):
        m, thr = c["mode"], c["thr"]
        if m == "If":
            return v != 0
        if m == "IfNot":
            return v == 0
        if m == "Greater":
            return v > thr
        if m == "Less":
            return v < thr
        if m == "Equals":
            return v == thr
        if m == "NotEqual":
            return v != thr
        raise ValueError(m)

    def frame(self):
        for L in self.layers:
            if L["cur"] is None:
                L["cur"] = L["dfl"]
                self.run_drivers(L["cur"])
                continue
            s = L["cur"]
            L["t"] += 1.0 / 60.0
            for t in s["transitions"]:
                if not t["conds"] and not t.get("exit"):
                    continue  # no condition and no exit time: Unity never takes it (the avatar build strips it)
                if t.get("exit") and L["t"] < t.get("exitTime", 0):
                    continue
                if all(self.cond_ok(c, self.p.get(c["p"], 0)) for c in t["conds"]):
                    L["cur"] = L["states"][t["to"]]
                    L["t"] = 0.0
                    self.run_drivers(L["cur"])
                    break

    def frames(self, n=1):
        for _ in range(n):
            self.frame()

    # --- display (blend trees)
    def eval_motion(self, m, w, out):
        if m is None:
            return
        if "clip" in m:
            for c in m["curves"]:
                k = (c["path"], c["prop"])
                out[k] = out.get(k, 0.0) + w * c["v"]
            return
        ch = m["children"]
        if m["type"] == "Direct":
            for c in ch:
                self.eval_motion(c["m"], w * self.p.get(c["direct"], 0), out)
        else:  # Simple1D
            v = self.p.get(m["param"], 0.0)
            ch = sorted(ch, key=lambda c: c["thr"])
            if v <= ch[0]["thr"]:
                self.eval_motion(ch[0]["m"], w, out)
            elif v >= ch[-1]["thr"]:
                self.eval_motion(ch[-1]["m"], w, out)
            else:
                for a, b in zip(ch, ch[1:]):
                    if a["thr"] <= v <= b["thr"]:
                        f = 0 if b["thr"] == a["thr"] else (v - a["thr"]) / (b["thr"] - a["thr"])
                        self.eval_motion(a["m"], w * (1 - f), out)
                        self.eval_motion(b["m"], w * f, out)
                        break

    def display(self):
        L = next(l for l in self.layers if l["name"] == "CoyotePad_Display")
        out = {}
        self.eval_motion(L["cur"]["motion"], 1.0, out)
        return out


def cell(out, quad):
    v = out.get(("Container/Content/" + quad, "material._MainTex_ST.z"))
    return None if v is None else int(round(v * 11))


def glyph(c):
    return " " if c == 10 else str(c)


def text_bar(out, ch):
    return glyph(cell(out, ch + "_Digit_H")) + glyph(cell(out, ch + "_Digit_T")) + glyph(cell(out, ch + "_Digit_O"))


def text_freq(out):
    return glyph(cell(out, "F_Digit_H")) + glyph(cell(out, "F_Digit_T")) + "0"


fails = 0


def check(name, cond, info=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(info) if info else ""))
    if not cond:
        fails += 1


# ---------------------------------------------------------------- 1. initial state
s = Sim()
s.frames(3)
check("initial: CoyoteFreq=50", s.p["CoyoteFreq"] == 50)
check("initial: A=B=0, ValA=ValB=0", s.p["CoyoteA"] == 0 and s.p["CoyoteB"] == 0 and s.p["CoyotePad/ValA"] == 0)
o = s.display()
check("initial: plate A='  0' B='  0' F=' 50'", (text_bar(o, "A"), text_bar(o, "B"), text_freq(o)) == ("  0", "  0", " 50"),
      (text_bar(o, "A"), text_bar(o, "B"), text_freq(o)))

# ---------------------------------------------------------------- helpers for the physical inputs
# The slider is a BOOST (0..+30, steps of 2) on top of the value the channel had when it was grabbed. The controller walks ONE
# step per frame along the chain of Boost states, so reaching the full boost takes up to 17 frames: BOOST_FRAMES is enough.
BOOST_FRAMES = 40


def tap(s, button, who="Self", down=6, up=6):
    """A finger touches a button for `down` frames and leaves for `up` frames (who: Self = your own, Others = another player)."""
    n = "CoyotePad/%s_Touch%s" % (button, who)
    s.p[n] = 1
    s.frames(down)
    s.p[n] = 0
    s.frames(up)


def grab(s, bar, stretch, frames=BOOST_FRAMES):
    s.p["CoyotePad/Pb%s_IsGrabbed" % bar] = 1
    s.p["CoyotePad/Pb%s_Stretch" % bar] = stretch
    s.frames(frames)


def let_go(s, bar, frames=5, posed=0):
    """Release the grip. When it is posed (locked) it stays where it is, so its stretch does not fall back to 0."""
    s.p["CoyotePad/Pb%s_IsGrabbed" % bar] = 0
    s.p["CoyotePad/Pb%s_IsPosed" % bar] = posed
    if not posed:
        s.p["CoyotePad/Pb%s_Stretch" % bar] = 0.0
    s.frames(frames)


def set_level(s, bar, value):
    """Put a channel at `value` the way the user does: with the +/- buttons (10 per touch)."""
    for _ in range(value // 10):
        tap(s, bar + "Plus")


# ---------------------------------------------------------------- 2. drag bar A (a boost from 0), then let go
s = Sim(); s.frames(2)
s.p["CoyotePad/PbA_IsGrabbed"] = 1
vals = []
for i in range(0, 101):
    s.p["CoyotePad/PbA_Stretch"] = i / 100.0
    s.frames(20)
    vals.append(s.p["CoyotePad/ValA"])
check("drag A from 0: monotonic", all(b >= a for a, b in zip(vals, vals[1:])))
check("drag A from 0: the end of the bar gives +30, NOT 200", vals[-1] == 30, vals[-1])
check("drag A from 0: never more than +30 anywhere on the bar", max(vals) == 30, max(vals))
check("drag A from 0: the middle (stretch .5) is about +15", 13 <= vals[50] <= 17, vals[50])
check("drag A from 0: stays 0 inside the dead zone (stretch<=0.03)", all(v == 0 for v in vals[:4]), vals[:5])
check("drag A from 0: moves in steps of 2", all(v % 2 == 0 for v in vals), sorted(set(vals)))
s.p["CoyotePad/PbA_Stretch"] = 1.0; s.frames(30)
o = s.display()
check("drag A: plate ' 30' and the marker at 30/200 of the bar while held",
      text_bar(o, "A") == " 30" and abs(o.get(("Container/Content/A_Handle", "m_LocalPosition.x")) - (BAR_X0 + (BAR_X1 - BAR_X0) * 30 / 200)) < 1e-6,
      (text_bar(o, "A"), o.get(("Container/Content/A_Handle", "m_LocalPosition.x"))))
check("drag A: CoyoteA follows (30/200) while held", abs(s.p["CoyoteA"] - 30 / 200.0) < 1e-6, s.p["CoyoteA"])
let_go(s, "A")
check("let go of A: the value drops back to 0 (what it was)", s.p["CoyotePad/ValA"] == 0, s.p["CoyotePad/ValA"])
check("let go of A: CoyoteA = 0 (OSC)", s.p["CoyoteA"] == 0, s.p["CoyoteA"])
check("let go of A: B untouched", s.p["CoyotePad/ValB"] == 0 and s.p["CoyoteB"] == 0)
o = s.display()
hx = o.get(("Container/Content/A_Handle", "m_LocalPosition.x"))
check("let go of A: plate '  0' and marker back at the left end", text_bar(o, "A") == "  0" and abs(hx - BAR_X0) < 1e-6, (text_bar(o, "A"), hx))

# a small pull (a forward tug, hand jitter) stays inside the dead zone and changes nothing
s = Sim(); s.frames(2)
grab(s, "A", 0.025, frames=30)
check("a small pull (inside the dead zone) does not change the value", s.p["CoyotePad/ValA"] == 0, s.p["CoyotePad/ValA"])

# posing (locking the grip in place) keeps the boost until the pose is released, which gives the old value back
s = Sim(); s.frames(2)
grab(s, "A", 0.5)
v = s.p["CoyotePad/ValA"]
s.p["CoyotePad/PbA_IsPosed"] = 1; s.frames(2)
let_go(s, "A", frames=60, posed=1)
check("posed grip keeps its boost after letting go", 12 <= v <= 16 and s.p["CoyotePad/ValA"] == v, (v, s.p["CoyotePad/ValA"]))
check("posed grip: CoyoteA keeps following", abs(s.p["CoyoteA"] - v / 200.0) < 1e-6)
s.p["CoyotePad/PbA_IsPosed"] = 0; s.p["CoyotePad/PbA_Stretch"] = 0.0; s.frames(5)
check("releasing the pose gives the old value back (0)", s.p["CoyotePad/ValA"] == 0, s.p["CoyotePad/ValA"])

# ---------------------------------------------------------------- 3. A and B together, intermediate values
s = Sim(); s.frames(2)
grab(s, "A", 0.25)
grab(s, "B", 0.49)
check("A~+7 B~+14 independent", 5 <= s.p["CoyotePad/ValA"] <= 9 and 12 <= s.p["CoyotePad/ValB"] <= 16, (s.p["CoyotePad/ValA"], s.p["CoyotePad/ValB"]))
check("CoyoteA=ValA/200 and CoyoteB=ValB/200", abs(s.p["CoyoteA"] - s.p["CoyotePad/ValA"] / 200) < 1e-6 and abs(s.p["CoyoteB"] - s.p["CoyotePad/ValB"] / 200) < 1e-6)
o = s.display()
check("plate shows the same values", text_bar(o, "A").strip() == str(int(s.p["CoyotePad/ValA"])) and text_bar(o, "B").strip() == str(int(s.p["CoyotePad/ValB"])), (text_bar(o, "A"), text_bar(o, "B")))
b_boost = s.p["CoyotePad/ValB"]
let_go(s, "A")
check("letting go of A leaves B alone", s.p["CoyotePad/ValA"] == 0 and s.p["CoyotePad/ValB"] == b_boost, (s.p["CoyotePad/ValA"], s.p["CoyotePad/ValB"]))
let_go(s, "B")
check("letting go of B gives B its old value (0)", s.p["CoyotePad/ValB"] == 0 and s.p["CoyoteB"] == 0)

# ---------------------------------------------------------------- 4. frequency (one step per touch)
s = Sim(); s.frames(2)
seq = []
for _ in range(7):                       # 7 touches up: 50 -> 100 and stops
    tap(s, "Up")
    seq.append(int(s.p["CoyoteFreq"]))
check("freq UP: 60,70,80,90,100,100,100", seq == [60, 70, 80, 90, 100, 100, 100], seq)
# a finger that stays on the button: only one step
s2 = Sim(); s2.frames(2)
s2.p["CoyotePad/Up_TouchSelf"] = 1; s2.frames(120)
check("freq UP touched for 2 s: a single step (60)", s2.p["CoyoteFreq"] == 60, s2.p["CoyoteFreq"])
s3 = Sim(); s3.frames(2)
tap(s3, "Up", "Others")
check("freq UP by ANOTHER player's finger: +10", s3.p["CoyoteFreq"] == 60, s3.p["CoyoteFreq"])
seq = []
for _ in range(12):
    tap(s, "Dn")
    seq.append(int(s.p["CoyoteFreq"]))
check("freq DOWN: 90..10 and stops at 10", seq == [90, 80, 70, 60, 50, 40, 30, 20, 10, 10, 10, 10], seq)
o = s.display()
check("plate freq at 10 = ' 10'", text_freq(o) == " 10", text_freq(o))
for _ in range(10):
    tap(s, "Up")
o = s.display()
check("plate freq at 100 = '100'", text_freq(o) == "100", text_freq(o))

# ---------------------------------------------------------------- 5. zero and stop
s = Sim(); s.frames(2)
s.p["CoyotePad/ValA"] = 180; s.p["CoyotePad/ValB"] = 100; s.frames(3)
check("before zeroing: A>0 B>0", s.p["CoyotePad/ValA"] > 0 and s.p["CoyotePad/ValB"] > 0)
s.p["CoyotePad/Zero"] = 1; s.frames(4); s.p["CoyotePad/Zero"] = 0; s.frames(3)
check("Zero: ValA=ValB=0, CoyoteA=CoyoteB=0", s.p["CoyotePad/ValA"] == 0 and s.p["CoyotePad/ValB"] == 0 and s.p["CoyoteA"] == 0 and s.p["CoyoteB"] == 0)
check("Zero does not touch the frequency", s.p["CoyoteFreq"] == 50)
s.p["CoyotePad/ValA"] = 100; s.frames(3)
s.p["CoyoteStop"] = 1; s.frames(4); s.p["CoyoteStop"] = 0; s.frames(3)
check("STOP also zeroes the panel", s.p["CoyotePad/ValA"] == 0 and s.p["CoyoteA"] == 0)

# ---------------------------------------------------------------- 6. ceiling
s = Sim(); s.frames(2)
s.p["CoyotePad/ValA"] = 250; s.frames(4)
check("ceiling: 250 -> 200", s.p["CoyotePad/ValA"] == 200, s.p["CoyotePad/ValA"])

# ---------------------------------------------------------------- 6b. -/+ touch buttons per channel (one step per touch)
s = Sim(); s.frames(2)
tap(s, "APlus")
check("A +: one touch = +10", s.p["CoyotePad/ValA"] == 10, s.p["CoyotePad/ValA"])
s.p["CoyotePad/APlus_TouchSelf"] = 1; s.frames(120); s.p["CoyotePad/APlus_TouchSelf"] = 0; s.frames(10)
check("A +: a finger resting on the button does NOT repeat (one more step only)", s.p["CoyotePad/ValA"] == 20, s.p["CoyotePad/ValA"])
for _ in range(25):
    tap(s, "APlus")
check("A +: touches stop at 200", s.p["CoyotePad/ValA"] == 200, s.p["CoyotePad/ValA"])
check("A +: CoyoteA=1.0", abs(s.p["CoyoteA"] - 1.0) < 1e-6)
for _ in range(25):
    tap(s, "AMinus")
check("A -: touches stop at 0", s.p["CoyotePad/ValA"] == 0, s.p["CoyotePad/ValA"])
tap(s, "BPlus", "Others")
check("B + by another player's finger, independent of A", s.p["CoyotePad/ValB"] == 10 and s.p["CoyotePad/ValA"] == 0)
tap(s, "AMinus")
check("A - at 0 does not go negative", s.p["CoyotePad/ValA"] == 0)
s.p["CoyotePad/APlus_TouchSelf"] = 1; s.p["CoyotePad/APlus_TouchOthers"] = 1; s.frames(10)
s.p["CoyotePad/APlus_TouchSelf"] = 0; s.p["CoyotePad/APlus_TouchOthers"] = 0; s.frames(10)
check("both receivers of one button on at once = one step", s.p["CoyotePad/ValA"] == 10, s.p["CoyotePad/ValA"])
s = Sim(); s.frames(2)
n = "CoyotePad/APlus_TouchSelf"
s.p[n] = 1; s.frames(2); s.p[n] = 0; s.frames(1); s.p[n] = 1; s.frames(2); s.p[n] = 0; s.frames(15)
check("contact chatter (on-off-on within 5 frames) = one step", s.p["CoyotePad/ValA"] == 10, s.p["CoyotePad/ValA"])

# ---------------------------------------------------------------- 6a. grabbing without pulling changes nothing; panel reset
s = Sim(); s.frames(2)
s.p["CoyotePad/ValA"] = 120; s.frames(3)
grab(s, "A", 0.0, frames=5)
check("grab without pulling keeps the value (120)", s.p["CoyotePad/ValA"] == 120, s.p["CoyotePad/ValA"])
s.p["CoyotePad/PbA_Stretch"] = 0.5; s.frames(BOOST_FRAMES)
check("pulling to the middle adds about 15 to the 120", 132 <= s.p["CoyotePad/ValA"] <= 136, s.p["CoyotePad/ValA"])
s.p["CoyotePad/PbA_Stretch"] = 0.005; s.frames(BOOST_FRAMES)
check("dragging back to rest gives the value it had (120)", s.p["CoyotePad/ValA"] == 120, s.p["CoyotePad/ValA"])
let_go(s, "A")
check("letting go keeps 120", s.p["CoyotePad/ValA"] == 120)
s = Sim(); s.frames(2)
tap(s, "APlus"); tap(s, "APlus")
grab(s, "A", 0.0, frames=4); let_go(s, "A")
check("grab and release without pulling leaves a value set with the buttons (20)", s.p["CoyotePad/ValA"] == 20, s.p["CoyotePad/ValA"])

# ---------------------------------------------------------------- 6b2. THE BOOST: the slider adds at most +30 to what is already set
s = Sim(); s.frames(2)
set_level(s, "A", 50)
check("setup: 5 touches of + give 50", s.p["CoyotePad/ValA"] == 50, s.p["CoyotePad/ValA"])
grab(s, "A", 1.0)
check("boost: 50 + a full pull = 80 (the example that was asked for)", s.p["CoyotePad/ValA"] == 80, s.p["CoyotePad/ValA"])
check("boost: CoyoteA = 80/200 while held", abs(s.p["CoyoteA"] - 80 / 200.0) < 1e-6, s.p["CoyoteA"])
o = s.display()
check("boost: the plate shows 80", text_bar(o, "A") == " 80", text_bar(o, "A"))
s.frames(600)
check("boost: holding the full pull for 10 s stays at 80", s.p["CoyotePad/ValA"] == 80, s.p["CoyotePad/ValA"])
s.p["CoyotePad/PbA_Stretch"] = 5.0; s.frames(60)
check("boost: a stretch far past the end of the bar still gives 80", s.p["CoyotePad/ValA"] == 80, s.p["CoyotePad/ValA"])
let_go(s, "A")
check("boost: letting go gives 50 back", s.p["CoyotePad/ValA"] == 50, s.p["CoyotePad/ValA"])
check("boost: CoyoteA is back to 50/200", abs(s.p["CoyoteA"] - 50 / 200.0) < 1e-6, s.p["CoyoteA"])

# a jump from rest to the end in one frame never goes past +30, not even for a frame
s = Sim(); s.frames(2)
set_level(s, "A", 100)
s.p["CoyotePad/PbA_IsGrabbed"] = 1; s.p["CoyotePad/PbA_Stretch"] = 1.0
seen = []
for _ in range(40):
    s.frames(1)
    seen.append(s.p["CoyotePad/ValA"])
check("boost: a jump to the end of the bar never shows more than 130", max(seen) == 130 and min(seen) >= 100, (min(seen), max(seen)))
check("boost: ... and it gets there within 20 frames", seen.index(130) <= 20, seen.index(130))
check("boost: the value only goes up by steps of 2 on the way", all(b - a in (0, 2) for a, b in zip(seen, seen[1:])), seen[:20])
let_go(s, "A")
check("boost: back to 100", s.p["CoyotePad/ValA"] == 100)

# near the ceiling: the clamp at 200 holds, and letting go still gives the exact old value
for base in (180, 190, 200):
    s = Sim(); s.frames(2)
    s.p["CoyotePad/ValA"] = base; s.frames(3)
    s.p["CoyotePad/PbA_IsGrabbed"] = 1; s.p["CoyotePad/PbA_Stretch"] = 1.0
    peak, peak_osc = 0, 0.0
    for _ in range(BOOST_FRAMES):
        s.frames(1)
        peak, peak_osc = max(peak, s.p["CoyotePad/ValA"]), max(peak_osc, s.p["CoyoteA"])
    held = s.p["CoyotePad/ValA"]
    check("ceiling: base %d: the value (and CoyoteA) never pass 200 / 1.0, not even for a frame" % base, peak <= 200 and peak_osc <= 1.0, (peak, peak_osc))
    let_go(s, "A")
    check("ceiling: base %d + a full pull is %d (never above 200)" % (base, min(200, base + 30)), held == min(200, base + 30), held)
    check("ceiling: ... and letting go gives back exactly %d" % base, s.p["CoyotePad/ValA"] == base, s.p["CoyotePad/ValA"])

# moving the grip up, down and back to rest in one grab does not change the value that will come back
s = Sim(); s.frames(2)
set_level(s, "A", 40)
grab(s, "A", 1.0)
s.p["CoyotePad/PbA_Stretch"] = 0.5; s.frames(BOOST_FRAMES)
mid = s.p["CoyotePad/ValA"]
s.p["CoyotePad/PbA_Stretch"] = 0.0; s.frames(BOOST_FRAMES)
check("up, down, to rest in one grab: back at 40 while still held", s.p["CoyotePad/ValA"] == 40 and 52 <= mid <= 56, (mid, s.p["CoyotePad/ValA"]))
s.p["CoyotePad/PbA_Stretch"] = 1.0; s.frames(BOOST_FRAMES)
let_go(s, "A")
check("... and after another pull, letting go still gives 40", s.p["CoyotePad/ValA"] == 40, s.p["CoyotePad/ValA"])

# many grabs in a row do not creep upwards (the old value is a snapshot, not a running total)
s = Sim(); s.frames(2)
set_level(s, "A", 60)
for i in range(40):
    grab(s, "A", (i % 10 + 1) / 10.0, frames=25)
    let_go(s, "A", frames=6)
check("40 grabs and releases leave the value at exactly 60", s.p["CoyotePad/ValA"] == 60, s.p["CoyotePad/ValA"])
check("... and CoyoteA at 60/200", abs(s.p["CoyoteA"] - 60 / 200.0) < 1e-6)

# the -/+ buttons do nothing while the slider is held (the slider owns the value then)
s = Sim(); s.frames(2)
set_level(s, "A", 50)
grab(s, "A", 1.0)
tap(s, "APlus"); tap(s, "APlus", "Others"); tap(s, "AMinus")
check("buttons ignored while the slider is held", s.p["CoyotePad/ValA"] == 80, s.p["CoyotePad/ValA"])
let_go(s, "A")
check("... and nothing they did sticks: 50 comes back", s.p["CoyotePad/ValA"] == 50, s.p["CoyotePad/ValA"])
tap(s, "APlus")
check("the buttons work again after letting go (60)", s.p["CoyotePad/ValA"] == 60, s.p["CoyotePad/ValA"])
s = Sim(); s.frames(2)
set_level(s, "A", 50)
grab(s, "A", 0.6)
s.p["CoyotePad/PbA_IsPosed"] = 1; s.frames(2)
let_go(s, "A", frames=20, posed=1)
before = s.p["CoyotePad/ValA"]
tap(s, "APlus")
check("buttons are also ignored while the grip is posed", s.p["CoyotePad/ValA"] == before, (before, s.p["CoyotePad/ValA"]))

# STOP / Zero while the slider is held: the old value must not come back when it is let go
s = Sim(); s.frames(2)
set_level(s, "A", 70)
grab(s, "A", 1.0)
s.p["CoyotePad/Zero"] = 1; s.frames(4); s.p["CoyotePad/Zero"] = 0; s.frames(4)
check("Zero while held: the panel shows 0", s.p["CoyotePad/ValA"] == 0, s.p["CoyotePad/ValA"])
let_go(s, "A")
check("Zero while held: letting go does NOT bring 70 back", s.p["CoyotePad/ValA"] == 0 and s.p["CoyoteA"] == 0, (s.p["CoyotePad/ValA"], s.p["CoyoteA"]))
s = Sim(); s.frames(2)
set_level(s, "B", 70)
grab(s, "B", 1.0)
s.p["CoyoteStop"] = 1; s.frames(4); s.p["CoyoteStop"] = 0; s.frames(4)
let_go(s, "B")
check("STOP while held: letting go does NOT bring 70 back", s.p["CoyotePad/ValB"] == 0 and s.p["CoyoteB"] == 0, (s.p["CoyotePad/ValB"], s.p["CoyoteB"]))

# the two channels are independent, each boosts its own value
s = Sim(); s.frames(2)
set_level(s, "A", 30); set_level(s, "B", 20)
grab(s, "A", 1.0); grab(s, "B", 1.0)
check("A: 30 + 30 = 60 and B: 20 + 30 = 50 at the same time", (s.p["CoyotePad/ValA"], s.p["CoyotePad/ValB"]) == (60, 50), (s.p["CoyotePad/ValA"], s.p["CoyotePad/ValB"]))
let_go(s, "A")
check("letting go of A only: A is 30 again, B keeps its boost (50)", (s.p["CoyotePad/ValA"], s.p["CoyotePad/ValB"]) == (30, 50), (s.p["CoyotePad/ValA"], s.p["CoyotePad/ValB"]))
let_go(s, "B")
check("letting go of B: B is 20 again", (s.p["CoyotePad/ValA"], s.p["CoyotePad/ValB"]) == (30, 20), (s.p["CoyotePad/ValA"], s.p["CoyotePad/ValB"]))

# the controller really keeps the remembered value in a local (not synced) Int
names = {x["n"]: x["t"] for x in J["params"]}
check("the remembered values BaseA/BaseB exist as Int parameters", names.get("CoyotePad/BaseA") == "Int" and names.get("CoyotePad/BaseB") == "Int", names)

s = Sim(); s.frames(2)
s.p["CoyotePad/Anchor"] = 1; s.frames(3)
check("locked: Anchor=1", s.p["CoyotePad/Anchor"] == 1)
s.p["CoyotePad/Show"] = 1; s.frames(4)
check("Show panel clears the lock (position reset)", s.p["CoyotePad/Anchor"] == 0, s.p["CoyotePad/Anchor"])
s.p["CoyotePad/Anchor"] = 1; s.frames(3)
check("after showing, locking works again", s.p["CoyotePad/Anchor"] == 1)
s.p["CoyotePad/Show"] = 0; s.frames(3); s.p["CoyotePad/Show"] = 1; s.frames(4)
check("hiding and showing again unlocks once more", s.p["CoyotePad/Anchor"] == 0)

# ---------------------------------------------------------------- 6d. random play: the boost's rules hold on EVERY frame
# Random grabs, pulls (also past the end of the bar), poses, releases and button touches on both channels. The rules, checked
# after every single frame: a held channel is never below the value it had when it was grabbed nor more than +30 above it
# (nor above 200); a free channel is exactly at its level; the buttons change a free channel by 10 and a held one not at all;
# CoyoteA/B never pass 1.0.
import random

rnd = random.Random(20261024)
violations = []
for trial in range(40):
    s = Sim(); s.frames(2)
    base = {"A": 0, "B": 0}
    held = {"A": False, "B": False}
    posed = {"A": False, "B": False}

    def watch(n):
        for _ in range(n):
            s.frames(1)
            for c in "AB":
                v = s.p["CoyotePad/Val" + c]
                lo = base[c]
                hi = min(200, base[c] + 30) if held[c] else base[c]
                # CoyoteA/B come from the previous frame's value (the Mirror layer runs first), so for one frame after a release
                # they still show the boosted value (at most 30 above): they never lag by more than that, and never pass 1.0
                if not (lo <= v <= hi) or s.p["Coyote" + c] > 1.0 + 1e-9 or abs(s.p["Coyote" + c] - v / 200.0) > 30 / 200.0 + 1e-6:
                    violations.append((trial, c, v, lo, hi, held[c]))

    for step in range(120):
        c = rnd.choice("AB")
        act = rnd.random()
        if not held[c]:
            if act < 0.5:                                    # a button: one step of 10 on a free channel
                which = rnd.choice(["Plus", "Minus"])
                tap(s, c + which, rnd.choice(["Self", "Others"]))
                if which == "Plus" and base[c] < 191:
                    base[c] += 10
                if which == "Minus" and base[c] > 9:
                    base[c] -= 10
                if s.p["CoyotePad/Val" + c] != base[c]:
                    violations.append((trial, c, "button", s.p["CoyotePad/Val" + c], base[c]))
            else:                                            # grab, with any stretch, also one far past the end of the bar
                s.p["CoyotePad/Pb%s_IsGrabbed" % c] = 1
                s.p["CoyotePad/Pb%s_Stretch" % c] = rnd.choice([0.0, 0.02, 0.2, 0.5, 0.8, 1.0, 3.0, rnd.random()])
                held[c] = True
                watch(25)
        else:
            if act < 0.4:                                    # move the grip
                s.p["CoyotePad/Pb%s_Stretch" % c] = rnd.choice([0.0, 0.03, 0.1, 0.5, 0.9, 1.0, 5.0, rnd.random()])
                watch(25)
            elif act < 0.6:                                  # a button touched while the slider is held: nothing happens
                s.p["CoyotePad/%s%s_TouchSelf" % (c, rnd.choice(["Plus", "Minus"]))] = 1
                watch(6)
                for b in ("Plus", "Minus"):
                    s.p["CoyotePad/%s%s_TouchSelf" % (c, b)] = 0
                watch(6)
            elif act < 0.7 and not posed[c]:                 # pose the grip (it stays where it is), then let go of it
                s.p["CoyotePad/Pb%s_IsPosed" % c] = 1
                posed[c] = True
                watch(3)
                s.p["CoyotePad/Pb%s_IsGrabbed" % c] = 0
                watch(10)
            else:                                            # let go for good: the old value comes back
                s.p["CoyotePad/Pb%s_IsGrabbed" % c] = 0
                s.p["CoyotePad/Pb%s_IsPosed" % c] = 0
                s.p["CoyotePad/Pb%s_Stretch" % c] = 0.0
                held[c] = False
                posed[c] = False
                watch(8)
    for c in "AB":                                           # at the end everything is let go: both channels sit at their levels
        s.p["CoyotePad/Pb%s_IsGrabbed" % c] = 0
        s.p["CoyotePad/Pb%s_IsPosed" % c] = 0
        s.p["CoyotePad/Pb%s_Stretch" % c] = 0.0
        held[c] = False
    watch(10)
check("random play, 40 sessions x 120 actions: the boost rules hold on every frame", not violations, violations[:4])

# ---------------------------------------------------------------- 6c. complete vectors (VRChat quirk: a missing component becomes 0)
s = Sim(); s.frames(3)
o = s.display()
bad = []
for q in ("A_Digit_H", "A_Digit_T", "A_Digit_O", "B_Digit_H", "B_Digit_T", "B_Digit_O", "F_Digit_H", "F_Digit_T"):
    p = "Container/Content/" + q
    vals = [o.get((p, "material._MainTex_ST." + c)) for c in "xyzw"]
    if None in vals or abs(vals[0] - 1 / 11) > 1e-6 or abs(vals[1] - 1) > 1e-6 or abs(vals[3]) > 1e-6:
        bad.append((q, vals))
check("digits: _MainTex_ST x,y,w correct (no component zeroed)", not bad, bad[:2])
bad = []
for q, row in (("A_Handle", 0.075), ("B_Handle", -0.015)):
    vals = [o.get(("Container/Content/" + q, "m_LocalPosition." + c)) for c in "xyz"]
    if None in vals or abs(vals[1] - row) > 1e-6 or abs(vals[2] - (-0.007)) > 1e-6:
        bad.append((q, vals))
check("markers: y and z fixed (they do not sink into the plate)", not bad, bad)

# ---------------------------------------------------------------- 7. exhaustive: digits 0..200 and the marker
bad = []
for n in range(0, 201):
    s = Sim(); s.frames(1)
    s.p["CoyotePad/ValA"] = n
    s.p["CoyotePad/ValB"] = 200 - n
    s.frames(3)
    o = s.display()
    expA = ("%3d" % n) if n >= 100 else ("  %d" % n if n < 10 else " %d" % n)
    expB = "%3d" % (200 - n) if (200 - n) >= 100 else (("  %d" % (200 - n)) if (200 - n) < 10 else " %d" % (200 - n))
    if text_bar(o, "A") != expA or text_bar(o, "B") != expB:
        bad.append((n, text_bar(o, "A"), expA, text_bar(o, "B"), expB))
    hx = o.get(("Container/Content/A_Handle", "m_LocalPosition.x"))
    if abs(hx - (BAR_X0 + (BAR_X1 - BAR_X0) * n / 200.0)) > 1e-6:
        bad.append(("handle", n, hx))
check("exhaustive 0..200: A/B digits and marker correct", not bad, bad[:5])
badf = []
for f in range(10, 101, 10):
    s = Sim(); s.frames(1)
    s.p["CoyoteFreq"] = f
    s.frames(3)
    o = s.display()
    exp = ("%3d" % f)
    if text_freq(o) != exp:
        badf.append((f, text_freq(o), exp))
check("exhaustive freq 10..100: digits correct", not badf, badf)

# ---------------------------------------------------------------- 8. mirror: ValA/ValB/CoyoteFreq -> CoyoteA/B and *_f
bad = []
s = Sim(); s.frames(3)
for n in (0, 1, 55, 100, 199, 200):
    s.p["CoyotePad/ValA"] = n
    s.p["CoyotePad/ValB"] = 200 - n
    s.frames(3)
    if abs(s.p["CoyoteA"] - n / 200.0) > 1e-6 or abs(s.p["CoyoteB"] - (200 - n) / 200.0) > 1e-6:
        bad.append((n, s.p["CoyoteA"], s.p["CoyoteB"]))
    if s.p["CoyotePad/ValA_f"] != n or s.p["CoyotePad/ValB_f"] != 200 - n:
        bad.append(("f", n, s.p["CoyotePad/ValA_f"], s.p["CoyotePad/ValB_f"]))
for f in (50, 90, 10, 100):
    s.p["CoyoteFreq"] = f
    s.frames(3)
    if s.p["CoyotePad/Freq_f"] != f:
        bad.append(("freq", f, s.p["CoyotePad/Freq_f"]))
check("mirror: CoyoteA/B = Val/200 and *_f follow ValA/ValB/CoyoteFreq AFTER load", not bad, bad[:5])

print("\nFAILURES:", fails)
sys.exit(1 if fails else 0)
