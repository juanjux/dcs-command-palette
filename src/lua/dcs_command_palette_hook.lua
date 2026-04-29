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

local function doLaunch(aircraft)
    local paletteDir = getPaletteDir()
    local executable, script = getExecutable(paletteDir)

    if not executable then
        log.write(paletteName, log.WARNING, "Palette executable not found in: " .. paletteDir)
        return
    end

    local aircraftDisplay = aircraft or "(unknown — letting palette use saved aircraft)"
    log.write(paletteName, log.INFO, "Starting palette for aircraft: " .. aircraftDisplay)

    -- Kill any leftover palette process from a previous DCS session.
    -- Avoids running two instances at once after upgrades, which causes
    -- the older instance to grab the hotkey and ignore the new code.
    -- /F = force, /T = also kill child processes, 2>nul silences output.
    os.execute('taskkill /F /IM dcs-command-palette.exe /T >nul 2>nul')

    -- Build the launch command.  Only pass --aircraft when we actually
    -- have a valid value.  Without it, the .exe uses the saved aircraft
    -- from settings.json, which is far better than "unknown".
    local aircraftArg = ""
    if aircraft then
        aircraftArg = ' --aircraft "' .. aircraft .. '"'
    end

    local cmd
    if script then
        -- Development mode: python.exe + main.py
        log.write(paletteName, log.INFO, "Python: " .. executable)
        log.write(paletteName, log.INFO, "Script: " .. script)
        cmd = 'start "" /B "' .. executable .. '" "' .. script .. '"' .. aircraftArg
    else
        -- Standalone .exe mode
        log.write(paletteName, log.INFO, "Executable: " .. executable)
        cmd = 'start "" /B "' .. executable .. '"' .. aircraftArg
    end

    log.write(paletteName, log.INFO, "Launching: " .. cmd)
    os.execute(cmd)

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
