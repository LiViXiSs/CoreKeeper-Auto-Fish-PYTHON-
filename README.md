# Core Keeper Python Auto Fisher

A Windows fishing controller that automatically casts, reads the local player's bite state, reels, and recasts. Python attaches to the game's Mono runtime and loads a small managed helper that sends normal game input. No Cheat Engine, AutoHotkey, or pixel calibration is required.

The fishing loop was tested in a running Core Keeper client connected to a privately hosted server on October 4, 2026. The game's catch counter increased by 15 during one test. The portable package has passed compilation and relocated-path checks; it has not been tested on a second computer.

## Requirements

- **64-bit Windows.** Linux, macOS, consoles, and Steam Deck are not supported.
- **64-bit Python with Tkinter/Tcl-Tk.** Tested with Python 3.12. No pip packages are needed. A standard Windows Python installation with Tcl/Tk enabled is suitable.
- A compatible **64-bit Mono version of Core Keeper** running locally, with a world loaded. The supplied helper was built against the tested installation; future updates or other distributions may require rebuilding and code changes. IL2CPP builds are unsupported.
- The game and controller must have compatible privilege levels. Normally use both without administrator privileges. If the game is elevated, the controller may need the same privileges.
- A writable folder for the controller's status and diagnostics files.

The game must remain focused while fishing. Equipping a rod and choosing the water target are still setup steps; casting and catching then run automatically. The helper uses the existing server input path, so server rules still apply.

## Run

1. Download or clone this repository into a writable folder.
2. Load a world in Core Keeper and stand beside water with a fishing rod equipped.
3. Double-click **Start Python Fisher.cmd**, or run `python core_keeper_fisher.py` using 64-bit Python.
4. Click **Start auto fishing**, return to the game, and point at water. The first valid frame saves the aim point. The tool charges a 0.6-second cast, releases, reads the bite flag, reels, and repeats.
5. Click **Stop**, press **F11** while the Python window is running, or close the controller to stop and remove the input hook.

Stop and start again to change the target. Opening blocking menus, moving, switching away from the game, or unequipping the rod pauses automation. Generated fishing input disables the legacy fishing minigame without changing the saved preference.

If Python is forcibly terminated, the helper can remain active in the game. Reopen the controller and use Stop, or restart Core Keeper. Restart the game before using a rebuilt helper because Mono retains loaded assemblies.

## Which files are needed?

| File | Purpose | Required to run? |
| --- | --- | --- |
| `core_keeper_fisher.py` | Python attachment, GUI, and controls | Yes |
| `CoreKeeperAutoFishPython.dll` | Game input and fishing-state helper | Yes; keep beside the script |
| `Start Python Fisher.cmd` | Finds Python and launches the GUI | Optional convenience |
| `CoreKeeperAutoFishPython.cs` | Full helper source | Only to rebuild |
| `build_helper.ps1` | Builds against your installed game | Only to rebuild |
| `README.md` | Instructions | No |
| `.gitignore` | Keeps local logs/cache out of Git | No |

This repository does not include the earlier AHK/CE prototypes, personal logs, credentials, or game DLLs. The supplied helper contains this project's compiled code and references dependencies from the user's existing game installation.

## Rebuild for your installation

Building requires a **.NET SDK version 8 or later**. A .NET runtime alone is insufficient. From PowerShell in the repository folder:

```powershell
.\build_helper.ps1
```

The script tries the running game's path and Steam library locations. For other installs or a custom folder:

```powershell
.\build_helper.ps1 -GameDirectory "D:\Games\Core Keeper"
```

It reads the game assemblies and compiles only this project's helper. It does not replace game files or distribute the game assemblies. Successful compilation confirms API compatibility but does not by itself prove that fishing works on a different game version.

## Diagnostics

The GUI shows hook execution (`inputTicks`), successful game-state reads (`gameReads`), cast/reel attempts, and the change in the game's catch counter (`catchDelta`). Casts and reels alone do not confirm catches.

`Core Keeper fishing status.txt` and `Python fisher diagnostics.jsonl` are generated beside the script and ignored by Git. Attach useful error text when reporting a problem. The program does not upload diagnostics or other data.

```text
python core_keeper_fisher.py --probe    # Read-only attachment check
python core_keeper_fisher.py --enable   # Enable without GUI
python core_keeper_fisher.py --disable  # Stop without GUI
```

F11 is monitored by the GUI, so use the GUI for normal operation. If a Mono call times out, restart Core Keeper before retrying. If a game update changes the input structure or game API, the helper may need source changes, not merely a rebuild.

## Publishing to GitHub

Upload the contents of this folder, including `.gitignore`, to your repository. The included DLL is the prebuilt runtime helper; leave it in the repository or distribute it alongside the Python script in a release. The source and build script make it reproducible against the installed game.
