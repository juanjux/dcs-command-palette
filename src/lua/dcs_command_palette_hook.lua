-- DCS Command Palette Hook
-- Auto-starts the command palette when a mission begins and stops it when the mission ends.
-- Install by copying this file to: Saved Games\DCS\Scripts\Hooks\

local paletteName = "DCS Command Palette"
local paletteProcess = nil

-- Read the palette configuration to find paths
local function getPaletteDir()
    -- The hook file lives in Scripts/Hooks/, palette is in dcs-command-palette/
    local savedGamesDir = lfs.writedir()
    return savedGamesDir .. "dcs-command-palette\\"
end

local function readSettings(paletteDir)
    local settingsPath = paletteDir .. "settings.json"
    local f = io.open(settingsPath, "r")
    if not f then
        return nil
    end
    local content = f:read("*a")
    f:close()
    return content
end

local function fileExists(path)
    local f = io.open(path, "r")
    if f then
        f:close()
        return true
    end
    return false
end

local function getExecutable(paletteDir)
    -- Option 1: Standalone .exe (distributed build)
    local exePath = paletteDir .. "dcs-command-palette.exe"
    if fileExists(exePath) then
        return exePath, nil
    end

    -- Option 2: venv pythonw.exe + main.py (development)
    local mainScript = paletteDir .. "main.py"
    local venvPython = paletteDir .. ".venv\\Scripts\\pythonw.exe"
    if fileExists(venvPython) and fileExists(mainScript) then
        return venvPython, mainScript
    end

    -- Option 3: venv python.exe (fallback)
    venvPython = paletteDir .. ".venv\\Scripts\\python.exe"
    if fileExists(venvPython) and fileExists(mainScript) then
        return venvPython, mainScript
    end

    return nil, nil
end

local paletteCallbacks = {}

-- State for deferred launch.  In onSimulationStart the player unit may
-- not be spawned yet, so DCS.getPlayerUnitType() returns nil and the
-- palette would launch with --aircraft "unknown".  We retry on each
-- onSimulationFrame until we get a real type or we've waited long
-- enough — then launch (passing nothing if still unknown so the .exe
-- falls back to the saved aircraft instead of breaking).
--
-- Real campaigns and mission-editor briefings can leave the player in a
-- selection screen for many seconds (sometimes a minute+) before the
-- unit actually spawns.  We're patient: poll for 5 minutes total before
-- giving up.  Polling itself is essentially free.
local pendingLaunch = false
local launchAttempts = 0
local MAX_LAUNCH_ATTEMPTS = 18000  -- 5 minutes at 60 fps

local function tryGetAircraft()
    local status, result = pcall(DCS.getPlayerUnitType)
    if status and result and result ~= "" then
        return result
    end
    return nil
end

-- Run a command via a hidden VBScript wrapper.  Plain os.execute() goes
-- through cmd.exe /c, which briefly flashes a console window on screen
-- every time it's called.  By writing a tiny .vbs and invoking it with
-- wscript //B, we collapse the two console calls (taskkill + launch)
-- into a single very brief wscript launch — and the commands the .vbs
-- runs internally use WScript.Shell.Run with windowstyle=0, so they
-- never flash a window at all.
local function vbsEscape(s)
    -- VBScript escapes a double-quote by doubling it.
    -- Wrap in parens so the gsub count return value doesn't leak when
    -- this function is used as an extra arg to something.
    return (s:gsub('"', '""'))
end

local function runHidden(paletteDir, taskkillCmd, launchCmd)
    local vbsPath = paletteDir .. "_dcs_palette_launch.vbs"
    -- "wb": binary mode so we don't get \r\n doubled to \r\r\n by Lua's
    -- text-mode line-ending conversion on Windows.  Write explicit \r\n.
    local f = io.open(vbsPath, "wb")
    if not f then
        -- Falling back to plain os.execute on write failure; better a
        -- brief flash than no launch at all.
        log.write(paletteName, log.WARNING,
            "Could not write VBS wrapper at " .. vbsPath ..
            "; falling back to direct os.execute (will flash cmd).")
        os.execute(taskkillCmd)
        os.execute(launchCmd)
        return
    end

    f:write('Set sh = CreateObject("WScript.Shell")\r\n')
    -- Wait for taskkill (True) so the old process is gone before we spawn the new one.
    f:write('sh.Run "' .. vbsEscape(taskkillCmd) .. '", 0, True\r\n')
    -- Don't wait for the palette launch (False) — fire-and-forget.
    f:write('sh.Run "' .. vbsEscape(launchCmd) .. '", 0, False\r\n')
    f:close()

    -- wscript //B = batch mode, no UI dialogs.  cmd /c still flashes for
    -- ~10ms while it spawns wscript and exits, but only this once total.
    os.execute('wscript //B //Nologo "' .. vbsPath .. '"')
end

local function doLaunch(aircraft)
    local paletteDir = getPaletteDir()
    local executable, script = getExecutable(paletteDir)

    if not executable then
        log.write(paletteName, log.WARNING, "Palette executable not found in: " .. paletteDir)
        return
    end

    local aircraftDisplay = aircraft or "(unknown — letting palette use saved aircraft)"
    log.write(paletteName, log.INFO, "Starting palette for aircraft: " .. aircraftDisplay)

    -- Build the kill + launch commands.  These will be executed hidden
    -- via the VBS wrapper (see runHidden above) — no cmd flashes for
    -- the user to see during mission load.
    local taskkillCmd = 'taskkill /F /IM dcs-command-palette.exe /T'

    -- Only pass --aircraft when we actually have a valid value.  Without
    -- it, the .exe uses the saved aircraft from settings.json, which is
    -- far better than "unknown".
    local aircraftArg = ""
    if aircraft then
        aircraftArg = ' --aircraft "' .. aircraft .. '"'
    end

    local launchCmd
    if script then
        -- Development mode: python.exe + main.py
        log.write(paletteName, log.INFO, "Python: " .. executable)
        log.write(paletteName, log.INFO, "Script: " .. script)
        launchCmd = '"' .. executable .. '" "' .. script .. '"' .. aircraftArg
    else
        -- Standalone .exe mode
        log.write(paletteName, log.INFO, "Executable: " .. executable)
        launchCmd = '"' .. executable .. '"' .. aircraftArg
    end

    log.write(paletteName, log.INFO, "Launching: " .. launchCmd)
    runHidden(paletteDir, taskkillCmd, launchCmd)

    paletteProcess = true
end

function paletteCallbacks.onSimulationStart()
    -- Don't launch yet — the player unit isn't always ready here.
    -- onSimulationFrame will detect a valid aircraft name and launch.
    pendingLaunch = true
    launchAttempts = 0

    -- Try once immediately in case the unit is already there.
    local aircraft = tryGetAircraft()
    if aircraft then
        pendingLaunch = false
        doLaunch(aircraft)
    end
end

function paletteCallbacks.onSimulationFrame()
    if not pendingLaunch then
        return
    end

    launchAttempts = launchAttempts + 1
    local aircraft = tryGetAircraft()

    if aircraft then
        pendingLaunch = false
        doLaunch(aircraft)
    elseif launchAttempts >= MAX_LAUNCH_ATTEMPTS then
        -- Give up waiting; launch without --aircraft so the palette
        -- uses the previously-saved aircraft instead of "unknown".
        pendingLaunch = false
        log.write(paletteName, log.WARNING,
            "DCS.getPlayerUnitType() still nil after ~5 min; " ..
            "launching without --aircraft")
        doLaunch(nil)
    end
end

function paletteCallbacks.onSimulationStop()
    -- Cancel any deferred launch in case sim stops before we got a unit type.
    pendingLaunch = false

    if paletteProcess then
        log.write(paletteName, log.INFO, "Stopping palette process")
        -- Kill all pythonw.exe instances running main.py
        -- We use taskkill with the window title approach, but since pythonw has no window,
        -- we'll use a more targeted approach via a shutdown signal file
        local paletteDir = getPaletteDir()
        local shutdownFile = paletteDir .. ".shutdown"
        local f = io.open(shutdownFile, "w")
        if f then
            f:write("stop")
            f:close()
            log.write(paletteName, log.INFO, "Shutdown signal written to: " .. shutdownFile)
        end
        paletteProcess = nil
    end
end

DCS.setUserCallbacks(paletteCallbacks)
log.write(paletteName, log.INFO, "Hook loaded from: " .. debug.getinfo(1).source)
