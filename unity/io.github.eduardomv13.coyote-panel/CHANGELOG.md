# Changelog

## 0.3.0

The slider is now a **boost**, asked for because it was too easy for anyone to drag a grip to 200. **Checked offline
only (the simulator replays the controller exactly as Unity built it: 95 checks); not tried in VRChat yet.**

- **A grip adds at most +30 to the value that is already set.** The channel's value is remembered when the grip is grabbed;
  pulling the grip along the bar adds 0 to +30 (steps of 2, never above 200), and **letting go gives the remembered value
  back** (50 + a full pull = 80, and it goes back to 50). Posing a grip keeps the boost until the pose is released.
  Constants: `BOOST_MAX`, `BOOST_STEP`, `BOOST_HYST` in `Editor/PanelLayout.cs`.
- To change the level for good (or by more than 30) people have to use the **−/+ buttons**, which are still ±10 per touch.
  They now do nothing while that channel's grip is held or posed.
- STOP and "Zero channels" also forget the remembered values, so a slider that is being held does not bring the old power
  back when it is let go.
- Two new local (not synced) animator parameters, `CoyotePad/BaseA` and `CoyotePad/BaseB`; the synced parameter memory is
  unchanged (26 bits). The controller goes from 40 to 68 states, still 14 layers.
- The offline simulator has 95 checks (it had 55) and the example export was regenerated from the 0.3.0 builder.
- **Rebuild the panel on your avatar** (Tools > Coyote Panel > Install on selected avatar) and upload it again to get this.

## 0.2.1

Two fixes after the first in-game test of 0.2.0 (which worked, apart from these). **Not tried in VRChat yet.**

- **The touch buttons only fire when a fingertip is practically on the button.** The sensor sphere was 18 mm and sat 6 mm
  in front of the plate, so a finger registered up to about 2.4 cm away. It is now 5 mm, 1 mm in front of the plate: about
  6 mm of reach. Both numbers are options (options window, *Touch buttons*: radius and height) because the right values
  depend on the size of your avatar's finger colliders (6 to 7 mm on the author's avatar).
- **Both of the wearer's hands press the buttons.** 0.2.0 deliberately ignored the hand that holds the panel (the left one
  by default), so the buttons seemed to work with one hand only. New option *Ignore the holding hand*, off by default,
  brings the old behavior back.

## 0.2.0

Three behavior changes, asked for after the first in-game test of 0.1.0. **None of them has been tried in VRChat yet**
(the offline simulator and a built test copy of an avatar pass; see `unity/README.md`, "What has been tested").

- **Letting go of a slider grip sets its channel back to 0** (it used to keep the last value while the grip sprang back).
  A grip that is *posed* (grab + trigger) keeps its value until the pose is released.
- **Only a sideways pull raises a channel.** Each grip is now one 1.5 m PhysBone bone with its root to the left of the bar
  (it used to be a 12 mm bone), so VRChat's distance-based stretch is almost only the sideways distance. Pulling
  forward/back/up/down or toward the root no longer counts, and a small dead zone (3 % of the travel) hides the rest.
  Option: `PB_ROOT_DISTANCE` in `Editor/PanelLayout.cs`.
- **The −/+ and frequency buttons are pressed by touching them with a fingertip** (contact receivers fed by the avatars'
  own fingertip senders) instead of grabbing and holding a PhysBone. One step per touch; a press lasts at least 0.1 s so
  contact chatter adds no steps; no hold-to-repeat. Your own fingers count except those of the hand that holds the panel;
  every finger of other players counts. The PhysBone count drops from 8 to 2 and there are 12 local-only contact receivers.
- The offline simulator now has 55 checks (it had 46) and rejects the old behavior.

## 0.1.0
## 0.1.0

First public version. Generalized from a panel that was built for one specific avatar.

- Installs on the avatar you select (menu **Tools > Coyote Panel > Install on selected avatar**, or the options window).
  Nothing about the author's avatar is hard-coded any more.
- The hand frame (where the palm faces, where the fingers point) is derived from the humanoid skeleton, with
  configurable distances, roll, scale, left/right hand and a "flip facing" option. A fixed-bone-axes mode reproduces the
  geometry the panel was originally tuned with.
- Generated meshes, materials and the animator controller are written to `Assets/CoyotePanel/Generated/<avatar name>/`,
  one folder per avatar. The two textures ship inside the package.
- Same panel as before: 14-layer FX controller, A/B bars with PhysBone grips, -/+ buttons, one +/-10 Hz frequency pair,
  "Show panel", "Lock in world", "Zero channels", "STOP". Verified identical (controller, hierarchy, meshes) to the
  original build on the original avatar.
- Developer tools: controller JSON exporter and an offline simulator (`Tools~/simulate_controller.py`), plus tests in the
  repository that check the package without Unity.
