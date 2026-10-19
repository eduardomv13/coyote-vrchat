// Menu items and the options window:  Tools > Coyote Panel > ...
using UnityEditor;
using UnityEngine;

namespace CoyotePanel.Editor
{
    public class CoyotePanelWindow : EditorWindow
    {
        const string MenuRoot = "Tools/Coyote Panel/";

        GameObject avatar;
        CoyotePanelOptions options;
        Vector2 scroll;
        string lastMessage = "";
        MessageType lastType = MessageType.None;

        [MenuItem(MenuRoot + "Install on selected avatar", false, 10)]
        static void InstallOnSelected()
        {
            var avatar = CoyotePanelInstaller.FindAvatarRoot(Selection.activeGameObject);
            var o = CoyotePanelOptions.Load();
            var problem = CoyotePanelInstaller.Validate(avatar, o);
            if (problem != null) { EditorUtility.DisplayDialog("Coyote Panel", problem, "OK"); return; }
            try { Debug.Log("[CoyotePanel] " + CoyotePanelInstaller.Install(avatar, o)); }
            catch (System.Exception e) { Debug.LogError(e); }
        }

        [MenuItem(MenuRoot + "Install on selected avatar", true)]
        static bool InstallOnSelectedValidate() { return CoyotePanelInstaller.FindAvatarRoot(Selection.activeGameObject) != null; }

        [MenuItem(MenuRoot + "Remove from selected avatar", false, 11)]
        static void RemoveFromSelected()
        {
            var avatar = CoyotePanelInstaller.FindAvatarRoot(Selection.activeGameObject);
            var o = CoyotePanelOptions.Load();
            CoyotePanelInstaller.Remove(avatar, o, false);
            Debug.Log("[CoyotePanel] removed the panel object from '" + avatar.name + "' (generated assets kept)");
        }

        [MenuItem(MenuRoot + "Remove from selected avatar", true)]
        static bool RemoveFromSelectedValidate()
        {
            return CoyotePanelInstaller.FindPanel(CoyotePanelInstaller.FindAvatarRoot(Selection.activeGameObject)) != null;
        }

        [MenuItem(MenuRoot + "Options window...", false, 30)]
        static void Open()
        {
            var w = GetWindow<CoyotePanelWindow>("Coyote Panel");
            w.minSize = new Vector2(380, 520);
            w.Show();
        }

        void OnEnable()
        {
            options = CoyotePanelOptions.Load();
            OnSelectionChange();
        }

        void OnSelectionChange()
        {
            var a = CoyotePanelInstaller.FindAvatarRoot(Selection.activeGameObject);
            if (a != null) avatar = a;
            Repaint();
        }

        void OnGUI()
        {
            scroll = EditorGUILayout.BeginScrollView(scroll);
            EditorGUILayout.Space(4);
            EditorGUILayout.LabelField("DG-LAB Coyote panel", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
                "Adds a hand-held control panel for a DG-LAB Coyote 3.0 to a VRChat avatar, through Modular Avatar. " +
                "It sends VRChat OSC parameters to the coyote-vrchat PC program.\n\n" +
                "SAFETY: anyone who can grab the panel can raise the intensity of whoever wears the electrodes. " +
                "Read the safety section of the README before you upload an avatar with this panel.",
                MessageType.Warning);

            EditorGUILayout.Space(6);
            avatar = (GameObject)EditorGUILayout.ObjectField("Avatar", avatar, typeof(GameObject), true);
            var panel = CoyotePanelInstaller.FindPanel(avatar);
            EditorGUILayout.LabelField("Status", avatar == null ? "select an avatar in the Hierarchy" : (panel != null ? "panel installed" : "no panel yet"));

            EditorGUILayout.Space(8);
            EditorGUILayout.LabelField("Where the panel is held", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
                "The defaults were tuned by eye on ONE small avatar with a wide sleeve. Expect to adjust them: install, then check the " +
                "placement (see 'Preview' below) and change these numbers.", MessageType.Info);
            options.hand = (PanelHand)EditorGUILayout.EnumPopup("Hand", options.hand);
            options.alongMeters = EditorGUILayout.Slider(new GUIContent("Toward fingers (m)", "Distance from the hand bone to the panel center, along the fingers."), options.alongMeters, -0.5f, 0.8f);
            options.outMeters = EditorGUILayout.Slider(new GUIContent("Out of palm (m)", "Distance from the hand bone to the panel center, out of the palm. Wide sleeves need more."), options.outMeters, -0.3f, 0.5f);
            options.rollDegrees = EditorGUILayout.Slider(new GUIContent("Roll (deg)", "Rotates the panel about its own viewing axis."), options.rollDegrees, -180f, 180f);
            options.scale = EditorGUILayout.Slider(new GUIContent("Scale", "Size of the whole panel; the two distances above scale with it."), options.scale, 0.25f, 4f);
            options.flipFacing = EditorGUILayout.Toggle(new GUIContent("Flip facing", "Put the plate on the back of the hand instead of the palm side."), options.flipFacing);

            EditorGUILayout.Space(8);
            EditorGUILayout.LabelField("Touch buttons", EditorStyles.boldLabel);
            EditorGUILayout.HelpBox(
                "A fingertip presses a button when it gets within about (radius + height) of the plate surface. If the buttons fire " +
                "from too far away, lower these; if you have to push the finger far into the plate, raise them. " +
                "Rebuild the panel after changing them.", MessageType.Info);
            options.touchRadius = EditorGUILayout.Slider(new GUIContent("Touch radius (m)", "Radius of the sensor sphere of each button."), options.touchRadius, 0.002f, 0.03f);
            options.touchHeight = EditorGUILayout.Slider(new GUIContent("Touch height (m)", "How far in front of the plate the sensor sphere sits (negative = behind the surface)."), options.touchHeight, -0.01f, 0.03f);
            options.excludeHoldingHand = EditorGUILayout.Toggle(new GUIContent("Ignore the holding hand", "Off: the fingers of both of your hands press the buttons. On: the hand that holds the panel is left out, in case it sets buttons off by accident."), options.excludeHoldingHand);

            EditorGUILayout.Space(4);
            options.frameMode = (FrameMode)EditorGUILayout.EnumPopup(new GUIContent("Hand direction", "Auto reads the skeleton. Hand-bone axes uses fixed axes of the hand bone (rig-specific)."), options.frameMode);
            if (options.frameMode == FrameMode.BoneAxes)
            {
                options.palmAxis = (BoneAxis)EditorGUILayout.EnumPopup("Palm normal = bone axis", options.palmAxis);
                options.fingersAxis = (BoneAxis)EditorGUILayout.EnumPopup("Fingers = bone axis", options.fingersAxis);
            }

            EditorGUILayout.Space(4);
            options.outputFolder = EditorGUILayout.TextField(new GUIContent("Output folder", "Generated meshes, materials and the animator controller are written to <folder>/<avatar name>/."), options.outputFolder);

            EditorGUILayout.Space(8);
            string problem = CoyotePanelInstaller.Validate(avatar, options);
            using (new EditorGUI.DisabledScope(problem != null))
            {
                if (GUILayout.Button(panel != null ? "Rebuild panel on this avatar" : "Install panel on this avatar", GUILayout.Height(28)))
                {
                    try { lastMessage = CoyotePanelInstaller.Install(avatar, options); lastType = MessageType.Info; Debug.Log("[CoyotePanel] " + lastMessage); }
                    catch (System.Exception e) { lastMessage = e.Message; lastType = MessageType.Error; Debug.LogError(e); }
                    panel = CoyotePanelInstaller.FindPanel(avatar);
                }
            }
            if (problem != null) EditorGUILayout.HelpBox(problem, MessageType.None);

            if (panel != null)
            {
                var content = panel.Find("Container/Content");
                EditorGUILayout.Space(6);
                EditorGUILayout.LabelField("Preview", EditorStyles.boldLabel);
                if (content != null)
                {
                    bool shown = content.gameObject.activeSelf;
                    if (GUILayout.Button(shown ? "Hide the panel in the Scene view" : "Show the panel in the Scene view"))
                    {
                        Undo.RecordObject(content.gameObject, "Toggle Coyote panel preview");
                        content.gameObject.SetActive(!shown);
                    }
                    if (shown)
                        EditorGUILayout.HelpBox("The panel is switched ON in the scene. Switch it off again before you upload: in the game it must start hidden and be shown by the 'Show panel' menu toggle.", MessageType.Warning);
                }
                using (new EditorGUILayout.HorizontalScope())
                {
                    if (GUILayout.Button("Remove panel (keep generated assets)"))
                    {
                        CoyotePanelInstaller.Remove(avatar, options, false);
                        lastMessage = "panel removed"; lastType = MessageType.Info;
                    }
                    if (GUILayout.Button("Remove panel + delete its assets"))
                    {
                        if (EditorUtility.DisplayDialog("Coyote Panel", "Delete the panel and the folder " + CoyotePanelInstaller.OutputDirFor(avatar, options) + "?", "Delete", "Cancel"))
                        {
                            CoyotePanelInstaller.Remove(avatar, options, true);
                            lastMessage = "panel and assets removed"; lastType = MessageType.Info;
                        }
                    }
                }
            }

            if (!string.IsNullOrEmpty(lastMessage)) EditorGUILayout.HelpBox(lastMessage, lastType);
            EditorGUILayout.EndScrollView();
            if (GUI.changed) options.Save();
        }
    }
}
