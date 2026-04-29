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

function paletteCallbacks.onSimulationStart()
    local paletteDir = getPaletteDir()
    local executable, script = getExecutable(paletteDir)

    if not executable then
        log.write(paletteName, log.WARNING, "Palette executable not found in: " .. paletteDir)
        return
    end

    -- Get the current aircraft type
    local aircraft = "unknown"
    local status, result = pcall(DCS.getPlayerUnitType)
    if status and result then
        aircraft = result
    end

    log.write(paletteName, log.INFO, "Starting palette for aircraft: " .. aircraft)

    -- Kill any leftover palette process from a previous DCS session.
    -- Avoids running two instances at once after upgrades, which causes
    -- the older instance to grab the hotkey and ignore the new code.
    -- /F = force, /T = also kill child processes, 2>nul silences output.
    os.execute('taskkill /F /IM dcs-command-palette.exe /T >nul 2>nul')

    -- Build the launch command
    local cmd
    if script then
        -- Development mode: python.exe + main.py
        log.write(paletteName, log.INFO, "Python: " .. executable)
        log.write(paletteName, log.INFO, "Script: " .. script)
        cmd = 'start "" /B "' .. executable .. '" "' .. script .. '" --aircraft "' .. aircraft .. '"'
    else
        -- Standalone .exe mode
        log.write(paletteName, log.INFO, "Executable: " .. executable)
        cmd = 'start "" /B "' .. executable .. '" --aircraft "' .. aircraft .. '"'
    end

    log.write(paletteName, log.INFO, "Launching: " .. cmd)
    os.execute(cmd)

    paletteProcess = true
end

function paletteCallbacks.onSimulationStop()
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
