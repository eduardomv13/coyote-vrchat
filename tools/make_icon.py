"""Draws the TEMPORARY logo of the program (a stylised wolf / coyote head, gold on black) and writes assets/coyote.png
and assets/coyote.ico.

It is an original drawing in the program's colours, not the official artwork of DG-LAB. To use a final logo, replace
assets/coyote.png and assets/coyote.ico (the .ico needs the sizes 16 to 256) and rebuild; this script is only needed to
regenerate the temporary one:

    python tools/make_icon.py        (needs Pillow: pip install pillow)
"""
import os
import sys

from PIL import Image, ImageDraw

BG, PANEL = "#0B0B0B", "#151515"
GOLD, GOLD_HI, GOLD_DIM = "#D4AF37", "#F0CB5A", "#8A6D1F"
S = 1024                                   # master size; everything below is in this coordinate system
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def mirrored(left):
    """A symmetric polygon from its left half (first and last points on the vertical axis)."""
    right = [(S - x, y) for x, y in reversed(left[1:-1])]
    return left + right


def side(pts):
    """The same polygon on the other side of the face."""
    return [(S - x, y) for x, y in pts]


def draw_logo() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((20, 20, S - 20, S - 20), radius=200, fill=BG, outline=GOLD_DIM, width=16)
    d.rounded_rectangle((52, 52, S - 52, S - 52), radius=170, outline=PANEL, width=6)

    # head: two pointed ears, cheek fur and a long muzzle (left half, mirrored)
    head = mirrored([(512, 330), (430, 295), (262, 120), (205, 425), (172, 535), (138, 640), (240, 655),
                     (300, 760), (420, 870), (512, 930)])
    d.polygon(head, fill=GOLD)

    # inner ears and the blaze on the forehead (darker gold)
    ear = [(280, 215), (245, 385), (375, 315)]
    d.polygon(ear, fill=GOLD_DIM)
    d.polygon(side(ear), fill=GOLD_DIM)
    d.polygon([(500, 338), (524, 338), (512, 505)], fill=GOLD_DIM)

    # muzzle (lighter gold)
    muzzle = mirrored([(512, 590), (450, 640), (430, 760), (470, 850), (512, 884)])
    d.polygon(muzzle, fill=GOLD_HI)

    # eyes (slanted), nose and mouth, in the background colour
    eye = [(296, 488), (432, 540), (416, 588), (312, 556)]
    d.polygon(eye, fill=BG)
    d.polygon(side(eye), fill=BG)
    for cx in (398, S - 398):                                  # a small glint in each eye
        d.ellipse((cx - 11, 549, cx + 11, 571), fill=GOLD_HI)
    d.polygon([(468, 812), (556, 812), (512, 866)], fill=BG)
    d.line([(512, 866), (512, 906)], fill=BG, width=12)
    return img


def main() -> int:
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(out, exist_ok=True)
    master = draw_logo()
    master.resize((512, 512), Image.LANCZOS).save(os.path.join(out, "coyote.png"))
    master.resize((256, 256), Image.LANCZOS).save(os.path.join(out, "coyote.ico"), format="ICO", sizes=ICO_SIZES)
    print("wrote", os.path.join(out, "coyote.png"), "and", os.path.join(out, "coyote.ico"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
