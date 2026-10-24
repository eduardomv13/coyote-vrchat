# Coyote panel for VRChat avatars

A hand-held control panel for a **DG-LAB Coyote 3.0**, built into a VRChat avatar. Two intensity sliders (A and B), −/+
buttons, and a frequency control. You grab the gold grips (PhysBones) and drag them sideways, you press the buttons by
touching them with a fingertip (contacts), the numbers show on the plate, and the values
reach the [coyote-vrchat PC program](../README.md) through VRChat OSC.

![The panel, rendered in the Unity editor](images/panel.png)

*A render from the Unity editor with the numbers and grips placed by hand to illustrate the layout. It is not a VRChat
screenshot: outside the game the animator does not run, so the plate shows zeros until you play.*

You install it with one menu click on the avatar you select (**Tools > Coyote Panel > Install on selected avatar**).
It is installed with [Modular Avatar](https://modular-avatar.nadena.dev/), adds one child object to your avatar and
changes nothing else on it.

> **This is hobby software, provided as is, with no warranty. It can make a real device deliver real stimulation to
> whoever wears it. Read [Safety](#safety-read-this-first) before you upload an avatar that has this panel.**
> Not affiliated with DG-LAB, VRChat or the Modular Avatar project.

**PC (Windows) only. Not tested on Quest/Android.** What has and has not been tested is listed
[at the end](#what-has-been-tested), and it is shorter than you might hope.

---

## Safety (read this first)

Everything in the safety section of the [main README](../README.md) applies: adults only,
informed consent, never put electrodes on or across the chest, head, neck or throat, start at zero and go slowly.
On top of that, this panel adds risks of its own:

- **Anyone who can grab or touch the panel can change the intensity of whoever wears the electrodes.** The grips accept
  grabs, and the buttons accept fingertips, from the wearer *and from other players*. "Lock in world" leaves the panel
  standing in the world so other people can walk up to it. Only do that with people you completely trust, and not in
  public instances.
- **Letting go of a grip sets its channel back to 0.** The power only stays while the grip is held, or while it is
  *posed* (grab it and pull the trigger/click to lock it in place; that keeps the value until you release the pose).
  The buttons set a value that stays until you change it.
- **A touch button is one step per touch, never a repeat.** A fingertip resting on a button must not keep raising the
  power, so to go up by 30 you touch three times. The fingers of both of the wearer's hands count, and so do other
  players'. The fingertip has to be practically on the button (about 6 mm from the plate, see
  [how the touch buttons work](#how-the-touch-buttons-work)). If the hand that holds the panel sets a button off by
  accident, turn on *Ignore the holding hand* in the options window and rebuild.
- **The panel's numbers are fractions of the program's ceiling, not device units.** The panel sends `CoyoteA` =
  value ÷ 200. The PC program turns that into a fraction of **its own intensity ceiling** (200 by default). Panel value
  200 always means "the ceiling", panel value 100 means "half of it". If you lower the ceiling in the program to 80,
  panel 200 produces 80. **Set the ceiling in the program to the highest intensity you would accept from a stranger.**
- Keep the program's **rise speed limit** on, and a **STOP** within reach: the menu button (`CoyoteStop`), the program's
  STOP ALL button, and the device's own physical controls.
- The avatar never saves an intensity: all the panel's parameters have default 0 (frequency 50) and "Saved" off, so
  loading the avatar starts from zero. The program also starts every channel at zero and ramps increases.
- The numbers on the plate and the "Show panel" / "Lock in world" states are **synced**: everyone in the instance can see
  the panel and read its values.
- While the panel is installed, it writes `CoyoteA` and `CoyoteB` on every frame. **Do not also drive those two
  parameters from a radial puppet** (as in [AVATAR_SETUP.md](../docs/AVATAR_SETUP.md)): the panel overwrites them.
- Whether another player can actually grab or touch the panel also depends on VRChat's own PhysBone/contact rules and
  their settings (for example the contact and interaction safety settings). **That has not been tested** (see below), so
  do not assume that it is blocked either.

---

## What you get

| Control | What it does |
|---|---|
| **A** / **B** gold grips | Grab and drag **sideways** along the bar: the value follows (0 at the left end, 200 at the right end). **Let go and the value drops to 0** while the grip springs back. Pulling forward, backward, up or down, or to the left of the rest position, does not raise it (see [how the sliders work](#how-the-sliders-work)). Grabbing without pulling does not change it. A grip can also be *posed* (grab, then pull the trigger/click) to lock it where it is; a posed grip keeps its value until the pose is released. |
| **−** / **+** buttons (per channel) | Touch with a fingertip = ±10, limited to 0…200. One step per touch; a finger left on the button does not repeat. |
| **▼** / **▲** (frequency) | Touch = ∓/±10 Hz, limited to 10…100 Hz. Starts at 50 Hz. One step per touch. |
| Plate numbers | Channel A, channel B and frequency, always readable (unlit). |
| Menu **Coyote > Show panel** | Shows/hides the panel in your hand. Showing it also puts it back in your hand if it was locked in the world. |
| Menu **Coyote > Lock in world** | The panel stays where it is (VRChat's constraint "Freeze To World"), so you can leave it standing and use both hands, or let others use it. |
| Menu **Coyote > Zero channels** | Sets A and B to 0 on the panel. |
| Menu **Coyote > STOP** | Sets `CoyoteStop`: the program's latched emergency stop (only the program window can re-enable it), and also zeroes the panel. |

The panel is 50 cm × 34 cm at Scale 1, and it is **off by default**: the "Show panel" toggle turns it on.

## Requirements

- Unity **2022.3** (the version VRChat requires) and the **VRChat Avatars SDK 3.10.2 or newer**.
- **[Modular Avatar](https://modular-avatar.nadena.dev/) 1.16.2 or newer** (installed through the VRChat Creator
  Companion).
- An avatar with a **Humanoid** rig, including the lower arm and the hand of the side you choose. Finger bones are
  recommended: they are used to work out which way the palm faces.
- The **[coyote-vrchat](../README.md) PC program**, a DG-LAB Coyote 3.0 and OSC enabled in VRChat.
- Optional: lilToon. If the project has it, the panel's black body and gold reliefs use it; otherwise they use Unity's
  built-in Standard shader.

The versions above are the ones it was developed and tested with (Unity 2022.3.22f1, SDK 3.10.2, Modular Avatar 1.16.2).
Older or newer ones might work; nobody has checked.

## Install

The package is in [`unity/io.github.eduardomv13.coyote-panel`](io.github.eduardomv13.coyote-panel). It is a standard
Unity package (it ships `.meta` files and an `.asmdef`), and it asks for the SDK and Modular Avatar in its `package.json`.

**Simplest: copy the folder.** Download this repository (**Code > Download ZIP**) or clone it, and copy
`unity/io.github.eduardomv13.coyote-panel` into the **`Packages`** folder of your avatar project (next to
`manifest.json`, `vpm-manifest.json`). Go back to Unity and let it compile. A **Tools > Coyote Panel** menu appears.
This is the way that has been tested, with the folder linked into `Packages/` (Unity reports it as an *embedded* package).

Two other ways *should* work, but **have not been tested**:

- *Unity Package Manager > + > Add package from git URL*:
  `https://github.com/eduardomv13/coyote-vrchat.git?path=/unity/io.github.eduardomv13.coyote-panel`
  (the package never writes inside its own folder, so a read-only install should be fine).
- *VRChat Creator Companion > Settings > Packages > User Packages > Add* and pick this repository's `unity` folder, then
  add "DG-LAB Coyote Panel for VRChat Avatars" to your project from its *Manage Project* page.

There is deliberately no `.unitypackage` and no VPM listing: a plain package folder is the least to maintain, it can
be read and diffed in git, and a `.unitypackage` would have to be rebuilt on every change. A VPM listing (so that the
Creator Companion could install it with a click) can be added later.

## Use it

1. In the Unity scene, **select your avatar** (the object with the *VRC Avatar Descriptor*; selecting any child also
   works).
2. **Tools > Coyote Panel > Install on selected avatar.** The console says what it did. A `Coyote Panel` child object
   appears on the avatar.
3. Check where the panel sits. Open **Tools > Coyote Panel > Options window...**, press *Show the panel in the Scene
   view*, and adjust (see [Where the panel is held](#where-the-panel-is-held)). Press *Rebuild panel on this avatar*
   after changing an option. **Switch the preview off again before you upload** (the window warns you): in the game
   the panel has to start hidden.
4. Upload or *Build & Test* the avatar as usual. Nothing else needs to be set up.
5. On the PC: start the [program](../README.md), connect the Coyote, and in VRChat turn on **Options > OSC > Enabled**.
   After the first upload of an avatar with new parameters, use **Options > OSC > Reset Config** and select the avatar
   again, as explained in [docs/AVATAR_SETUP.md](../docs/AVATAR_SETUP.md#3-turn-on-osc-in-vrchat).
6. In the game: radial menu > **Coyote > Show panel**. Start with the program's ceiling low and the electrodes **off your
   body** (or the program's `--simulate` mode), move a slider a little, and check that the program follows.

Running the install again **replaces** the panel (it deletes the old `Coyote Panel` child and rebuilds). **Tools > Coyote
Panel > Remove from selected avatar** takes it off and keeps the generated assets (the options window can delete them too).
The scene changes of an install are registered with Unity's Undo; the generated assets are not.

What the install adds to your avatar, all inside the `Coyote Panel` child object:

- Modular Avatar *Merge Animator* (the 14-layer FX controller), *Parameters*, *Menu Installer* + menu items, *Object
  Toggle* and *Bone Proxy* components;
- a `VRCParentConstraint` that follows the hand (and "Freeze To World" for the lock);
- the panel itself: 2 PhysBones (the slider grips), 12 contact receivers (two per touch button), 14 renderers, 5 materials;
- generated assets in `Assets/CoyotePanel/Generated/<avatar name>/` (meshes, materials and the controller; **one folder per
  avatar**, so several avatars in one project do not overwrite each other).

If your avatar's root menu is already full (VRChat allows 8 controls), move the `Coyote` submenu with the *Install
Target* field of the Menu Installer on the `Coyote Panel/Coyote` object, or with your usual menu tool.

## Where the panel is held

The panel is attached to the hand bone and sits a little past it, on the palm side, so that you look at it with your
palm facing you. Three things decide where it ends up:

1. **Which way the palm faces and the fingers point.** *Hand direction = Auto* (the default) works this out from the
   skeleton: the forearm direction, and the index and little finger bones (little finger → index finger = toward the
   thumb, which is the panel's "up"). If the rig has no finger bones it assumes a T-pose with palms down and tells you
   in the console. If Auto gets it wrong on your rig, *Hand-bone axes* lets you say which local axis of the hand bone
   points out of the palm and which toward the fingers.
2. **The two distances**: *Toward fingers* (default 0.24 m) and *Out of palm* (default 0.08 m), measured from the hand
   bone to the center of the panel.
3. **Roll**, **Scale**, **Hand** (left/right) and **Flip facing** (plate on the back of the hand).

**These defaults were tuned by eye on one avatar** (a small avatar with a wide hoodie sleeve; 0.08 m clears that
sleeve). They are starting points, not universal values: expect to adjust them for yours. Scale multiplies the panel
*and* the two distances.

On that original avatar, *Auto* lands within 5.4° of the placement that was tuned by hand (palm direction; 2.6° for the
finger direction). *Hand-bone axes* with palm = −Z and fingers = +Y reproduces the hand-tuned placement exactly (it is
the geometry that avatar's hand bone happens to have; other rigs use other axes).

## How it talks to the PC program

The panel works through four avatar parameters, which are the contract with the PC program. If you rename them in the
program's OSC panel, rename them in the `Names` class of `Editor/PanelLayout.cs` too and rebuild the panel:

| Parameter | Type | Written by the panel as | In the program |
|---|---|---|---|
| `CoyoteA` | float | `0…1` = panel value ÷ 200, updated every frame | channel A target, as a fraction of the program's ceiling |
| `CoyoteB` | float | same, channel B | channel B |
| `CoyoteFreq` | **int**, Hz | `10…100` in steps of 10, default 50 | frequency of both channels (the program ignores 0 and non-integers) |
| `CoyoteStop` | bool | `true` while you press STOP | the latched emergency stop |

VRChat itself sends these over OSC (port 9001 on your PC) once OSC is enabled; the panel does not open any network
connection. `CoyoteA`, `CoyoteB` and `CoyoteStop` are *local-only* (OSC output is local to your own client).

### Parameter budget

The panel needs 9 avatar parameters and adds **26 bits** of synced parameter memory (VRChat's limit is 256 bits per
avatar):

| Parameter | Type | Synced | Bits |
|---|---|---|---|
| `CoyoteFreq` | int | yes | 8 |
| `CoyotePad/ValA`, `CoyotePad/ValB` (the numbers on the plate) | int | yes | 8 + 8 |
| `CoyotePad/Show`, `CoyotePad/Anchor` | bool | yes | 1 + 1 |
| `CoyoteA`, `CoyoteB`, `CoyoteStop`, `CoyotePad/Zero` | float / bool | no (local only) | 0 |

The PhysBone and contact parameters (`CoyotePad/PbA_Stretch`, `…_IsGrabbed`, `…_IsPosed`, `CoyotePad/AMinus_TouchSelf`
and so on) are not part of the avatar's expression parameters, so they are not synced and do not count. Measured in a built test copy: the author's avatar totals **184 / 256**
bits with the panel, and a bare sample rig **50 / 256** (26 of them from the panel).

### The FX controller (14 layers, 40 states)

All layers have Write Defaults on and are merged by Modular Avatar (*Match Avatar Write Defaults* is on, so it
converts them if your avatar uses Write Defaults off).

| Layer | Job |
|---|---|
| `CoyotePad_Mirror` | Copies the synced numbers to local floats for the display, and writes `CoyoteA = ValA/200`, `CoyoteB = ValB/200`. Loops every frame. |
| `CoyotePad_TrackA`, `_TrackB` | While a grip is grabbed or posed, turns its PhysBone stretch into the value; when it is neither, sets the value to 0. |
| `CoyotePad_StepA`, `_StepB` | −/+ touch buttons: ±10 per touch, no repeat, a press lasts at least 0.1 s (contact chatter adds no steps). |
| `CoyotePad_Freq` | ▼/▲ touch buttons: ±10 Hz per touch, 10…100. |
| `CoyotePad_Clamp` | Safety clamp at 200. |
| `CoyotePad_Zero` | "Zero channels" and STOP set A and B to 0. |
| `CoyotePad_ShowReset` | "Show panel" clears the world lock. |
| `CoyotePad_Anchor` | "Lock in world": animates `FreezeToWorld` on the constraint. |
| `CoyotePad_PressA`, `_PressB`, `_PressF` | The button "click" (blendshapes on the plate mesh). |
| `CoyotePad_Display` | Direct blend trees that move the digits (texture offset) and the value markers. |

Two VRChat quirks the controller is built around, so you do not trip on them if you edit it: animating a vector
property (`material._MainTex_ST`, `m_LocalPosition`) needs **all** its components or the missing ones become 0, and a
transition with **no condition and no exit time** is stripped by the avatar build (the Mirror layer uses exit time 0
and duration 0 to loop).

Performance cost, as built: 2 PhysBone components (4 bone transforms), 12 local-only contact receivers (they do not
count toward the avatar's contact rank), 14 renderers with 5 materials, about 5 MB of
texture memory (two uncompressed textures, no mipmaps, so the thin digits stay sharp), and the controller's 14 layers.

## What has been tested

**Tested by the author, in VRChat (PC, the author's own avatar, 2026-10-16):** the panel shown in the hand;
grabbing a grip and dragging it changes the value; that value reaches the PC program through OSC (the
slider path: `CoyoteA`/`CoyoteB` = value ÷ 200). The program side has also been tested with a real Coyote 3.0 (see the
main README).

**Reported by the author for 0.2.0 (VRChat, PC, 2026-10-18):** it worked, apart from two problems: the touch buttons
fired from too far away, and only one hand's fingers pressed them (0.2.0 left out the hand that holds the panel on
purpose). The fact that one hand's fingers did press them also shows that an avatar's own fingertip senders are detected
by its own receivers. Those two problems are what 0.2.1 changes, and 0.2.1 itself has not been tried yet.

**Checked without VRChat (this is what the version in this repository was verified with):**

- The controller built by this package is identical to the one built by the original, single-avatar builder (0
  differences in 14 layers, 40 states, 23 parameters, all transitions, drivers and blend trees), and so are the
  hierarchy, the meshes and the hand placement (with *Hand-bone axes*).
- An offline simulator ([`Tools~/simulate_controller.py`](io.github.eduardomv13.coyote-panel/Tools~/simulate_controller.py))
  replays the controller and passes **55 checks** (dragging, letting go, posing, the dead zone, touching −/+ and the arrows, frequency limits, zero/stop, the lock, digits
  0…200, `CoyoteA = value/200` after load). A deliberately broken controller (a Mirror transition with no exit time, the
  bug that once stopped the slider from reaching the program) fails 11 of them. It tests the *logic*, with VRChat's
  animator semantics as we understand them; it is not VRChat.
- A VRCFury *Build an Editor Test Copy* (which runs the Modular Avatar/NDMF build) of the author's avatar and of a bare
  sample rig: 858 animation bindings, 0 unresolved, all vector components present, the Mirror layer's transitions
  survive the build, 14 layers, the parameter counts above, the menu items in place.
- A fresh, never-touched avatar (the VRChat SDK's "Robot Avatar" sample rig, in a scratch scene that was not saved):
  installed with the default options, left and right hand, flip, roll and scale, then removed, and the placement looked
  at in the editor.
- The tests in this repository (`tests/test_unity_package.py`) check the package metadata, that every asset has a
  `.meta` file, that the layout numbers in the C# and in the texture script agree, and that the simulator passes on the
  example export (`Tools~/ctrl.example.json`).

**Not tested (so treat all of this as unknown):**

- **Other players** grabbing the panel or touching its buttons, and the lock in the world for other players: who can grab, whether a player who
  joins after the panel was locked sees it in the right place, and what the synced values look like to them. This is
  the point of the "Lock in world" feature and it has not been tried.
- **Which input you use.** The author did not test desktop mode and VR hands/controllers separately, so treat the one you
  use as unconfirmed until you try it.
- Anything in VRChat on **any avatar other than the author's**, **the right hand** in the game, and avatars with **Write
  Defaults off** (the build converts the states, which was checked in the editor, not in the game).
- **What changed in 0.2.1:** the smaller touch sensor (5 mm radius, 1 mm in front of the plate: about 6 mm of reach; that
  suits finger colliders of 6 to 7 mm like the author's, and other avatars may need other numbers), and both of the
  wearer's hands pressing the buttons (including the one that holds the panel, which can set a button off by accident).
- Fingertip senders on **avatars other than the author's**. The author's avatar uses VRChat's automatic finger colliders,
  and the VRChat documentation says every humanoid avatar gets them; that is all this package relies on.
- In the game, separately: **Lock in world** and posing a grip.
- **Quest/Android.** The panel uses PhysBones, a constraint and built-in unlit shaders that were never checked for Quest.
  Upload PC only, or remove the panel from the Quest variant.
- Other **Unity, SDK or Modular Avatar versions**, the two other install methods above, and the Standard-shader fallback
  (when lilToon is not in the project).
- Whether the hand placement suits other avatars: the numbers were tuned on one. Check them in the Scene view.

## How the sliders work

A grip is one PhysBone bone lying along the bar, and VRChat's `_Stretch` parameter says how far that bone is stretched.
VRChat stretches a bone according to the **distance** between its root and your hand, so with a short bone *any* pull
away from rest (forward, up, down, to the other side) would count as "more". To make only the sideways part count, each
bone is **1.5 m long**: its root sits 1.5 m to the left of the bar, and only its tip (with the gold knob) is near the
panel. Over such a long bone the distance is almost only the sideways distance. A forward pull of 10 cm adds about 3
mm (under 2 % of the bar), a pull of 20 cm adds about 13 mm, and a pull toward the root is ignored (Max Squish is 0).
A small dead zone (3 % of the travel) hides what is left, and the bone is only allowed to rotate 0.3°, which should keep the knob within about 8 mm of the bar.

Side effects you should know about:

- The bone is invisible and **1.5 m long**, so the grip can be grabbed anywhere along a line that runs 1.5 m from the
  left end of each bar (past the panel's left edge, as seen from the front). Whether grabbing it away from the knob
  moves the knob the way you would expect has not been tried; it is an odd, invisible handle. The length is `PB_ROOT_DISTANCE` in
  `Editor/PanelLayout.cs` (shorter = a shorter line but more leakage from forward pulls; longer = the reverse).
- A pull toward the root and a forward pull never move the knob much, but a big forward pull (30 cm or more) can still
  add a few percent. This is a physical approximation, not a guarantee.
- Letting go of the grip makes the knob spring back by itself (the PhysBone's `Pull`), and the value goes to 0 at the same
  moment, so the marker on the plate does not wait for the knob.

## How the touch buttons work

Each button has two small sphere **contact receivers** on the plate, one for your own fingers and one for other players'.
VRChat gives every humanoid avatar fingertip contact senders (tag `Finger`, from the standard finger colliders in the
Avatar Descriptor), so the buttons need nothing from whoever touches them. A button counts as pressed while a fingertip
overlaps its sphere, which means while the fingertip is within about **radius + height** of the plate surface. The
defaults are a radius of 5 mm and a height of 1 mm (about 6 mm of reach), and a finger still counts up to about 1 cm
from the center of a button when it touches the plate (that figure is for finger colliders of 6 to 7 mm, which is what
the author's avatar has).

- The right numbers depend on the avatar: the sensor looks at the finger *collider*, not at the skin. If your avatar's
  finger colliders are thick, buttons fire from a little too far: lower the radius, or set a negative height to push the
  sensor behind the plate surface. If you have to push the finger far into the plate, raise them. Both are in the
  options window (*Touch buttons*); rebuild the panel after changing them.
- The receivers are **local only**: they cost nothing in the avatar's performance rank, and it also means that only the
  wearer sees a button sink when it is pressed (everybody sees the number change, because that value is synced).
- A press lasts at least 0.1 s, so contact flicker at the edge of the sphere does not add extra steps.

## Troubleshooting

| Symptom | What to do |
|---|---|
| *Tools > Coyote Panel* is missing | The package did not compile: look for red errors in the console. Check you have the SDK and Modular Avatar at the versions above. |
| "needs a Humanoid rig" / "no hand bone" | Set the avatar's rig to Humanoid and map the hand and lower-arm bones. |
| The panel is in the wrong place or upside down | Use the options window: Hand, distances, Roll, Flip facing, or *Hand-bone axes*. Rebuild, and check in the Scene view. |
| A touch button does nothing | The finger needs a contact sender with the tag `Finger`. VRChat adds them to humanoid avatars unless the avatar defines its own, so check that your avatar and the other player's are humanoid. If you have to push the finger far into the plate, raise *Touch radius* / *Touch height* in the options window and rebuild. Other players' fingers are also subject to VRChat's own safety/interaction settings (theirs and yours) |
| A touch button fires from too far away, or by itself | Lower *Touch radius* / *Touch height* in the options window and rebuild (a finger registers within about radius + height of the plate; the defaults, 5 mm + 1 mm, suit finger colliders of 6 to 7 mm). If it is the hand that holds the panel that sets it off, turn on *Ignore the holding hand*. Props or other avatars' hands near the panel can also trigger it; move the panel (*Out of palm* / *Toward fingers*) |
| The panel is always visible in the game | You left the preview on. Turn off `Coyote Panel/Container/Content` (the options window has a button) and upload again. |
| In the game the panel moves but nothing reaches the program | OSC enabled? **Options > OSC > Reset Config**, then select the avatar again. Is the program running and showing "OSC: receiving"? See [docs/AVATAR_SETUP.md](../docs/AVATAR_SETUP.md). |
| `CoyoteA`/`CoyoteB` jump back to 0 or flicker | Something else also writes them (for example a radial puppet). Remove it: the panel owns those two parameters. |
| "Parameter memory exceeded" on upload | The panel adds 26 bits. Free some elsewhere, or remove the panel. |
| The Coyote submenu is not in the radial menu | The root menu is probably full (8 controls). Move the `Coyote` submenu (Install Target on its Menu Installer). |
| The digits look blurry | The two textures were re-imported with other settings. In the Project window select the package's `Textures/*.png`: Mip Maps off, Wrap Mode Clamp, Compression None. |

## For developers

- Code: [`Editor/`](io.github.eduardomv13.coyote-panel/Editor). `CoyotePanelInstaller` is the public entry point
  (`Install(GameObject avatar, CoyotePanelOptions options)`); `HandFrame` finds the hand directions; `PanelAssets` builds
  the meshes and materials; `PanelController` builds the animator controller; `PanelLayout` holds every number.
- **Tools > Coyote Panel > Developer > Export FX controller JSON...** dumps the controller of the selected avatar's panel;
  `python Tools~/simulate_controller.py ctrl.json` replays it.
- The plate and digit textures are drawn by [`Tools~/make_textures.py`](io.github.eduardomv13.coyote-panel/Tools~/make_textures.py)
  (needs Pillow; `--font` picks the font). If you change a layout number in `PanelLayout.cs`, change it there too: the
  repository's tests fail if the two disagree. The shipped PNGs were drawn with Arial Bold; any bold font gives the same
  layout, so if you prefer an open font (for example Inter Bold, SIL OFL), regenerate them.
- Run `python -m unittest` in the repository root.

## License

[MIT](../LICENSE), like the rest of this repository.
