# Setting up your VRChat avatar

The program listens for four **avatar parameters** that VRChat sends over OSC. Your avatar has to define them, and
you need some way to change them (usually the radial menu). This page shows the minimal setup using only the standard
VRChat Avatars SDK (3.x) tools — no extra packages required.

> Read the [safety section of the README](../README.md) first. Everything below can make a
> real device deliver real stimulation to whoever is wearing it.
>
> **Prefer a ready-made hand-held panel with sliders?** There is a Unity package for that, installed with one menu
> click through Modular Avatar: see [`unity/README.md`](../unity/README.md). Use it *instead of* the radial puppets
> below for `CoyoteA`/`CoyoteB` (the panel writes those two parameters itself).

## The contract

| Parameter | Type | Range / meaning |
|---|---|---|
| `CoyoteA` | Float | `0`–`1`. `1` = the intensity **ceiling** set in the program (200 by default). Channel A |
| `CoyoteB` | Float | `0`–`1`. Same, channel B |
| `CoyoteFreq` | **Int** | `1`–`100` Hz for **both** channels. `0` and floats are ignored on purpose |
| `CoyoteStop` | Bool | `true` = emergency stop (stays latched in the program until you re-enable it there) |

The names can be changed in the program's OSC panel if you prefer other ones.

## 1. Add the parameters

1. Select your avatar in the Unity hierarchy and find its **VRC Avatar Descriptor**.
2. Open the **Expression Parameters** asset it points to (create one and assign it if the field is empty — better to
   duplicate the asset first if it is shared between several avatars).
3. Add these four entries:

   | Name | Type | Default | Saved | Synced |
   |---|---|---|---|---|
   | `CoyoteA` | Float | `0` | **off** | off |
   | `CoyoteB` | Float | `0` | **off** | off |
   | `CoyoteFreq` | Int | `50` | **off** | off |
   | `CoyoteStop` | Bool | off | **off** | off |

   * **Keep "Saved" off and the defaults at zero.** A saved intensity would be sent again every time the avatar
     loads. (The program also starts everything at zero and ramps increases, but do not rely on that alone.)
   * "Synced" can stay off: OSC output is local to your own client. Turn it on only if other players' clients need
     to see the value (for example to display it on a panel); it costs parameter memory.

## 2. Add menu controls

1. Open the **Expressions Menu** asset used by your avatar (again, duplicate it first if it is shared).
2. Add controls such as:

   | Control | Type | Setting |
   |---|---|---|
   | Channel A | **Radial Puppet** | the **Rotation** parameter → `CoyoteA` |
   | Channel B | **Radial Puppet** | the **Rotation** parameter → `CoyoteB` |
   | Frequency 30 / 50 / 80 Hz … | **Button** (or Toggle) | *Parameter* → `CoyoteFreq`, *Value* → `30` / `50` / `80` |
   | STOP | **Button** | *Parameter* → `CoyoteStop`, *Value* → `1` |

   A radial puppet gives a float from 0 to 1, which the program multiplies by the ceiling. `CoyoteFreq` is an
   integer, so a radial puppet cannot drive it — use buttons or toggles with fixed values.
3. Make sure the menu is reachable from your avatar's main menu (add the controls to it, or add a sub-menu
   control that points to a "Coyote" menu).
4. Upload (or Build & Test) the avatar.

> If a menu control does not seem to move the value, also add the same parameter (same name and type) to the
> **Parameters** list of your FX animator controller. It is harmless.

## 3. Turn on OSC in VRChat

1. Radial menu → **Options → OSC → Enabled**.
2. After adding or renaming parameters, use **Options → OSC → Reset Config** and then re-select the avatar. VRChat
   caches a JSON file per avatar listing its parameters
   (`%USERPROFILE%\AppData\LocalLow\VRChat\VRChat\OSC\usr_…\Avatars\avtr_….json`) and an old one will hide the new
   parameters.
3. Make sure the program is running and shows **OSC: receiving** after you move a control.

## 4. Check it works — safely

1. Open the program, connect the Coyote, leave the electrodes **off your body**, or open it with `--simulate`.
2. In VRChat, move **Channel A** a tiny bit. The program's channel A target should follow, and the OSC panel should
   list the received values.
3. Press the **STOP** menu button: the program should show the emergency stop, and every channel goes to zero until
   you click **RE-ENABLE CONTROLS** in the window.
4. Only then put the electrodes on, and start with the lowest intensities.

No VRChat at hand? `python tools/send_test_osc.py --a 0.05` sends the same messages. See the README.

## Optional: a touch contact that fires a shock

If your avatar already has the `ShockOsc/_all` parameter (a bool contact receiver, as set up by the ShockOSC / OpenShock
prefabs), the program can fire a shock when someone touches it: see
[Shock trigger](../README.md#shock-trigger-a-touch-on-the-shockosc-contact). There is nothing to add to the avatar.

If you want to build the contact yourself: add a **VRC Contact Receiver** to a small object on the avatar, type *Constant*,
**Allow Others** on, a collision tag such as `Finger` or `Hand`, parameter `ShockOsc/_all`, and a **Bool** `ShockOsc/_all`
(not saved, not synced) to the Expression Parameters. The contact only sets the bool; the program decides what to do with it.
(The author has not tried building this contact: the author's avatar already had the parameter.) As with the panel, the people
who can touch it can shock you: switch the trigger on only among people you trust.

## Optional: reading values back with OSCQuery

VRChat advertises an OSCQuery HTTP server (look for "OSCQuery on <port>" in its log). `GET
http://127.0.0.1:<port>/avatar/parameters/CoyoteA` returns the live value of the parameter, which is a quick way to
see whether your menu control changes it at all, independently of this program.

## Giving other people access (read twice)

You can build controls that other players can touch (for example a panel anchored in the world, driven by PhysBones
or Contacts; the [Unity package](../unity/README.md) has a "Lock in world" option that does exactly that). That means they can raise your intensity. If you do:

- keep the **intensity ceiling** in the program low;
- keep the **rise speed limit** on;
- make sure a **STOP** control is reachable by you, and that your own physical device controls are in reach;
- do it only with people you completely trust.
