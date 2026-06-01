"""PTSL Bridge — connection management and command wrappers for py-ptsl."""

import functools
import subprocess
import threading
import time
import re
from typing import Optional, List, Dict, Any

import grpc
from ptsl import Engine
from ptsl.engine import open_engine
from ptsl import ops
from ptsl.ops.operation import Operation
import ptsl.PTSL_pb2 as pt
from ptsl.errors import CommandError

from utils import samples_to_timecode, is_sample_position


# Custom Operation subclasses for commands that exist in protobuf
# but have no ops module wrapper in py-ptsl
class SetTrackMuteState(Operation):
    pass


class SetTrackSoloState(Operation):
    pass


class SetTrackSoloSafeState(Operation):
    pass


class GetTrackPlaylists(Operation):
    @classmethod
    def command_id(cls):
        return getattr(pt, "CId_GetTrackPlaylists", -1)

    def json_messup(self, in_json: str) -> str:
        """Remove track_id from the JSON to avoid 'only one of track_id/track_name' error."""
        import json as _json
        d = _json.loads(in_json)
        d.pop("track_id", None)
        return _json.dumps(d)


class GetPlaylistElements(Operation):
    @classmethod
    def command_id(cls):
        return getattr(pt, "CId_GetPlaylistElements", -1)

    def json_messup(self, in_json: str) -> str:
        import json as _json
        d = _json.loads(in_json)
        d.pop("playlist_id", None)
        return _json.dumps(d)


class Undo(Operation):
    @classmethod
    def command_id(cls):
        return getattr(pt, "CId_Undo", 104)


class PTSLConnectionError(Exception):
    """Raised when PTSL connection cannot be established."""
    pass


def ptsl_command(func):
    """Decorator that wraps PTSL calls with connection management and error handling.

    The decorated function receives `engine` as its first argument after `self`.
    Returns structured data on success, or a structured error dict on failure.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            engine = self._ensure_connected()
            return func(self, engine, *args, **kwargs)
        except PTSLConnectionError:
            return {"error": "ptsl_unavailable",
                    "message": "Pro Tools is not running or PTSL connection failed on port 31416"}
        except CommandError as e:
            msg = str(e.message) if hasattr(e, 'message') else str(e)
            # Classify no-session errors
            if "no session" in msg.lower() or "no open" in msg.lower():
                return {"error": "no_session",
                        "message": "No Pro Tools session is currently open"}
            return {"error": "ptsl_command_error", "message": msg}
        except grpc.RpcError as e:
            self._reset_connection()
            return {"error": "ptsl_unavailable",
                    "message": f"Lost connection to Pro Tools: {e}"}
        except Exception as e:
            return {"error": "unexpected_error",
                    "message": f"Unexpected error: {type(e).__name__}: {e}"}
    return wrapper


class PTSLBridge:
    """Manages the PTSL connection and provides wrapped command methods."""

    def __init__(self):
        self._engine: Optional[Engine] = None
        self._edl_cache: Optional[Dict[str, Any]] = None
        self._edl_cache_time: float = 0.0
        self._edl_cache_ttl: float = 30.0  # seconds

    def _ensure_connected(self) -> Engine:
        """Lazily connect to Pro Tools. Returns the Engine instance."""
        if self._engine is None:
            try:
                self._engine = Engine(
                    company_name="ProToolsMCP",
                    application_name="protools-mcp"
                )
            except grpc.RpcError:
                raise PTSLConnectionError(
                    "Pro Tools is not running or PTSL connection failed on port 31416")
            except Exception as e:
                raise PTSLConnectionError(str(e))
        return self._engine

    def _reset_connection(self):
        """Reset the cached engine so the next call will reconnect."""
        if self._engine:
            try:
                self._engine.close()
            except Exception:
                pass
        self._engine = None

    # ── Session Info ──

    @ptsl_command
    def get_session_name(self, engine) -> str:
        return engine.session_name()

    @ptsl_command
    def get_session_path(self, engine) -> str:
        return engine.session_path()

    @ptsl_command
    def get_session_sample_rate(self, engine) -> int:
        return engine.session_sample_rate()

    @ptsl_command
    def get_session_bit_depth(self, engine) -> str:
        bd = engine.session_bit_depth()
        return pt.BitDepth.Name(bd)

    @ptsl_command
    def get_session_timecode_rate(self, engine) -> str:
        tcr = engine.session_timecode_rate()
        return pt.SessionTimeCodeRate.Name(tcr)

    @ptsl_command
    def get_session_length(self, engine) -> str:
        return engine.session_length()

    @ptsl_command
    def get_session_start_time(self, engine) -> str:
        return engine.session_start_time()

    @ptsl_command
    def get_track_count(self, engine) -> int:
        tracks = engine.track_list()
        return len(tracks)

    @ptsl_command
    def get_audio_file_count(self, engine) -> int:
        files = engine.get_file_location()
        return len(files)

    # ── Track List ──

    @ptsl_command
    def get_track_list(self, engine, track_filter: str = "all") -> list:
        filters = []
        if track_filter == "inactive":
            filters = [pt.TrackListInvertibleFilter(filter=pt.Inactive, is_inverted=False)]
        elif track_filter == "active":
            filters = [pt.TrackListInvertibleFilter(filter=pt.Inactive, is_inverted=True)]
        else:
            filters = [pt.TrackListInvertibleFilter(filter=pt.All, is_inverted=False)]

        tracks = engine.track_list(filters=filters)
        result = []
        for t in tracks:
            # For "audio" filter, post-filter by track type
            if track_filter == "audio" and t.type != pt.TT_Audio:
                continue
            attrs = t.track_attributes
            result.append({
                "name": t.name,
                "type": pt.TrackType.Name(t.type),
                "format": pt.TrackFormat.Name(t.format),
                "active": attrs.is_inactive == pt.TAState_None,
                "muted": attrs.is_muted,
                "soloed": attrs.is_soloed,
                "record_armed": attrs.is_record_enabled,
                "hidden": attrs.is_hidden != pt.TAState_None,
                "color": t.color
            })
        return result

    # ── Markers ──

    @ptsl_command
    def get_memory_locations(self, engine) -> list:
        markers = engine.get_memory_locations()
        # Get sample rate for conversion
        sample_rate = engine.session_sample_rate() or 48000
        # Determine fps from timecode rate
        fps = self._get_fps(engine)

        result = []
        for m in markers:
            tc = m.start_time
            if is_sample_position(tc):
                tc = samples_to_timecode(int(tc), sample_rate=sample_rate, fps=fps)
            result.append({
                "index": m.number,
                "name": m.name,
                "timecode": tc,
                "comment": m.comments
            })
        return result

    def _get_fps(self, engine) -> int:
        """Get the session frame rate as an integer."""
        try:
            tcr = engine.session_timecode_rate()
            tcr_name = pt.SessionTimeCodeRate.Name(tcr)
            # Map common rates
            fps_map = {
                "STCR_Fps23976": 24,
                "STCR_Fps24": 24,
                "STCR_Fps25": 25,
                "STCR_Fps2997": 30,
                "STCR_Fps2997Drop": 30,
                "STCR_Fps30": 30,
            }
            return fps_map.get(tcr_name, 24)
        except Exception:
            return 24

    # ── EDL / Clips ──

    @ptsl_command
    def get_edl_text(self, engine) -> str:
        """Export session text with track EDLs. Cached for 30s."""
        now = time.time()
        if self._edl_cache is not None and (now - self._edl_cache_time) < self._edl_cache_ttl:
            return self._edl_cache

        builder = engine.export_session_as_text()
        builder.include_track_edls()
        builder.time_type("timecode")
        text = builder.export_string()
        self._edl_cache = text
        self._edl_cache_time = now
        return text

    def invalidate_edl_cache(self):
        """Force EDL cache refresh on next call."""
        self._edl_cache = None
        self._edl_cache_time = 0.0

    # ── Track Playlists ──

    @ptsl_command
    def get_track_playlists(self, engine, track_name: str) -> list:
        op = GetTrackPlaylists(
            track_name=track_name,
            pagination_request=pt.PaginationRequest(limit=100, offset=0)
        )
        engine.client.run(op)
        playlists = op.response.playlists if op.response else []
        return [
            {
                "name": p.playlist_name,
                "is_active": p.is_target,
                "clip_count": -1  # Not directly available without querying each
            }
            for p in playlists
        ]

    # ── Transport / Navigation ──

    @ptsl_command
    def get_timeline_selection(self, engine):
        in_time, out_time = engine.get_timeline_selection()
        return {"in_time": in_time, "out_time": out_time}

    @ptsl_command
    def set_timeline_selection(self, engine, in_time: str, out_time: str = None):
        engine.set_timeline_selection(in_time=in_time, out_time=out_time)
        return {"confirmed": True}

    @ptsl_command
    def get_selected_tracks(self, engine) -> list:
        """Return names of currently selected tracks."""
        tracks = engine.track_list()
        return [
            t.name for t in tracks
            if t.track_attributes.is_selected != pt.TAState_None
        ]

    # ── Edit Operations ──

    @ptsl_command
    def select_tracks_by_name(self, engine, names: list):
        engine.select_tracks_by_name(names=names)
        return {"confirmed": True}

    @ptsl_command
    def set_track_mute(self, engine, track_names: list, enabled: bool):
        op = SetTrackMuteState(track_names=track_names, enabled=enabled)
        engine.client.run(op)
        return {"confirmed": True, "new_state": "muted" if enabled else "unmuted"}

    @ptsl_command
    def set_track_solo(self, engine, track_names: list, enabled: bool):
        op = SetTrackSoloState(track_names=track_names, enabled=enabled)
        engine.client.run(op)
        return {"confirmed": True, "new_state": "soloed" if enabled else "unsoloed"}

    @ptsl_command
    def create_marker(self, engine, name: str, timecode: str, comment: str = ""):
        engine.create_memory_location(
            name=name,
            start_time=timecode,
            time_properties=pt.TP_Marker,
            reference=pt.MLR_Absolute,
            comments=comment
        )
        # Get the new marker index by re-fetching markers
        markers = engine.get_memory_locations()
        new_marker = next((m for m in markers if m.name == name), None)
        marker_index = new_marker.number if new_marker else -1
        return {"marker_index": marker_index, "confirmed": True}

    @ptsl_command
    def consolidate_clip(self, engine, track_name: str, start_tc: str, end_tc: str):
        engine.select_tracks_by_name(names=[track_name])
        engine.set_timeline_selection(in_time=start_tc, out_time=end_tc)
        engine.consolidate_clip()
        return {"new_clip_name": f"{track_name}_consolidated", "confirmed": True}

    # ── Session Management ──

    @ptsl_command
    def save_session(self, engine):
        engine.client.run(ops.SaveSession())
        session_name = engine.session_name()
        return {"confirmed": True, "session_name": session_name}

    @ptsl_command
    def close_session(self, engine, save_on_close: bool = True):
        session_name = engine.session_name()
        engine.client.run(ops.CloseSession(save_on_close=save_on_close))
        self._reset_connection()
        return {"confirmed": True, "session_name": session_name}

    @ptsl_command
    def open_session(self, engine, session_path: str):
        engine.client.run(ops.OpenSession(session_path=session_path))
        session_name = engine.session_name()
        return {"confirmed": True, "session_name": session_name}

    @ptsl_command
    def export_selected_tracks_as_aaf(self, engine, file_type, bit_depth,
                                       copy_option, container_file_name: str,
                                       container_file_location: str,
                                       enforce_avid_compat: bool = False,
                                       quantize_to_frame: bool = True,
                                       stereo_as_multichannel: bool = False,
                                       sequence_name: str = ""):
        """Export selected tracks as AAF. Runs PTSL command in a thread and
        uses osascript to dismiss the folder picker dialog Pro Tools shows."""

        # Ensure trailing slash
        if not container_file_location.endswith("/"):
            container_file_location += "/"

        export_result = {"done": False, "error": None}

        def _run_export():
            try:
                engine.client.run(ops.ExportSelectedTracksAsAAFOMF(
                    file_type=file_type,
                    bit_depth=bit_depth,
                    copy_option=copy_option,
                    enforce_media_composer_compatibility=enforce_avid_compat,
                    quantize_edits_to_frame_boundaries=quantize_to_frame,
                    export_stereo_as_multichannel=stereo_as_multichannel,
                    container_file_name=container_file_name,
                    container_file_location=container_file_location,
                    sequence_name=sequence_name or container_file_name
                ))
                export_result["done"] = True
            except Exception as e:
                export_result["error"] = str(e)
                export_result["done"] = True

        # Start the PTSL command in a background thread (it blocks on dialog)
        export_thread = threading.Thread(target=_run_export, daemon=True)
        export_thread.start()

        # Give Pro Tools a moment to show the dialog
        time.sleep(2.0)

        # Use osascript to handle Pro Tools' folder picker dialog.
        # Strategy: wait for the "Open" window, use Cmd+Shift+G (Go to Folder),
        # type the path, press Go, then press the Choose/Open button.
        # If that fails, try Cmd+/ (path bar) or direct keystroke Return.
        applescript = f'''
            tell application "System Events"
                tell process "Pro Tools"
                    set frontmost to true

                    -- Wait for the dialog window to appear (up to 5 seconds)
                    set dialogFound to false
                    repeat 10 times
                        try
                            if exists window "Open" then
                                set dialogFound to true
                                exit repeat
                            end if
                        end try
                        delay 0.5
                    end repeat

                    if not dialogFound then
                        -- Check for any sheet on the front window
                        try
                            set sheetCount to count of sheets of window 1
                            if sheetCount > 0 then set dialogFound to true
                        end try
                    end if

                    if dialogFound then
                        delay 0.3
                        -- Open "Go to Folder" sheet
                        keystroke "g" using {{command down, shift down}}
                        delay 1.0

                        -- Type the destination path
                        keystroke "{container_file_location}"
                        delay 0.5

                        -- Press Return to navigate to the folder
                        keystroke return
                        delay 1.0

                        -- Press Return again to confirm/choose
                        keystroke return
                    end if
                end tell
            end tell
        '''

        osascript_worked = False
        try:
            r = subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True, text=True, timeout=20
            )
            osascript_worked = r.returncode == 0
        except subprocess.TimeoutExpired:
            pass

        if not osascript_worked:
            # Wait briefly — if PTSL completed without a dialog, great
            export_thread.join(timeout=3)
            if not export_result["done"]:
                return {
                    "error": "dialog_waiting",
                    "message": (
                        f"Pro Tools is showing a folder picker dialog. "
                        f"Please navigate to: {container_file_location} and click Choose. "
                        f"osascript could not dismiss it automatically — grant Accessibility "
                        f"access to the terminal/Python in System Settings > Privacy & Security > Accessibility."
                    ),
                    "tracks_selected": True,
                    "settings_applied": True
                }

        # Wait for the export to complete
        export_thread.join(timeout=120)

        if export_result["error"]:
            return {"error": "export_failed", "message": export_result["error"]}

        if not export_result["done"]:
            return {"error": "export_timeout", "message": "AAF export timed out after 120s"}

        return {
            "confirmed": True,
            "file_name": container_file_name,
            "location": container_file_location
        }

    @ptsl_command
    def save_session_as(self, engine, session_name: str, session_location: str):
        # Pro Tools requires trailing slash on directory path
        if not session_location.endswith("/"):
            session_location += "/"
        engine.client.run(ops.SaveSessionAs(
            session_name=session_name,
            session_location=session_location
        ))
        new_name = engine.session_name()
        new_path = engine.session_path()
        return {"confirmed": True, "session_name": new_name, "session_path": new_path}

    # ── Edit Mode & Editing ──

    @ptsl_command
    def get_edit_mode(self, engine) -> str:
        op = ops.GetEditMode()
        engine.client.run(op)
        mode_enum = op.response.current_setting
        return pt.EditMode.Name(mode_enum)

    @ptsl_command
    def set_edit_mode(self, engine, mode: str):
        mode_map = {
            "shuffle": pt.EMode_Shuffle,
            "slip": pt.EMode_Slip,
            "spot": pt.EMode_Spot,
            "grid_absolute": pt.EMode_GridAbsolute,
            "grid_relative": pt.EMode_GridRelative,
        }
        mode_enum = mode_map.get(mode.lower())
        if mode_enum is None:
            return {"error": "invalid_mode",
                    "message": f"Unknown edit mode '{mode}'. Use: shuffle, slip, spot, grid_absolute, grid_relative"}
        engine.client.run(ops.SetEditMode(edit_mode=mode_enum))
        return {"confirmed": True, "edit_mode": mode}

    @ptsl_command
    def clear_selection(self, engine):
        engine.client.run(ops.Clear())
        return {"confirmed": True}

    @ptsl_command
    def cut_selection(self, engine):
        engine.client.run(ops.Cut())
        return {"confirmed": True}

    @ptsl_command
    def create_fades(self, engine, preset_name: str = "", auto_adjust: bool = True):
        engine.client.run(ops.CreateFadesBasedOnPreset(
            fade_preset_name=preset_name,
            auto_adjust_bounds=auto_adjust
        ))
        return {"confirmed": True}

    @ptsl_command
    def trim_to_selection(self, engine):
        engine.client.run(ops.TrimToSelection())
        return {"confirmed": True}

    @ptsl_command
    def extend_selection_to_target_tracks(self, engine, track_names: list):
        engine.client.run(ops.ExtendSelectionToTargetTracks(
            tracks_to_extend_to=track_names
        ))
        return {"confirmed": True}

    @ptsl_command
    def undo(self, engine):
        op = Undo()
        engine.client.run(op)
        return {"confirmed": True}

    # ── Import / Rename / Bounce (added 2026-04-29) ──

    @ptsl_command
    def import_audio_files(self, engine, file_list: List[str],
                           audio_operations: str = "CopyAudio",
                           destination: str = "NewTrack",
                           location: str = "SessionStart") -> dict:
        """Import audio file(s) into the open session.

        py-ptsl 601.0.0 has a bug — its `engine.import_audio` hardcodes
        `import_type=1` (Session), which makes Pro Tools reject the request as
        "The path to the imported session is missed." We bypass that and call
        CId_Import directly with `import_type=2` (Audio).

        :param file_list: Absolute paths to audio files.
        :param audio_operations: "AddAudio" | "CopyAudio" | "ConvertAudio" | "Default".
            CopyAudio (default) copies files into the session's Audio Files folder.
        :param destination: "NewTrack" | "ClipList" | "MainVideoTrack". Default
            "NewTrack" creates a new track per file.
        :param location: "SessionStart" | "SongStart" | "Selection" | "Spot".
        """
        ao_map = {
            "AddAudio": pt.AOperations_AddAudio,
            "CopyAudio": pt.AOperations_CopyAudio,
            "ConvertAudio": pt.AOperations_ConvertAudio,
            "Default": pt.AOperations_Default,
        }
        md_map = {
            "NewTrack": pt.MD_NewTrack,
            "ClipList": pt.MD_ClipList,
            "MainVideoTrack": pt.MD_MainVideoTrack,
        }
        ml_map = {
            "SessionStart": pt.ML_SessionStart,
            "SongStart": pt.ML_SongStart,
            "Selection": pt.ML_Selection,
            "Spot": pt.ML_Spot,
        }
        if audio_operations not in ao_map:
            raise ValueError(f"audio_operations must be in {list(ao_map)}")
        if destination not in md_map:
            raise ValueError(f"destination must be in {list(md_map)}")
        if location not in ml_map:
            raise ValueError(f"location must be in {list(ml_map)}")

        location_data = pt.SpotLocationData(
            location_type=pt.SLType_Start,
            location_options=pt.TOOptions_TimeCode,
        )
        audio_data = pt.AudioData(
            file_list=file_list,
            audio_operations=ao_map[audio_operations],
            audio_destination=md_map[destination],
            audio_location=ml_map[location],
            location_data=location_data,
        )
        # import_type=2 = Audio (py-ptsl hardcodes 1 = Session, which is the bug)
        op = ops.CId_Import(import_type=pt.IType_Audio, audio_data=audio_data)
        engine.client.run(op)
        return {
            "imported": len(file_list),
            "files": file_list,
            "audio_operations": audio_operations,
            "destination": destination,
            "location": location,
        }

    @ptsl_command
    def rename_track(self, engine, old_name: str, new_name: str) -> dict:
        """Rename a single track by name."""
        engine.rename_target_track(old_name, new_name)
        return {"old_name": old_name, "new_name": new_name}

    @ptsl_command
    def bounce_to_disk(
        self,
        engine,
        output_dir: str,
        base_name: str,
        file_type: str = "MP3",
        source_name: str = "Out 1-2",
        source_type: str = "Output",
        export_format: str = "Interleaved",
        bit_depth: int = 16,
        sample_rate: int = 48000,
        offline: bool = True,
    ) -> dict:
        """Export the active mix bus(es) to disk — equivalent to PT's "Bounce to Disk".

        :param output_dir: Folder to write the bounce into.
        :param base_name:  File-name stem (extension added by Pro Tools).
        :param file_type:  "MP3" | "WAV" | "AIFF" | "MOV" | "M4A".
        :param source_name: Bus / output name to bounce (default "Out 1-2").
        :param source_type: "Output" | "Bus" | "PhysicalOut".
        :param export_format: "Interleaved" (stereo) | "Mono" | "MultipleMono".
        :param bit_depth:  16 | 24 | 32 (32 = float). Ignored for MP3.
        :param sample_rate: 44100 | 48000 | 88200 | 96000 | 176400 | 192000.
        :param offline: True for offline (faster-than-realtime) bounce.
        """
        # Map string params → proto enum values
        ft_map = {
            "MP3": pt.EMFType_MP3,
            "WAV": pt.EMFType_WAV,
            "AIFF": pt.EMFType_AIFF,
            "MOV": pt.EMFType_MOV,
            "M4A": pt.EMFType_M4A,
        }
        st_map = {
            "Output": pt.EMSType_Output,
            "Bus": pt.EMSType_Bus,
            "PhysicalOut": pt.EMSType_PhysicalOut,
        }
        ef_map = {
            "Interleaved": pt.EFormat_Interleaved,
            "Mono": pt.EFormat_Mono,
            "MultipleMono": pt.EFormat_MultipleMono,
        }
        bd_map = {16: pt.BDepth_16, 24: pt.BDepth_24, 32: pt.BDepth_32Float}
        sr_map = {
            44100: pt.SRate_44100,
            48000: pt.SRate_48000,
            88200: pt.SRate_88200,
            96000: pt.SRate_96000,
            176400: pt.SRate_176400,
            192000: pt.SRate_192000,
        }

        if file_type not in ft_map:
            raise ValueError(f"file_type must be one of {list(ft_map.keys())}")
        if source_type not in st_map:
            raise ValueError(f"source_type must be one of {list(st_map.keys())}")
        if export_format not in ef_map:
            raise ValueError(f"export_format must be one of {list(ef_map.keys())}")
        if bit_depth not in bd_map:
            raise ValueError(f"bit_depth must be one of {list(bd_map.keys())}")
        if sample_rate not in sr_map:
            raise ValueError(f"sample_rate must be one of {list(sr_map.keys())}")

        audio_info = pt.EM_AudioInfo(
            compression_type=pt.CT_PCM,
            export_format=ef_map[export_format],
            bit_depth=bd_map[bit_depth],
            sample_rate=sr_map[sample_rate],
            pad_to_frame_boundary=pt.TB_False,
            delivery_format=pt.EM_DF_SingleFile,
        )
        sources = [pt.EM_SourceInfo(source_type=st_map[source_type], name=source_name)]
        video_info = pt.EM_VideoInfo(
            include_video=pt.TB_False,
            export_option=pt.VE_None,
            replace_timecode_track=pt.TB_False,
        )
        location_info = pt.EM_LocationInfo(
            import_after_bounce=pt.TB_False,
            file_destination=pt.EM_FD_Directory,
            directory=output_dir,
        )
        dolby_atmos_info = pt.EM_DolbyAtmosInfo()  # empty for non-Atmos bounce

        engine.export_mix(
            base_name=base_name,
            file_type=ft_map[file_type],
            sources=sources,
            audio_info=audio_info,
            video_info=video_info,
            location_info=location_info,
            dolby_atmos_info=dolby_atmos_info,
            offline_bounce=pt.TB_True if offline else pt.TB_False,
        )
        return {
            "output_dir": output_dir,
            "base_name": base_name,
            "file_type": file_type,
            "source": source_name,
            "format": export_format,
            "sample_rate": sample_rate,
            "bit_depth": bit_depth,
            "offline": offline,
        }


def parse_edl_text(text: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse Pro Tools text export with track EDLs into structured data.

    The actual format from Pro Tools is tab-delimited with columns:
    CHANNEL  EVENT  CLIP NAME  START TIME  END TIME  DURATION  STATE

    Returns a dict keyed by track name, each value is a list of clip dicts.
    """
    tracks = {}
    current_track = None
    in_clip_section = False
    clip_index = 0

    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()

        # Detect track header
        if stripped.startswith("TRACK NAME:"):
            current_track = stripped.split("TRACK NAME:")[1].strip()
            tracks[current_track] = []
            in_clip_section = False
            clip_index = 0
            continue

        # Detect the clip listing header row
        if current_track and stripped.startswith("CHANNEL") and "CLIP NAME" in stripped:
            in_clip_section = True
            continue

        # Blank line ends clip section
        if in_clip_section and not stripped:
            in_clip_section = False
            continue

        # Parse clip rows (tab-delimited)
        if in_clip_section and current_track and stripped:
            parts = line.split("\t")
            # Clean up whitespace from each part
            parts = [p.strip() for p in parts]
            # Filter out empty parts
            parts = [p for p in parts if p]

            if len(parts) >= 7:
                # Full format: channel, event, clip_name, start, end, duration, state
                clip_index += 1
                tracks[current_track].append({
                    "index": clip_index,
                    "clip_name": parts[2],
                    "start": parts[3],
                    "end": parts[4],
                    "duration": parts[5],
                    "state": parts[6]
                })
            elif len(parts) >= 5:
                # Partial format: try to map what we can
                clip_index += 1
                tracks[current_track].append({
                    "index": clip_index,
                    "clip_name": parts[2] if len(parts) > 2 else parts[0],
                    "start": parts[3] if len(parts) > 3 else "",
                    "end": parts[4] if len(parts) > 4 else "",
                    "duration": parts[5] if len(parts) > 5 else "",
                    "state": parts[6] if len(parts) > 6 else "Unmuted"
                })

    return tracks
