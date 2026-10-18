# Changelog

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
