## What's New in v1.0.0

### Performance
- **Instant first palette open** -- Pre-created UI widgets and pre-computed default search results eliminate the ~1 second delay on the first Ctrl+Space press.
- **Faster startup** -- DCS-BIOS TCP/UDP protocol detection now runs in a background thread instead of blocking for 500ms.
- **Search debounce** -- 40ms debounce on keystroke search prevents redundant work while typing quickly.
- **Instant settings dialog** -- ConfigWindow imports are pre-warmed in a background thread 2 seconds after startup.

### Bug Fixes
- **Palette not stopping when DCS closes** (v0.6.0) -- Fixed `PROJECT_DIR` resolving to `_internal/` in PyInstaller, which broke the Lua hook shutdown signal.
- **Settings reset on reinstall** (v0.6.0) -- Settings file now lives at the project root, surviving installer updates.
- **Multi-position switches skipping positions** (v0.6.0) -- Steps through intermediate positions for switches that only allow single-step movement.
- **DCS-BIOS commands not working** (v0.5.0) -- Auto-detects TCP vs UDP for DCS-BIOS command sending.
- **5-second settings window delay** (v0.4.0) -- Skips git calls in frozen executable.

### New Features
- **Toggle state animation** (v0.6.0) -- Binary switch toggles show a brief "OFF → ON" transition before closing.
- **Position labels from BIOS JSON** -- Selectors read labels from the DCS-BIOS `positions` array as a fallback source.

### Housekeeping
- Project metadata completed (description, authors, license, URLs in pyproject.toml)
- Build artifacts excluded from .gitignore

## Full Changelog
https://github.com/juanjux/dcs-command-palette/compare/v0.6.0...v1.0.0
