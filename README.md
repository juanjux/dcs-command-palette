# DCS Command Palette

A VS Code-style command palette for DCS World. Press a hotkey (Ctrl+Space by default, configurable to any keyboard combo or HOTAS button) and a searchable overlay appears over DCS. Type to fuzzy-search all cockpit controls and keyboard shortcuts, then execute them instantly.

## Features

- **Fuzzy search** across all DCS-BIOS controls and keyboard shortcuts (powered by RapidFuzz)
- **Works in fullscreen DCS** -- uses a Win32 low-level keyboard hook (`WH_KEYBOARD_LL`) that intercepts keys before DCS sees them
- **HOTAS button support** -- bind the palette toggle to any joystick button (e.g. `Joy0_Button3`)
- **Auto-starts/stops with DCS missions** via a Lua hook that detects simulation start/stop
- **Live cockpit state** from DCS-BIOS -- shows current switch positions in the palette
- **User keybind support** -- reads `Keyboard.diff.lua` customizations on top of default aircraft bindings
- **Smart search ranking** -- combines fuzzy match score, usage frequency, and recency (configurable weights)
- **Multi-word matching** and category search (e.g. type "fuel" to see all fuel-related controls)
- **Sub-menus** for multi-position switches, dials, and sliders with current state highlighted
- **System tray integration** with show/change aircraft/settings/quit actions
- **Built-in DCS-BIOS installer** in the settings dialog
- **Auto-hide** -- palette disappears after a configurable timeout

## Requirements

- DCS World (Steam or standalone)
- Python 3.13+ (for development) or standalone `.exe`
- DCS-BIOS (can be installed from the Settings dialog)

## Installation

### From Release (.exe)

1. Download the latest release
2. Extract to `Saved Games\DCS\dcs-command-palette\`
3. Run `dcs-command-palette.exe` once to configure
4. Open Settings -> Install Lua Hook
5. (Optional) Open Settings -> Install/Update DCS-BIOS

### From Source

```bash
cd "Saved Games\DCS"
git clone <repo> dcs-command-palette
cd dcs-command-palette
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\python main.py
```

The Lua hook (`dcs_command_palette_hook.lua`) will automatically find either the `.exe` or the `.venv\Scripts\pythonw.exe` + `main.py` setup.

## Usage

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

## How It Works

1. **Keyboard shortcuts** are parsed from DCS Lua input files in three layers: common defaults, aircraft-specific defaults, and user customizations (`Keyboard.diff.lua`)
2. **DCS-BIOS controls** are parsed from the JSON definition files in `Saved Games\DCS\Scripts\DCS-BIOS\doc\json\`
3. **Live cockpit state** is read via DCS-BIOS UDP multicast (`239.255.50.10:5010`)
4. **Commands are sent** via DCS-BIOS UDP (port `7778`) or keyboard simulation (pynput)
5. **The Lua hook** (`Scripts/Hooks/dcs_command_palette_hook.lua`) starts the palette on mission start with the current aircraft type, and writes a `.shutdown` file on mission stop
6. **The palette listens** on UDP port `7780` for `TOGGLE_PALETTE` messages from the hook

### Search Ranking

Results are ranked using a weighted combination of:
- Fuzzy match score (60%)
- Usage frequency (25%)
- Recency of last use (15%)

Prefix matches get a bonus. Weights are configurable in `config.py`.

## Development

```bash
# Run tests
.venv\Scripts\python -m pytest tests/ -v

# Type checking
.venv\Scripts\python -m mypy *.py

# Run with debug logging
.venv\Scripts\python main.py --debug

# Run with a specific aircraft (bypasses interactive selection)
.venv\Scripts\python main.py --aircraft FA-18C_hornet
```

### Dependencies

- **PyQt6** -- overlay UI, system tray, settings dialog
- **RapidFuzz** -- fuzzy string matching
- **pynput** -- keyboard simulation for executing key-bound commands
- **pygame** -- joystick/HOTAS button reading

### Dev Dependencies

- **pytest** -- test framework
- **mypy** -- static type checking (strict mode)

## Supported Aircraft

Any aircraft with DCS-BIOS support. The palette auto-detects installed modules from the DCS installation directory. Keyboard shortcut parsing works for all standard DCS aircraft.

## License

MIT
