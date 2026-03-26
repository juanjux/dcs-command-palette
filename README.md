# DCS Command Palette

A VS Code-style command palette for DCS World. Press a hotkey (Ctrl+Space by default, configurable to any keyboard combo or HOTAS button) and a searchable overlay appears over DCS. Type to fuzzy-search all cockpit controls and keyboard shortcuts, then execute them instantly.

## Features

- **Fuzzy search** across all DCS-BIOS controls and keyboard shortcuts (powered by RapidFuzz)
- **HOTAS button support** -- bind the palette toggle to any joystick button (e.g. `Joy0_Button3`)
- **Auto-starts/stops with DCS** via a Lua hook that detects simulation start/stop
- **Live cockpit state** from DCS-BIOS -- shows current switch positions in the palette
- **Built-in DCS-BIOS installer** in the settings dialog

## Requirements

- DCS World (Steam or standalone)
- DCS-BIOS (can be installed from the Settings dialog)

## Installation

### From Release (.exe)

1. Download the latest release
2. Extract to `Saved Games\DCS\dcs-command-palette\`
3. Run `dcs-command-palette.exe` once to configure
4. Open Settings -> Install Lua Hook
5. (Optional) Open Settings -> Install/Update DCS-BIOS

### From Source (for devs)

```bash
cd "Saved Games\DCS"
git clone https://github.com/juanjux/dcs-command-palette
cd dcs-command-palette
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\python main.py
```

The Lua hook (`dcs_command_palette_hook.lua`) will automatically find either the `.exe` or the `.venv\Scripts\pythonw.exe` + `main.py` setup.

## Usage

- Once installed, DCS-Palette should start with the simulation and automatically stop when exiting it.
- **Ctrl+Space** (default): Toggle the command palette
- Type to search, **Up/Down/Tab** to navigate, **Enter** to execute
- **Escape**: Close palette or go back from a sub-menu
- Multi-position switches show a sub-menu with the current state highlighted
- Dials show INC/DEC buttons and a slider

### Built-in Palette Commands

The palette includes several built-in commands (search for them by name):

- **Open Palette Settings** -- opens the configuration dialog
- **Change Aircraft** -- switch to a different aircraft module
- **Restart Palette** -- reload commands and restart the process
- **Exit Palette** -- shut down the palette

## Configuration

Open Settings from the palette (search "settings") or from the system tray icon.

- **Aircraft**: Auto-detected from DCS on mission start, or manually selected
- **Hotkey**: Keyboard combo (default `Ctrl+Space`) or HOTAS button (e.g. `Joy0_Button3`)
- **Auto-hide**: Configurable timeout in seconds (0 to disable)
- **Show identifiers**: Toggle DCS-BIOS control IDs below command names
- **DCS install directory**: Auto-detected or manually selected on first run
- **Lua Hook**: Install/uninstall the DCS hook from Settings
- **DCS-BIOS**: Install or update DCS-BIOS from Settings


## Reporting bugs

Run the .exe or .py (if using the source distribution) with the `--debug` parameter. Try to reproduce the issue and create and
issue on https://github.com/juanjux/dcs-command-palette/issues attaching the dcs_command_palette.log on your `C:\Users\YOURUSER\Saved Games\DCS\dcs-command-palette` directory.


## Supported Aircraft

Any aircraft with DCS-BIOS support. The palette auto-detects installed modules from the DCS installation directory. Keyboard shortcut parsing works for all standard DCS aircraft.

## License

MIT
