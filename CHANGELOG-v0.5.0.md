## What's New in v0.5.0

### Bug Fixes
- **Fixed DCS-BIOS commands not working** -- The command sender now auto-detects whether DCS-BIOS is listening on TCP or UDP (port 7778). Modern DCS-BIOS versions (flightpanels fork) use TCP for receiving commands; the palette was previously sending via UDP only, which meant cockpit controls could not be actuated. The TCP connection is persistent with automatic reconnection on failure.
- **Improved position labels for multi-position switches** -- Selectors like INS, Radar, FLIR etc. now read position names directly from the DCS-BIOS JSON `positions` array (47 controls on the F/A-18C), instead of relying solely on keyboard entry enrichment.

## Full Changelog
https://github.com/juanjux/dcs-command-palette/compare/v0.4.0...v0.5.0
