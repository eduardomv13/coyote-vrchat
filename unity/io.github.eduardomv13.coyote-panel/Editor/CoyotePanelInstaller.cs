// Builds (or rebuilds) the "Coyote Panel" child object on a VRChat avatar.
//
// 100% non-destructive: the install only adds ONE child object of the avatar root, carrying Modular Avatar components
// (Merge Animator, Parameters, Menu Installer, Bone Proxy, Object Toggle). Nothing of the avatar itself is edited.
// Re-running it deletes the previous "Coyote Panel" child and rebuilds everything from scratch.
//
// OSC contract with the PC program (coyote-vrchat):
//   CoyoteA / CoyoteB : float 0-1 (= panel value / 200)    CoyoteFreq : int Hz (1-100, default 50)    CoyoteStop : bool
using System.Collections.Generic;
using nadena.dev.modular_avatar.core;
using UnityEditor;
using UnityEngine;
using VRC.Dynamics;
using VRC.SDK3.Avatars.Components;
using VRC.SDK3.Dynamics.Constraint.Components;
using VRC.SDK3.Dynamics.Contact.Components;
using VRC.SDK3.Dynamics.PhysBone.Components;
using static CoyotePanel.Editor.Names;
using static CoyotePanel.Editor.PanelLayout;

namespace CoyotePanel.Editor
{
    public static class CoyotePanelInstaller
    {
        /// <summary>The avatar root (the object with the VRC Avatar Descriptor) that contains <paramref name="selected"/>, or null.</summary>
        public static GameObject FindAvatarRoot(GameObject selected)
        {
            if (selected == null) return null;
            var d = selected.GetComponentInParent<VRCAvatarDescriptor>(true);
            return d != null ? d.gameObject : null;
        }

        public static Transform FindPanel(GameObject avatar)
        {
            return avatar != null ? avatar.transform.Find(RootName) : null;
        }

        /// <summary>Why the avatar cannot get the panel, or null if it can.</summary>
        public static string Validate(GameObject avatar, CoyotePanelOptions o)
        {
            if (avatar == null) return "Select an avatar (the object that has the VRC Avatar Descriptor) in the Hierarchy.";
            if (EditorUtility.IsPersistent(avatar)) return "Pick the avatar in the scene, not the prefab asset in the Project window.";
            var anim = avatar.GetComponent<Animator>();
            if (anim == null || anim.avatar == null || !anim.avatar.isHuman) return "The avatar needs a Humanoid rig (Animator with a Humanoid Avatar).";
            if (anim.GetBoneTransform(HandFrame.HandBone(o.hand)) == null) return "The humanoid rig has no " + o.hand + " hand bone.";
            return null;
        }

        /// <summary>Folder where this avatar's generated meshes/materials/controller live.</summary>
        public static string OutputDirFor(GameObject avatar, CoyotePanelOptions o)
        {
            var safe = new System.Text.StringBuilder();
            foreach (char ch in avatar.name) safe.Append(char.IsLetterOrDigit(ch) || ch == '-' || ch == '_' ? ch : '_');
            return o.outputFolder.TrimEnd('/') + "/" + (safe.Length > 0 ? safe.ToString() : "Avatar");
        }

        static void EnsureFolder(string path)
        {
            var parts = path.Split('/');
            string cur = parts[0];
            for (int i = 1; i < parts.Length; i++)
            {
                string next = cur + "/" + parts[i];
                if (!AssetDatabase.IsValidFolder(next)) AssetDatabase.CreateFolder(cur, parts[i]);
                cur = next;
            }
        }

        public static void Remove(GameObject avatar, CoyotePanelOptions o, bool deleteGeneratedAssets)
        {
            var old = FindPanel(avatar);
            if (old != null) Undo.DestroyObjectImmediate(old.gameObject);
            if (deleteGeneratedAssets)
            {
                var dir = OutputDirFor(avatar, o);
                if (AssetDatabase.IsValidFolder(dir)) AssetDatabase.DeleteAsset(dir);
            }
            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(avatar.scene);
        }

        public static string Install(GameObject avatar, CoyotePanelOptions o)
        {
            o.Sanitized();
            var problem = Validate(avatar, o);
            if (problem != null) throw new System.Exception("[CoyotePanel] " + problem);

            // Work out what can fail on a bad configuration BEFORE touching the avatar.
            var frame = HandFrame.Compute(avatar.GetComponent<Animator>(), o);

            AssetDatabase.Refresh();
            var old = FindPanel(avatar);
            if (old != null) Undo.DestroyObjectImmediate(old.gameObject);
            try
            {
                return Build(avatar, o, frame);
            }
            catch
            {
                // do not leave a half-built panel on the avatar
                var partial = FindPanel(avatar);
                if (partial != null) Undo.DestroyObjectImmediate(partial.gameObject);
                throw;
            }
        }

        static string Build(GameObject avatar, CoyotePanelOptions o, HandFrame frame)
        {
            string dir = OutputDirFor(avatar, o);
            EnsureFolder(dir);

            // ------------------------------------------------ assets
            var assets = new PanelAssets(dir);
            assets.BuildAll();

            // ------------------------------------------------ hierarchy
            var panel = new GameObject(RootName);
            Undo.RegisterCreatedObjectUndo(panel, "Coyote Panel");
            panel.transform.SetParent(avatar.transform, false);
            panel.transform.localPosition = Vector3.zero;
            panel.transform.localRotation = Quaternion.identity;

            // A target attached to the hand bone + a container that follows it through ONE VRCParentConstraint.
            // "Lock in world" turns on FreezeToWorld: the container stays at its last world pose.
            var hand = frame.hand;

            var handTarget = Child(panel, "HandTarget");
            handTarget.transform.SetPositionAndRotation(hand.position, hand.rotation);
            var bp = handTarget.AddComponent<ModularAvatarBoneProxy>();
            bp.boneReference = HandFrame.HandBone(o.hand);
            bp.attachmentMode = BoneProxyAttachmentMode.AsChildAtRoot;

            var container = Child(panel, "Container");
            container.transform.SetPositionAndRotation(hand.position, hand.rotation);
            var pc = container.AddComponent<VRCParentConstraint>();
            pc.TargetTransform = container.transform;
            pc.Sources.Add(new VRCConstraintSource(handTarget.transform, 1f, Vector3.zero, Vector3.zero));
            pc.IsActive = true;            // always on; FreezeToWorld does the locking
            pc.FreezeToWorld = false;      // default: follows the hand
            pc.GlobalWeight = 1f;
            pc.SolveInLocalSpace = false;
            pc.Locked = true;

            var content = Child(container, "Content");
            frame.Place(content.transform, o, avatar.transform.lossyScale.y);
            content.SetActive(false); // default: panel hidden (the "Show panel" toggle turns it on)

            var st = Child(content, "Static3D");
            var sr = st.AddComponent<SkinnedMeshRenderer>();
            sr.sharedMesh = assets.statics;
            sr.sharedMaterials = new[] { assets.matBody, assets.matGold, assets.matPlate };
            sr.localBounds = assets.statics.bounds;
            sr.updateWhenOffscreen = false;
            NoShadows(sr);

            // value marker (animated by CoyotePad/ValA|B) - NOT grabbable
            Mesh2(content, "A_Handle", assets.cube, assets.matNeedle, new Vector3(BAR_X0, ROW_A, Z_NEEDLE), new Vector3(NEEDLE_W, NEEDLE_H, NEEDLE_D));
            Mesh2(content, "B_Handle", assets.cube, assets.matNeedle, new Vector3(BAR_X0, ROW_B, Z_NEEDLE), new Vector3(NEEDLE_W, NEEDLE_H, NEEDLE_D));
            for (int i = 0; i < 3; i++)
            {
                Mesh2(content, "A_Digit_" + "HTO"[i], assets.quad, assets.matDigit, new Vector3(DIG_X[i], ROW_A, Z_FACE), new Vector3(CELL_W, CELL_H, 1f));
                Mesh2(content, "B_Digit_" + "HTO"[i], assets.quad, assets.matDigit, new Vector3(DIG_X[i], ROW_B, Z_FACE), new Vector3(CELL_W, CELL_H, 1f));
            }
            for (int i = 0; i < 3; i++)   // F_Digit_O stays fixed on the material's "0" (frequency is always a multiple of 10)
                Mesh2(content, "F_Digit_" + "HTO"[i], assets.quad, assets.matDigit, new Vector3(FDIG_X[i], ROW_F, Z_FACE), new Vector3(CELL_W, CELL_H, 1f));

            // PhysBone grips: stretch when grabbed (one long bone per grip, see the note in PanelLayout.cs)
            AddGrip(content, "A_Grip", ROW_A, PFX_A, assets.cube, assets.matGold);
            AddGrip(content, "B_Grip", ROW_B, PFX_B, assets.cube, assets.matGold);
            // Touch buttons: contact receivers fed by the avatars' fingertips. Every finger counts: the wearer's (both hands)
            // and other players'. With o.excludeHoldingHand the wearer's holding hand is left out.
            string selfTag = !o.excludeHoldingHand ? "Finger" : (o.hand == PanelHand.Left ? "FingerR" : "FingerL");
            float tz = -o.touchHeight;      // the viewer is at -Z, so "in front of the plate" is negative
            float tr = o.touchRadius;
            AddTouch(content, "A_Minus", new Vector3(MINUS_X, ROW_A, tz), TB_AMINUS, selfTag, tr);
            AddTouch(content, "A_Plus", new Vector3(PLUS_X, ROW_A, tz), TB_APLUS, selfTag, tr);
            AddTouch(content, "B_Minus", new Vector3(MINUS_X, ROW_B, tz), TB_BMINUS, selfTag, tr);
            AddTouch(content, "B_Plus", new Vector3(PLUS_X, ROW_B, tz), TB_BPLUS, selfTag, tr);
            AddTouch(content, "F_Down", new Vector3(BTN_DN_X, ROW_F, tz), TB_DN, selfTag, tr);
            AddTouch(content, "F_Up", new Vector3(BTN_UP_X, ROW_F, tz), TB_UP, selfTag, tr);

            // ------------------------------------------------ animator FX
            var ctrl = PanelController.Build(dir + "/CoyotePanel_FX.controller");

            // ------------------------------------------------ Modular Avatar
            var ma = panel.AddComponent<ModularAvatarMergeAnimator>();
            ma.animator = ctrl;
            ma.layerType = VRCAvatarDescriptor.AnimLayerType.FX;
            ma.deleteAttachedAnimator = false;
            ma.pathMode = MergeAnimatorPathMode.Relative;
            ma.matchAvatarWriteDefaults = true;

            var mp = panel.AddComponent<ModularAvatarParameters>();
            mp.parameters = new List<ParameterConfig>
            {
                // OSC contract with the PC program: local only (OSC is local to your own client), never saved
                Par(P_A, ParameterSyncType.Float, true, 0f),
                Par(P_B, ParameterSyncType.Float, true, 0f),
                Par(P_FREQ, ParameterSyncType.Int, false, 50f),
                Par(P_STOP, ParameterSyncType.Bool, true, 0f),
                // numbers shown on the plate (everyone sees them)
                Par(P_VALA, ParameterSyncType.Int, false, 0f),
                Par(P_VALB, ParameterSyncType.Int, false, 0f),
                // panel state (everyone sees it)
                Par(P_SHOW, ParameterSyncType.Bool, false, 0f),
                Par(P_ANCHOR, ParameterSyncType.Bool, false, 0f),
                // local only
                Par(P_ZERO, ParameterSyncType.Bool, true, 0f),
            };

            // menu: a "Coyote" submenu in the root menu
            var menu = Child(panel, "Coyote");
            menu.AddComponent<ModularAvatarMenuInstaller>();
            var sub = menu.AddComponent<ModularAvatarMenuItem>();
            sub.PortableControl.Type = PortableControlType.SubMenu;
            sub.MenuSource = SubmenuSource.Children;

            var show = Child(menu, "Show panel");
            var showItem = show.AddComponent<ModularAvatarMenuItem>();
            showItem.PortableControl.Type = PortableControlType.Toggle;
            showItem.PortableControl.Parameter = P_SHOW;
            showItem.PortableControl.Value = 1f;
            showItem.isSynced = true; showItem.isSaved = false; showItem.isDefault = false;
            var tog = show.AddComponent<ModularAvatarObjectToggle>();
            var tobj = new ToggledObject();
            tobj.Object = new AvatarObjectReference();
            tobj.Object.referencePath = RelPath(avatar.transform, content.transform);
            tobj.Active = true;
            tog.Objects.Add(tobj);

            MenuToggle(menu, "Lock in world", P_ANCHOR, true);
            MenuButton(menu, "Zero channels", P_ZERO);
            MenuButton(menu, "STOP", P_STOP);

            AssetDatabase.SaveAssets();
            UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(avatar.scene);
            o.Save();
            return "installed on '" + avatar.name + "' | " + frame.note + " | assets in " + dir + " | controller=" + AssetDatabase.GetAssetPath(ctrl);
        }

        // ================================================================ scene helpers
        static void MenuToggle(GameObject menu, string name, string param, bool synced)
        {
            var g = Child(menu, name);
            var it = g.AddComponent<ModularAvatarMenuItem>();
            it.PortableControl.Type = PortableControlType.Toggle;
            it.PortableControl.Parameter = param;
            it.PortableControl.Value = 1f;
            it.isSynced = synced; it.isSaved = false; it.isDefault = false;
        }

        static void MenuButton(GameObject menu, string name, string param)
        {
            var g = Child(menu, name);
            var it = g.AddComponent<ModularAvatarMenuItem>();
            it.PortableControl.Type = PortableControlType.Button;
            it.PortableControl.Parameter = param;
            it.PortableControl.Value = 1f;
            it.isSynced = false; it.isSaved = false; it.isDefault = false;
        }

        static GameObject Child(GameObject parent, string name)
        {
            var g = new GameObject(name);
            g.transform.SetParent(parent.transform, false);
            return g;
        }

        static string RelPath(Transform root, Transform t)
        {
            var s = t.name;
            while (t.parent != null && t.parent != root) { t = t.parent; s = t.name + "/" + s; }
            return s;
        }

        static void NoShadows(Renderer r)
        {
            r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            r.receiveShadows = false;
            r.lightProbeUsage = UnityEngine.Rendering.LightProbeUsage.Off;
            r.reflectionProbeUsage = UnityEngine.Rendering.ReflectionProbeUsage.Off;
            r.motionVectorGenerationMode = MotionVectorGenerationMode.ForceNoMotion;
        }

        static GameObject Mesh2(GameObject parent, string name, Mesh mesh, Material mat, Vector3 pos, Vector3 scale)
        {
            var g = Child(parent, name);
            g.transform.localPosition = pos;
            g.transform.localScale = scale;
            g.AddComponent<MeshFilter>().sharedMesh = mesh;
            var r = g.AddComponent<MeshRenderer>();
            r.sharedMaterial = mat;
            NoShadows(r);
            return g;
        }

        // A slider grip: one long PhysBone bone lying along the bar. Its root is PB_ROOT_DISTANCE to the left of the bar and
        // its tip (carrying the knob) rests PB_REST from the bar's minimum end; grabbing and pulling toward the right
        // stretches it (_Stretch 0-1). Because the bone is long, only the SIDEWAYS part of a pull counts (see PanelLayout.cs).
        static void AddGrip(GameObject parent, string name, float row, string prefix, Mesh knobMesh, Material knobMat)
        {
            var root = Child(parent, name);
            root.transform.localPosition = new Vector3(BAR_X0 + PB_REST - PB_ROOT_DISTANCE, row, Z_PB);
            var tip = Child(root, "Tip");
            tip.transform.localPosition = new Vector3(PB_ROOT_DISTANCE, 0f, 0f);
            Mesh2(tip, "Knob", knobMesh, knobMat, Vector3.zero, new Vector3(KNOB_W, KNOB_H, KNOB_D));
            var pb = root.AddComponent<VRCPhysBone>();
            pb.rootTransform = root.transform;
            pb.integrationType = VRCPhysBoneBase.IntegrationType.Simplified;
            pb.pull = PB_PULL;
            pb.spring = 0f;
            pb.gravity = 0f;
            pb.gravityFalloff = 0f;
            pb.immobileType = VRCPhysBoneBase.ImmobileType.AllMotion;
            pb.immobile = 1f;
            pb.allowCollision = VRCPhysBoneBase.AdvancedBool.False;
            pb.radius = PB_GRIP_RADIUS;
            pb.limitType = VRCPhysBoneBase.LimitType.Angle;   // (almost) no rotation: the knob only slides along the bar axis
            pb.maxAngleX = PB_ANGLE_LIMIT;
            pb.allowGrabbing = VRCPhysBoneBase.AdvancedBool.True;
            var gf = pb.grabFilter; gf.allowSelf = true; gf.allowOthers = true; pb.grabFilter = gf;
            // poseable grips: grab, then pull the trigger/click to LOCK the grip where it is (VRChat "Pose")
            pb.allowPosing = VRCPhysBoneBase.AdvancedBool.True;
            var pf = pb.poseFilter; pf.allowSelf = true; pf.allowOthers = true; pb.poseFilter = pf;
            pb.grabMovement = 1f;
            pb.snapToHand = false;
            pb.maxStretch = PB_MAX_STRETCH;
            pb.maxSquish = 0f;                // a pull toward the root changes nothing
            pb.stretchMotion = 0f;
            pb.isAnimated = false;
            pb.resetWhenDisabled = true;     // hiding/showing the panel resets the simulation
            pb.parameter = prefix;
        }

        // A touch button: two sphere contact receivers on the same spot, both local only (they cost nothing in the
        // avatar's performance rank) and both "Constant" (the bool is on while a fingertip is inside).
        //   Self   : the wearer's own fingers (tag "Finger" = both hands; the holding hand's side is left out when asked to)
        //   Others : any finger ("Finger") of another player
        // They are two receivers, not one, only so that the wearer's tag set can differ from the others'.
        static void AddTouch(GameObject parent, string name, Vector3 pos, string button, string selfTag, float radius)
        {
            var g = Child(parent, name);
            g.transform.localPosition = pos;
            AddReceiver(g, "Self", TouchSelf(button), selfTag, true, false, radius);
            AddReceiver(g, "Others", TouchOthers(button), "Finger", false, true, radius);
        }

        static void AddReceiver(GameObject parent, string name, string parameter, string tag, bool allowSelf, bool allowOthers, float radius)
        {
            var g = Child(parent, name);
            var r = g.AddComponent<VRCContactReceiver>();
            r.rootTransform = g.transform;
            r.shapeType = ContactBase.ShapeType.Sphere;
            r.radius = radius;
            r.position = Vector3.zero;
            r.rotation = Quaternion.identity;
            r.collisionTags = new List<string> { tag };
            r.receiverType = ContactReceiver.ReceiverType.Constant;
            r.parameter = parameter;
            r.allowSelf = allowSelf;
            r.allowOthers = allowOthers;
            r.localOnly = true;
            r.minVelocity = 0f;
        }

        static ParameterConfig Par(string name, ParameterSyncType type, bool localOnly, float def)
        {
            return new ParameterConfig
            {
                nameOrPrefix = name,
                remapTo = "",
                internalParameter = false,
                isPrefix = false,
                syncType = type,
                localOnly = localOnly,
                defaultValue = def,
                saved = false,
                hasExplicitDefaultValue = true,
            };
        }
    }
}
