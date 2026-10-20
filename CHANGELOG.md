# Changelog

Every version has a number and its own [GitHub release](https://github.com/eduardomv13/coyote-vrchat/releases) (tag
`vMAJOR.MINOR.PATCH`). Old releases are never removed or replaced: a new version is a new release. The in-game panel for
Unity (`unity/`) has its own version number, listed in [its changelog](unity/io.github.eduardomv13.coyote-panel/CHANGELOG.md).

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
