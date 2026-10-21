# Changelog

Every version has a number and its own [GitHub release](https://github.com/eduardomv13/coyote-vrchat/releases) (tag
`vMAJOR.MINOR.PATCH`). Old releases are never removed or replaced: a new version is a new release. The in-game panel for
Unity (`unity/`) has its own version number, listed in [its changelog](unity/io.github.eduardomv13.coyote-panel/CHANGELOG.md).

## Unreleased

- **A new window with three tabs**, like a settings dialog: *Coyote settings* (Bluetooth connection, Channel A, Channel B,
  Patterns, Safety limits), *Shock contact* (everything about the contact shock) and *Extras* (VRChat OSC, AI / Claude
  Code MCP, Log). The header with the status chips and STOP ALL stays visible on every tab.
- The tab you click keeps its size (it used to shrink a little because of the theme's own padding for the selected tab); only
  its colors change.
- **Each channel has its own shock settings**: its own lowest and highest random power and its own shortest and longest
  random duration (1 to 30 s), drawn separately for A and B at every touch. Controller: a shock now has its own level and
  end time per channel (`start_shocks`, `shock_active(channel)`); a touch is ignored only while one of ITS channels is
  shocking.
- **Several contacts**: a list of contact triggers, each with the channels it fires. The default is `ShockOsc/_all`, which
  fires **both channels**; "Add trigger" adds more (up to 8). Settings: `shock_a_*`/`shock_b_*` and `shock_triggers`
  replace `shock_min_pct`, `shock_max_pct`, `shock_seconds`, `shock_channels` and `osc_param_shock`; a settings file from an
  older version is converted (the same numbers for both channels, one contact with the old channels).
- The chatbox message now says each channel's numbers: default text `Shock {shock}`, for example
  `Shock A 37% for 5 s, B 20% for 3 s`. Also `{percent}`, `{seconds}` (the highest and the longest), `{a_percent}`,
  `{a_seconds}`, `{b_percent}`, `{b_seconds}`. A saved copy of an old default text takes the new default.
- **The chatbox message also appears when the Coyote is not connected.** A touch on a contact now shows the message
  (for example `Shock A 37% for 5 s, B 20% for 3 s`) in the VRChat chatbox, and clears it as usual, even without a connected
  Coyote, but **no shock is delivered**. The chip at the top says *Shock trigger: chatbox only* (gold) instead of *NOT READY*, and the card and the
  bottom of the window say the touch only reached the chatbox. During the announced seconds a second touch is not announced
  on top of it. If the chatbox message is off, empty or too soon after another, such a touch is still ignored. With the
  emergency stop active nothing is announced, as before.
- Switching the trigger off now also takes a message that is still on screen off the chatbox.
- 298 automated tests (it was 261).

## 1.2.1 (2026-10-20)

- **The VRChat chatbox now shows the power and the duration of the shock**: the default message is
  `Shock {percent}% for {seconds} s`, for example `Shock 37% for 5 s` (it used to say only the power). The text is still
  editable in the *Shock trigger* card. A settings file that still holds the old default (`Shock {percent}%`) takes the new
  one the next time the program starts; a text you wrote yourself is never touched.
- `build_exe.bat` also leaves `CoyoteVRChat.exe` next to `main.py` (a copy of `dist\CoyoteVRChat.exe`, not committed), and
  explains what to do when the build cannot replace an `.exe` that is open.
- 261 automated tests (it was 257).

## 1.2.0 (2026-10-19)

- **A Windows program in one file**: `CoyoteVRChat-1.2.0.exe` runs with a double-click, no Python needed. It opens only the
  window (no console), shows the logo in the title bar, the taskbar and the file icon, and carries Windows version
  information. About 13 MB. Built with PyInstaller (`build_exe.bat`, recipe in `coyote_vrchat.spec`; UPX is off on purpose).
- The file is built by GitHub Actions on a clean Windows machine when a release is published
  (`.github/workflows/release-exe.yml`: tests, then `--version`/`--selftest`/MCP checks, then it is attached together with
  `SHA256SUMS.txt`), so the build log is public.
- The file is **not code-signed**, so Windows SmartScreen asks for *More info → Run anyway* and some antivirus programs may
  complain. Compare it with `SHA256SUMS.txt`.
- **Temporary logo**: an original black-and-gold wolf's head drawn by `tools/make_icon.py` (not DG-LAB's artwork). Replace
  `assets/coyote.ico` and `assets/coyote.png` to change it.
- New options, for the `.exe` and for `python main.py`: `--selftest` (checks the logo, the window library, Windows Bluetooth
  and the two ports, then exits; non-zero if something the program needs is missing), `--version`, and `--mcp` (the MCP
  server for an AI). With the `.exe`, the command for Claude is `"<folder>\CoyoteVRChat.exe" --mcp` — the same file is the
  window and the MCP server — and the **Copy MCP command** / **Register in the Claude Desktop app** buttons produce it.
- The first time the `.exe` starts without settings of its own, it copies the settings of a copy that was run from the
  Microsoft-Store Python (Windows keeps those in a private folder the `.exe` cannot see), so the ceilings and the API token do
  not silently go back to the defaults.
- The taskbar groups the program under its own identity and logo instead of under Python.
- When started from a terminal, `--version`/`--selftest`/`--help` print into that terminal (also from the one-file layout,
  where the program runs in a child process), and leave a redirected output (`> file`, `| more`) alone.
- 257 automated tests (it was 237).

## 1.1.0 (2026-10-19)

- **Shock trigger** (new, off by default and at every start): when someone touches the avatar's `ShockOsc/_all` contact, the
  program fires one shock at a random power between a **minimum** and a **maximum** you set (percentages of the intensity
  ceiling), for 1 to 30 seconds, on channel A, B or both. A touch while a shock is running is ignored, and there is no other
  delay between shocks.
- The power is announced in the VRChat chatbox (`Shock 37%`, editable text) and the message is removed again after 3 seconds
  (editable; 0 = leave it). Removing it is done with an empty message, which VRChat does not document: it may not work on every
  VRChat version.
- A shock is a temporary *minimum* level: it never lowers what the window, a panel or the AI ask for, follows the intensity
  ceiling and the rise limit, and STOP ALL cancels it (and removes the chatbox message).
- It never fires without a connected Coyote or during the emergency stop. Ticking the trigger asks for confirmation and tries
  to connect the Coyote; the header chip says **NOT READY** in red while it cannot fire, and a touch that is ignored is shown
  with the reason.
- `tools/send_test_osc.py --shock` simulates a touch.
- The Unity panel package went from 0.1.0 to 0.2.1 (release to zero, sideways-only sliders, finger-touch buttons).
- 237 automated tests (it was 175).

## 1.0.0 (2026-10-16)

First public version: direct Bluetooth control of a DG-LAB Coyote 3.0 from VRChat OSC (`CoyoteA`, `CoyoteB`, `CoyoteFreq`,
`CoyoteStop`), a window with manual sliders and patterns, safety limits (ceiling, rise limit, latched emergency stop, OSC
watchdog) and an optional local API / MCP server for an AI.
