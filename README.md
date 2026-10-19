# Coyote × VRChat

[![CI](https://github.com/eduardomv13/coyote-vrchat/actions/workflows/ci.yml/badge.svg)](https://github.com/eduardomv13/coyote-vrchat/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A Windows program that connects **directly over Bluetooth** to a **DG-LAB Coyote 3.0** and receives
**VRChat OSC**: avatar parameters (`CoyoteA`, `CoyoteB`, `CoyoteFreq`, `CoyoteStop`) control the intensity and
frequency of the two channels. It has a black-and-gold window, manual sliders, basic patterns, strict safety
limits, and an optional local API so an AI assistant (Claude) can adjust things — always inside the limits **you**
set.

No phone app and no second program in the middle: Bluetooth is spoken by this program itself, using the public
DG-LAB V3 protocol.

> **Not affiliated with DG-LAB or VRChat.** "DG-LAB", "Coyote" and "VRChat" are trademarks of their owners.

---

## ⚠️ Safety first — please read

This software drives an **electro-stimulation device**. Use it responsibly:

- **Adults only, with the informed consent of everyone involved.** Whoever wears the electrodes must be able to stop
  at any moment.
- **Never place electrodes on or across the chest/heart, the head, the neck or the throat**, or on broken skin.
  Do not use it with a pacemaker or other implanted electronics, during pregnancy, with epilepsy or a heart
  condition, or if a doctor told you to avoid electrical stimulation. When in doubt, ask a medical professional.
- **Start at zero and go slowly.** The first minutes should be at the lowest intensities (5–10 out of 200).
- Anything that can write to your avatar's parameters can change the intensity — including other players if you
  expose controls to them (for example a world-anchored panel). **Only let people you completely trust do that**, and
  keep the ceilings low.
- **The shock trigger lets other players shock you.** If you switch it on, whoever can touch the contact on your avatar
  fires a random shock. It is off every time the program starts and has to be switched on in the window. Keep its power
  range low, and only switch it on among people you trust (see
  [Shock trigger](#shock-trigger-a-touch-on-the-shockosc-contact)).
- Keep the **STOP ALL** button, the `CoyoteStop` parameter and the device's own physical controls within reach.
- This is a hobby project provided **as is, with no warranty** (see [LICENSE](LICENSE)). You use it at your own risk.

The program is built so that the safe thing is the default: everything starts at zero, increases are ramped, there is
an intensity ceiling, a latched emergency stop, and an optional watchdog. Details in [Safety](#7-safety-summary).

---

## What it does

- Direct Bluetooth LE connection to the Coyote 3.0 (V3 protocol), 100 ms command loop, automatic reconnection.
- Receives VRChat OSC on UDP port 9001: intensity per channel, one frequency for both channels, and an emergency stop.
- Manual control window: per-channel sliders, frequency, pulse width, 8 waveform patterns.
- **Shock trigger** (optional, off by default): a touch on the avatar's `ShockOsc/_all` contact fires one timed shock at a
  random power you choose (a lowest and a highest percentage, 1 to 30 s), and the power is shown in the VRChat chatbox.
- Safety layer: intensity ceiling, maximum rise speed, latched emergency stop, OSC watchdog, zero on (re)connect.
- Optional AI control through a localhost-only, token-protected API and an MCP server (Claude Code / Claude Desktop),
  with its own lower ceiling.
- An optional **in-game control panel for your avatar** (sliders, buttons, frequency; a Unity package that installs with
  Modular Avatar). It is a separate piece: see [unity/README.md](unity/README.md).
- 237 automated tests (protocol, Bluetooth with a simulated Coyote, OSC, API, MCP, interface logic, the shock trigger,
  and checks on the Unity package that do not need Unity).

**Tested on:** Windows 11, a real Coyote 3.0, and VRChat on PC. The automated tests use a simulated Coyote. Other
operating systems are untested (the Bluetooth library, `bleak`, is cross-platform, but nothing here has been tried on
Linux or macOS).

---

## 1. Install

You need **Windows 10/11 with Bluetooth LE** and **Python 3.10 or newer**
(<https://www.python.org/downloads/> — during installation, check *Add python.exe to PATH*).

**Easy way:** download the newest numbered version from the [Releases](https://github.com/eduardomv13/coyote-vrchat/releases)
page (every version stays there; see the [changelog](CHANGELOG.md)) or clone this repository, and double-click `run.bat`. The first time it creates a `.venv`
folder and installs the only dependency (`bleak`, the Bluetooth library). After that it just opens the program.

**Manual way** (in a terminal, inside the project folder):

```
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

Just want to look at the window without the device? `python main.py --simulate` opens the program with a fake
Coyote.

Command-line options: `--simulate` (fake Coyote), `--connect` (connect on startup), `--headless` (no window, OSC and
API only), `--settings <file>` (use a different settings file).

## 2. First use (take it slow)

1. **Close any other program that uses the Coyote**: the DG-LAB phone app, other VRChat/OSC controllers, etc. The
   Coyote only accepts **one** Bluetooth connection at a time.
2. Turn the Coyote on (leave the device's own intensity at zero) and bring it close to the PC.
3. Open the program → **Scan** → pick your device (it usually appears as `47L121000`) → **Connect**. The dot turns
   green and the battery level shows up. (You normally do not need to pair it in Windows settings.)
4. **Test with low values first**: drag channel A's slider to 5–10 and raise it slowly.
5. The big **STOP ALL** button (or the `Esc` key with the window focused) zeroes everything and **latches** the
   controls. To control again, click **RE-ENABLE CONTROLS**. Neither the AI nor VRChat can re-enable them.

## 3. The window

| Panel | What it is for |
|---|---|
| Header | Bluetooth, OSC and AI status; STOP ALL button |
| Bluetooth connection | Scan, connect, disconnect, battery, errors, automatic reconnection |
| Channel A / Channel B | Intensity 0–200 (slider, −10/−1/+1/+10, Zero), frequency 1–100 Hz, pulse width 0–100. The ▼ on the slider shows the value actually going out during the ramp-up; the red mark is the ceiling |
| VRChat OSC | Port, address and parameter names; shows whether packets are arriving |
| Patterns | Constant, Breathing, Pulses, Heartbeat, Ramp, Frequency sweep, Random, Staccato; speed, channels and A/B alternation |
| Safety limits | Intensity ceiling, maximum rise speed, OSC watchdog |
| Shock trigger | Switches the ShockOSC-contact trigger on/off; lowest and highest random power, duration (up to 30 s), channels, chatbox message and tests |
| AI | Turns AI control on/off, AI ceiling, command to register in Claude Code |
| Log | Everything that happened (connections, stops, AI actions…) |

Patterns change the **waveform** (Hz and pulse width). The intensity is still the one from the sliders, VRChat or the
AI.

## 4. Connecting to VRChat (OSC)

1. In VRChat: radial menu → **Options → OSC → Enabled**.
2. VRChat **sends** to port **9001** of your PC; the program already listens on it.
3. Your **avatar needs the parameters below**. How to add them (and a menu to drive them) is explained step by step in
   **[docs/AVATAR_SETUP.md](docs/AVATAR_SETUP.md)**. If you would rather have a ready-made hand-held panel with
   sliders, install the Unity package in **[unity/](unity/README.md)** instead (read its safety section first).

| Avatar parameter | Type | What it does |
|---|---|---|
| `CoyoteA` | float 0–1 (or int/bool) | 0 = zero, 1 = the configured **ceiling** (200 by default) on channel A |
| `CoyoteB` | float 0–1 (or int/bool) | same, channel B |
| `CoyoteStop` | bool | `true` triggers the same emergency stop as the window (stays latched until you re-enable it) |
| `CoyoteFreq` | **int**, Hz (1–100) | frequency of **both** channels at once. Only integers count: `0` and floats are ignored (a parameter that is not initialized yet arrives as 0 and must not drop the frequency to 1 Hz). Values above 100 become 100 |

| `ShockOsc/_all` | bool | a touch on the avatar's contact: fires **one** shock if the [shock trigger](#shock-trigger-a-touch-on-the-shockosc-contact) is switched on (the name is compared ignoring upper/lower case) |

The names can be changed in the window. Any VRChat packet counts as "I am alive": if you enable the **watchdog**
(Safety limits), the channels commanded by VRChat go back to zero when it stays silent for X seconds (for example,
if the game freezes).

**Only one program can listen on port 9001.** If "another OSC program may be using this port" shows up, close any
other OSC tool, or use an OSC router.

### Shock trigger: a touch on the ShockOSC contact

Avatars set up for ShockOSC (OpenShock) have a contact receiver whose parameter is `ShockOsc/_all`, a bool that is on while
the contact is touched. This program can listen to it: **when someone touches the contact, it fires one shock at a random
power**, for a few seconds, on the channels you pick, and shows the power in the VRChat chatbox. It is the **Shock trigger**
card in the window.

- **Random power:** a lowest and a highest slider (1 to 100 %). Every touch draws a new whole-number percentage between
  them. The percentage is of the *intensity ceiling*, the same scale as `CoyoteA`: with the default ceiling of 200, 30 % is 60.
- **Duration:** 1 to 30 seconds. **Channels:** A, B or both.
- **Chatbox:** when a shock starts, the program sends `Shock 37%` (the text is editable; `{percent}` and `{seconds}` are
  replaced) to VRChat's OSC input, which listens on port **9000** (OSC has to be enabled in VRChat; the port is a field in the
  card). VRChat drops chatbox messages that come in too fast, so at most one is sent every 1.6 s. **Test chatbox** sends a
  test message without any shock.
- **The message goes away by itself** 3 seconds later (a field in the card; 0 = leave it to VRChat). It is also removed at
  once when you press STOP ALL, switch the trigger off, or close the program. VRChat's documentation does not describe how to
  clear a message over OSC: what chatbox tools do is send an *empty* message, and that is what this program does. It is not
  guaranteed on every VRChat version; if it does not clear for you, the message disappears after VRChat's own "chatbox
  display duration" setting.
- **One shock per touch.** A contact that stays on does not repeat: it has to turn off and on again. A touch while a shock is
  running is ignored. There is no pause after a shock: as soon as it ends, the next touch can fire a new one.
- **It never fires** unless the trigger is ticked, the Coyote is connected and the emergency stop is not active, and nothing is
  announced for a shock that did not happen. Ticking the trigger also tries to connect the Coyote if it is not connected.
  While it cannot fire, the chip at the top says **Shock trigger: NOT READY** in red and the card says why. A touch that is
  ignored is shown in red at the bottom of the window and in the card (with the reason and how long ago), and the card also
  shows when the contact was last touched, so you can tell "VRChat never sent the touch" from "the program ignored it".
- **It is a floor, not a replacement.** During the shock each chosen channel is held at *at least* the drawn power: what the
  window, a panel or the AI ask for is never lowered, and afterwards the channel goes back to it. The ceiling and the rise
  limit still apply (with the default rise limit of 100 per second, a 100 % shock takes 2 s to reach full power; set the limit
  to unlimited if you want instant shocks), and **STOP ALL** cancels it at once.
- **It starts off every time**, and ticking it asks for confirmation, because other players pull this trigger, not you.
  Switching it off also cancels a shock that is running.
- The parameter name can be changed in the card (some avatars spell it `ShockOsc/_All`; the comparison ignores upper/lower
  case).

### Testing without VRChat

With the program open, send fake avatar parameters from another terminal:

```
python tools/send_test_osc.py --a 0.05            # channel A at 5% of the ceiling
python tools/send_test_osc.py --a 0.05 --b 0.05 --freq 60
python tools/send_test_osc.py --stop              # emergency stop
python tools/send_test_osc.py --shock             # touches the ShockOsc/_all contact (needs the shock trigger switched on)
python tools/send_test_osc.py --a 0 --b 0         # back to zero
```

Start the program with `--simulate` if you do not want the real device to react.

## 5. Coyote 3.0 limits (read this)

- **Frequency: 1 to 100 Hz, not 200.** In the V3 protocol the frequency is sent as a *period in milliseconds*
  (10 to 1000 ms). That gives a maximum of **100 Hz** and a minimum of **1 Hz**. Above 100 Hz simply does not exist on
  the device, so the program caps it at 100 and never sends a value the device would discard.
- **Intensity: 0 to 200.** The program writes the chosen ceiling into the device itself (the protocol's `BF` command,
  "soft limit") on every connection and uses 200 by default. If your device does not go above a lower value, check
  the limit configured in the device / DG-LAB app.
- The Coyote needs a command **every 100 ms**; the program handles that in a separate task, so dragging or freezing
  the window does not interrupt anything.

## 6. AI control (Claude Code / Claude Desktop)

The AI talks to the program through an API that only exists on your computer (`127.0.0.1`) and requires a secret
token. **It is off by default and always starts off.**

There are **two places** where Claude can be registered, and they are independent:

- **Claude Code in the terminal:** in the **AI** panel, click **Copy MCP command**, paste it into a terminal and
  press Enter (only once). The command looks like this:
  `claude mcp add --scope user coyote -- "<python>" "<folder>\coyote_mcp.py"`
  Check with `claude mcp list` (or `/mcp` inside Claude Code). It applies to **new** terminal sessions.
- **Claude Desktop app:** click **Register in the Claude Desktop app** in the **AI** panel (or run
  `python register_claude_desktop.py`). This adds `coyote` to `claude_desktop_config.json` without deleting anything
  already there (it makes a `.bak-...` copy first). Then **fully quit the Claude app, including from the Windows
  tray, and open it again**. If the file has a JSON error, the program does not touch it and tells you; use
  `python register_claude_desktop.py --print` and paste the snippet into Settings > Developer > Edit Config.

Then:

1. Tick **Allow an AI to control** in the window and confirm the warning. The app has to be open (the MCP only talks
   to it).
2. Adjust the **AI ceiling** (default **50**) to the maximum you accept it using.
3. Ask, for example: *"turn channel A on at 20 with 40 Hz and set the Breathing pattern"*.

To test the MCP path without depending on a Claude session, run `mcp_sequence_check.py` (with the app open, the
Coyote connected and AI allowed): it starts `coyote_mcp.py` the way Claude Code does and sends 50 for 2 s, 100 for 5 s
and 200 for 1 s through the MCP tools only, showing what the app applied. It respects the same ceilings (it works
around nothing), asks for Enter before starting, and zeroes the channel at the end or on Ctrl+C. Use `--channel AB`
for both channels.

Tools the AI gets: `coyote_status`, `coyote_set_intensity`, `coyote_set_frequency`, `coyote_set_pulse_width`,
`coyote_list_patterns`, `coyote_set_pattern`, `coyote_stop`.

Rules the AI **cannot** get around:

- it only works with the box ticked; unticking it also zeroes what it had turned on;
- intensity is limited to the **AI ceiling** (default **50**, adjustable on the slider) and to the global ceiling;
- the rise respects the configured maximum rise speed;
- `coyote_stop` zeroes everything, but **only you** can re-enable it, from the window.

If you want to use the API directly (other tools): `GET /status`, `GET /patterns`, `POST /intensity`, `/frequency`,
`/width`, `/pattern`, `/stop`, with the header `Authorization: Bearer <token>` (**Copy token** button).

## 7. Safety (summary)

- Intensities go to **zero** whenever Bluetooth (re)connects and when the program closes.
- Increasing is gradual (default: 100 per second; 0 → 200 in 2 s). Decreasing is immediate.
- The emergency stop is **latched**: only the window re-enables it. It works through the button, `Esc`, the VRChat
  `CoyoteStop` parameter and the AI.
- The shock trigger is off at every start, asks for confirmation when you switch it on, fires one shock per touch (never
  longer than 30 s), only with the Coyote connected and no emergency stop, and always inside
  the ceiling and the rise limit.
- The AI API only accepts connections from this same PC, with a token, and refuses web pages (a site open in the
  browser cannot send a shock).
- The `Esc` key only works with the program window focused. Inside the game, use the `CoyoteStop` parameter (and the
  device's physical button still works).
- Your settings, including the API token, live in `%APPDATA%\CoyoteVRChat\settings.json` — never in this folder, so
  they cannot end up in a commit by accident.

## 8. Troubleshooting

| Symptom | What to do |
|---|---|
| "Coyote not found" | Turn the device on, get closer, close the DG-LAB app/other controllers, check that the PC's Bluetooth is on |
| It connects but I feel nothing | The channel only outputs with intensity > 0 **and** pulse width > 0; check the electrodes and the device's physical knob |
| OSC "receiving" never shows up | Is OSC enabled in VRChat? Is port 9001 free? Does the avatar have the parameters? After adding parameters, use *Options → OSC → Reset Config* in VRChat and re-select the avatar. See [docs/AVATAR_SETUP.md](docs/AVATAR_SETUP.md) |
| OSC shows packets but nothing changes | Only parameters named exactly `CoyoteA`/`CoyoteB`/`CoyoteFreq`/`CoyoteStop` count (names can be changed in the OSC panel). `CoyoteFreq` must be an **int** parameter |
| Frequency never changes | `CoyoteFreq` ignores `0` and floats on purpose; send an int between 1 and 100 |
| Touching the contact does nothing | Read the red/gold line in the *Shock trigger* card and the chip at the top: **NOT READY** usually means the Bluetooth chip is not *Connected*. The Coyote has to be on, close to the PC and not held by another app (the DG-LAB phone app, OpenShock Desktop): while another app holds it, it does not even show up in *Scan*. Then: is *Shock trigger* ticked (it starts off every time)? Is the parameter name right (`ShockOsc/_all` on your avatar)? Does the card say the contact was touched? If it says *not touched since the program started*, VRChat never sent the touch: the contact on the avatar may not accept your hand (for example, "Allow Self" off means only OTHER players can trigger it, and a small radius means the hand has to be close) |
| The chatbox message does not appear | Is OSC enabled in VRChat? VRChat normally listens for OSC input on port 9000; if your setup changed that (an OSC router, another program holding 9000), put the right port in the card. Try *Test chatbox*. VRChat can also hide chatbox messages (check its settings) |
| "tkinter missing" | Reinstall Python with *tcl/tk and IDLE* checked (or use `--headless`) |
| My configuration got lost | It lives in `%APPDATA%\CoyoteVRChat\settings.json` (if it gets corrupted, the program keeps a `.bak` copy and starts over) |

## 9. Development

```
python -m unittest        (inside the project folder)
```

The tests cover the protocol (with the hexadecimal examples from the official documentation), Bluetooth with a
simulated Coyote, OSC, the API, the MCP server and the interface logic. **What they do not cover:** a real Coyote,
Windows Bluetooth and the real look of the window — that can only be checked by opening the program. CI runs the
tests on Windows with Python 3.10 and 3.12.

```
main.py                      entry point (--simulate, --connect, --headless, --settings)
coyote_mcp.py                MCP server for Claude Code / Claude Desktop
register_claude_desktop.py   registers the MCP in the Claude Desktop app
mcp_sequence_check.py        tests the MCP with a sequence of intensities
run.bat                      installs and opens (Windows)
tools/send_test_osc.py       sends fake VRChat OSC parameters to the program
docs/AVATAR_SETUP.md         adding the parameters and a menu to a VRChat avatar
unity/                       Unity package: a hand-held control panel for your avatar (Modular Avatar), with its guide
coyote_vrc/
  protocol.py                B0/BF/B1 packets of the BLE V3 protocol and frequency conversion
  ble.py                     Bluetooth connection (bleak), 100 ms sending, reconnection
  control.py                 channel state, limits, ramp, emergency stop, patterns
  patterns.py                the 8 patterns
  osc.py                     OSC reader (UDP) and sender (VRChat chatbox)
  shock.py                   the ShockOSC-contact trigger: random power, timing, chatbox message
  api.py / mcp_server.py     bridge for the AI
  engine.py                  wires everything together
  gui.py                     the window
  mcp_register.py            registers the MCP in the Claude Desktop app
tests/                       automated tests
```

The Unity package has its own checks in `tests/test_unity_package.py` (metadata, `.meta` files, layout numbers, the
offline controller simulator). They do **not** compile the C# or build a panel: that needs Unity, and is described in
[unity/README.md](unity/README.md#what-has-been-tested).

Issues and pull requests are welcome. Please keep the safety behavior intact: anything that raises the intensity must
go through the ceiling, the ramp limit and the latched stop.

## Credits

The Bluetooth protocol implementation follows DG-LAB's public documentation
(<https://github.com/dungeonlab-open/dglab-bluetooth-protocol>, Coyote V3). Thanks to DG-LAB for publishing it.

## License

[MIT](LICENSE).
