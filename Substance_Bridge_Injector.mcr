macroScript Substance_Bridge
category:"Physicl"
tooltip:"Substance Painter Bridge"
buttonText:"SP Bridge"
icon:#("SubstanceBridge", 1)
(
    global substanceBridgeRollout
    -- Stop the monitor timer before destroying, then close any open instance.
    -- Prevents a crash when the toolbar button is pressed again while open.
    try (substanceBridgeRollout.tmr_checkSubstance.active = false) catch ()
    try (destroyDialog substanceBridgeRollout) catch ()

    -- =================================================================================================
    -- SETTINGS & PATHS
    -- =================================================================================================
    local projectPath = ""
    local fbxName = "SP_Export.fbx"
    local statusText = "Ready"
    local uv_channel = 3
    local isModelBaked = false

    fn updateStatus txt = (
        if substanceBridgeRollout != undefined do (
            substanceBridgeRollout.lblStatus.text = "Status: " + txt
            format "Bridge Status: %\n" txt
        )
    )
    
    fn getProjectPath = (
        projectPath = "C:\\SubstanceBridge\\"
        if not (doesFileExist projectPath) do makeDir projectPath
        return projectPath
    )

    -- =================================================================================================
    -- PROCESS & DIRECTORY HELPERS
    -- =================================================================================================
    fn isSubstanceRunning = (
        local processes = (dotnetclass "System.Diagnostics.Process").GetProcesses()
        local running = false
        for p in processes do (
            local pName = p.ProcessName
            if (matchPattern pName pattern:"*Substance*Painter*") or (matchPattern pName pattern:"*Substance 3D Painter*") do (
                running = true
            )
        )
        return running
    )

    fn cleanSubstanceExportFolder = (
        local path = getProjectPath() + "tex_sp\\"
        if (doesFileExist path) do (
            local files = getFiles (path + "*.*")
            for f in files do deleteFile f
        )
    )

    fn deleteFolderRecursive folderPath = (
        -- Strip a trailing slash — .NET Directory.Delete can throw on "C:\foo\".
        local p = folderPath
        while p.count > 0 and (p[p.count] == "\\" or p[p.count] == "/") do
            p = substring p 1 (p.count - 1)
        try (
            local dirClass = dotnetclass "System.IO.Directory"
            if dirClass.Exists p do dirClass.Delete p true
        ) catch (
            DOSCommand ("rmdir /s /q \"" + p + "\"")
        )
    )

    -- =================================================================================================
    -- BAKING HELPERS (from Dirt Injector)
    -- =================================================================================================
    
    fn getDiffuseMap mat = (
        if mat == undefined do return undefined
        if classOf mat == VRayMtl then return mat.texmap_diffuse
        else if classOf mat == PhysicalMaterial then return mat.base_color_map
        return undefined
    )

    fn setDiffuseMap mat map = (
        if mat == undefined do return false
        if classOf mat == VRayMtl then mat.texmap_diffuse = map
        else if classOf mat == PhysicalMaterial then mat.base_color_map = map
        return true
    )

    fn getBakePath filename = (
        local texDir = getProjectPath() + "temp_bkd\\"
        if not (doesFileExist texDir) do makeDir texDir
        return texDir + filename
    )

    fn closeVFB = (
        if (vrayVFBControl != undefined) then (
            try ( vrayVFBControl #show false ) catch ()
        )
        local windowsToClose = #("*V-Ray Frame Buffer*", "*V-Ray messages*")
        for w in (windows.getChildrenHWND 0) do (
            for titlePattern in windowsToClose do (
                if (matchPattern w[5] pattern:titlePattern) do (
                    windows.sendMessage w[1] 0x0010 0 0
                )
            )
        )
    )

    fn runBakePBR obj channel outputPrefix size:4096 = (
        if obj == undefined or obj.material == undefined do return #()
        
        local mat = obj.material
        local isVray = matchPattern ((renderers.current as string)) pattern:"*V_Ray*"
        local rtt = obj.INodeBakeProperties
        
        local origDiffuse = if classOf mat == VRayMtl then mat.texmap_diffuse else if isProperty mat #base_color_map then mat.base_color_map else if isProperty mat #diffuseMap then mat.diffuseMap else undefined
        local origNormal = if classOf mat == VRayMtl then mat.texmap_bump else if isProperty mat #bump_map then mat.bump_map else if isProperty mat #bumpMap then mat.bumpMap else undefined
        local origRough = if classOf mat == VRayMtl then mat.texmap_roughness else if isProperty mat #roughness_map then mat.roughness_map else if isProperty mat #roughnessMap then mat.roughnessMap else undefined
        
        -- Helper to swap diffuse
        fn swapDiffuse targetMat newMap = (
            if classOf targetMat == VRayMtl then targetMat.texmap_diffuse = newMap
            else if isProperty targetMat #base_color_map then targetMat.base_color_map = newMap
            else if isProperty targetMat #diffuseMap then targetMat.diffuseMap = newMap
        )
        
        local wasVFBOn = true
        local wasGIOn = false
        local wasDispOn = true
        local wasSamplerType = 1
        local wasMaxSubdivs = 24
        
        if isVray do (
            try (
                wasVFBOn = renderers.current.vfb_on
                wasGIOn = renderers.current.gi_on
                wasDispOn = renderers.current.options_displacement
                wasSamplerType = renderers.current.imageSampler_type
                wasMaxSubdivs = renderers.current.twoLevel_maxSubdivs
                
                renderers.current.vfb_on = false
                renderers.current.gi_on = false
                renderers.current.options_displacement = false
                renderers.current.imageSampler_type = 1 -- Bucket
                renderers.current.twoLevel_maxSubdivs = 1 -- Fast anti-aliasing
            ) catch ()
        )
        
        local bakedFiles = #()
        
        -- ==========================================
        -- 1. BAKE DIFFUSE
        -- ==========================================
        rtt.removeAllBakeElements()
        if origDiffuse != undefined do (
            local bakeFileD = getBakePath (outputPrefix + "_D.png")
            local beD = if isVray then (try(VRayDiffuseFilterMap())catch(diffuseMap())) else diffuseMap()
            beD.outputSzX = beD.outputSzY = size
            beD.fileType = bakeFileD; beD.fileName = bakeFileD; beD.filterOn = true; beD.enabled = true
            
            rtt.addBakeElement beD
            rtt.bakeEnabled = true
            rtt.bakeChannel = channel
            rtt.nDilations = 4
            
            render rendertype:#bakeSelected vfb:off progressBar:true outputSize:[size,size]
            closeVFB()
            append bakedFiles #(bakeFileD, "_D")
        )
        
        -- ==========================================
        -- 2. BAKE NORMAL (Via Diffuse Swap)
        -- ==========================================
        -- Extract the actual bitmap from the Normal_Bump node
        local extractedNormal = origNormal
        if classOf origNormal == Normal_Bump then extractedNormal = origNormal.normal_map
        else if classOf origNormal == VRayNormalMap then extractedNormal = origNormal.normal_map
        
        if extractedNormal != undefined do (
            rtt.removeAllBakeElements()
            swapDiffuse mat extractedNormal
            
            local bakeFileN = getBakePath (outputPrefix + "_N.png")
            local beN = if isVray then (try(VRayDiffuseFilterMap())catch(diffuseMap())) else diffuseMap()
            beN.outputSzX = beN.outputSzY = size
            beN.fileType = bakeFileN; beN.fileName = bakeFileN; beN.filterOn = true; beN.enabled = true
            
            rtt.addBakeElement beN
            rtt.bakeEnabled = true
            rtt.bakeChannel = channel
            rtt.nDilations = 4
            
            render rendertype:#bakeSelected vfb:off progressBar:true outputSize:[size,size]
            closeVFB()
            swapDiffuse mat origDiffuse -- Restore
            append bakedFiles #(bakeFileN, "_N")
        )
        
        -- ==========================================
        -- 3. BAKE ROUGHNESS (Via Diffuse Swap)
        -- ==========================================
        if origRough != undefined do (
            rtt.removeAllBakeElements()
            swapDiffuse mat origRough
            
            local bakeFileR = getBakePath (outputPrefix + "_R.png")
            local beR = if isVray then (try(VRayDiffuseFilterMap())catch(diffuseMap())) else diffuseMap()
            beR.outputSzX = beR.outputSzY = size
            beR.fileType = bakeFileR; beR.fileName = bakeFileR; beR.filterOn = true; beR.enabled = true
            
            rtt.addBakeElement beR
            rtt.bakeEnabled = true
            rtt.bakeChannel = channel
            rtt.nDilations = 4
            
            render rendertype:#bakeSelected vfb:off progressBar:true outputSize:[size,size]
            closeVFB()
            swapDiffuse mat origDiffuse -- Restore
            append bakedFiles #(bakeFileR, "_R")
        )
        
        if isVray do (
            try (
                renderers.current.vfb_on = wasVFBOn
                renderers.current.gi_on = wasGIOn
                renderers.current.options_displacement = wasDispOn
                renderers.current.imageSampler_type = wasSamplerType
                renderers.current.twoLevel_maxSubdivs = wasMaxSubdivs
            ) catch ()
        )
        
        -- ==========================================
        -- CREATE BITMAPS
        -- ==========================================
        local results = #()
        for res in bakedFiles do (
            if doesFileExist res[1] then (
                local tex = Bitmaptexture filename:res[1]
                local nodeName = case res[2] of (
                    "_D": "D"
                    "_R": "R"
                    "_N": "N"
                    "_M": "M"
                    default: res[2]
                )
                tex.name = nodeName
                append results #(res[2], tex)
            )
        )
        return results
    )

    -- =================================================================================================
    -- PHASE 1: PREPARE
    -- =================================================================================================
    
    fn step1_CreateUV3 = (
        local sel = selection as array
        if sel.count == 0 do (updateStatus "Error: Select objects!"; return false)
        
        for obj in sel do (
            undo "Bridge: Create UV3" on (
                local unw = Unwrap_UVW()
                addModifier obj unw
                select obj
                max modify mode
                modPanel.setCurrentObject unw
                unw.setMapChannel uv_channel
                local numFaces = unw.numberPolygons()
                unw.selectPolygons #{1..numFaces}
                unw.flattenMap 45.0 #() 0.01 true 0 true true
                collapseStack obj
            )
        )
        updateStatus "UV Channel 3 created."
    )

    fn autoOrientUVs unw polyObj = (
        local numFaces = unw.numberPolygons()
        local processedFaces = #{}
        
        local uvX=0.0, uvY=0.0, uvWidth=0.0, uvHeight=0.0, uvArea=0.0, uvGeomArea=0.0
        
        for i = 1 to numFaces do (
            if not processedFaces[i] do (
                unw.selectPolygons #{i}
                unw.selectElement()
                local elemFaces = unw.getSelectedPolygons()
                processedFaces += elemFaces
                
                local bmin = [1e9,1e9,1e9]
                local bmax = [-1e9,-1e9,-1e9]
                
                for f in elemFaces do (
                    local vIndices = polyop.getFaceVerts polyObj.baseObject f
                    for v in vIndices do (
                        local p = polyop.getVert polyObj.baseObject v
                        if p.x < bmin.x do bmin.x = p.x
                        if p.y < bmin.y do bmin.y = p.y
                        if p.z < bmin.z do bmin.z = p.z
                        if p.x > bmax.x do bmax.x = p.x
                        if p.y > bmax.y do bmax.y = p.y
                        if p.z > bmax.z do bmax.z = p.z
                    )
                )
                
                local width3D = distance [bmin.x, bmin.y, 0] [bmax.x, bmax.y, 0]
                local height3D = bmax.z - bmin.z
                
                local ratio3D = width3D / (height3D + 0.0001)
                
                if (ratio3D > 1.2) or (ratio3D < 0.8) do (
                    unw.getArea elemFaces &uvX &uvY &uvWidth &uvHeight &uvArea &uvGeomArea
                    local ratioUV = uvWidth / (uvHeight + 0.0001)
                    
                    if (ratio3D > 1.2 and ratioUV < 0.8) or (ratio3D < 0.8 and ratioUV > 1.2) do (
                        local cx = uvX + uvWidth / 2.0
                        local cy = uvY + uvHeight / 2.0
                        local center = [cx, cy, 0]
                        unw.moveSelected -center
                        unw.rotateSelected (pi / 2.0) [0,0,1]
                        unw.moveSelected center
                    )
                )
            )
        )
    )

    fn step1_CreateUV3_Optimized = (
        local sel = selection as array
        if sel.count == 0 do (updateStatus "Error: Select objects!"; return false)

        local angleThresh = 60.0
        local padding = 0.002

        for obj in sel do (
            undo "Bridge: Create UV3 Optimized" on (
                collapseStack obj
                convertToPoly obj

                local unw = Unwrap_UVW()
                addModifier obj unw
                select obj
                max modify mode
                modPanel.setCurrentObject unw
                unw.setMapChannel uv_channel
                local numFaces = unw.numberPolygons()
                unw.selectPolygons #{1..numFaces}

                -- 1. Initial Flatten with relaxed angle
                unw.flattenMap angleThresh #() padding true 0 true true

                -- 2. First Pack: Let Unfold3D straighten all islands perfectly (allows rotation)
                try (
                    unw.packMethod = 2
                    unw.packSpacing = padding
                    unw.packRotate = true
                    unw.packFillHoles = true
                    unw.pack 2 padding true true true
                ) catch (
                    unw.pack 1 padding true true true
                )

                -- 3. Auto Orient: Fixes any 90-degree rotations introduced by the packer
                autoOrientUVs unw obj

                -- 4. Re-select ALL polygons so the final pack includes everything
                unw.selectPolygons #{1..numFaces}

                -- 5. Second Pack: Final layout without rotation to preserve upright walls
                try (
                    unw.packMethod = 2
                    unw.packSpacing = padding
                    unw.packRotate = false
                    unw.packFillHoles = true
                    unw.pack 2 padding true false true
                ) catch (
                    unw.pack 1 padding true false true
                )

                collapseStack obj
            )
        )
        updateStatus "UV Channel 3 created (Opt: Unfold3D)."
    )

    fn step1_CreateUV1_Direct = (
        local sel = selection as array
        if sel.count == 0 do (updateStatus "Error: Select objects!"; return false)

        local angleThresh = 60.0
        local padding = 0.002

        for obj in sel do (
            undo "Bridge: Create UV1 Direct" on (
                collapseStack obj
                convertToPoly obj

                local unw = Unwrap_UVW()
                addModifier obj unw
                select obj
                max modify mode
                modPanel.setCurrentObject unw
                unw.setMapChannel 1
                local numFaces = unw.numberPolygons()
                unw.selectPolygons #{1..numFaces}

                -- 1. Initial Flatten with relaxed angle
                unw.flattenMap angleThresh #() padding true 0 true true

                -- 2. First Pack: Let Unfold3D straighten all islands perfectly (allows rotation)
                try (
                    unw.packMethod = 2
                    unw.packSpacing = padding
                    unw.packRotate = true
                    unw.packFillHoles = true
                    unw.pack 2 padding true true true
                ) catch (
                    unw.pack 1 padding true true true
                )

                -- 3. Auto Orient: Fixes any 90-degree rotations introduced by the packer
                autoOrientUVs unw obj

                -- 4. Re-select ALL polygons so the final pack includes everything
                unw.selectPolygons #{1..numFaces}

                -- 5. Second Pack: Final layout without rotation to preserve upright walls
                try (
                    unw.packMethod = 2
                    unw.packSpacing = padding
                    unw.packRotate = false
                    unw.packFillHoles = true
                    unw.pack 2 padding true false true
                ) catch (
                    unw.pack 1 padding true false true
                )

                collapseStack obj
            )
        )
        updateStatus "UV Channel 1 created (Unfold3D)."
    )

    fn step2_BakeAndPrepare = (
        local sel = selection as array
        if sel.count == 0 do (updateStatus "Error: Select objects!"; return false)
        
        local success = false
        for obj in sel where obj.material != undefined do (
            local results = runBakePBR obj uv_channel (obj.material.name + "_Base_Baked")
            if results.count > 0 then (
                success = true
                undo "Bridge: Bake & Prepare" on (
                    local mat = obj.material
                    
                    -- Assign baked maps to the material
                    for res in results do (
                        local tex = res[2]
                        if tex != undefined do (
                            tex.coords.mapChannel = uv_channel
                            if res[1] == "_D" then (
                                if classOf mat == VRayMtl then mat.texmap_diffuse = tex 
                                else if isProperty mat #base_color_map then mat.base_color_map = tex
                                else if isProperty mat #diffuseMap then mat.diffuseMap = tex
                            ) else if res[1] == "_N" then (
                                local nMap = Normal_Bump normal_map:tex
                                nMap.name = "N"
                                if classOf mat == VRayMtl then mat.texmap_bump = nMap 
                                else if isProperty mat #bump_map then mat.bump_map = nMap
                                else if isProperty mat #bumpMap then mat.bumpMap = nMap
                            ) else if res[1] == "_R" then (
                                if classOf mat == VRayMtl then mat.texmap_roughness = tex 
                                else if isProperty mat #roughness_map then mat.roughness_map = tex
                                else if isProperty mat #roughnessMap then mat.roughnessMap = tex
                            )
                        )
                    )
                    
                    -- Copy UVs
                    channelInfo.CopyChannel obj 3 3
                    channelInfo.PasteChannel obj 3 1
                    
                    -- Switch maps to use Channel 1
                    for res in results do (
                        if res[2] != undefined do res[2].coords.mapChannel = 1
                    )
                    
                    collapseStack obj
                )
            )
        )
        if success then (
            updateStatus "Bake PBR & Prepare complete."
            return true
        ) else (
            return false
        )
    )

    fn sbr_findMapPropertyName mat keywords = (
        -- Finds the property NAME of the opacity/cutout map slot on ANY material
        -- type by scanning its exposed properties, instead of hardcoding a slot
        -- name that varies between VRayMtl/PhysicalMaterial/versions. A candidate
        -- must mention "map" plus one of the keywords, and not be a companion
        -- "_on" toggle or "_amount" multiplier.
        local found = undefined
        try (
            local names = getPropNames mat
            for nm in names do (
                local nmLower = toLower (nm as string)
                if (matchPattern nmLower pattern:"*map*") do (
                    for kw in keywords while found == undefined do (
                        if (matchPattern nmLower pattern:("*" + kw + "*")) and \
                           not (matchPattern nmLower pattern:"*amount*") and \
                           not (matchPattern nmLower pattern:"*_on") do (
                            found = nm
                        )
                    )
                )
                if found != undefined do exit
            )
        ) catch ()
        return found
    )

    fn sbr_getOpacityMap mat = (
        -- Reads the current value of the auto-detected opacity/cutout property.
        local propName = sbr_findMapPropertyName mat #("opacity", "cutout", "alpha")
        if propName == undefined do return undefined
        local v = undefined
        try ( v = getProperty mat propName ) catch ()
        if v != undefined and (superClassOf v == textureMap) then v else undefined
    )

    fn sbr_debugDumpOpacityProps mat = (
        -- Diagnostic: print EVERY property whose name mentions opacity/cutout/
        -- alpha, with its current value — so we can see any "amount"/multiplier
        -- or threshold scalar that might be dampening the cutout even though
        -- the map itself is correctly assigned.
        try (
            local names = getPropNames mat
            for nm in names do (
                local nmLower = toLower (nm as string)
                if (matchPattern nmLower pattern:"*opac*") or \
                   (matchPattern nmLower pattern:"*cutout*") or \
                   (matchPattern nmLower pattern:"*alpha*") do (
                    local v = undefined
                    try ( v = getProperty mat nm ) catch ()
                    format "Bridge:   [prop] % = %\n" nm v
                )
            )
        ) catch ()
    )

    fn sbr_setOpacityMap mat tex = (
        -- Writes tex into the auto-detected opacity/cutout property, and enables
        -- its companion "<prop>_on" toggle if the material exposes one.
        format "Bridge: Opacity-related properties on '%' BEFORE assignment:\n" mat.name
        sbr_debugDumpOpacityProps mat

        local propName = sbr_findMapPropertyName mat #("opacity", "cutout", "alpha")
        if propName == undefined do return false
        try (
            setProperty mat propName tex
            local onProp = ((propName as string) + "_on") as name
            try ( setProperty mat onProp true ) catch ()
            -- Also force any companion "amount"/multiplier scalar to full
            -- strength, in case the material blends between opaque and the
            -- cutout map based on this value (defaulting below 1.0/100).
            local amountProp = ((propName as string) + "_amount") as name
            try ( setProperty mat amountProp 1.0 ) catch ()
            format "Bridge: Opacity assigned via property '%' on material '%'\n" propName mat.name

            format "Bridge: Opacity-related properties on '%' AFTER assignment:\n" mat.name
            sbr_debugDumpOpacityProps mat
            return true
        ) catch ( return false )
    )

    fn getBmpPath tex = (
        if tex == undefined do return undefined
        local cls = (classOf tex) as string

        -- 1. Standard bitmap
        if classOf tex == Bitmaptexture do return tex.fileName

        -- 2. V-Ray bitmap (VRayHDRI / VRayBitmap) — file is in .HDRIMapName
        if isProperty tex #HDRIMapName do return tex.HDRIMapName

        -- 3. Normal maps — recurse into the embedded sub-map
        if classOf tex == Normal_Bump do return getBmpPath tex.normal_map
        if (matchPattern cls pattern:"*VRayNormalMap*") and (isProperty tex #normal_map) do return getBmpPath tex.normal_map

        -- 4. Wrapper nodes (ColorCorrection, Output, Gamma&Gain, etc.)
        if isProperty tex #map do return getBmpPath tex.map
        if isProperty tex #sourceMap do return getBmpPath tex.sourceMap
        if isProperty tex #texmap do return getBmpPath tex.texmap

        -- 5. Generic fallback: any node exposing a file path
        if isProperty tex #fileName do return tex.fileName
        if isProperty tex #bitmap and tex.bitmap != undefined do return tex.bitmap.filename

        -- Diagnostic: unrecognized map type
        format "Bridge: getBmpPath could not resolve map of class '%'\n" cls
        return undefined
    )

    fn resolveTexPath p = (
        -- Bitmaps may store a RELATIVE path (e.g. "\textures\foo.png").
        -- Try to resolve it to a real file on disk.
        if p == undefined or p == "" do return undefined

        -- 1. Already a valid absolute path
        if doesFileExist p do return p

        -- 2. Use Max's own map-path resolver (searches configured bitmap paths)
        try (
            local resolved = mapPaths.getFullFilePath p
            if resolved != undefined and resolved != "" and (doesFileExist resolved) do return resolved
        ) catch ()

        -- 3. Combine with the .max scene folder (strip leading slashes first)
        if maxFilePath != "" do (
            local rel = p
            while rel.count > 0 and (rel[1] == "\\" or rel[1] == "/") do rel = substring rel 2 -1
            local combined = maxFilePath + rel
            if doesFileExist combined do return combined
        )

        return undefined
    )

    fn extractExistingTextures = (
        local bkdFolder = getProjectPath() + "temp_bkd\\"
        if not (doesFileExist bkdFolder) do makeDir bkdFolder
        
        local oldFiles = getFiles (bkdFolder + "*.*")
        for f in oldFiles do deleteFile f
        
        local sel = selection as array
        local count = 0

        for obj in sel where obj.material != undefined do (
            local mat = obj.material
            local isVray = matchPattern ((classOf mat) as string) pattern:"*VRayMtl*"

            format "Bridge: Extracting from '%' — material '%' (class: %)\n" \
                   obj.name mat.name ((classOf mat) as string)

            local dMap = if isVray then mat.texmap_diffuse else if isProperty mat #base_color_map then mat.base_color_map else if isProperty mat #diffuseMap then mat.diffuseMap else undefined
            local nMap = if isVray then mat.texmap_bump else if isProperty mat #bump_map then mat.bump_map else if isProperty mat #bumpMap then mat.bumpMap else undefined
            local rMap = if isVray then mat.texmap_roughness else if isProperty mat #roughness_map then mat.roughness_map else if isProperty mat #roughnessMap then mat.roughnessMap else undefined
            local mMap = if isVray then mat.texmap_metalness else if isProperty mat #metalness_map then mat.metalness_map else if isProperty mat #metalnessMap then mat.metalnessMap else undefined
            local aMap = sbr_getOpacityMap mat

            format "Bridge:   D=% N=% R=% M=% A=%\n" \
                   (if dMap == undefined then "none" else (classOf dMap) as string) \
                   (if nMap == undefined then "none" else (classOf nMap) as string) \
                   (if rMap == undefined then "none" else (classOf rMap) as string) \
                   (if mMap == undefined then "none" else (classOf mMap) as string) \
                   (if aMap == undefined then "none" else (classOf aMap) as string)

            local dPath = resolveTexPath (getBmpPath dMap)
            local nPath = resolveTexPath (getBmpPath nMap)
            local rPath = resolveTexPath (getBmpPath rMap)
            local mPath = resolveTexPath (getBmpPath mMap)
            local aPath = resolveTexPath (getBmpPath aMap)

            -- Name baked files by MATERIAL, not object: SP creates a Texture Set
            -- per material, so the names must match the material for auto-assign.
            local prefix = mat.name + "_Base_Baked"

            if dPath != undefined do (
                copyFile dPath (bkdFolder + prefix + "_D" + getFilenameType dPath)
                count += 1
            )
            if nPath != undefined do (
                copyFile nPath (bkdFolder + prefix + "_N" + getFilenameType nPath)
                count += 1
            )
            if rPath != undefined do (
                copyFile rPath (bkdFolder + prefix + "_R" + getFilenameType rPath)
                count += 1
            )
            if mPath != undefined do (
                copyFile mPath (bkdFolder + prefix + "_M" + getFilenameType mPath)
                count += 1
            )
            if aPath != undefined do (
                copyFile aPath (bkdFolder + prefix + "_A" + getFilenameType aPath)
                count += 1
            )
        )
        updateStatus ("Extracted " + (count as string) + " assigned textures.")
        return count
    )

    -- =================================================================================================
    -- PHASE 2: SUBSTANCE BRIDGE (EXPORT)
    -- =================================================================================================
    
    fn hasUVChannel1 obj = (
        -- Returns true if the object has intentional UV on channel 1.
        -- Parametric primitives without Unwrap_UVW modifier → false.
        local hasUV = false
        try (
            for m in obj.modifiers do (
                if classOf m == Unwrap_UVW do ( hasUV = true; exit )
            )
            if not hasUV do (
                local baseClass = classOf obj.baseObject
                if baseClass == Editable_Poly or baseClass == Editable_Mesh do (
                    local snap = snapshotAsMesh obj
                    hasUV = snap.numTVerts > 0
                    delete snap
                )
            )
        ) catch ( hasUV = false )
        return hasUV
    )

    fn validateUVQuality obj = (
        -- Returns #(outOfBounds, hasOverlaps, isDegenerate)
        -- outOfBounds:  any TV vert outside [0,1]
        -- hasOverlaps:  total UV face area > 1.05 (islands stacked on top = overlaps)
        -- isDegenerate: total UV face area < 0.05 (islands collapsed/squashed into a
        --               sliver = broken unwrap, e.g. all faces welded into a line)
        local outOfBounds = false
        local hasOverlaps = false
        local isDegenerate = false
        try (
            local snap = snapshotAsMesh obj

            -- Bounds check
            for i = 1 to snap.numTVerts do (
                local tv = getTVert snap i
                if tv.x < -0.001 or tv.x > 1.001 or tv.y < -0.001 or tv.y > 1.001 do (
                    outOfBounds = true
                    exit
                )
            )

            -- Sum of UV triangle areas AND a coverage grid of really-painted cells.
            -- Good unwrap: sum of areas ≈ covered area (islands don't stack).
            -- Overlapping unwrap: sum of areas >> covered area (islands pile up),
            --   so the ratio area_uv / covered spikes — this catches stacked
            --   islands even when their total area stays under one tile.
            local N = 64
            local grid = #{}
            local area_uv = 0.0
            for i = 1 to snap.numFaces do (
                local tvFace = getTVFace snap i
                local tv1 = getTVert snap tvFace.x
                local tv2 = getTVert snap tvFace.y
                local tv3 = getTVert snap tvFace.z
                local e1 = tv2 - tv1
                local e2 = tv3 - tv1
                area_uv += (abs (e1.x * e2.y - e1.y * e2.x)) / 2.0

                -- mark grid cells inside this triangle's UV bbox (clamped 0..1)
                local minU = amin tv1.x tv2.x tv3.x
                local maxU = amax tv1.x tv2.x tv3.x
                local minV = amin tv1.y tv2.y tv3.y
                local maxV = amax tv1.y tv2.y tv3.y
                if minU < 0.0 do minU = 0.0
                if minV < 0.0 do minV = 0.0
                if maxU > 1.0 do maxU = 1.0
                if maxV > 1.0 do maxV = 1.0
                local c0 = (minU * (N - 1)) as integer
                local c1 = (maxU * (N - 1)) as integer
                local r0 = (minV * (N - 1)) as integer
                local r1 = (maxV * (N - 1)) as integer
                for r = r0 to r1 do for c = c0 to c1 do grid[(r * N) + c + 1] = true
            )

            local covered = (grid.numberSet as float) / (N * N)
            local ratio = area_uv / (covered + 0.0001)

            hasOverlaps  = (area_uv > 1.05) or (ratio > 1.8)
            isDegenerate = (snap.numFaces > 0) and (area_uv < 0.05)

            format "Bridge UV Quality: % → oob=% overlaps=% degenerate=% (area=% covered=% ratio=%)\n" \
                   obj.name outOfBounds hasOverlaps isDegenerate area_uv covered ratio

            delete snap
        ) catch ()
        return #(outOfBounds, hasOverlaps, isDegenerate)
    )

    global sbr_uvChoice
    global sbr_uvInfoText = ""
    fn sbr_badUVDialog infoText = (
        -- 3-choice dialog: Re-create / Keep current / Cancel. queryBox only does
        -- Yes/No, so we use a small modal rollout. Data passes via globals —
        -- rollout handlers cannot reference outer LOCAL variables in MAXScript.
        sbr_uvChoice = #cancel
        sbr_uvInfoText = infoText
        rollout uvdlg "Bridge: Bad UV Detected" width:360 height:210 (
            label lblHdr "WARNING: Invalid UV detected!" pos:[15,12] width:330
            edittext etInfo "" pos:[15,32] width:330 height:80 readOnly:true
            label lblQ "You can re-create a simple UV, keep the current one," pos:[15,118] width:330
            label lblQ2 "or cancel the export." pos:[15,134] width:330
            button btnRecreate "Re-create Simple UV" pos:[15,158] width:330 height:26
            button btnKeep "Keep Current UVs (send as-is)" pos:[15,186] width:200 height:22
            button btnCancel "Cancel" pos:[225,186] width:120 height:22
            on uvdlg open do etInfo.text = sbr_uvInfoText
            on btnRecreate pressed do ( sbr_uvChoice = #recreate; destroyDialog uvdlg )
            on btnKeep pressed do ( sbr_uvChoice = #keep; destroyDialog uvdlg )
            on btnCancel pressed do ( sbr_uvChoice = #cancel; destroyDialog uvdlg )
        )
        createDialog uvdlg modal:true
        return sbr_uvChoice
    )

    fn checkAndEnsureUV = (
        local sel = selection as array
        if sel.count == 0 do ( updateStatus "Error: Select objects!"; return false )

        -- Pass 1: objects with NO UV at all
        local noUVObjects = #()
        for obj in sel do (
            if not (hasUVChannel1 obj) do append noUVObjects obj
        )

        if noUVObjects.count > 0 do (
            local names = ""
            for i = 1 to (amin noUVObjects.count 3) do
                names += "  - " + noUVObjects[i].name + "\n"
            if noUVObjects.count > 3 do
                names += "  ... and " + ((noUVObjects.count - 3) as string) + " more\n"

            local answer = queryBox ("The following objects have NO UV unwrap:\n\n" + names + \
                                     "\nCreate Simple UV automatically and continue?") \
                                    title:"Bridge: No UV Detected"
            if answer then (
                select noUVObjects
                step1_CreateUV1_Direct()
                select sel
            ) else (
                updateStatus "Export cancelled — no UV on selected objects."
                return false
            )
        )

        -- Pass 2: objects with UV but bad quality (out of bounds / overlaps / degenerate)
        local badUVObjects = #()
        local badUVReasons = #()
        for obj in sel do (
            if hasUVChannel1 obj do (
                local quality = validateUVQuality obj
                local oob = quality[1]
                local ovr = quality[2]
                local deg = quality[3]
                if oob or ovr or deg do (
                    local reason = ""
                    if deg then reason = "degenerate/collapsed unwrap"
                    else if oob and ovr then reason = "out of bounds + overlapping"
                    else if oob then reason = "out of bounds (outside 0-1 tile)"
                    else reason = "overlapping UV islands"
                    append badUVObjects obj
                    append badUVReasons reason
                )
            )
        )

        if badUVObjects.count > 0 do (
            local names = ""
            for i = 1 to (amin badUVObjects.count 3) do
                names += "  - " + badUVObjects[i].name + " [" + badUVReasons[i] + "]\n"
            if badUVObjects.count > 3 do
                names += "  ... and " + ((badUVObjects.count - 3) as string) + " more\n"

            local infoText = "These objects have invalid UVs:\r\n" + \
                             (substituteString names "\n" "\r\n")
            local choice = sbr_badUVDialog infoText
            case choice of (
                #recreate: (
                    select badUVObjects
                    step1_CreateUV1_Direct()
                    select sel
                )
                #keep: (
                    updateStatus "Keeping current UVs — sending as-is."
                )
                default: (
                    updateStatus "Export cancelled — bad UV on selected objects."
                    return false
                )
            )
        )

        return true
    )

    fn ensureObjectNamedMaterials = (
        -- SP creates one Texture Set per MATERIAL name. To get a predictable
        -- Texture Set per object, give every selected object a material named
        -- after the object. If the name already matches, do nothing.
        --
        -- IMPORTANT: prefer RENAMING the existing material (keeps ALL params:
        -- reflection, IOR, etc.). Only COPY when the material is shared by other
        -- objects — and `copy` on VRayMtl can reset some params, so we restore
        -- the critical reflection settings onto the copy afterwards.
        local sel = selection as array
        for obj in sel where obj.material != undefined do (
            if obj.material.name != obj.name do (
                local srcMat = obj.material
                -- count how many scene objects use this exact material
                local users = 0
                for o in objects where o.material == srcMat do users += 1

                undo "Bridge: Name material after object" on (
                    if users <= 1 then (
                        -- Unique material → just rename. Nothing is lost.
                        srcMat.name = obj.name
                        format "Bridge: Renamed material of '%' (params kept).\n" obj.name
                    ) else (
                        -- Shared material → copy so other objects aren't touched.
                        local newMat = copy srcMat
                        newMat.name = obj.name
                        -- Restore reflection params that copy may have reset (VRayMtl)
                        if (classOf srcMat == VRayMtl) and (classOf newMat == VRayMtl) do (
                            try ( newMat.reflection_color      = srcMat.reflection_color )      catch ()
                            try ( newMat.reflection_glossiness = srcMat.reflection_glossiness ) catch ()
                            try ( newMat.reflection_ior        = srcMat.reflection_ior )        catch ()
                            try ( newMat.reflection_fresnel    = srcMat.reflection_fresnel )    catch ()
                            try ( newMat.reflection_lockIOR    = srcMat.reflection_lockIOR )    catch ()
                            try ( newMat.refraction_ior        = srcMat.refraction_ior )        catch ()
                            try ( newMat.brdf_type             = srcMat.brdf_type )             catch ()
                        )
                        obj.material = newMat
                        format "Bridge: Copied shared material for '%' (refl/IOR restored).\n" obj.name
                    )
                )
            )
        )
    )

    fn exportToSubstance withTextures:false = (
        local sel = selection as array
        if sel.count == 0 do (updateStatus "Error: Select objects!"; return false)
        
        local path = getProjectPath()
        local fbxExportPath = path + fbxName
        local bkdFolder = path + "temp_bkd\\"
        if not (doesFileExist bkdFolder) do makeDir bkdFolder
        
        -- Configure FBX Settings for Substance
        FBXExporterSetParam "SelectionOnly" true
        FBXExporterSetParam "SmoothingGroups" true
        FBXExporterSetParam "TangentsBinormals" true
        FBXExporterSetParam "PreserveEdgeOrientation" true
        FBXExporterSetParam "ConvertUnitString" "cm"
        FBXExporterSetParam "ASCII" false
        FBXExporterSetParam "UpAxis" "Y"
        FBXExporterSetParam "EmbedTextures" withTextures
        
        -- Export
        exportFile fbxExportPath #noPrompt selectedOnly:true
        
        local msg = if withTextures then "Exported (With Textures)" else "Exported (No Textures)"
        updateStatus msg
        return true
    )

    fn launchSubstance = (
        local projectDir = getProjectPath()
        local fbxPath = projectDir + fbxName

        if not (doesFileExist fbxPath) then (
            updateStatus "Error: Export model first!"
            return false
        )

        cleanSubstanceExportFolder()

        local sppFiles = getFiles (projectDir + "*.spp")
        local targetToOpen = if sppFiles.count > 0 then sppFiles[1] else ""

        local spPath = "C:\\Program Files\\Adobe\\Adobe Substance 3D Painter\\Adobe Substance 3D Painter.exe"
        if doesFileExist spPath then (
            if targetToOpen != "" then (
                shellLaunch spPath ("\"" + targetToOpen + "\"")
                updateStatus "Opening existing project..."
            ) else (
                shellLaunch spPath ""
                updateStatus "Launching SP & Auto-creating project..."
            )
            substanceBridgeRollout.tmr_checkSubstance.active = true
            updateStatus "Monitoring Substance Painter..."
        ) else (
            shellLaunch "explorer.exe" projectDir
            updateStatus "Substance not found. Opening folder."
        )
    )

    -- =================================================================================================
    -- PHASE 3: IMPORT & ASSIGN
    -- =================================================================================================
    
    fn importTextures = (
        local path = getProjectPath() + "temp_bkd\\"
        if not (doesFileExist path) do (updateStatus "Error: Folder 'temp_bkd' not found!"; return false)
        
        local files = getFiles (path + "*.*")
        if files.count == 0 do (updateStatus "Error: No textures in 'temp_bkd'!"; return false)
        
        local count = 0
        for obj in selection do (
            if obj.material == undefined do (
                if (queryBox ("Object '" + obj.name + "' has no material. Create V-Ray Material?") title:"Bridge") then (
                    obj.material = VRayMtl()
                    obj.material.name = obj.name + "_Mtl"
                ) else continue
            )
            
            local mat = obj.material
            local objName = obj.name
            local isVray = (classOf mat == VRayMtl)
            
            for f in files do (
                local fileName = filenameFromPath f
                
                -- Support robust Substance suffixes
                if matchPattern fileName pattern:("*BaseColor*") or matchPattern fileName pattern:("*Base_Color*") or matchPattern fileName pattern:("*Diffuse*") or matchPattern fileName pattern:("*Albedo*") do (
                    local tex = Bitmaptexture fileName:f
                    tex.name = "D"
                    if isVray then mat.texmap_diffuse = tex
                    else if isProperty mat #base_color_map then mat.base_color_map = tex
                    else if isProperty mat #diffuseMap then mat.diffuseMap = tex
                    count += 1
                )
                
                if matchPattern fileName pattern:("*Normal*") do (
                    local tex = Bitmaptexture fileName:f
                    tex.name = "N"
                    local nMap = Normal_Bump()
                    nMap.name = "N"
                    nMap.normal_map = tex
                    if isVray then mat.texmap_bump = nMap
                    else if isProperty mat #bumpMap then mat.bumpMap = nMap
                    count += 1
                )
                
                if matchPattern fileName pattern:("*Roughness*") or matchPattern fileName pattern:("*Rough*") do (
                    local tex = Bitmaptexture fileName:f
                    tex.name = "R"
                    if isVray then mat.texmap_roughness = tex
                    else if isProperty mat #roughnessMap then mat.roughnessMap = tex
                    count += 1
                )
                
                if matchPattern fileName pattern:("*Metallic*") or matchPattern fileName pattern:("*Metalness*") or matchPattern fileName pattern:("*Metal*") do (
                    local tex = Bitmaptexture fileName:f
                    tex.name = "M"
                    if isVray then mat.texmap_metalness = tex
                    else if isProperty mat #metalnessMap then mat.metalnessMap = tex
                    count += 1
                )
            )
        )
        updateStatus ("Imported " + (count as string) + " textures.")
    )

    fn sbr_copyTexSettings oldTex newTex = (
        -- Preserve whatever Bitmap Parameters (Mono Channel Output, Alpha
        -- Source, RGB Channel Output, Premultiplied Alpha, Filtering, etc.)
        -- were already set on the texture being replaced — e.g. a D map
        -- manually set to Mono Channel Output: Alpha before ever going to
        -- Substance should still have that after re-import, since the new
        -- Bitmaptexture sbr_makeTex creates is a blank object with none of
        -- that carried over. Copies every property except the file path
        -- itself (that must stay pointed at the freshly imported file).
        if oldTex == undefined or newTex == undefined do return false
        if classOf oldTex != Bitmaptexture or classOf newTex != Bitmaptexture do return false
        local skipProps = #(#filename, #bitmap)
        for p in (getPropNames oldTex) do (
            if (findItem skipProps p) == 0 do (
                try ( setProperty newTex p (getProperty oldTex p) ) catch ()
            )
        )
        true
    )

    fn sbr_makeTex path isLinear = (
        -- Non-color maps (Roughness, Normal, Metalness) must be loaded with
        -- Gamma Override = 1.0. Only BaseColor stays sRGB/automatic.
        -- NOTE: this used to also force filtering:None on cutout D/A maps
        -- to keep the Opacity edge crisp (avoid mip-blur halo). Removed —
        -- setting .filtering on the texmap, even deferred until after
        -- material assignment, still left the bitmap stuck black in the
        -- viewport/render until the user manually hit Reload, even though
        -- the file on disk was fine. Opacity/cutout maps now use default
        -- Pyramidal filtering like everything else.
        if isLinear then (
            local tt = Bitmaptexture()
            tt.bitmap = openBitMap path gamma:1.0
            tt
        ) else (
            Bitmaptexture fileName:path
        )
    )

    fn importSubstanceTextures = (
        local path = getProjectPath() + "tex_sp\\"
        if not (doesFileExist path) do (updateStatus "Error: Folder 'tex_sp' not found!"; return false)
        
        local files = getFiles (path + "*.png")
        if files.count == 0 do (updateStatus "Error: No textures in 'tex_sp'!"; return false)
        
        local projectRoot = if maxFilePath != "" then maxFilePath else ((getDir #temp) + "\\")
        local texturesFolder = projectRoot + "textures\\"
        if not (doesFileExist texturesFolder) do makeDir texturesFolder
        
        -- Copy and rename files from tex_sp to textures/
        local textureMappings = #()
        for f in files do (
            local baseName = getFilenameFile f
            local suffix = ""
            local matPart = ""
            
            if (matchPattern baseName pattern:"*_D") then ( suffix = "_D"; matPart = substring baseName 1 (baseName.count - 2) )
            else if (matchPattern baseName pattern:"*_R") then ( suffix = "_R"; matPart = substring baseName 1 (baseName.count - 2) )
            else if (matchPattern baseName pattern:"*_M") then ( suffix = "_M"; matPart = substring baseName 1 (baseName.count - 2) )
            else if (matchPattern baseName pattern:"*_N") then ( suffix = "_N"; matPart = substring baseName 1 (baseName.count - 2) )
            else if (matchPattern baseName pattern:"*_A") then ( suffix = "_A"; matPart = substring baseName 1 (baseName.count - 2) )
            
            if suffix != "" do (
                -- File name is just "<model/material>_suffix" (scene name prefix
                -- dropped to avoid overly long file names).
                local newFileName = matPart + suffix + ".png"
                local newFilePath = texturesFolder + newFileName
                
                if (doesFileExist newFilePath) do deleteFile newFilePath
                copyFile f newFilePath

                append textureMappings #(f, newFilePath, baseName, matPart, suffix)
            )
        )

        local count = 0
        local matchedObjects = #()

        for obj in selection do (
            if obj.material == undefined do (
                if (queryBox ("Object '" + obj.name + "' has no material. Create V-Ray Material?") title:"Bridge") then (
                    obj.material = VRayMtl()
                    obj.material.name = obj.name + "_Mtl"
                ) else continue
            )

            local mat = obj.material
            local objName = obj.name
            local isVray = (classOf mat == VRayMtl)
            local matName = mat.name

            for m in textureMappings do (
                if (matchPattern m[4] pattern:matName) or (matchPattern m[4] pattern:objName) do (
                    local isLin = (m[5] == "_R" or m[5] == "_N" or m[5] == "_M" or m[5] == "_A")
                    -- Capture whatever texture is CURRENTLY in this slot
                    -- before it gets replaced, so its Bitmap Parameters
                    -- (Mono Channel Output, Alpha Source, etc.) can be
                    -- carried over to the freshly imported one.
                    local oldTex = case m[5] of (
                        "_D": (if isVray then mat.texmap_diffuse else if isProperty mat #base_color_map then mat.base_color_map else if isProperty mat #diffuseMap then mat.diffuseMap else undefined)
                        "_R": (if isVray then mat.texmap_roughness else if isProperty mat #roughnessMap then mat.roughnessMap else undefined)
                        "_M": (if isVray then mat.texmap_metalness else if isProperty mat #metalnessMap then mat.metalnessMap else undefined)
                        "_A": sbr_getOpacityMap mat
                        default: undefined
                    )
                    local tex = sbr_makeTex m[2] isLin
                    sbr_copyTexSettings oldTex tex
                    local nodeName = case m[5] of (
                        "_D": "D"
                        "_R": "R"
                        "_N": "N"
                        "_M": "M"
                        "_A": "A"
                        default: m[5]
                    )
                    tex.name = nodeName
                    tex.coords.mapChannel = 1

                    if m[5] == "_D" then (
                        if isVray then mat.texmap_diffuse = tex
                        else if isProperty mat #base_color_map then mat.base_color_map = tex
                        else if isProperty mat #diffuseMap then mat.diffuseMap = tex
                        count += 1
                        appendIfUnique matchedObjects obj
                    )
                    else if m[5] == "_R" then (
                        if isVray then (
                            mat.texmap_roughness = tex
                            mat.roughness_useRoughness = 1
                        )
                        else if isProperty mat #roughnessMap then mat.roughnessMap = tex
                        count += 1
                        appendIfUnique matchedObjects obj
                    )
                    else if m[5] == "_M" then (
                        if isVray then mat.texmap_metalness = tex
                        else if isProperty mat #metalnessMap then mat.metalnessMap = tex
                        count += 1
                        appendIfUnique matchedObjects obj
                    )
                    else if m[5] == "_N" then (
                        local nMap = if isVray then (
                            try(VRayNormalMap normal_map:tex)catch(Normal_Bump normal_map:tex)
                        ) else (
                            Normal_Bump normal_map:tex
                        )
                        nMap.name = "N"
                        if isVray then mat.texmap_bump = nMap
                        else if isProperty mat #bumpMap then mat.bumpMap = nMap
                        count += 1
                        appendIfUnique matchedObjects obj
                    )
                    else if m[5] == "_A" then (
                        if sbr_setOpacityMap mat tex then (
                            count += 1
                            appendIfUnique matchedObjects obj
                        ) else (
                            format "Bridge: No opacity/cutout map property found on material '%'\n" mat.name
                        )
                    )
                )
            )
        )

        if count == 0 do (
            for obj in objects where obj.material != undefined do (
                local mat = obj.material
                local objName = obj.name
                local isVray = (classOf mat == VRayMtl)
                local matName = mat.name
                
                for m in textureMappings do (
                    if (matchPattern m[4] pattern:matName) or (matchPattern m[4] pattern:objName) do (
                        local isLin = (m[5] == "_R" or m[5] == "_N" or m[5] == "_M" or m[5] == "_A")
                        local oldTex = case m[5] of (
                            "_D": (if isVray then mat.texmap_diffuse else if isProperty mat #base_color_map then mat.base_color_map else if isProperty mat #diffuseMap then mat.diffuseMap else undefined)
                            "_R": (if isVray then mat.texmap_roughness else if isProperty mat #roughnessMap then mat.roughnessMap else undefined)
                            "_M": (if isVray then mat.texmap_metalness else if isProperty mat #metalnessMap then mat.metalnessMap else undefined)
                            "_A": sbr_getOpacityMap mat
                            default: undefined
                        )
                        local tex = sbr_makeTex m[2] isLin
                        sbr_copyTexSettings oldTex tex
                        local nodeName = case m[5] of (
                            "_D": "D"
                            "_R": "R"
                            "_N": "N"
                            "_M": "M"
                            "_A": "A"
                            default: m[5]
                        )
                        tex.name = nodeName
                        tex.coords.mapChannel = 1

                        if m[5] == "_D" then (
                            if isVray then mat.texmap_diffuse = tex
                            else if isProperty mat #base_color_map then mat.base_color_map = tex
                            else if isProperty mat #diffuseMap then mat.diffuseMap = tex
                            count += 1
                            appendIfUnique matchedObjects obj
                        )
                        else if m[5] == "_R" then (
                            if isVray then (
                                mat.texmap_roughness = tex
                                mat.roughness_useRoughness = 1
                            )
                            else if isProperty mat #roughnessMap then mat.roughnessMap = tex
                            count += 1
                            appendIfUnique matchedObjects obj
                        )
                        else if m[5] == "_M" then (
                            if isVray then mat.texmap_metalness = tex
                            else if isProperty mat #metalnessMap then mat.metalnessMap = tex
                            count += 1
                            appendIfUnique matchedObjects obj
                        )
                        else if m[5] == "_N" then (
                            local nMap = if isVray then (
                                try(VRayNormalMap normal_map:tex)catch(Normal_Bump normal_map:tex)
                            ) else (
                                Normal_Bump normal_map:tex
                            )
                            nMap.name = "N"
                            if isVray then mat.texmap_bump = nMap
                            else if isProperty mat #bumpMap then mat.bumpMap = nMap
                            count += 1
                            appendIfUnique matchedObjects obj
                        )
                        else if m[5] == "_A" then (
                            if sbr_setOpacityMap mat tex then (
                                count += 1
                                appendIfUnique matchedObjects obj
                            ) else (
                                format "Bridge: No opacity/cutout map property found on material '%'\n" mat.name
                            )
                        )
                    )
                )
            )
        )

        if count > 0 then (
            updateStatus ("Auto-imported " + (count as string) + " textures.")
            if matchedObjects.count > 0 do select matchedObjects
            
            -- Success! Clean up Substance_Work recursive
            local workDir = getProjectPath()
            deleteFolderRecursive workDir
        ) else (
            updateStatus "Error: No matching textures found in 'tex_sp'!"
        )
        return (count > 0)
    )

    -- =================================================================================================
    -- UI
    -- =================================================================================================
    
    -- =================================================================================================
    -- UI SUB-ROLLOUTS
    -- =================================================================================================
    
    /*
    rollout rollPrep "1. Model Preparation"
    (
        -- button btnStep1Opt "1. CREATE UV3 (OPTIMIZED UNFOLD3D)" width:275 height:35 color:(color 180 180 255)
        button btnStep1UV1 "CREATE SIMPLE UV" width:275 height:35 color:(color 200 200 255)
        label lblUV1Info1 "Click here if your model has NO UV unwrap." align:#center offset:[0,2]
        label lblUV1Info2 "If the model ALREADY HAS UVs — DO NOT click." align:#center offset:[0,0] color:(color 255 180 80)
        -- button btnStep2 "2. BAKE & PREPARE (UV1)" width:275 height:35 color:(color 200 230 255) offset:[0,5]
        -- checkbox chkModelBaked "Model Baked" enabled:false align:#center offset:[0,5]

        -- on btnStep1Opt pressed do step1_CreateUV3_Optimized()
        on btnStep1UV1 pressed do step1_CreateUV1_Direct()
        -- on btnStep2 pressed do (
        --     if step2_BakeAndPrepare() == true do (
        --         chkModelBaked.checked = true
        --         isModelBaked = true
        --     )
        -- )
    )
    */

    -- =================================================================================================
    -- UI
    -- =================================================================================================

    local sbr_iniFile = ((getdir #userscripts) + "\\SubstanceBridge\\SubstanceBridge_settings.ini")

    fn sbr_savePosToIni = (
        -- Wrapped in try: getDialogPos crashes if called while the dialog is
        -- being destroyed (e.g. re-pressing the toolbar button).
        try (
            if substanceBridgeRollout != undefined do (
                local pos = getDialogPos substanceBridgeRollout
                setINISetting sbr_iniFile "Position" "PosX" (pos.x as string)
                setINISetting sbr_iniFile "Position" "PosY" (pos.y as string)
            )
        ) catch ()
    )

    fn sbr_loadPos = (
        local x = (getINISetting sbr_iniFile "Position" "PosX") as integer
        local y = (getINISetting sbr_iniFile "Position" "PosY") as integer
        if x == 0 do x = 100
        if y == 0 do y = 100
        [x, y]
    )

    rollout substanceBridgeRollout "Substance Bridge v2.8.4" width:200 height:100
    (
        -- Main action button
        button btnExport "SEND TO PAINTER" pos:[10,10] width:180 height:50 \
            color:(color 60 130 60)

        -- Status
        label lblStatus "Ready" pos:[0,68] width:200 align:#center \
            color:(color 130 130 130)

        -- Hidden timer
        Timer tmr_checkSubstance "wait" pos:[300,300] interval:1000 active:false

        on btnExport pressed do (
            if selection.count == 0 do (
                messageBox "No objects selected!\n\nPlease select the model before sending to Painter." title:"Bridge: Nothing Selected" beep:false
                return()
            )
            if not (checkAndEnsureUV()) do return()
            -- Make each object's material name match the object so SP creates
            -- a predictable Texture Set per object.
            ensureObjectNamedMaterials()
            if not isModelBaked do (
                updateStatus "Extracting textures..."
                extractExistingTextures()
            )
            if (exportToSubstance withTextures:true) do (
                launchSubstance()
            )
        )

        on tmr_checkSubstance tick do (
            local path = getProjectPath() + "tex_sp\\"
            local isRunning = isSubstanceRunning()

            if doesFileExist path do (
                local files = getFiles (path + "*.png")
                if files.count > 0 do (
                    local sizes1 = for f in files collect getFileSize f
                    sleep 0.2
                    local sizes2 = for f in files collect getFileSize f
                    local matches = true
                    for i = 1 to files.count do (
                        if sizes1[i] != sizes2[i] do matches = false
                    )
                    if matches do (
                        tmr_checkSubstance.active = false
                        updateStatus "Importing textures..."
                        importSubstanceTextures()
                        updateStatus "Done!"
                    )
                )
            )

            if not isRunning and tmr_checkSubstance.active do (
                local gotTextures = false
                if doesFileExist path do (
                    local files = getFiles (path + "*.png")
                    if files.count > 0 do ( gotTextures = importSubstanceTextures() )
                )
                tmr_checkSubstance.active = false
                updateStatus (if gotTextures then "Done!" else "Ready")
            )
        )

        on substanceBridgeRollout moved pos do sbr_savePosToIni()
    )

    local startPos = sbr_loadPos()
    createDialog substanceBridgeRollout pos:startPos style:#(#style_titlebar, #style_sysmenu, #style_toolwindow)
)
