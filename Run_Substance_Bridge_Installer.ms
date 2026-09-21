-- Substance Bridge - MZP Installer
-- Installs the 3ds Max macro, its toolbar icons, and the Substance Painter plugin.
-- Package all files listed below FLAT (same folder) next to this installer, then
-- zip + rename to .mzp.

(
    local sourceDir     = getFilenamePath (getThisScriptFilename())
    local userMacroDir  = getDir #userMacros
    local userIconDir   = getDir #userIcons

    -- Safe path join (getDir returns paths WITHOUT a trailing backslash)
    fn joinPath dir file = (
        local d = dir
        if d.count > 0 and d[d.count] != "\\" and d[d.count] != "/" do d += "\\"
        return d + file
    )

    fn getSPdocsRoot = (
        local docs = (dotnetclass "System.Environment").GetFolderPath \
                     (dotnetclass "System.Environment+SpecialFolder").MyDocuments
        return (docs + "\\Adobe\\Adobe Substance 3D Painter\\")
    )

    -- Resolve "...\Documents\Adobe\Adobe Substance 3D Painter\python\plugins"
    fn getSPpluginDir = ( getSPdocsRoot() + "python\\plugins\\" )

    -- Resolve "...\Documents\Adobe\Adobe Substance 3D Painter\assets\smart-masks"
    fn getSPsmartMaskDir = ( getSPdocsRoot() + "assets\\smart-masks\\" )

    -- Files that go into 3ds Max user macros
    local macroFiles = #( "Substance_Bridge_Injector.mcr" )

    -- Toolbar icon BMP pairs (legacy icon system) -> user icons
    local iconFiles = #(
        "SubstanceBridge_16i.bmp", "SubstanceBridge_16a.bmp",
        "SubstanceBridge_24i.bmp", "SubstanceBridge_24a.bmp"
    )

    -- Substance Painter plugin
    local spPluginFile = "SP_To_Max_Bridge.py"

    -- Substance Painter smart mask (weathering preset)
    local spSmartMaskFile = "SB_Weathering.spmsk"

    -- Ground-dirt texture — lives NEXT TO the .py plugin (plugin imports it)
    local spGroundTexFile = "aerial_grass_rock_diff.png"

    -- ── Generic copy helper (with delete/rename fallback if file is locked) ──
    fn installFile sourceFile targetDir = (
        local sourcePath = joinPath sourceDir sourceFile
        local targetPath = joinPath targetDir sourceFile

        if not (doesFileExist sourcePath) do (
            format "ERROR: source file not found: %\n" sourcePath
            return false
        )
        if not (doesFileExist targetDir) do makeDir targetDir all:true

        if doesFileExist targetPath do (
            if not (deleteFile targetPath) do (
                local stamp = substituteString ((getLocalTime()) as string) ":" "-"
                stamp = substituteString stamp " " "_"
                local backupPath = targetPath + ".old_" + stamp
                if not (renameFile targetPath backupPath) do (
                    format "ERROR: cannot overwrite locked file: %\n" targetPath
                    return false
                )
            )
        )

        if copyFile sourcePath targetPath then (
            format "Installed: %\n" targetPath
            return true
        ) else (
            format "ERROR: failed to copy %\n" sourceFile
            return false
        )
    )

    format "\n=== SUBSTANCE BRIDGE INSTALLER ===\n"
    format "Source folder: %\n\n" sourceDir

    local ok = true
    local spInstalled = false
    local iconCount = 0

    -- 1. Macro — this is the ONLY critical file. Install fails only if it fails.
    for f in macroFiles do ( if not (installFile f userMacroDir) do ok = false )

    -- 2. Icons (best-effort — missing icons just mean a button without an icon,
    --    they must NOT fail the whole install)
    for f in iconFiles do ( if (installFile f userIconDir) do iconCount += 1 )
    if iconCount < iconFiles.count do
        format "NOTE: % of % icon files installed (button may have no icon).\n" \
               iconCount iconFiles.count

    -- 3. Substance Painter plugin (best-effort — SP may not be installed)
    local spDir = getSPpluginDir()
    if doesFileExist (joinPath sourceDir spPluginFile) then (
        if installFile spPluginFile spDir then (
            spInstalled = true
        ) else (
            format "WARNING: could not install SP plugin automatically.\n"
        )
        -- ground-dirt texture goes next to the plugin
        if doesFileExist (joinPath sourceDir spGroundTexFile) do (
            installFile spGroundTexFile spDir
        )
    )

    -- 3b. Substance Painter weathering smart mask (best-effort)
    --     SP auto-scans assets\smart-masks on startup, so just drop it there.
    local smDir = getSPsmartMaskDir()
    if doesFileExist (joinPath sourceDir spSmartMaskFile) then (
        if installFile spSmartMaskFile smDir then (
            format "Installed weathering smart mask.\n"
        ) else (
            format "WARNING: could not install smart mask automatically.\n"
        )
    )

    -- 4. Reload macros
    if ok do (
        format "\nReloading macros...\n"
        try ( fileIn (joinPath userMacroDir "Substance_Bridge_Injector.mcr") ) catch ()
    )

    -- 5. Report
    if ok then (
        local spMsg = if spInstalled then \
            "Substance Painter plugin installed automatically.\nIn SP: Python menu - enable 'SP_To_Max_Bridge'.\n\n" \
        else \
            ("Substance Painter plugin was NOT auto-installed.\nCopy '" + spPluginFile + "' manually to:\n" + spDir + "\n\n")

        format "\n=== INSTALL COMPLETE ===\n"
        messageBox ( \
            "Substance Bridge installed!\n\n" + \
            "3ds Max:\n" + \
            "  Customize -> Customize User Interface -> Toolbars\n" + \
            "  Category: Physicl  ->  'Substance Bridge'\n\n" + \
            spMsg + \
            "You may need to restart 3ds Max for the icon to appear." \
        ) title:"Substance Bridge - Install Complete" beep:false
    ) else (
        format "\n=== INSTALL FAILED ===\n"
        messageBox ( \
            "Installation finished with errors.\n\n" + \
            "Check:\n" + \
            "1. Write access to 3ds Max user folders\n" + \
            "2. All files present in the package\n" + \
            "3. MAXScript Listener for details" \
        ) title:"Substance Bridge - Install Error" beep:true
    )

    format "\nMacros dir: %\n" userMacroDir
    format "Icons dir:  %\n" userIconDir
    format "SP plugins: %\n" spDir
    format "Done.\n"
)
