// Geometry of the panel (meters, in the panel's own frame) and the names of every animator parameter / PhysBone prefix.
// The layout numbers MUST match Tools~/make_textures.py, which draws the plate they sit on
// (tests/test_unity_package.py in the repository checks that they do).
namespace CoyotePanel.Editor
{
    internal static class PanelLayout
    {
        // The viewer sits at -Z looking toward +Z ("camera" frame): +X is their right.
        public const float PW = 0.50f, PH = 0.34f;
        public const float ROW_A = 0.075f, ROW_B = -0.015f, ROW_F = -0.105f;
        public const float BAR_X0 = -0.12f, BAR_X1 = 0.08f;
        public const float MINUS_X = -0.155f, PLUS_X = 0.115f;
        public static readonly float[] DIG_X = { 0.165f, 0.195f, 0.225f };
        public static readonly float[] FDIG_X = { -0.045f, -0.015f, 0.015f };   // hundreds, tens, ones (ones is always 0)
        public const float CELL_W = 0.028f, CELL_H = 0.044f;
        public const float BTN_DN_X = -0.13f, BTN_UP_X = 0.14f;

        public const float Z_FACE = -0.0015f;      // digits almost flush with the plate (less parallax)
        public const float RELIEF_D = 0.003f;      // height of the gold reliefs (-/+ and arrows)
        public const float Z_RELIEF = -RELIEF_D / 2f;
        public const float PRESS_DEPTH = 0.0022f;  // how far a relief sinks when clicked
        public const float PRESS_SCALE = 0.88f;    // and how much it shrinks
        public const float Z_PB = -0.012f;         // the PhysBone grips slightly in front of the plate
        public const float KNOB_W = 0.016f, KNOB_H = 0.044f, KNOB_D = 0.022f;   // the grabbable grip
        public const float NEEDLE_W = 0.004f, NEEDLE_H = 0.056f, NEEDLE_D = 0.010f; // thin value marker (not grabbable)
        public const float Z_NEEDLE = -0.007f;
        public const float BODY_D = 0.034f;

        // PhysBone grips. Each grip is ONE bone lying along the bar whose ROOT is PB_ROOT_DISTANCE to the left of the bar.
        // VRChat's stretch follows the DISTANCE between the root and the hand, so with a short bone any pull away from
        // rest (forward, up, down...) counts as "more". With a long bone that distance is almost only the sideways
        // distance: a forward pull of f adds about f*f / (2 * PB_ROOT_DISTANCE) (about 3 mm for 10 cm), and a pull
        // toward the root squishes (Max Squish is 0), so it adds nothing.
        public const float PB_ROOT_DISTANCE = 1.5f;    // rest length of the bone = distance from its root to the knob
        public const float PB_REST = 0.012f;           // the knob rests this far from the minimum end of the bar
        public static readonly float PB_MAX_STRETCH = ((BAR_X1 - BAR_X0) - PB_REST) / PB_ROOT_DISTANCE; // multiple of the length
        public const float PB_ANGLE_LIMIT = 0.3f;      // degrees: sideways play of the knob = PB_ROOT_DISTANCE * tan(this), ~8 mm
        public const float PB_GRIP_RADIUS = 0.020f;    // grab radius of the grip
        public const float PB_PULL = 0.6f;             // force back to rest on release

        // Touch buttons: VRChat contact receivers fed by the avatars' own fingertip senders (tags "Finger...")
        public const float TOUCH_RADIUS = 0.018f;      // radius of the sphere a fingertip has to enter
        public const float TOUCH_Z = -0.006f;          // in front of the plate surface
        public const float TOUCH_DEBOUNCE = 0.1f;      // seconds a press lasts at least (contact chatter must not add steps)

        // _Stretch (0-1) -> 0-200: below 0.03 it does not update (a dead zone: a small forward pull or hand jitter must
        // not move the value, and grabbing without pulling does not change it); 0.97 already means 200
        public const float STR_SRC_MIN = 0.03f, STR_SRC_MAX = 0.97f;
    }

    internal static class Names
    {
        public const string RootName = "Coyote Panel";

        // OSC contract with the PC program (coyote-vrchat): CoyoteA/CoyoteB float 0-1 (= value/200),
        // CoyoteFreq int Hz (1-100, default 50), CoyoteStop bool.
        public const string P_A = "CoyoteA", P_B = "CoyoteB", P_FREQ = "CoyoteFreq", P_STOP = "CoyoteStop";
        // The numbers shown on the plate (synced, so everyone sees them)
        public const string P_VALA = "CoyotePad/ValA", P_VALB = "CoyotePad/ValB";
        public const string P_VALA_F = "CoyotePad/ValA_f", P_VALB_F = "CoyotePad/ValB_f", P_FREQ_F = "CoyotePad/Freq_f";
        // PhysBone prefixes (VRChat creates <prefix>_IsGrabbed, <prefix>_IsPosed, <prefix>_Stretch ...)
        public const string PFX_A = "CoyotePad/PbA", PFX_B = "CoyotePad/PbB";
        public const string P_GRABA = PFX_A + "_IsGrabbed", P_GRABB = PFX_B + "_IsGrabbed";
        public const string P_POSEA = PFX_A + "_IsPosed", P_POSEB = PFX_B + "_IsPosed";
        public const string P_STRA = PFX_A + "_Stretch", P_STRB = PFX_B + "_Stretch";

        // Touch buttons. Each one has two contact receivers, each writing its own local bool:
        // "<button>_TouchSelf" = your own fingers (the holding hand excluded), "<button>_TouchOthers" = any finger of another player.
        public const string TB_AMINUS = "CoyotePad/AMinus", TB_APLUS = "CoyotePad/APlus";
        public const string TB_BMINUS = "CoyotePad/BMinus", TB_BPLUS = "CoyotePad/BPlus";
        public const string TB_UP = "CoyotePad/Up", TB_DN = "CoyotePad/Dn";
        public static readonly string[] AllButtons = { TB_AMINUS, TB_APLUS, TB_BMINUS, TB_BPLUS, TB_DN, TB_UP };
        public static string TouchSelf(string button) { return button + "_TouchSelf"; }
        public static string TouchOthers(string button) { return button + "_TouchOthers"; }
        public const string P_SHOW = "CoyotePad/Show", P_ANCHOR = "CoyotePad/Anchor", P_ZERO = "CoyotePad/Zero";
        public const string P_ONE = "CoyotePad/One";

        // click blendshapes on the static mesh
        public const string BS_AMINUS = "Press_AMinus", BS_APLUS = "Press_APlus", BS_BMINUS = "Press_BMinus", BS_BPLUS = "Press_BPlus";
        public const string BS_DN = "Press_Dn", BS_UP = "Press_Up";
    }
}
