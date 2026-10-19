// Settings for one install of the Coyote panel. Remembered per machine (EditorPrefs), not per avatar.
using UnityEditor;
using UnityEngine;

namespace CoyotePanel.Editor
{
    public enum PanelHand { Left, Right }

    /// <summary>How the direction of the palm / fingers is found.</summary>
    public enum FrameMode
    {
        /// <summary>From the skeleton: forearm direction + index/little finger bones. Works on most humanoid rigs.</summary>
        Auto,
        /// <summary>From fixed axes of the hand bone. Rig-specific: you tell it which local axis points out of the palm and which toward the fingers.</summary>
        BoneAxes,
    }

    public enum BoneAxis { PlusX, MinusX, PlusY, MinusY, PlusZ, MinusZ }

    [System.Serializable]
    public class CoyotePanelOptions
    {
        // The two offsets and the facing below were tuned by eye on ONE avatar (a small avatar with a wide hoodie sleeve).
        // They are starting points, not universal values: adjust them for your avatar.
        public PanelHand hand = PanelHand.Left;
        /// <summary>Panel center, from the hand bone toward the fingers (meters, before Scale).</summary>
        public float alongMeters = 0.24f;
        /// <summary>Panel center, out of the palm (meters, before Scale). Wide sleeves need more.</summary>
        public float outMeters = 0.08f;
        /// <summary>Extra rotation about the panel's own viewing axis (degrees).</summary>
        public float rollDegrees = 0f;
        /// <summary>Uniform size multiplier of the whole panel and of the two offsets.</summary>
        public float scale = 1f;
        /// <summary>Put the plate on the back of the hand instead of the palm side.</summary>
        public bool flipFacing = false;

        /// <summary>Radius of the sensor sphere of each touch button (meters, before Scale). Smaller = the fingertip has to be closer.</summary>
        public float touchRadius = 0.005f;
        /// <summary>How far in front of the plate surface the center of that sphere sits (meters, before Scale; negative = behind it).
        /// A fingertip counts as pressing when it gets within about touchRadius + touchHeight of the plate surface.</summary>
        public float touchHeight = 0.001f;
        /// <summary>Leave the fingers of the hand that holds the panel out of the touch buttons. Off by default, so both of the
        /// wearer's hands can press them; turn it on if that hand sets buttons off by accident.</summary>
        public bool excludeHoldingHand = false;

        public FrameMode frameMode = FrameMode.Auto;
        /// <summary>BoneAxes mode only: local axis of the hand bone that points out of the palm.</summary>
        public BoneAxis palmAxis = BoneAxis.MinusZ;
        /// <summary>BoneAxes mode only: local axis of the hand bone that points toward the fingers.</summary>
        public BoneAxis fingersAxis = BoneAxis.PlusY;

        /// <summary>Generated meshes, materials and the animator controller go to "&lt;outputFolder&gt;/&lt;avatar name&gt;/".</summary>
        public string outputFolder = "Assets/CoyotePanel/Generated";

        const string PrefsKey = "CoyotePanel.Options.v1";

        public static CoyotePanelOptions Load()
        {
            var o = new CoyotePanelOptions();
            try
            {
                var json = EditorPrefs.GetString(PrefsKey, "");
                if (!string.IsNullOrEmpty(json)) JsonUtility.FromJsonOverwrite(json, o);
            }
            catch (System.Exception) { /* keep defaults */ }
            return o.Sanitized();
        }

        public void Save()
        {
            try { EditorPrefs.SetString(PrefsKey, JsonUtility.ToJson(Sanitized())); }
            catch (System.Exception) { }
        }

        public CoyotePanelOptions Sanitized()
        {
            scale = Mathf.Clamp(scale, 0.25f, 4f);
            alongMeters = Mathf.Clamp(alongMeters, -1f, 1f);
            outMeters = Mathf.Clamp(outMeters, -1f, 1f);
            touchRadius = Mathf.Clamp(touchRadius, 0.002f, 0.03f);
            touchHeight = Mathf.Clamp(touchHeight, -0.03f, 0.03f);
            if (string.IsNullOrWhiteSpace(outputFolder) || !outputFolder.Replace('\\', '/').StartsWith("Assets"))
                outputFolder = "Assets/CoyotePanel/Generated";
            outputFolder = outputFolder.Replace('\\', '/').TrimEnd('/');
            return this;
        }

        public static Vector3 AxisVector(BoneAxis a)
        {
            switch (a)
            {
                case BoneAxis.PlusX: return Vector3.right;
                case BoneAxis.MinusX: return Vector3.left;
                case BoneAxis.PlusY: return Vector3.up;
                case BoneAxis.MinusY: return Vector3.down;
                case BoneAxis.PlusZ: return Vector3.forward;
                default: return Vector3.back;
            }
        }
    }
}
