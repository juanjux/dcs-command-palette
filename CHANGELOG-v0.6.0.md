## What's New in v0.6.0

### New Features
- **Toggle state animation** -- When toggling binary switches (OBOGS, ALT BARO/RDR, etc.), the palette now shows a brief state transition animation (e.g. "OFF  →  ON") before closing, giving visual confirmation of the action.

### Bug Fixes
- **Palette not stopping when DCS closes** -- The Lua hook shutdown signal (`.shutdown` file) was being written to the project root but checked inside `_internal/`. Fixed `PROJECT_DIR` to resolve correctly in PyInstaller frozen builds.
- **Settings reset on reinstall** -- `settings.json` was stored inside `_internal/` which gets overwritten by the installer. Now stored at the project root where it persists across updates.
- **Multi-position switches skipping positions** -- Some DCS switches only allow single-step movement. The palette now steps through intermediate positions with delays when the target is more than one step away.
- **Position labels from BIOS JSON** -- Selectors now read labels from the DCS-BIOS JSON `positions` array as a fallback, after keyboard entry enrichment (which remains the primary source for correct ordering).

## Full Changelog
https://github.com/juanjux/dcs-command-palette/compare/v0.5.0...v0.6.0
