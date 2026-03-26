-- DCS Command Palette - Export.lua integration
-- Add the following line to your Saved Games\DCS\Scripts\Export.lua:
--   dofile(lfs.writedir() .. "dcs-command-palette/dcs_command_palette_export.lua")
--
-- Then bind "Toggle Command Palette" in DCS Controls to your preferred key.

local palette_socket = nil
local palette_port = 7780

-- Open the UDP socket on first use
local function ensureSocket()
    if palette_socket then return true end
    local ok, sock = pcall(require, "socket")
    if not ok then
        return false
    end
    palette_socket = sock.udp()
    if palette_socket then
        palette_socket:settimeout(0)
        return true
    end
    return false
end

function DCSCommandPalette_Toggle()
    if ensureSocket() then
        palette_socket:sendto("TOGGLE_PALETTE\n", "127.0.0.1", palette_port)
    end
end
