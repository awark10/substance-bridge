import substance_painter.ui as ui
import substance_painter.project as project
import substance_painter.resource as resource
import substance_painter.display as display
import substance_painter.js as js
import os
import tempfile

try:
    from PySide2 import QtWidgets, QtGui, QtCore
    QAction = QtWidgets.QAction
except ImportError:
    from PySide6 import QtWidgets, QtGui, QtCore
    QAction = QtGui.QAction

VERSION = "2.1.050"
BRIDGE_DIR = r"C:\SubstanceBridge"
plugin_widgets = []
last_imported_res = None

# Name of the user-made Smart Mask that ADD WEATHERING will prefer if it exists.
# Build your ideal weathering mask by hand in SP, right-click the mask ->
# "Create smart mask", and name it exactly this. The plugin will then apply it.
WEATHERING_SMART_MASK = "SB_Weathering"

# Ground-dirt color texture (moss/rock at the base of the model). Shipped next to
# the plugin; the plugin imports it on demand. Name used to find it once imported.
GROUND_TEXTURE_FILE = "aerial_grass_rock_diff.png"
GROUND_TEXTURE_NAME = "aerial_grass_rock_diff"

def display_msg(msg):
    try:
        display.display_message(msg, display.MessageType.Info, 3000)
    except:
        print(f"Bridge: {msg}")

def parse_channel_type(name):
    """Map filename suffixes to Substance Painter ChannelType enums."""
    import substance_painter.textureset as ts
    n = name.lower()
    
    # Base Color / Diffuse
    if any(s in n for s in ["_d", "_basecolor", "_base_color", "_bc", "_color", "_diffuse", "_diff"]):
        return ts.ChannelType.BaseColor
    # Roughness
    if any(s in n for s in ["_r", "_roughness", "_rough"]):
        return ts.ChannelType.Roughness
    # Metallic / Metal
    if any(s in n for s in ["_m", "_metallic", "_metal"]):
        return ts.ChannelType.Metallic
    # Normal
    if any(s in n for s in ["_n", "_normal", "_norm"]):
        return ts.ChannelType.Normal
    # Height / Displacement
    if any(s in n for s in ["_h", "_height", "_disp"]):
        return ts.ChannelType.Height
    # Ambient Occlusion
    if any(s in n for s in ["_ao", "_ambientocclusion", "_ambient_occlusion"]):
        return ts.ChannelType.AO
    # Opacity / Cutout Alpha
    if any(s in n for s in ["_o", "_opacity", "_opac", "_a"]):
        return ts.ChannelType.Opacity
    # Emissive
    if any(s in n for s in ["_e", "_emissive", "_emit"]):
        return ts.ChannelType.Emissive
    return None

def _reduce_ao_occluder_distance(texture_set_name, factor=0.1):
    """Shrink how far away other geometry can still cast an AO shadow onto
    this Texture Set. Opacity/cutout decals are still solid geometry to the
    AO baker (it only sees the mesh, not the painted alpha), so a decal
    physically raised/offset above another model still darkens that model's
    baked AO underneath it. Max_Occluder_Distance isn't exposed by the
    documented Python baking module — only by the internal JS scripting API
    (alg.baking) — so this goes through substance_painter.js.evaluate()."""
    import substance_painter.js as js
    import json as _json
    try:
        params = js.evaluate(f'alg.baking.textureSetBakingParameters("{texture_set_name}")')
        ao_def = params.get("definitions", {}).get("Ambient_occlusion", {})
        ao_params = ao_def.get("parameters", {})
        if "Max_Occluder_Distance" not in ao_params:
            print(f"Bridge: No Max_Occluder_Distance param found for '{texture_set_name}'.")
            return
        old_val = ao_params["Max_Occluder_Distance"]
        new_val = old_val * factor
        # setTextureSetBakingParameters does NOT deep-merge definitions.* —
        # sending only {"parameters": {...}} replaces the WHOLE
        # Ambient_occlusion definition, silently resetting "enabled" to its
        # default (false) and turning the AO baker off entirely. Carry the
        # existing "enabled" flag through explicitly to avoid that.
        patch = {
            "definitions": {
                "Ambient_occlusion": {
                    "enabled": ao_def.get("enabled", True),
                    "parameters": {"Max_Occluder_Distance": new_val}
                }
            }
        }
        js.evaluate(f'alg.baking.setTextureSetBakingParameters("{texture_set_name}", {_json.dumps(patch)})')
        print(f"Bridge: '{texture_set_name}' AO Max_Occluder_Distance {old_val} -> {new_val:.6f} (excludes distant/offset opacity decals as occluders).")
    except Exception as e:
        print(f"Bridge: Failed to adjust AO occluder distance for '{texture_set_name}': {e}")

def import_model_from_3dsmax():
    """Opens FBX from C:\SubstanceBridge as a new SP project."""
    fbx_path = os.path.join(BRIDGE_DIR, "SP_Export.fbx")
    if not os.path.exists(fbx_path):
        display_msg("No FBX found in C:\\SubstanceBridge!")
        return
    try:
        # Write last imported FBX path to a temp file for context
        temp_file = os.path.join(tempfile.gettempdir(), "sp_bridge_fbx_path.txt")
        try:
            with open(temp_file, "w") as f:
                f.write(fbx_path)
        except: pass

        display_msg(f"Creating project from: {os.path.basename(fbx_path)}")
        try:
            project.create(mesh_file_path=fbx_path, settings=project.Settings(default_texture_resolution=4096))
        except:
            project.create(fbx_path)
    except Exception as e:
        display_msg(f"Import Error: {str(e)}")

def process_import(fbx_path=None):
    """Imports all textures from BRIDGE_DIR/temp_bkd and returns their ResourceIDs."""
    global last_imported_res
    try:
        bkd_dir = os.path.join(BRIDGE_DIR, "temp_bkd")
        if not os.path.exists(bkd_dir):
            display_msg("Folder temp_bkd not found!")
            return []
            
        textures = [os.path.join(bkd_dir, f) for f in os.listdir(bkd_dir) if f.lower().endswith(".png")]
        if not textures:
            display_msg("No PNG textures found!")
            return []
            
        imported_resources = []
        for t in textures:
            try:
                res = resource.import_project_resource(t, resource.Usage.TEXTURE)
                if res:
                    imported_resources.append(res)
                    last_imported_res = res.identifier()
                    print(f"Bridge: Imported {os.path.basename(t)}")
            except Exception as e:
                print(f"Bridge: Failed to import {t}: {e}")

        if imported_resources:
            print(f"Bridge: SUCCESS: Imported {len(imported_resources)} textures.")
            print("Bridge: Triggering forced Asset Browser refresh...")
            
            # Force UI update with discovery delay
            def delayed_ui_update():
                print("Bridge: Executing library refresh...")
                try: 
                    import substance_painter.js as js
                    # 1. Refresh all shelves
                    resource.Shelves.refresh_all()
                    # 2. Select and show the new resources (Needs Resource objects, not IDs)
                    resource.show_resources_in_ui(imported_resources)
                    # 3. Fallback JS refresh for UI state
                    try: js.evaluate("alg.ui.assetBrowser.refresh()")
                    except: pass
                    print("Bridge: Asset Browser refresh finished.")
                except Exception as e:
                    print(f"Bridge: Refresh failed: {e}")
            
            QtCore.QTimer.singleShot(1000, delayed_ui_update)
            
        return [r.identifier() for r in imported_resources]
        
    except Exception as e:
        print(f"Bridge Import Error: {str(e)}")
        return []

def _enable_alpha_blending_shader():
    """Switch the project's shader to the Alpha Test PBR variant.
    SP's default PBR Metal/Rough shader ignores the Opacity channel entirely —
    a separate .glsl shader is required for the viewport (and bakes) to render
    the cutout. Alpha TEST (hard binary threshold, no color blending at the
    edge) is used rather than Alpha Blending — Blend mode linearly mixes the
    BaseColor's edge pixels with the background, producing a light/white
    fringe around the cutout unless the source art uses premultiplied alpha.
    Alpha Test avoids that entirely, matching a "Cutout" opacity map."""
    try:
        import substance_painter.resource as resource
        import substance_painter.js as js

        candidates = resource.search("s:starterassets u:shader alpha-test")
        if not candidates:
            candidates = resource.search("s:starterassets u:shader alpha test")
        if not candidates:
            candidates = resource.search("alpha-test")
        if not candidates:
            print("Bridge: Alpha-test shader resource not found — "
                  "enable it manually via Shader Settings.")
            return
        rid = candidates[0].identifier()
        shader_url = rid.url()
        print(f"Bridge: Found alpha-test shader: '{rid.name}' url={shader_url}")

        js_code = (
            "(function() {"
            "  var instances = alg.shaders.instances();"
            "  for (var i = 0; i < instances.length; i++) {"
            f'    alg.shaders.updateShaderInstance(instances[i].id, "{shader_url}");'
            "  }"
            "})();"
        )
        js.evaluate(js_code)
        print("Bridge: Switched project shader to Alpha Test PBR (cutout).")
    except Exception as e:
        print(f"Bridge: Failed to enable alpha-test shader: {e}")

def finish_assignment():
    # pyrefly: ignore [missing-import]
    import substance_painter.project as project
    import substance_painter.textureset as ts
    import substance_painter.layerstack as ls
    
    try:
        if not project.is_open():
            display_msg("No project open!")
            return

        # 1. Get textures from last FBX path context
        temp_file = os.path.join(tempfile.gettempdir(), "sp_bridge_fbx_path.txt")
        fbx_path = os.path.join(BRIDGE_DIR, "SP_Export.fbx")
        if os.path.exists(temp_file):
            try:
                with open(temp_file, "r") as f:
                    path_val = f.read().strip()
                    if path_val and os.path.exists(path_val):
                        fbx_path = path_val
            except: pass
        
        # 2. Import resources (may be empty if temp_bkd had no textures —
        #    that's fine, mesh maps are already baked at this point)
        resource_ids = process_import(fbx_path)
        if not resource_ids:
            display_msg("Mesh maps baked. (No base textures to assign.)")
            return

        # 3. Assign per texture set — match each baked texture to the model it
        #    belongs to by name. Baked files are "<objectName>_Base_Baked_X",
        #    and the SP texture set name == object name.
        def _norm(s):
            return "".join(c.lower() for c in s if c.isalnum())

        def _channel_format_for(channel_type):
            # stack.add_channel() requires an explicit format (no default).
            # RGB-ish channels use RGB8; everything else (Roughness, Metallic,
            # AO, Height, Opacity...) is single-channel luminance -> L8.
            if channel_type in (ts.ChannelType.BaseColor, ts.ChannelType.Normal,
                                 ts.ChannelType.Emissive):
                return ts.ChannelFormat.RGB8
            return ts.ChannelFormat.L8

        total_assigned = 0
        sets_done = 0
        opacity_added = False
        for texture_set in ts.all_texture_sets():
            try:
                stack = texture_set.get_stack("")
            except Exception as e:
                print(f"Bridge: get_stack failed for '{texture_set.name}': {e}")
                continue

            ts_key = _norm(texture_set.name)
            ts_resources = [rid for rid in resource_ids
                            if _norm(rid.name).startswith(ts_key)]
            if not ts_resources:
                print(f"Bridge: No baked textures matched set '{texture_set.name}'.")
                continue

            # Find or create the "Base Baked" layer in THIS stack
            target_layer = None
            try:
                for node in ls.get_root_layer_nodes(stack):
                    if node.get_name() == "Base Baked":
                        target_layer = node
                        break
            except Exception:
                pass
            if not target_layer:
                pos = ls.InsertPosition.from_textureset_stack(stack)
                target_layer = ls.insert_fill(pos)
                target_layer.set_name("Base Baked")
                print(f"Bridge: Created 'Base Baked' in '{texture_set.name}'.")

            # Assign matched channels
            for res_id in ts_resources:
                channel_type = parse_channel_type(res_id.name)
                if not channel_type:
                    continue
                try:
                    if not stack.has_channel(channel_type):
                        stack.add_channel(channel_type, _channel_format_for(channel_type))
                        print(f"Bridge: Added channel {channel_type.name} to '{texture_set.name}'.")
                        if channel_type == ts.ChannelType.Opacity:
                            opacity_added = True
                    target_layer.set_source(channel_type, res_id)
                    print(f"Bridge: [{texture_set.name}] {res_id.name} -> {channel_type.name}")
                    total_assigned += 1
                except Exception as e:
                    print(f"Bridge: assign failed ({channel_type.name}): {e}")
            sets_done += 1

        if opacity_added:
            _enable_alpha_blending_shader()

        display_msg(f"SUCCESS: Assigned {total_assigned} channels across {sets_done} model(s).")
        
    except Exception as e:
        print(f"Bridge Assignment Error: {str(e)}")
        import traceback; traceback.print_exc()
        display_msg("Error: Check console for details")

def on_bake_finished(event):
    import substance_painter.event as sp_event
    import substance_painter.baking as baking
    import substance_painter.ui as ui
    
    try:
        sp_event.DISPATCHER.disconnect(sp_event.BakingProcessEnded, on_bake_finished)
    except:
        pass
        
    if event.status == baking.BakingStatus.Success:
        display_msg("Baking successful. Assigning textures...")
        
        # Switch back to painting mode automatically
        try:
            ui.switch_to_mode(ui.UIMode.Edition)
        except Exception as e:
            print(f"Bridge: Failed to close baking window: {e}")
            
        finish_assignment()
    else:
        display_msg(f"Baking failed or was canceled ({event.status.name}).")

def start_bake_and_assign():
    """Trigger Mesh Map Baking then Automated PBR assignment."""
    import substance_painter.project as project
    import substance_painter.textureset as ts
    import substance_painter.baking as baking
    import substance_painter.event as sp_event
    
    if not project.is_open():
        display_msg("No project open!")
        return

    all_sets = ts.all_texture_sets()

    # 1. Setup bakers (shared setup, runs once regardless of how many bake
    # passes actually happen below)
    for texture_set in all_sets:
        # The Texture Set's OWN paint/export resolution is separate from the
        # mesh-map bake's OutputSize below — without this, the canvas stayed
        # at SP's project-creation default (1024) and every exported map got
        # upscaled to 4096 on export, which is what produced the soft/blurry
        # halo around cutout edges.
        try:
            current_res = texture_set.get_resolution()
            if current_res.width != 4096 or current_res.height != 4096:
                texture_set.set_resolution(ts.Resolution(4096, 4096))
                print(f"Bridge: Set texture set '{texture_set.name}' resolution to 4096x4096 (was {current_res.width}x{current_res.height}).")
        except Exception as e:
            print(f"Bridge: Failed to set texture set resolution for '{texture_set.name}': {e}")

        baking_params = baking.BakingParameters.from_texture_set(texture_set)
        baking_params.set_textureset_enabled(True)

        # Set resolution to 4096x4096 (2^12)
        common_params = baking_params.common()
        if 'OutputSize' in common_params:
            baking.BakingParameters.set({
                common_params['OutputSize']: (12, 12)
            })

        baking_params.set_enabled_bakers([
            ts.MeshMapUsage.Normal,
            ts.MeshMapUsage.WorldSpaceNormal,
            ts.MeshMapUsage.AO,
            ts.MeshMapUsage.Position,
            ts.MeshMapUsage.Curvature
        ])

    # NOTE: a two-phase bake (disable opacity models' Texture Set, bake
    # non-opacity models, re-enable, bake opacity models) was tried here to
    # keep opacity meshes from casting AO shadows onto other models, but
    # `BakingParameters.set_textureset_enabled(False)` only skips generating
    # THAT Texture Set's own output maps — its geometry is still used as an
    # occluder for everyone else regardless. Confirmed by testing: the
    # shadow persisted even with the flag off. There is no Texture-Set-level
    # way to exclude a model's geometry from occluding others.

    # 1b. Models in this pipeline are physically raised/offset from each
    # other, but are all still solid geometry to the AO baker regardless of
    # Opacity. Shrink Max_Occluder_Distance on EVERY Texture Set — no model
    # should pick up a cross-model shadow from another, opacity or not, only
    # its own real self-occlusion. Tune the `factor` in
    # _reduce_ao_occluder_distance if this is too aggressive (washes out
    # real self-AO) or not aggressive enough (cross-model shadow still
    # visible).
    for texture_set in all_sets:
        _reduce_ao_occluder_distance(texture_set.name)

    # 2. Connect the event
    sp_event.DISPATCHER.connect(sp_event.BakingProcessEnded, on_bake_finished)

    # 3. Trigger bake
    baking.bake_selected_textures_async()
    display_msg("Baking Mesh Maps (Normal, WSN, AO, Position, Curvature)...")

def export_to_max():
    import substance_painter.export
    import substance_painter.project as project
    
    if not project.is_open():
        display_msg("No project open!")
        return

    reply = QtWidgets.QMessageBox.question(
        None,
        "Confirm Export & Exit",
        "Are you sure you want to export textures and close Substance Painter?",
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        QtWidgets.QMessageBox.No
    )
    
    if reply != QtWidgets.QMessageBox.Yes:
        return

    try:
        export_dir = os.path.join(BRIDGE_DIR, "tex_sp")
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            
        preset_name = "3dsMax_Bridge_Preset"
        preset_name_opacity = "3dsMax_Bridge_Preset_Opacity"

        default_params = {
            "fileFormat": "png",
            "bitDepth": "8",
            "sizeLog2": 12,
            "dithering": False,
            "paddingAlgorithm": "infinite"
        }

        # NOTE: color-bleed-into-transparent-zone (the white halo around a
        # cutout) is now fixed on the 3ds Max side instead (sbr_dilateColorFromMask
        # in the .mcr), which reliably dilates the real color into the alpha=0
        # zone using the actual opacity mask. Neither "transparent" nor
        # "diffusion" SP export padding reliably fixed it here, so the D map
        # for opacity texture sets just uses the same defaults as everything
        # else — no special padding needed on this side anymore.
        default_params_d_opacity = default_params

        d_channels = [
            {"destChannel": "R", "srcChannel": "R", "srcMapType": "documentMap", "srcMapName": "basecolor"},
            {"destChannel": "G", "srcChannel": "G", "srcMapType": "documentMap", "srcMapName": "basecolor"},
            {"destChannel": "B", "srcChannel": "B", "srcMapType": "documentMap", "srcMapName": "basecolor"}
        ]
        r_map = {
            "fileName": "$textureSet_R",
            "channels": [
                {"destChannel": "L", "srcChannel": "L", "srcMapType": "documentMap", "srcMapName": "roughness"}
            ],
            "parameters": default_params
        }
        m_map = {
            "fileName": "$textureSet_M",
            "channels": [
                {"destChannel": "L", "srcChannel": "L", "srcMapType": "documentMap", "srcMapName": "metallic"}
            ],
            "parameters": default_params
        }
        n_map = {
            "fileName": "$textureSet_N",
            "channels": [
                {"destChannel": "R", "srcChannel": "R", "srcMapType": "virtualMap", "srcMapName": "Normal_DirectX"},
                {"destChannel": "G", "srcChannel": "G", "srcMapType": "virtualMap", "srcMapName": "Normal_DirectX"},
                {"destChannel": "B", "srcChannel": "B", "srcMapType": "virtualMap", "srcMapName": "Normal_DirectX"}
            ],
            "parameters": default_params
        }

        maps = [
            {"fileName": "$textureSet_D", "channels": d_channels, "parameters": default_params},
            r_map, m_map, n_map
        ]

        # Opacity preset: D gets an extra alpha channel (embedded RGBA), plus a
        # standalone grayscale $textureSet_A map for the material's Cutout/Opacity slot.
        maps_opacity = [
            {
                "fileName": "$textureSet_D",
                "channels": d_channels + [
                    {"destChannel": "A", "srcChannel": "L", "srcMapType": "documentMap", "srcMapName": "opacity"}
                ],
                "parameters": default_params_d_opacity
            },
            r_map, m_map, n_map,
            {
                "fileName": "$textureSet_A",
                "channels": [
                    {"destChannel": "L", "srcChannel": "L", "srcMapType": "documentMap", "srcMapName": "opacity"}
                ],
                "parameters": default_params
            }
        ]

        export_list = []
        import substance_painter.textureset as ts
        for texture_set in ts.all_texture_sets():
            entry = {"rootPath": texture_set.name}
            try:
                if texture_set.get_stack("").has_channel(ts.ChannelType.Opacity):
                    entry["exportPreset"] = preset_name_opacity
            except Exception as e:
                print(f"Bridge: opacity channel check failed for '{texture_set.name}': {e}")
            export_list.append(entry)

        export_config = {
            "exportPath": export_dir,
            "exportShaderParams": False,
            "defaultExportPreset": preset_name,
            "exportPresets": [
                {"name": preset_name, "maps": maps},
                {"name": preset_name_opacity, "maps": maps_opacity}
            ],
            "exportList": export_list
        }
        
        display_msg("Exporting 4K textures to Max...")
        export_result = substance_painter.export.export_project_textures(export_config)
        
        if export_result.status != substance_painter.export.ExportStatus.Success:
            display_msg(f"Export failed: {export_result.message}")
        else:
            display_msg(f"SUCCESS: Textures exported to tex_sp folder!")
            display_msg(f"Closing Substance Painter...")
            
            import substance_painter.application as sp_app
            sp_app.close()
            
    except Exception as e:
        display_msg(f"Export Error: {str(e)}")
        print(f"Export Error: {str(e)}")


class BridgeWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("3ds Max Bridge")
        self.setMinimumWidth(250)
        self.dirt_gen = None           # Dirt generator of the LAST processed set
        self.rain_streaks_layer = None # Weather Streaks layer of the LAST set
        self.ground_layer = None       # Ground Dirt layer of the LAST set
        self.ground_pos_gen = None     # Ground Dirt Position generator of the LAST set
        self.rust_layer = None         # Rust layer of the LAST set
        self.rust_gen = None           # Rust Curvature generator of the LAST set
        # Lists collect one ref per texture set so sliders can drive them all
        self.dirt_gens = []            # Dirt generator nodes (per model)
        self.rain_streaks_layers = []  # Weather Streaks fill layers (per model)
        self.ground_layers = []        # Ground Dirt fill layers (per model)
        self.ground_pos_gens = []      # Ground Dirt Position generators (per model)
        self.rust_layers = []          # Rust fill layers (per model)
        self.rust_gens = []            # Rust Curvature generators (per model)
        self.setup_ui()

    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QtWidgets.QLabel("3DS MAX BRIDGE v2.8.4")
        header.setStyleSheet("font-weight: bold; font-size: 16px; color: #ffaa00;")
        header.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(header)

        # Apply effects to all texture sets (models) or just the active one
        self.apply_all_check = QtWidgets.QCheckBox("Apply to all models")
        self.apply_all_check.setChecked(True)
        self.apply_all_check.setStyleSheet("color: #cccccc; font-size: 11px;")
        self.apply_all_check.setToolTip(
            "ON: effect is added to every Texture Set (model).\n"
            "OFF: only the active Texture Set."
        )
        layout.addWidget(self.apply_all_check)

        # ── Dirt ──────────────────────────────────────────────────────────
        self.dirt_btn = QtWidgets.QPushButton("1. ADD DIRT")
        self.dirt_btn.setMinimumHeight(40)
        self.dirt_btn.setStyleSheet(
            "background-color: #3a5c3a; color: #ccffcc; font-weight: bold; font-size: 13px;"
            "border: 1px solid #558855;"
        )
        self.dirt_btn.clicked.connect(
            lambda: self._apply_to_targets(self.add_dirt_layer, [("dirt_gen", "dirt_gens")]))
        layout.addWidget(self.dirt_btn)

        self.dirt_intensity_label = QtWidgets.QLabel("Dirt Intensity: 100%")
        self.dirt_intensity_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.dirt_intensity_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.dirt_intensity_label)

        self.dirt_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.dirt_slider.setRange(0, 100)
        self.dirt_slider.setValue(100)
        self.dirt_slider.setEnabled(False)
        self.dirt_slider.valueChanged.connect(self.on_dirt_intensity_changed)
        layout.addWidget(self.dirt_slider)

        # ── Weathering ────────────────────────────────────────────────────
        self.rain_btn = QtWidgets.QPushButton("2. ADD WEATHERING")
        self.rain_btn.setMinimumHeight(40)
        self.rain_btn.setStyleSheet(
            "background-color: #4a2f1a; color: #ffccaa; font-weight: bold; font-size: 13px;"
            "border: 1px solid #885533;"
        )
        self.rain_btn.clicked.connect(
            lambda: self._apply_to_targets(self.add_rain_effect, [("rain_streaks_layer", "rain_streaks_layers")]))
        layout.addWidget(self.rain_btn)

        self.rain_intensity_label = QtWidgets.QLabel("Weathering Intensity: 75%")
        self.rain_intensity_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.rain_intensity_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.rain_intensity_label)

        self.rain_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.rain_slider.setRange(0, 100)
        self.rain_slider.setValue(75)
        self.rain_slider.setEnabled(False)
        self.rain_slider.valueChanged.connect(self.on_rain_intensity_changed)
        layout.addWidget(self.rain_slider)

        # ── Ground Dirt ───────────────────────────────────────────────────
        self.ground_btn = QtWidgets.QPushButton("3. ADD GROUND DIRT")
        self.ground_btn.setMinimumHeight(40)
        self.ground_btn.setStyleSheet(
            "background-color: #3a4a2a; color: #d8ffaa; font-weight: bold; font-size: 13px;"
            "border: 1px solid #6a8844;"
        )
        self.ground_btn.clicked.connect(
            lambda: self._apply_to_targets(self.add_ground_dirt,
                [("ground_layer", "ground_layers"), ("ground_pos_gen", "ground_pos_gens")]))
        layout.addWidget(self.ground_btn)

        self.ground_intensity_label = QtWidgets.QLabel("Ground Dirt Intensity: 100%")
        self.ground_intensity_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.ground_intensity_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.ground_intensity_label)

        self.ground_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.ground_slider.setRange(0, 100)
        self.ground_slider.setValue(100)
        self.ground_slider.setEnabled(False)
        self.ground_slider.valueChanged.connect(self.on_ground_intensity_changed)
        layout.addWidget(self.ground_slider)

        # Ground Height — how high up the base the dirt climbs (Position balance)
        self.ground_height_label = QtWidgets.QLabel("Ground Height: 12%")
        self.ground_height_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.ground_height_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.ground_height_label)

        self.ground_height_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.ground_height_slider.setRange(2, 50)   # % of height the dirt rises
        self.ground_height_slider.setValue(12)
        self.ground_height_slider.setEnabled(False)
        self.ground_height_slider.valueChanged.connect(self.on_ground_height_changed)
        layout.addWidget(self.ground_height_slider)

        # Ground Softness — how soft/gradual the top edge fades (Position contrast)
        self.ground_soft_label = QtWidgets.QLabel("Ground Softness: 11%")
        self.ground_soft_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.ground_soft_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.ground_soft_label)

        self.ground_soft_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.ground_soft_slider.setRange(0, 100)    # higher = softer transition
        self.ground_soft_slider.setValue(11)        # 11 -> contrast 0.89
        self.ground_soft_slider.setEnabled(False)
        self.ground_soft_slider.valueChanged.connect(self.on_ground_softness_changed)
        layout.addWidget(self.ground_soft_slider)

        # ── Rust / Aging ──────────────────────────────────────────────────
        self.rust_btn = QtWidgets.QPushButton("4. ADD RUST / AGING")
        self.rust_btn.setMinimumHeight(40)
        self.rust_btn.setStyleSheet(
            "background-color: #5a2e1a; color: #ffbb88; font-weight: bold; font-size: 13px;"
            "border: 1px solid #aa6633;"
        )
        self.rust_btn.clicked.connect(
            lambda: self._apply_to_targets(self.add_rust,
                [("rust_layer", "rust_layers"), ("rust_gen", "rust_gens")]))
        layout.addWidget(self.rust_btn)

        self.rust_intensity_label = QtWidgets.QLabel("Rust Intensity: 80%")
        self.rust_intensity_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.rust_intensity_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.rust_intensity_label)

        self.rust_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.rust_slider.setRange(0, 100)
        self.rust_slider.setValue(80)
        self.rust_slider.setEnabled(False)
        self.rust_slider.valueChanged.connect(self.on_rust_intensity_changed)
        layout.addWidget(self.rust_slider)

        # Rust Balance — how far the rust spreads off the edges (Curvature balance)
        self.rust_balance_label = QtWidgets.QLabel("Rust Balance: 7%")
        self.rust_balance_label.setStyleSheet("color: #888888; font-size: 11px;")
        self.rust_balance_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.rust_balance_label)

        self.rust_balance_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.rust_balance_slider.setRange(0, 100)   # Curvature Global Balance (0..1)
        self.rust_balance_slider.setValue(7)
        self.rust_balance_slider.setEnabled(False)
        self.rust_balance_slider.valueChanged.connect(self.on_rust_balance_changed)
        layout.addWidget(self.rust_balance_slider)

        # ── Export ────────────────────────────────────────────────────────
        self.export_btn = QtWidgets.QPushButton("5. SEND TO MAX (EXPORT 4K)")
        self.export_btn.setMinimumHeight(45)
        self.export_btn.setStyleSheet("background-color: #774433; color: white; font-weight: bold;")
        self.export_btn.clicked.connect(export_to_max)
        layout.addWidget(self.export_btn)

        layout.addStretch()

    # ── Dirt intensity ─────────────────────────────────────────────────────
    def on_dirt_intensity_changed(self, value):
        self.dirt_intensity_label.setText(f"Dirt Intensity: {value}%")
        for gen in self.dirt_gens:
            if gen is None:
                continue
            try:
                src = gen.get_source()
                if src is None:
                    continue
                params = src.get_parameters()
                updated = dict(params)
                for key in params:
                    if key.lower() in ("dirt_level", "level", "dirtlevel"):
                        updated[key] = value / 100.0
                src.set_parameters(updated)
            except Exception as e:
                print(f"Bridge: Dirt intensity error: {e}")

    # ── Rain intensity ─────────────────────────────────────────────────────
    def on_rain_intensity_changed(self, value):
        self.rain_intensity_label.setText(f"Weathering Intensity: {value}%")
        import substance_painter.textureset as ts
        for layer in self.rain_streaks_layers:
            if layer is None:
                continue
            try:
                layer.set_opacity(value / 100.0, ts.ChannelType.BaseColor)
            except Exception as e:
                print(f"Bridge: Weathering intensity error: {e}")

    # ── Run an effect on all texture sets, or just the active one ───────────
    def _apply_to_targets(self, effect_fn, ref_specs):
        """If 'Apply to all models' is on, run effect_fn for every texture set
        (making each active in turn). Otherwise run once on the active set.
        ref_specs is a list of (ref_attr, list_attr) pairs: after each run, each
        effect ref is collected into its list so sliders can drive every model."""
        import substance_painter.project as project
        import substance_painter.textureset as ts
        if not project.is_open():
            display_msg("No project open!")
            return

        for _, list_attr in ref_specs:
            setattr(self, list_attr, [])  # rebuild each ref list

        def _run_and_collect():
            for ref_attr, _ in ref_specs:
                setattr(self, ref_attr, None)
            effect_fn()
            for ref_attr, list_attr in ref_specs:
                ref = getattr(self, ref_attr)
                if ref is not None:
                    getattr(self, list_attr).append(ref)

        if not self.apply_all_check.isChecked():
            _run_and_collect()
            return

        try:
            original = ts.get_active_stack()
        except Exception:
            original = None
        for tset in ts.all_texture_sets():
            try:
                ts.set_active_stack(tset.get_stack(""))
                _run_and_collect()
            except Exception as e:
                print(f"Bridge: apply-all failed on '{tset.name}': {e}")
        if original is not None:
            try:
                ts.set_active_stack(original)
            except Exception:
                pass

    # ── Ground dirt intensity ──────────────────────────────────────────────
    def on_ground_intensity_changed(self, value):
        self.ground_intensity_label.setText(f"Ground Dirt Intensity: {value}%")
        import substance_painter.textureset as ts
        for layer in self.ground_layers:
            if layer is None:
                continue
            try:
                layer.set_opacity(value / 100.0, ts.ChannelType.BaseColor)
            except Exception as e:
                print(f"Bridge: Ground dirt intensity error: {e}")

    def on_ground_height_changed(self, value):
        # value = % of model height the dirt climbs; higher % -> lower Position balance
        self.ground_height_label.setText(f"Ground Height: {value}%")
        balance = 1.0 - (value / 100.0)
        for gen in self.ground_pos_gens:
            if gen is None:
                continue
            try:
                src = gen.get_source()
                if src is None:
                    continue
                params = src.get_parameters()
                updated = dict(params)
                for key in params:
                    if key.lower().replace(" ", "_") == "global_balance":
                        updated[key] = balance
                src.set_parameters(updated)
            except Exception as e:
                print(f"Bridge: Ground height error: {e}")

    def on_ground_softness_changed(self, value):
        # higher slider = softer transition = lower Position contrast
        self.ground_soft_label.setText(f"Ground Softness: {value}%")
        contrast = 1.0 - (value / 100.0)
        for gen in self.ground_pos_gens:
            if gen is None:
                continue
            try:
                src = gen.get_source()
                if src is None:
                    continue
                params = src.get_parameters()
                updated = dict(params)
                for key in params:
                    if key.lower().replace(" ", "_") == "global_contrast":
                        updated[key] = contrast
                src.set_parameters(updated)
            except Exception as e:
                print(f"Bridge: Ground softness error: {e}")

    # ── Rust intensity ──────────────────────────────────────────────────────
    def on_rust_intensity_changed(self, value):
        self.rust_intensity_label.setText(f"Rust Intensity: {value}%")
        import substance_painter.textureset as ts
        for layer in self.rust_layers:
            if layer is None:
                continue
            try:
                layer.set_opacity(value / 100.0, ts.ChannelType.BaseColor)
            except Exception as e:
                print(f"Bridge: Rust intensity error: {e}")

    # ── Rust balance (Curvature Global Balance) ─────────────────────────────
    def on_rust_balance_changed(self, value):
        self.rust_balance_label.setText(f"Rust Balance: {value}%")
        balance = value / 100.0
        for gen in self.rust_gens:
            if gen is None:
                continue
            try:
                src = gen.get_source()
                if src is None:
                    continue
                params = src.get_parameters()
                updated = dict(params)
                for key in params:
                    if key.lower().replace(" ", "_") == "global_balance":
                        updated[key] = balance
                src.set_parameters(updated)
            except Exception as e:
                print(f"Bridge: Rust balance error: {e}")

    # ── Generator search helper ────────────────────────────────────────────
    def _find_generator(self, search_queries):
        """Try each query in order, return first valid ResourceID or None."""
        for q in search_queries:
            try:
                results = resource.search(q)
                for r in results:
                    rid = r.identifier()
                    print(f"Bridge: Found generator candidate: '{rid.name}' [{rid.context}]")
                    return rid
            except Exception as e:
                print(f"Bridge: Search '{q}' failed: {e}")
        return None

    # ── Texture search helper ──────────────────────────────────────────────
    def _find_texture(self, search_queries):
        """Try each query in order, return first matching texture ResourceID."""
        for q in search_queries:
            try:
                results = resource.search(q)
                for r in results:
                    rid = r.identifier()
                    print(f"Bridge: Found texture candidate: '{rid.name}' [{rid.context}]")
                    return rid
            except Exception as e:
                print(f"Bridge: Texture search '{q}' failed: {e}")
        return None

    # ── Smart mask search helper ───────────────────────────────────────────
    def _find_smart_mask(self, name):
        """Find a user smart mask by exact name; return ResourceID or None."""
        try:
            results = resource.search(name)
            # Prefer an exact name match
            for r in results:
                rid = r.identifier()
                if rid.name == name:
                    print(f"Bridge: Found smart mask '{rid.name}' [{rid.context}]")
                    return rid
            # Otherwise first candidate
            for r in results:
                rid = r.identifier()
                print(f"Bridge: Using smart mask candidate '{rid.name}' [{rid.context}]")
                return rid
        except Exception as e:
            print(f"Bridge: Smart mask search failed: {e}")
        return None

    # ── Rain Effect ───────────────────────────────────────────────────────
    def add_rain_effect(self):
        """Weathering effect: dark drip marks from convex edges (Curvature + Grunge)."""
        import substance_painter.textureset as ts
        import substance_painter.layerstack as ls
        import substance_painter.source as sp_source
        from substance_painter.colormanagement import Color

        try:
            if not project.is_open():
                display_msg("No project open!")
                return
            stack = ts.get_active_stack()
            if not stack:
                display_msg("Select a Texture Set first!")
                return

            self.rain_pos_gen = None
            self.rain_grunge_gen = None

            # ══════════════════════════════════════════════════════════════
            # WEATHER STREAKS — dark drip marks from edges, BaseColor only
            # ══════════════════════════════════════════════════════════════
            pos2 = ls.InsertPosition.from_textureset_stack(stack)
            streaks_layer = ls.insert_fill(pos2)
            streaks_layer.set_name("Weather Streaks")
            self.rain_streaks_layer = streaks_layer

            try:
                streaks_layer.active_channels = {ts.ChannelType.BaseColor}
            except Exception as e:
                print(f"Bridge Streaks: active_channels failed: {e}")

            # Same dark tone as ADD DIRT (#1a1208)
            try:
                src_sc = streaks_layer.get_source(ts.ChannelType.BaseColor)
                if isinstance(src_sc, sp_source.SourceUniformColor):
                    src_sc.set_color(Color(0.1, 0.07, 0.03))
                    print("Bridge Streaks: BaseColor set.")
            except Exception as e:
                print(f"Bridge Streaks: BaseColor failed: {e}")

            try:
                streaks_layer.add_mask(ls.MaskBackground.Black)
            except Exception as e:
                print(f"Bridge Streaks: mask failed: {e}")

            streaks_mask_insert = ls.InsertPosition.inside_node(
                streaks_layer, ls.NodeStack.Mask
            )

            # ── PREFERRED: apply user's own Smart Mask if it exists ──────
            sm_rid = self._find_smart_mask(WEATHERING_SMART_MASK)
            if sm_rid:
                try:
                    ls.insert_smart_mask(streaks_mask_insert, sm_rid)
                    self.rain_streaks_gen = None  # smart mask manages its own scale
                    self.rain_slider.setValue(75)
                    self.rain_slider.setEnabled(True)
                    self.rain_intensity_label.setStyleSheet("color: #ffccaa; font-size: 11px;")
                    display_msg(f"Weathering added! (Smart Mask: {WEATHERING_SMART_MASK})")
                    print(f"Bridge Streaks: Applied smart mask '{WEATHERING_SMART_MASK}'")
                    return
                except Exception as e:
                    print(f"Bridge Streaks: insert_smart_mask failed, using default: {e}")

            # ── DEFAULT (no smart mask found): AO + leak texture ─────────
            # AO generator: darkens RECESSES and the area AROUND OPENINGS
            # (window/door reveals, under sills) — this confines the effect to
            # those zones instead of the whole wall. Brick micro-detail is killed
            # so it reacts to big shapes only.
            ao_rid = self._find_generator([
                "s:starterassets u:generator n:Ambient Occlusion",
                "s:starterassets u:generator n:AO",
                "s:starterassets u:generator n:Dirt",
                "s:starterassets u:generator n:Curvature",
            ])
            self.rain_curv_gen = None
            if ao_rid:
                try:
                    gen3 = ls.insert_generator_effect(streaks_mask_insert, ao_rid)
                    self.rain_curv_gen = gen3
                    src3 = gen3.get_source()
                    if src3:
                        params3 = src3.get_parameters()
                        print(f"Bridge Streaks: AO/base gen params: {list(params3.keys())}")
                        updated3 = dict(params3)
                        for key in params3:
                            kl = key.lower().replace(" ", "_")
                            # High contrast + low balance → effect ONLY in the
                            # darkest occluded zones (around openings, recesses)
                            if kl == "global_contrast":
                                updated3[key] = 0.8
                            elif kl == "global_balance":
                                updated3[key] = 0.35   # less coverage
                            elif kl == "global_blur":
                                updated3[key] = 0.15
                            elif kl in ("range", "ao_range"):
                                updated3[key] = 0.5    # how far AO reaches from edges
                            elif kl in ("intensity", "global_intensity"):
                                updated3[key] = 1.0
                            # Kill brick micro-detail influence
                            elif kl in ("microdetails_curvature_intensity",
                                        "microdetails_height_details_intensity",
                                        "microdetails_height", "microdetails_normal",
                                        "curvature_fine"):
                                updated3[key] = 0.0
                        src3.set_parameters(updated3)
                        print("Bridge Streaks: AO params applied (openings/recesses).")
                except Exception as e:
                    print(f"Bridge Streaks: AO gen failed: {e}")

            # Grunge LEAK TEXTURE on top of Curvature, blended MULTIPLY.
            # This breaks up the uniform curvature edge-darkening into organic,
            # non-uniform vertical streaks (the realistic weathering look).
            leak_rid = self._find_texture([
                "s:starterassets u:texture leak",
                "s:starterassets u:texture grunge",
                "s:starterassets u:texture streak",
                "s:starterassets u:texture dirt",
                "leak",
                "grunge",
            ])
            self.rain_streaks_gen = None
            if leak_rid:
                try:
                    leak_fill = ls.insert_fill(streaks_mask_insert)
                    self.rain_streaks_gen = leak_fill
                    # Mask fill: channel must be None
                    leak_fill.set_source(None, leak_rid)
                    # Multiply so the texture modulates the curvature below it
                    try:
                        leak_fill.set_blending_mode(ls.BlendingMode.Multiply)
                    except Exception as eb:
                        print(f"Bridge Streaks: blend mode failed: {eb}")
                    # Triplanar projection → streaks follow world space
                    try:
                        leak_fill.set_projection_mode(ls.ProjectionMode.Triplanar)
                        # Finer default tiling (factor 2.0) reads as natural streaks
                        params = leak_fill.get_projection_parameters()
                        if params is not None:
                            params.uv_transformation = ls.UVTransformationParams(
                                scale_mode=ls.ScaleMode.Factors,
                                scale=[2.0, 2.0],
                            )
                            leak_fill.set_projection_parameters(params)
                    except Exception as ep:
                        print(f"Bridge Streaks: projection failed: {ep}")
                    print(f"Bridge Streaks: Leak texture (Multiply) added: {leak_rid.name}")
                except Exception as e:
                    print(f"Bridge Streaks: leak texture fill failed: {e}")
            else:
                print("Bridge Streaks: No leak/grunge texture found — curvature only.")

            # ── Activate slider ─────────────────────────────────────────
            self.rain_slider.setValue(75)
            self.rain_slider.setEnabled(True)
            self.rain_intensity_label.setStyleSheet("color: #ffccaa; font-size: 11px;")
            display_msg("Weathering added! (Weather Streaks: dark drips from edges)")

        except Exception as e:
            import traceback
            print(f"Bridge ADD WEATHERING Error: {e}")
            traceback.print_exc()
            display_msg(f"ADD WEATHERING Error: {str(e)[:60]}")

    # ── Ground dirt texture import ──────────────────────────────────────────
    def _get_ground_texture(self):
        """Find the ground texture if already imported, else import it from the
        plugin folder. Returns ResourceID or None."""
        # 1. Already imported?
        try:
            for r in resource.search(GROUND_TEXTURE_NAME):
                rid = r.identifier()
                if GROUND_TEXTURE_NAME in rid.name:
                    return rid
        except Exception as e:
            print(f"Bridge Ground: search failed: {e}")
        # 2. Import from the plugin folder
        try:
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(plugin_dir, GROUND_TEXTURE_FILE)
            if os.path.exists(path):
                res = resource.import_project_resource(path, resource.Usage.TEXTURE)
                print(f"Bridge Ground: imported texture from {path}")
                return res.identifier()
            print(f"Bridge Ground: texture not found at {path}")
        except Exception as e:
            print(f"Bridge Ground: import failed: {e}")
        return None

    # ── Ground Dirt ─────────────────────────────────────────────────────────
    def add_ground_dirt(self):
        """Moss/dirt at the BASE of the model: a fill layer whose BaseColor is the
        grass/rock texture, masked by a bottom-heavy Position gradient + grunge."""
        import substance_painter.textureset as ts
        import substance_painter.layerstack as ls
        import substance_painter.source as sp_source

        try:
            if not project.is_open():
                display_msg("No project open!")
                return
            stack = ts.get_active_stack()
            if not stack:
                display_msg("Select a Texture Set first!")
                return

            # Texture (moss/rock) used as the layer's base color
            tex_rid = self._get_ground_texture()

            # ── Fill layer ──────────────────────────────────────────────
            pos = ls.InsertPosition.from_textureset_stack(stack)
            ground_layer = ls.insert_fill(pos)
            ground_layer.set_name("Ground Dirt")
            self.ground_layer = ground_layer

            try:
                ground_layer.active_channels = {ts.ChannelType.BaseColor}
            except Exception as e:
                print(f"Bridge Ground: active_channels failed: {e}")

            # BaseColor = grass/rock texture (triplanar so it ignores UVs)
            if tex_rid:
                try:
                    ground_layer.set_source(ts.ChannelType.BaseColor, tex_rid)
                    try:
                        ground_layer.set_projection_mode(ls.ProjectionMode.Triplanar)
                        params = ground_layer.get_projection_parameters()
                        if params is not None:
                            params.uv_transformation = ls.UVTransformationParams(
                                scale_mode=ls.ScaleMode.Factors, scale=[3.0, 3.0])
                            ground_layer.set_projection_parameters(params)
                    except Exception as ep:
                        print(f"Bridge Ground: projection failed: {ep}")
                    print("Bridge Ground: BaseColor set to grass/rock texture.")
                except Exception as e:
                    print(f"Bridge Ground: set_source failed: {e}")
            else:
                # Fallback: mossy green-brown uniform color
                from substance_painter.colormanagement import Color
                try:
                    src = ground_layer.get_source(ts.ChannelType.BaseColor)
                    if isinstance(src, sp_source.SourceUniformColor):
                        src.set_color(Color(0.18, 0.20, 0.10))
                except Exception:
                    pass

            # ── Black mask ──────────────────────────────────────────────
            try:
                ground_layer.add_mask(ls.MaskBackground.Black)
            except Exception as e:
                display_msg(f"Ground: mask failed: {e}")
                return
            mask_insert = ls.InsertPosition.inside_node(ground_layer, ls.NodeStack.Mask)

            # ── Position gradient: BOTTOM-heavy (effect only near the base) ─
            pos_rid = self._find_generator([
                "s:starterassets u:generator n:Position",
                "s:starterassets u:generator n:3D Linear Gradient",
            ])
            if pos_rid:
                try:
                    gp = ls.insert_generator_effect(mask_insert, pos_rid)
                    self.ground_pos_gen = gp
                    src = gp.get_source()
                    if src:
                        params = src.get_parameters()
                        print(f"Bridge Ground: Position params: {list(params.keys())}")
                        updated = dict(params)
                        for key in params:
                            kl = key.lower().replace(" ", "_")
                            if kl == "global_invert":
                                updated[key] = 1      # int32; effect at the BASE
                            elif kl == "global_balance":
                                updated[key] = 0.88   # default = 12% height (slider)
                            elif kl == "global_contrast":
                                updated[key] = 0.89
                            elif kl == "top_to_bottom":
                                updated[key] = 1      # vertical axis
                            elif kl in ("right_to_left", "front_to_back"):
                                updated[key] = 0
                        src.set_parameters(updated)
                        print("Bridge Ground: Position params applied (bottom).")
                except Exception as e:
                    print(f"Bridge Ground: Position gen failed: {e}")

            # ── Activate sliders ────────────────────────────────────────
            self.ground_slider.setValue(100)
            self.ground_slider.setEnabled(True)
            self.ground_intensity_label.setStyleSheet("color: #d8ffaa; font-size: 11px;")
            self.ground_height_slider.setValue(12)
            self.ground_height_slider.setEnabled(True)
            self.ground_height_label.setStyleSheet("color: #d8ffaa; font-size: 11px;")
            self.ground_soft_slider.setValue(11)
            self.ground_soft_slider.setEnabled(True)
            self.ground_soft_label.setStyleSheet("color: #d8ffaa; font-size: 11px;")
            display_msg("Ground dirt added! (moss/rock at the base)")

        except Exception as e:
            import traceback
            print(f"Bridge ADD GROUND DIRT Error: {e}")
            traceback.print_exc()
            display_msg(f"ADD GROUND DIRT Error: {str(e)[:60]}")

    # ── Rust / Aging ────────────────────────────────────────────────────────
    def add_rust(self):
        """Rust / aging on EDGES and raised areas (edge wear): a rusty fill layer
        masked by Curvature (convex edges) broken up with a grunge texture."""
        import substance_painter.textureset as ts
        import substance_painter.layerstack as ls
        import substance_painter.source as sp_source
        from substance_painter.colormanagement import Color

        try:
            if not project.is_open():
                display_msg("No project open!")
                return
            stack = ts.get_active_stack()
            if not stack:
                display_msg("Select a Texture Set first!")
                return

            # ── Fill layer ──────────────────────────────────────────────
            pos = ls.InsertPosition.from_textureset_stack(stack)
            rust_layer = ls.insert_fill(pos)
            rust_layer.set_name("Rust")
            self.rust_layer = rust_layer

            # Rust affects color + roughness (rust is rough/matte)
            try:
                if not stack.has_channel(ts.ChannelType.Roughness):
                    stack.add_channel(ts.ChannelType.Roughness, ts.ChannelFormat.L8)
                rust_layer.active_channels = {ts.ChannelType.BaseColor, ts.ChannelType.Roughness}
            except Exception as e:
                print(f"Bridge Rust: active_channels failed: {e}")

            # Rusty orange-brown BaseColor (#5e2710)
            try:
                src_c = rust_layer.get_source(ts.ChannelType.BaseColor)
                if isinstance(src_c, sp_source.SourceUniformColor):
                    src_c.set_color(Color(0.37, 0.15, 0.06))
            except Exception as e:
                print(f"Bridge Rust: BaseColor failed: {e}")

            # High roughness — rust is matte
            try:
                src_r = rust_layer.get_source(ts.ChannelType.Roughness)
                if isinstance(src_r, sp_source.SourceUniformColor):
                    src_r.set_color(Color(0.85, 0.85, 0.85))
            except Exception as e:
                print(f"Bridge Rust: Roughness failed: {e}")

            # ── Black mask ──────────────────────────────────────────────
            try:
                rust_layer.add_mask(ls.MaskBackground.Black)
            except Exception as e:
                display_msg(f"Rust: mask failed: {e}")
                return
            mask_insert = ls.InsertPosition.inside_node(rust_layer, ls.NodeStack.Mask)

            # ── Curvature: rust collects on convex EDGES (edge wear) ─────
            curv_rid = self._find_generator([
                "s:starterassets u:generator n:Curvature",
                "s:starterassets u:generator n:Metal Edge Wear",
                "s:starterassets u:generator n:Ambient Occlusion",
            ])
            if curv_rid:
                try:
                    gc = ls.insert_generator_effect(mask_insert, curv_rid)
                    self.rust_gen = gc
                    src = gc.get_source()
                    if src:
                        params = src.get_parameters()
                        print(f"Bridge Rust: Curvature params: {list(params.keys())}")
                        updated = dict(params)
                        for key in params:
                            kl = key.lower().replace(" ", "_")
                            if kl == "global_blur":
                                updated[key] = 1.35
                            elif kl == "global_balance":
                                updated[key] = 0.07   # default = Rust Balance slider
                            elif kl == "global_contrast":
                                updated[key] = 0.04
                        src.set_parameters(updated)
                        print("Bridge Rust: Curvature params applied.")
                except Exception as e:
                    print(f"Bridge Rust: Curvature gen failed: {e}")

            # ── Grunge texture (Multiply): break edge wear into patches ──
            grunge_rid = self._find_texture([
                "s:starterassets u:texture grunge",
                "s:starterassets u:texture rust",
                "s:starterassets u:texture dirt",
                "grunge",
            ])
            if grunge_rid:
                try:
                    gf = ls.insert_fill(mask_insert)
                    gf.set_source(None, grunge_rid)
                    try:
                        gf.set_blending_mode(ls.BlendingMode.Multiply)
                    except Exception:
                        pass
                    try:
                        gf.set_projection_mode(ls.ProjectionMode.Triplanar)
                    except Exception:
                        pass
                    print(f"Bridge Rust: grunge texture added: {grunge_rid.name}")
                except Exception as e:
                    print(f"Bridge Rust: grunge fill failed: {e}")

            # ── Activate sliders ────────────────────────────────────────
            self.rust_slider.setValue(80)
            self.rust_slider.setEnabled(True)
            self.rust_intensity_label.setStyleSheet("color: #ffbb88; font-size: 11px;")
            self.rust_balance_slider.setValue(7)
            self.rust_balance_slider.setEnabled(True)
            self.rust_balance_label.setStyleSheet("color: #ffbb88; font-size: 11px;")
            display_msg("Rust / aging added! (edge wear)")

        except Exception as e:
            import traceback
            print(f"Bridge ADD RUST Error: {e}")
            traceback.print_exc()
            display_msg(f"ADD RUST Error: {str(e)[:60]}")

    def on_import_clicked(self):
        import substance_painter.project as project
        mesh_path = project.last_imported_mesh_path()
        if mesh_path: process_import(mesh_path)
        else: display_msg("No mesh found in current project!")

    def add_dirt_layer(self):
        """Create a Fill Layer named 'Dirt' with base color #242424,
        a Black mask, and a Dirt generator with preset parameters."""
        import substance_painter.textureset as ts
        import substance_painter.layerstack as ls
        import substance_painter.resource as resource
        from substance_painter.colormanagement import Color

        try:
            if not project.is_open():
                display_msg("No project open!")
                return

            stack = ts.get_active_stack()
            if not stack:
                display_msg("Select a Texture Set first!")
                return

            # ── 1. Insert Fill Layer at top of stack ─────────────────────────
            pos = ls.InsertPosition.from_textureset_stack(stack)
            dirt_layer = ls.insert_fill(pos)
            dirt_layer.name = "Dirt"

            # ── 2. Activate only Base Color channel FIRST, then set color ────────
            # active_channels must be set before get_source() — otherwise source is None
            try:
                dirt_layer.active_channels = {ts.ChannelType.BaseColor}
            except Exception:
                pass

            import substance_painter.source as sp_source
            # Color() takes exactly 3 floats (r, g, b) — no alpha arg
            dark_dirt = Color(0.1, 0.07, 0.03)
            color_set = False

            try:
                src = dirt_layer.get_source(ts.ChannelType.BaseColor)
                if isinstance(src, sp_source.SourceUniformColor):
                    src.set_color(dark_dirt)
                    color_set = True
                    print("Bridge: Color set via set_color()")
                else:
                    dirt_layer.set_source(ts.ChannelType.BaseColor, dark_dirt)
                    color_set = True
                    print("Bridge: Color set via set_source()")
            except Exception as e:
                print(f"Bridge: set_color failed: {e}")

            if not color_set:
                print("Bridge: WARNING - Could not set fill color. Remains at default.")

            # ── 3. Add Black Mask ─────────────────────────────────────────────
            try:
                dirt_layer.add_mask(ls.MaskBackground.Black)
                print("Bridge: Black mask added.")
            except Exception as e:
                print(f"Bridge: Could not add mask: {e}")
                display_msg("Dirt layer created (mask may need to be added manually).")
                return

            # ── 4 & 5. Find and Insert the Dirt generator ─────────────────────
            gen = None
            dirt_res_id = None
            mask_pos = ls.InsertPosition.inside_node(dirt_layer, ls.NodeStack.Mask)
            
            try:
                candidates = resource.search("Dirt")
                # First pass: exact name match
                for r in candidates:
                    rid = r.identifier()
                    if rid.name.lower() == "dirt":
                        try:
                            gen = ls.insert_generator_effect(mask_pos, rid)
                            dirt_res_id = rid
                            self.dirt_gen = gen
                            print(f"Bridge: Inserted Dirt generator: {rid.name} [{rid.context}]")
                            break
                        except ValueError:
                            pass

                # Second pass: partial name match if exact failed
                if not gen:
                    for r in candidates:
                        rid = r.identifier()
                        try:
                            gen = ls.insert_generator_effect(mask_pos, rid)
                            dirt_res_id = rid
                            self.dirt_gen = gen
                            print(f"Bridge: Inserted fallback Dirt generator: {rid.name} [{rid.context}]")
                            break
                        except ValueError:
                            pass
            except Exception as e:
                print(f"Bridge: Generator search error: {e}")

            if not gen:
                display_msg("'Dirt' generator not found or invalid!")
                print("Bridge: Dirt generator not found. Mask added without generator.")
                return

            # ── 6. Set generator parameters ───────────────────────────────────
            # Parameters from the user's reference screenshot:
            #   Dirt Level        0.51
            #   Dirt Contrast     0.45
            #   Use Triplanar     False
            #   Grunge Amount     0.3
            #   Grunge Scale      4
            #   Edges Masking     0.5
            DESIRED_PARAMS = {
                # Possible SP internal names for Dirt generator
                "dirt_level":              0.51,
                "level":                   0.51,
                "dirtlevel":               0.51,
                "dirt_contrast":           0.45,
                "contrast":                0.45,
                "dirtcontrast":            0.45,
                "use_triplanar":           0, # SP requires int32 for booleans
                "usetriplanar":            0,
                "triplanar":               0,
                "grunge_amount":           0.3,
                "grungeamount":            0.3,
                "amount":                  0.3,
                "grunge_scale":            4,
                "grungeschale":            4,
                "scale":                   4,
                "edges_masking":           0.5,
                "edgesmasking":            0.5,
                "edges":                   0.5,
                "triplanar_blend_contrast":0.5,
                "triplanarblencontrast":   0.5,
            }

            try:
                src = gen.get_source()
                if src:
                    current_params = src.get_parameters()
                    print(f"Bridge: Dirt generator params available: {list(current_params.keys())}")

                    updated = dict(current_params)
                    for key in list(current_params.keys()):
                        key_norm = key.lower().replace(" ", "_").replace("-", "")
                        if key_norm in DESIRED_PARAMS:
                            updated[key] = DESIRED_PARAMS[key_norm]
                        elif key.lower() in DESIRED_PARAMS:
                            updated[key] = DESIRED_PARAMS[key.lower()]

                    src.set_parameters(updated)
                    print("Bridge: Dirt generator parameters applied.")
                else:
                    print("Bridge: Generator source is None after insertion.")
            except Exception as e:
                print(f"Bridge: Could not set generator parameters: {e}")

            display_msg("Dirt layer added! (Fill + Black Mask + Dirt Generator)")
            self.dirt_slider.setValue(100)
            self.dirt_slider.setEnabled(True)
            self.dirt_intensity_label.setStyleSheet("color: #ccffcc; font-size: 11px;")

        except Exception as e:
            import traceback
            print(f"Bridge ADD DIRT Error: {str(e)}")
            traceback.print_exc()
            display_msg(f"ADD DIRT Error: {str(e)[:60]}")

def create_bridge_ui():
    try:
        for w in plugin_widgets:
            if isinstance(w, BridgeWindow): w.show(); w.raise_(); return
        window = BridgeWindow()
        ui.add_dock_widget(window)
        window.show()
        plugin_widgets.append(window)
    except: pass

def try_import_baked_textures():
    """Called after project creation. Imports any baked textures from temp_bkd
    (if present), then ALWAYS triggers mesh-map baking + assignment — baking
    must run regardless of whether temp_bkd has textures."""
    import substance_painter.project as project
    if not project.is_open():
        return

    bkd_dir = os.path.join(BRIDGE_DIR, "temp_bkd")
    textures = []
    if os.path.exists(bkd_dir):
        textures = [f for f in os.listdir(bkd_dir) if f.lower().endswith(".png")]

    if textures:
        display_msg(f"Auto-importing {len(textures)} baked textures...")
        process_import()
    else:
        display_msg("No baked textures in temp_bkd — baking mesh maps only.")

    # Always bake mesh maps + assign, whether or not base textures exist
    display_msg("Auto-triggering Bake & Assign in 2 seconds...")
    QtCore.QTimer.singleShot(2000, start_bake_and_assign)

def auto_import_on_startup():
    """On SP startup: auto-open FBX from BRIDGE_DIR, then import baked textures."""
    import substance_painter.project as project
    fbx_path = os.path.join(BRIDGE_DIR, "SP_Export.fbx")

    if not os.path.exists(fbx_path):
        # No FBX ready yet, nothing to do
        return

    # Write last imported FBX path to a temp file for context
    temp_file = os.path.join(tempfile.gettempdir(), "sp_bridge_fbx_path.txt")
    try:
        with open(temp_file, "w") as f:
            f.write(fbx_path)
    except: pass

    if project.is_open():
        # Project already open — just try to import baked textures
        try_import_baked_textures()
        return

    # No project open — auto-create from FBX
    try:
        display_msg(f"Auto-loading: {os.path.basename(fbx_path)}")
        try:
            project.create(mesh_file_path=fbx_path, settings=project.Settings(default_texture_resolution=4096))
        except:
            project.create(fbx_path)
        # After project creation, wait 5s then auto-import baked textures
        QtCore.QTimer.singleShot(5000, try_import_baked_textures)
    except Exception as e:
        display_msg(f"Auto-load error: {str(e)}")

def start_plugin():
    QtCore.QTimer.singleShot(3000, create_bridge_ui)
    # Wait 4s for SP to fully initialize, then auto-load FBX & textures
    QtCore.QTimer.singleShot(4000, auto_import_on_startup)

def close_plugin():
    for widget in plugin_widgets:
        try: ui.delete_ui_element(widget)
        except: pass
    plugin_widgets.clear()

if __name__ == "__main__":
    start_plugin()
