// The FX animator controller of the panel: 14 layers, all with Write Defaults on, merged into the avatar by Modular Avatar.
//
// Two things learned the hard way in VRChat, both respected below:
//  * When animating a vector property you must animate ALL its components (material._MainTex_ST.x/y/z/w,
//    m_LocalPosition.x/y/z). The ones left out become 0.
//  * A transition with no condition AND no exit time is stripped by the avatar build, so a state machine that "loops"
//    with such transitions runs once at load and never again. Use exit time 0 + duration 0 for a valid every-frame loop.
using System.Collections.Generic;
using UnityEditor;
using UnityEditor.Animations;
using UnityEngine;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3.Dynamics.Constraint.Components;
using VRC.SDKBase;
using static CoyotePanel.Editor.Names;
using static CoyotePanel.Editor.PanelLayout;

namespace CoyotePanel.Editor
{
    internal static class PanelController
    {
        public static AnimatorController Build(string path)
        {
            AssetDatabase.DeleteAsset(path);
            var c = AnimatorController.CreateAnimatorControllerAtPath(path);
            while (c.layers.Length > 0) c.RemoveLayer(0);

            void F(string n, float d = 0f) { c.AddParameter(new AnimatorControllerParameter { name = n, type = AnimatorControllerParameterType.Float, defaultFloat = d }); }
            void I(string n, int d = 0) { c.AddParameter(new AnimatorControllerParameter { name = n, type = AnimatorControllerParameterType.Int, defaultInt = d }); }
            void B(string n) { c.AddParameter(new AnimatorControllerParameter { name = n, type = AnimatorControllerParameterType.Bool, defaultBool = false }); }
            F(P_A); F(P_B); F(P_STRA); F(P_STRB); F(P_VALA_F); F(P_VALB_F); F(P_FREQ_F); F(P_ONE, 1f);
            I(P_FREQ, 50); I(P_VALA); I(P_VALB); I(P_BASEA); I(P_BASEB);
            B(P_GRABA); B(P_GRABB); B(P_POSEA); B(P_POSEB); B(P_SHOW); B(P_ANCHOR); B(P_ZERO); B(P_STOP);
            foreach (var tb in AllButtons) { B(TouchSelf(tb)); B(TouchOthers(tb)); }

            // ---- mirror: synced Int -> local float (blend trees) and -> CoyoteA/B (OSC = value/200)
            {
                var sm = Layer(c, "CoyotePad_Mirror");
                var s1 = State(sm, "M1", 0, 0);
                var s2 = State(sm, "M2", 1, 0);
                // exit time 0 + zero duration = a valid every-frame loop (see the note at the top of the file)
                foreach (var lt in new[] { Link(s1, s2), Link(s2, s1) }) { lt.hasExitTime = true; lt.exitTime = 0f; }
                foreach (var s in new[] { s1, s2 })
                {
                    var d = Driver(s, false);
                    d.parameters.Add(Copy(P_VALA, P_VALA_F));
                    d.parameters.Add(Copy(P_VALB, P_VALB_F));
                    d.parameters.Add(Copy(P_FREQ, P_FREQ_F));
                    d.parameters.Add(CopyRange(P_VALA, P_A, 0f, 200f, 0f, 1f));
                    d.parameters.Add(CopyRange(P_VALB, P_B, 0f, 200f, 0f, 1f));
                }
            }

            // ---- bars: a BOOST on top of the value set with the -/+ buttons. While the grip is grabbed (or posed = locked in
            //      place) the stretch adds 0..BOOST_MAX to the value the channel had when it was grabbed; letting go gives
            //      that value back
            TrackLayer(c, "CoyotePad_TrackA", P_GRABA, P_POSEA, P_STRA, P_VALA, P_BASEA);
            TrackLayer(c, "CoyotePad_TrackB", P_GRABB, P_POSEB, P_STRB, P_VALB, P_BASEB);

            // ---- "Show panel": returns the panel to the hand (unlocks it from the world)
            {
                var sm = Layer(c, "CoyotePad_ShowReset");
                var idle = State(sm, "Idle", 0, 0);
                var rst = State(sm, "Reset", 1, 0);
                Driver(rst, true).parameters.Add(SetV(P_ANCHOR, 0f));
                var t = Link(idle, rst); t.AddCondition(AnimatorConditionMode.If, 0, P_SHOW);
                t = Link(rst, idle); t.AddCondition(AnimatorConditionMode.IfNot, 0, P_SHOW);
            }

            // ---- -/+ buttons per channel (+-10 per touch); they do nothing while that channel's slider is held
            StepLayer(c, "CoyotePad_StepA", TB_AMINUS, TB_APLUS, P_VALA, P_GRABA, P_POSEA);
            StepLayer(c, "CoyotePad_StepB", TB_BMINUS, TB_BPLUS, P_VALB, P_GRABB, P_POSEB);

            // ---- animated button click (blendshapes on the static mesh)
            PressLayer(c, "CoyotePad_PressA", TB_AMINUS, TB_APLUS, BS_AMINUS, BS_APLUS);
            PressLayer(c, "CoyotePad_PressB", TB_BMINUS, TB_BPLUS, BS_BMINUS, BS_BPLUS);
            PressLayer(c, "CoyotePad_PressF", TB_DN, TB_UP, BS_DN, BS_UP);

            // ---- safety clamp at the ceiling (200)
            {
                var sm = Layer(c, "CoyotePad_Clamp");
                var idle = State(sm, "Idle", 0, 0);
                var ca = State(sm, "ClampA", 1, -1);
                var cb = State(sm, "ClampB", 1, 1);
                Driver(ca, true).parameters.Add(SetV(P_VALA, 200f));
                Driver(cb, true).parameters.Add(SetV(P_VALB, 200f));
                var t = Link(idle, ca); t.AddCondition(AnimatorConditionMode.Greater, 200f, P_VALA);
                t = Link(ca, idle); t.AddCondition(AnimatorConditionMode.Less, 201f, P_VALA);
                t = Link(idle, cb); t.AddCondition(AnimatorConditionMode.Greater, 200f, P_VALB);
                t = Link(cb, idle); t.AddCondition(AnimatorConditionMode.Less, 201f, P_VALB);
            }

            // ---- frequency: one touch = +-10 Hz, 10..100
            {
                var sm = Layer(c, "CoyotePad_Freq");
                var idle = State(sm, "Idle", 0, 0);
                var up = State(sm, "Up +10", 1, -1);
                var dn = State(sm, "Down -10", 1, 1);
                Driver(up, true).parameters.Add(Add(P_FREQ, 10f));
                Driver(dn, true).parameters.Add(Add(P_FREQ, -10f));
                foreach (var t in LinkOnTouch(idle, up, TB_UP)) t.AddCondition(AnimatorConditionMode.Less, 91f, P_FREQ);
                LinkOffTouch(up, idle, TB_UP, TOUCH_DEBOUNCE);
                foreach (var t in LinkOnTouch(idle, dn, TB_DN)) t.AddCondition(AnimatorConditionMode.Greater, 19f, P_FREQ);
                LinkOffTouch(dn, idle, TB_DN, TOUCH_DEBOUNCE);
            }

            // ---- zero / stop: puts A and B at 0 on the panel
            {
                var sm = Layer(c, "CoyotePad_Zero");
                var idle = State(sm, "Idle", 0, 0);
                var z = State(sm, "Zero", 1, 0);
                var d = Driver(z, true);
                d.parameters.Add(SetV(P_VALA, 0f));
                d.parameters.Add(SetV(P_VALB, 0f));
                // a slider that is held right now must not give the old value back when it is let go
                d.parameters.Add(SetV(P_BASEA, 0f));
                d.parameters.Add(SetV(P_BASEB, 0f));
                var t = Link(idle, z); t.AddCondition(AnimatorConditionMode.If, 0, P_ZERO);
                t = Link(idle, z); t.AddCondition(AnimatorConditionMode.If, 0, P_STOP);
                t = Link(z, idle); t.AddCondition(AnimatorConditionMode.IfNot, 0, P_ZERO); t.AddCondition(AnimatorConditionMode.IfNot, 0, P_STOP);
            }

            // ---- "Lock in world": FreezeToWorld on the container constraint => it stays at its last world pose
            {
                var sm = Layer(c, "CoyotePad_Anchor");
                var free = State(sm, "OnHand", 0, 0);
                var frozen = State(sm, "Frozen", 1, 0);
                free.motion = ConstClip(c, "Cp_Anchor_OnHand",
                    Curve("Container", typeof(VRCParentConstraint), "IsActive", 1f),
                    Curve("Container", typeof(VRCParentConstraint), "FreezeToWorld", 0f));
                frozen.motion = ConstClip(c, "Cp_Anchor_Frozen",
                    Curve("Container", typeof(VRCParentConstraint), "IsActive", 1f),
                    Curve("Container", typeof(VRCParentConstraint), "FreezeToWorld", 1f));
                var t = Link(free, frozen); t.AddCondition(AnimatorConditionMode.If, 0, P_ANCHOR);
                t = Link(frozen, free); t.AddCondition(AnimatorConditionMode.IfNot, 0, P_ANCHOR);
            }

            // ---- display: direct blend trees (fixed weight 1) with the digits and the markers
            {
                var sm = Layer(c, "CoyotePad_Display");
                var s = State(sm, "Display", 0, 0);
                var root = new BlendTree { name = "CoyotePad_Display", blendType = BlendTreeType.Direct, useAutomaticThresholds = false };
                AssetDatabase.AddObjectToAsset(root, c);
                var subs = new List<BlendTree>();
                subs.Add(DigitsTree(c, "A_Digit_O", P_VALA_F, 'O', 200));
                subs.Add(DigitsTree(c, "A_Digit_T", P_VALA_F, 'T', 200));
                subs.Add(DigitsTree(c, "A_Digit_H", P_VALA_F, 'H', 200));
                subs.Add(DigitsTree(c, "B_Digit_O", P_VALB_F, 'O', 200));
                subs.Add(DigitsTree(c, "B_Digit_T", P_VALB_F, 'T', 200));
                subs.Add(DigitsTree(c, "B_Digit_H", P_VALB_F, 'H', 200));
                subs.Add(DigitsTree(c, "F_Digit_T", P_FREQ_F, 'T', 100));
                subs.Add(DigitsTree(c, "F_Digit_H", P_FREQ_F, 'H', 100));
                subs.Add(HandleTree(c, "A_Handle", P_VALA_F, ROW_A));
                subs.Add(HandleTree(c, "B_Handle", P_VALB_F, ROW_B));
                foreach (var bt in subs) root.AddChild(bt);
                var ch = root.children;
                for (int i = 0; i < ch.Length; i++) ch[i].directBlendParameter = P_ONE;
                root.children = ch;
                s.motion = root;
            }

            var layers = c.layers;
            for (int i = 0; i < layers.Length; i++) layers[i].defaultWeight = 1f;
            c.layers = layers;
            EditorUtility.SetDirty(c);
            AssetDatabase.SaveAssets();
            return c;
        }

        // The slider is a temporary BOOST on top of the value the channel had when the grip was grabbed.
        //
        //   Idle --grabbed or posed--> Hold (remembers the value in `baseVal`) --> Boost +0 <-> Boost +2 <-> ... <-> Boost +30
        //   any Boost --neither grabbed nor posed--> Release (puts `baseVal` back) --> Idle
        //
        // Boost +k sets `val` = `baseVal` + k, so the value is never more than BOOST_MAX above what it was. An Animator
        // condition can only compare a parameter with a constant (not "value + 30"), so instead of computing the sum the
        // layer walks one step per frame along the chain of Boost states, following the stretch of the grip; each state
        // writes base + its own boost when it is entered. Letting go restores the remembered value instead of subtracting
        // (so the ceiling clamp at 200 can never make the value drift).
        static void TrackLayer(AnimatorController c, string name, string grabbed, string posed, string stretch, string val, string baseVal)
        {
            int steps = BOOST_MAX / BOOST_STEP;
            float span = STR_SRC_MAX - STR_SRC_MIN;
            var sm = Layer(c, name);
            var idle = State(sm, "Idle", 0, 0);
            var hold = State(sm, "Hold", 1, 0);
            var rel = State(sm, "Release", 2, 0);
            Driver(hold, true).parameters.Add(Copy(val, baseVal));
            Driver(rel, true).parameters.Add(Copy(baseVal, val));

            var boost = new AnimatorState[steps + 1];
            for (int k = 0; k <= steps; k++)
            {
                boost[k] = State(sm, "Boost +" + (k * BOOST_STEP), 3 + k % 8, k / 8);
                var d = Driver(boost[k], true);
                d.parameters.Add(Copy(baseVal, val));
                if (k > 0) d.parameters.Add(Add(val, k * BOOST_STEP));
            }

            foreach (var gate in new[] { grabbed, posed })
            {
                var t = Link(idle, hold); t.AddCondition(AnimatorConditionMode.If, 0, gate);
            }
            // exit time 0 + zero duration: a valid transition without a condition (see the note at the top of the file)
            var go = Link(hold, boost[0]); go.hasExitTime = true; go.exitTime = 0f;

            for (int k = 0; k <= steps; k++)
            {
                // letting go comes first (a transition list is checked in order)
                var t = Link(boost[k], rel);
                t.AddCondition(AnimatorConditionMode.IfNot, 0, grabbed);
                t.AddCondition(AnimatorConditionMode.IfNot, 0, posed);
                if (k < steps)   // up one step once the stretch is clearly past the middle of the next step...
                {
                    t = Link(boost[k], boost[k + 1]);
                    t.AddCondition(AnimatorConditionMode.Greater, STR_SRC_MIN + span * ((k + 1) - 0.5f + BOOST_HYST) / steps, stretch);
                    // ...but never above 200: the boost stops where base + boost would pass the ceiling (so the value never
                    // even touches 201 and no clamp is needed; the Clamp layer only acts when the value changes while idle)
                    t.AddCondition(AnimatorConditionMode.Less, 201f - BOOST_STEP * (k + 1), baseVal);
                }
                if (k > 0)       // down one step once it is clearly below the middle of this step
                {
                    t = Link(boost[k], boost[k - 1]);
                    t.AddCondition(AnimatorConditionMode.Less, STR_SRC_MIN + span * (k - 0.5f - BOOST_HYST) / steps, stretch);
                }
            }
            var back = Link(rel, idle); back.hasExitTime = true; back.exitTime = 0f;
        }

        // a button counts as touched when EITHER of its two receivers is on
        static List<AnimatorStateTransition> LinkOnTouch(AnimatorState a, AnimatorState b, string button)
        {
            var list = new List<AnimatorStateTransition>();
            foreach (var p in new[] { TouchSelf(button), TouchOthers(button) })
            {
                var t = Link(a, b);
                t.AddCondition(AnimatorConditionMode.If, 0, p);
                list.Add(t);
            }
            return list;
        }

        // ... and as released when BOTH are off (and, with minSeconds, no sooner than that after the press began)
        static AnimatorStateTransition LinkOffTouch(AnimatorState a, AnimatorState b, string button, float minSeconds)
        {
            var t = Link(a, b);
            t.AddCondition(AnimatorConditionMode.IfNot, 0, TouchSelf(button));
            t.AddCondition(AnimatorConditionMode.IfNot, 0, TouchOthers(button));
            if (minSeconds > 0f) { t.hasExitTime = true; t.exitTime = minSeconds; }
            return t;
        }

        // two neighboring buttons: Idle / A pressed / B pressed; each clip writes BOTH blendshapes
        static void PressLayer(AnimatorController c, string name, string buttonA, string buttonB, string bsA, string bsB)
        {
            string path = "Container/Content/Static3D";
            var sm = Layer(c, name);
            System.Func<float, float, string, AnimationClip> clip = delegate (float a, float b, string n)
            {
                return ConstClip(c, "Cp_" + name + "_" + n,
                    Curve(path, typeof(SkinnedMeshRenderer), "blendShape." + bsA, a),
                    Curve(path, typeof(SkinnedMeshRenderer), "blendShape." + bsB, b));
            };
            var idle = State(sm, "Idle", 0, 0); idle.motion = clip(0f, 0f, "Idle");
            var sa = State(sm, "Press " + bsA, 1, -1); sa.motion = clip(100f, 0f, "A");
            var sb = State(sm, "Press " + bsB, 1, 1); sb.motion = clip(0f, 100f, "B");
            foreach (var t in LinkOnTouch(idle, sa, buttonA)) t.duration = 0.04f;
            foreach (var t in LinkOnTouch(idle, sb, buttonB)) t.duration = 0.04f;
            LinkOffTouch(sa, idle, buttonA, 0f).duration = 0.08f;
            LinkOffTouch(sb, idle, buttonB, 0f).duration = 0.08f;
        }

        // -/+ : ONE step of +-10 per touch (limited to 0..200). No repeat while a finger stays on the button: a finger
        // resting on a button must not keep raising the power, so every further step needs a new touch.
        // While the channel's slider is held (grabbed or posed) the buttons do nothing: the slider owns the value then and
        // gives the old one back when it is let go.
        static void StepLayer(AnimatorController c, string name, string minus, string plus, string val, string grabbed, string posed)
        {
            var sm = Layer(c, name);
            var idle = State(sm, "Idle", 0, 0);
            var p = State(sm, "Plus", 1, -1);
            var m = State(sm, "Minus", 1, 1);
            Driver(p, true).parameters.Add(Add(val, 10f));
            Driver(m, true).parameters.Add(Add(val, -10f));
            foreach (var t in LinkOnTouch(idle, p, plus))
            {
                t.AddCondition(AnimatorConditionMode.Less, 191f, val);
                t.AddCondition(AnimatorConditionMode.IfNot, 0, grabbed);
                t.AddCondition(AnimatorConditionMode.IfNot, 0, posed);
            }
            foreach (var t in LinkOnTouch(idle, m, minus))
            {
                t.AddCondition(AnimatorConditionMode.Greater, 9f, val);
                t.AddCondition(AnimatorConditionMode.IfNot, 0, grabbed);
                t.AddCondition(AnimatorConditionMode.IfNot, 0, posed);
            }
            LinkOffTouch(p, idle, plus, TOUCH_DEBOUNCE);
            LinkOffTouch(m, idle, minus, TOUCH_DEBOUNCE);
        }

        // ---------------------------------------------------------------- display
        // digit strip: cells 0..9 and 10 = blank; full ST (x,y,z,w): scale 1/11 in U, offset = cell/11
        static BlendTree DigitsTree(AnimatorController c, string quad, string param, char which, int max)
        {
            string path = "Container/Content/" + quad;
            var cache = new Dictionary<int, AnimationClip>();
            System.Func<int, AnimationClip> cell = delegate (int k)
            {
                AnimationClip clip;
                if (!cache.TryGetValue(k, out clip))
                {
                    clip = ConstClip(c, "Cp_" + quad + "_D" + k,
                        Curve(path, typeof(MeshRenderer), "material._MainTex_ST.x", 1f / 11f),
                        Curve(path, typeof(MeshRenderer), "material._MainTex_ST.y", 1f),
                        Curve(path, typeof(MeshRenderer), "material._MainTex_ST.z", k / 11f),
                        Curve(path, typeof(MeshRenderer), "material._MainTex_ST.w", 0f));
                    cache[k] = clip;
                }
                return clip;
            };
            var bt = new BlendTree { name = quad, blendType = BlendTreeType.Simple1D, blendParameter = param, useAutomaticThresholds = false };
            AssetDatabase.AddObjectToAsset(bt, c);
            int decades = max / 10;
            if (which == 'O')
            {
                for (int k = 0; k <= decades; k++)
                {
                    bt.AddChild(cell(0), 10f * k);
                    bt.AddChild(cell(9), 10f * k + 9f);
                }
            }
            else if (which == 'T')
            {
                for (int j = 0; j <= decades; j++)
                {
                    var m = cell(j == 0 ? 10 : j % 10);
                    bt.AddChild(m, 10f * j);
                    bt.AddChild(m, 10f * j + 9f);
                }
            }
            else // 'H' hundreds: blank < 100, "1" in 100..199, "2" at 200
            {
                bt.AddChild(cell(10), 0f);
                bt.AddChild(cell(10), 99f);
                bt.AddChild(cell(1), 100f);
                bt.AddChild(cell(1), max >= 200 ? 199f : 109f);
                if (max >= 200)
                {
                    bt.AddChild(cell(2), 200f);
                    bt.AddChild(cell(2), 209f);
                }
            }
            return bt;
        }

        // bar marker: x goes from BAR_X0 (0) to BAR_X1 (200); y and z FIXED in both clips (full vector)
        static BlendTree HandleTree(AnimatorController c, string quad, string param, float row)
        {
            string path = "Container/Content/" + quad;
            var lo = ConstClip(c, "Cp_" + quad + "_Min",
                Curve(path, typeof(Transform), "m_LocalPosition.x", BAR_X0),
                Curve(path, typeof(Transform), "m_LocalPosition.y", row),
                Curve(path, typeof(Transform), "m_LocalPosition.z", Z_NEEDLE));
            var hi = ConstClip(c, "Cp_" + quad + "_Max",
                Curve(path, typeof(Transform), "m_LocalPosition.x", BAR_X1),
                Curve(path, typeof(Transform), "m_LocalPosition.y", row),
                Curve(path, typeof(Transform), "m_LocalPosition.z", Z_NEEDLE));
            var bt = new BlendTree { name = quad, blendType = BlendTreeType.Simple1D, blendParameter = param, useAutomaticThresholds = false };
            AssetDatabase.AddObjectToAsset(bt, c);
            bt.AddChild(lo, 0f);
            bt.AddChild(hi, 200f);
            return bt;
        }

        // ---------------------------------------------------------------- animator helpers
        struct CV { public EditorCurveBinding B; public float V; }

        static CV Curve(string path, System.Type type, string prop, float v)
        {
            return new CV { B = EditorCurveBinding.FloatCurve(path, type, prop), V = v };
        }

        static AnimationClip ConstClip(AnimatorController c, string name, params CV[] cvs)
        {
            var clip = new AnimationClip { name = name };
            foreach (var cv in cvs)
                AnimationUtility.SetEditorCurve(clip, cv.B, new AnimationCurve(new Keyframe(0f, cv.V)));
            AssetDatabase.AddObjectToAsset(clip, c);
            return clip;
        }

        static AnimatorStateMachine Layer(AnimatorController c, string name)
        {
            var sm = new AnimatorStateMachine { name = name, hideFlags = HideFlags.HideInHierarchy };
            AssetDatabase.AddObjectToAsset(sm, c);
            c.AddLayer(new AnimatorControllerLayer { name = name, stateMachine = sm, defaultWeight = 1f });
            return sm;
        }

        static AnimatorState State(AnimatorStateMachine sm, string name, int col, int row)
        {
            var s = sm.AddState(name, new Vector3(250f * col, 90f * row, 0f));
            s.writeDefaultValues = true;
            return s;
        }

        static AnimatorStateTransition Link(AnimatorState a, AnimatorState b)
        {
            var t = a.AddTransition(b);
            t.hasExitTime = false;
            t.hasFixedDuration = true;
            t.duration = 0f;
            t.exitTime = 0f;
            t.canTransitionToSelf = false;
            return t;
        }

        static VRCAvatarParameterDriver Driver(AnimatorState s, bool localOnly)
        {
            var d = s.AddStateMachineBehaviour<VRCAvatarParameterDriver>();
            d.parameters = new List<VRC_AvatarParameterDriver.Parameter>();
            d.localOnly = localOnly;
            return d;
        }

        static VRC_AvatarParameterDriver.Parameter Copy(string src, string dst)
        {
            return new VRC_AvatarParameterDriver.Parameter { type = VRC_AvatarParameterDriver.ChangeType.Copy, source = src, name = dst };
        }

        static VRC_AvatarParameterDriver.Parameter CopyRange(string src, string dst, float sMin, float sMax, float dMin, float dMax)
        {
            return new VRC_AvatarParameterDriver.Parameter
            {
                type = VRC_AvatarParameterDriver.ChangeType.Copy, source = src, name = dst,
                convertRange = true, sourceMin = sMin, sourceMax = sMax, destMin = dMin, destMax = dMax
            };
        }

        static VRC_AvatarParameterDriver.Parameter SetV(string dst, float v)
        {
            return new VRC_AvatarParameterDriver.Parameter { type = VRC_AvatarParameterDriver.ChangeType.Set, name = dst, value = v };
        }

        static VRC_AvatarParameterDriver.Parameter Add(string dst, float v)
        {
            return new VRC_AvatarParameterDriver.Parameter { type = VRC_AvatarParameterDriver.ChangeType.Add, name = dst, value = v };
        }
    }
}
