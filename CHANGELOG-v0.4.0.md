## What's New in v0.4.0

### Bug Fixes
- **Fixed 5-second delay opening Settings window** in the installed .exe -- The version info section was running `git rev-parse` with a 5-second timeout, which always timed out in the PyInstaller-frozen environment where there is no git repo. Now skips the git call when running as a frozen executable.
- **Fixed installer default path** -- The Inno Setup installer now correctly defaults to `Saved Games\DCS\dcs-command-palette` instead of resolving to the wrong directory.
- **Renamed "BIOS offline" to "DCS-BIOS offline"** for clarity.
- Removed debug profiling code from settings dialog and main module.

## Full Changelog
https://github.com/juanjux/dcs-command-palette/compare/v0.3.0...v0.4.0
