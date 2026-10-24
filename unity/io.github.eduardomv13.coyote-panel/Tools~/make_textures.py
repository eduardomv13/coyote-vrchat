"""Generates the plate texture and the digit strip of the Coyote panel (black and gold).

    python make_textures.py --out ../Textures [--font path/to/Bold.ttf]

The PNGs that ship in the package were drawn with this script and Arial Bold. Any bold TrueType/OpenType font works
(for example Inter Bold, which is under the SIL Open Font License); the layout does not depend on the font.
The layout constants below MUST match PanelLayout.cs in the Unity package (tests/test_unity_package.py checks it).
Needs Pillow: python -m pip install pillow
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Textures"),
                help="output folder (default: the package's Textures folder)")
ap.add_argument("--font", default=None, help="bold font file to draw with (default: the first of a few common ones)")
args = ap.parse_args()

FONT_B = args.font or next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
if FONT_B is None or not os.path.exists(FONT_B):
    sys.exit("No bold font found. Pass one with --font path/to/Bold.ttf")

OUT = args.out
os.makedirs(OUT, exist_ok=True)

GOLD = (212, 168, 67, 255)
GOLD_HI = (255, 211, 106, 255)
BG = (0, 0, 0, 255)
PANEL = (0, 0, 0, 255)
INSET = (0, 0, 0, 255)
TRACK = (44, 44, 44, 255)

# ---- layout (meters, panel frame; MUST match the C# builder) ----
PW, PH = 0.50, 0.34
PPM = 2500
W, H = int(PW * PPM), int(PH * PPM)
ROW_A, ROW_B, ROW_F, TITLE_Y = 0.075, -0.015, -0.105, 0.145
BAR_X0, BAR_X1 = -0.12, 0.08
MINUS_X, PLUS_X, PAD_R = -0.155, 0.115, 0.024
LABEL_X = -0.222
DIG_X = [0.165, 0.195, 0.225]
FDIG_X = [-0.045, -0.015, 0.015]
CELL_W, CELL_H = 0.028, 0.044
BTN_DN_X, BTN_UP_X, BTN_R = -0.13, 0.14, 0.03


def px(x, y):
    return ((x + PW / 2) * PPM, (PH / 2 - y) * PPM)


def font(size_m):
    return ImageFont.truetype(FONT_B, int(size_m * PPM))


img = Image.new("RGBA", (W, H), BG)
d = ImageDraw.Draw(img)
d.rounded_rectangle([4, 4, W - 5, H - 5], radius=30, fill=PANEL, outline=GOLD, width=9)

tx, ty = px(0, TITLE_Y)
d.text((tx, ty), "DGLAB COYOTE 3.0", font=font(0.034), fill=GOLD, anchor="mm")


def inset(cx, cy, w, h):
    x0, y0 = px(cx - w / 2, cy + h / 2)
    x1, y1 = px(cx + w / 2, cy - h / 2)
    d.rounded_rectangle([x0, y0, x1, y1], radius=8, fill=INSET, outline=GOLD, width=3)


def pad(cx, cy, r, plus):
    x0, y0 = px(cx - r, cy + r)
    x1, y1 = px(cx + r, cy - r)
    d.ellipse([x0, y0, x1, y1], fill=INSET, outline=GOLD, width=4)
    s = r * 0.55
    a, b = px(cx - s, cy), px(cx + s, cy)
    d.line([a, b], fill=GOLD_HI, width=9)
    if plus:
        a, b = px(cx, cy - s), px(cx, cy + s)
        d.line([a, b], fill=GOLD_HI, width=9)


def row_bar(y, label):
    lx, ly = px(LABEL_X, y)
    d.text((lx, ly), label, font=font(0.042), fill=GOLD_HI, anchor="mm")
    pad(MINUS_X, y, PAD_R, False)
    pad(PLUS_X, y, PAD_R, True)
    x0, y0 = px(BAR_X0, y + 0.008)
    x1, y1 = px(BAR_X1, y - 0.008)
    d.rounded_rectangle([x0, y0, x1, y1], radius=14, fill=TRACK, outline=GOLD, width=3)
    # the bar is a BOOST on top of the level set with the -/+ buttons (0 ... +30), not the level itself: ticks every +10
    for i in range(4):
        xm = BAR_X0 + (BAR_X1 - BAR_X0) * i / 3
        d.line([px(xm, y - 0.014), px(xm, y - 0.024)], fill=GOLD, width=4)
    for i, t in ((0, "0"), (1, "+10"), (2, "+20"), (3, "+30")):
        xm = BAR_X0 + (BAR_X1 - BAR_X0) * i / 3
        tx_, ty_ = px(xm, y - 0.033)
        d.text((tx_, ty_), t, font=font(0.014), fill=GOLD, anchor="mm")
    inset(sum(DIG_X) / 3, y, CELL_W * 3 + 0.006, CELL_H + 0.006)


row_bar(ROW_A, "A")
row_bar(ROW_B, "B")

# frequency
inset((FDIG_X[0] + FDIG_X[2]) / 2, ROW_F, CELL_W * 3 + 0.006, CELL_H + 0.006)
# (the frequency's ones digit is a quad like the other digits, so nothing is drawn for it here)
hx, hy = px(0.075, ROW_F)
d.text((hx, hy), "Hz", font=font(0.028), fill=GOLD, anchor="mm")


def button(cx, cy, up):
    x0, y0 = px(cx - BTN_R, cy + BTN_R)
    x1, y1 = px(cx + BTN_R, cy - BTN_R)
    d.ellipse([x0, y0, x1, y1], fill=INSET, outline=GOLD, width=5)
    s = BTN_R * 0.5
    if up:
        pts = [px(cx, cy + s), px(cx - s, cy - s * 0.7), px(cx + s, cy - s * 0.7)]
    else:
        pts = [px(cx, cy - s), px(cx - s, cy + s * 0.7), px(cx + s, cy + s * 0.7)]
    d.polygon(pts, fill=GOLD_HI)
    tx_, ty_ = px(cx, cy - BTN_R - 0.012)
    d.text((tx_, ty_), "+10" if up else "-10", font=font(0.014), fill=GOLD, anchor="mm")


button(BTN_DN_X, ROW_F, False)
button(BTN_UP_X, ROW_F, True)

img.save(os.path.join(OUT, "CoyotePlate.png"))

# digit strip: 0..9 + blank (index 10)
CW, CH = 112, 176
strip = Image.new("RGBA", (CW * 11, CH), INSET)
sd = ImageDraw.Draw(strip)
fd = ImageFont.truetype(FONT_B, 150)
for i in range(10):
    sd.text((CW * i + CW // 2, CH // 2 + 4), str(i), font=fd, fill=GOLD_HI, anchor="mm")
strip.save(os.path.join(OUT, "CoyoteDigits.png"))
print("ok", W, H, "->", os.path.abspath(OUT), "| font:", FONT_B)
