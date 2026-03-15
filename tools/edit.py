"""Edit operation tools (Group 5) — these modify the session.

WARNING: All tools in this module are write operations. Claude should always
describe the intended operation and confirm with the user before calling them.
"""

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from typing import Optional, List

import ptsl.PTSL_pb2 as pt


def _check_error(result):
    if isinstance(result, dict) and "error" in result:
        raise ToolError(result["message"])
    return result


def register_edit_tools(mcp: FastMCP, bridge):

    @mcp.tool()
    def select_region(start_timecode: str, end_timecode: str,
                      track_names: Optional[List[str]] = None) -> dict:
        """[WRITE] Makes a timeline selection between two timecodes. Optionally selects specific tracks. This modifies the session selection state."""
        if track_names:
            _check_error(bridge.select_tracks_by_name(names=track_names))
        result = bridge.set_timeline_selection(in_time=start_timecode, out_time=end_timecode)
        _check_error(result)
        tracks_str = ", ".join(track_names) if track_names else "all tracks"
        return {"confirmed": True,
                "message": f"Selected region {start_timecode} to {end_timecode} on {tracks_str}"}

    @mcp.tool()
    def create_marker(name: str, timecode: str, comment: Optional[str] = None) -> dict:
        """[WRITE] Creates a named memory location marker at the specified timecode. This adds a new marker to the session."""
        result = bridge.create_marker(name=name, timecode=timecode, comment=comment or "")
        return _check_error(result)

    @mcp.tool()
    def mute_track(track_name: str) -> dict:
        """[WRITE] Mutes a track by name. This changes the track's mute state in the session."""
        result = bridge.set_track_mute(track_names=[track_name], enabled=True)
        return _check_error(result)

    @mcp.tool()
    def unmute_track(track_name: str) -> dict:
        """[WRITE] Unmutes a track by name. This changes the track's mute state in the session."""
        result = bridge.set_track_mute(track_names=[track_name], enabled=False)
        return _check_error(result)

    @mcp.tool()
    def solo_track(track_name: str) -> dict:
        """[WRITE] Solos a track by name. This changes the track's solo state in the session."""
        result = bridge.set_track_solo(track_names=[track_name], enabled=True)
        return _check_error(result)

    @mcp.tool()
    def consolidate_clip(track_name: str, start_timecode: str, end_timecode: str) -> dict:
        """[WRITE] Consolidates a region on a track into a single clip. This modifies audio data in the session."""
        result = bridge.consolidate_clip(
            track_name=track_name, start_tc=start_timecode, end_tc=end_timecode)
        return _check_error(result)

    @mcp.tool()
    def save_session() -> dict:
        """[WRITE] Saves the current Pro Tools session to disk."""
        result = bridge.save_session()
        return _check_error(result)

    @mcp.tool()
    def close_session(save_before_close: bool = True) -> dict:
        """[WRITE] Closes the current Pro Tools session. Optionally saves before closing (default: true)."""
        result = bridge.close_session(save_on_close=save_before_close)
        return _check_error(result)

    @mcp.tool()
    def open_session(session_path: str) -> dict:
        """[WRITE] Opens a Pro Tools session from a file path (.ptx or .ptf)."""
        result = bridge.open_session(session_path=session_path)
        return _check_error(result)

    @mcp.tool()
    def save_session_as(session_name: str, session_location: str) -> dict:
        """[WRITE] Saves the current session with a new name. session_name is the new filename (without extension), session_location is the directory to save in."""
        result = bridge.save_session_as(
            session_name=session_name, session_location=session_location)
        return _check_error(result)

    @mcp.tool()
    def export_tracks_as_aaf(track_names: List[str], destination_folder: str,
                             file_name: str,
                             audio_format: str = "WAV",
                             bit_depth: str = "24",
                             copy_option: str = "copy",
                             quantize_to_frame: bool = True,
                             avid_compatible: bool = False,
                             stereo_as_multichannel: bool = False,
                             sequence_name: Optional[str] = None) -> dict:
        """[WRITE] Exports selected tracks as an AAF file. Selects the specified tracks, then exports with the given settings. Uses osascript to handle the Pro Tools folder dialog automatically.

        Parameters:
        - track_names: List of track names to export
        - destination_folder: Directory to save the AAF (e.g. session's Bounced Files folder)
        - file_name: AAF filename (without extension)
        - audio_format: 'WAV', 'AIFF', 'MXF', or 'Embedded' (default: WAV)
        - bit_depth: '16' or '24' (default: 24)
        - copy_option: 'copy', 'consolidate', or 'link' (default: copy)
        - quantize_to_frame: Quantize edits to frame boundaries (default: true)
        - avid_compatible: Enforce Avid Media Composer compatibility (default: false)
        - stereo_as_multichannel: Export stereo as multichannel (default: false)
        - sequence_name: AAF sequence name (defaults to file_name)
        """
        # Map string params to protobuf enums
        format_map = {
            "WAV": pt.AAF_WAV, "AIFF": pt.AAF_AIFF,
            "MXF": pt.AAF_MXF, "Embedded": pt.AAF_Embedded
        }
        depth_map = {"16": pt.AAF_Bit16, "24": pt.AAF_Bit24}
        copy_map = {
            "copy": pt.CopyFromSourceMedia,
            "consolidate": pt.ConsolidateFromSourceMedia,
            "link": pt.LinkFromSourceMedia
        }

        file_type = format_map.get(audio_format, pt.AAF_WAV)
        bd = depth_map.get(bit_depth, pt.AAF_Bit24)
        co = copy_map.get(copy_option, pt.CopyFromSourceMedia)

        # Select the tracks first
        _check_error(bridge.select_tracks_by_name(names=track_names))

        # Run export (bridge handles threading + osascript dialog)
        result = bridge.export_selected_tracks_as_aaf(
            file_type=file_type,
            bit_depth=bd,
            copy_option=co,
            container_file_name=file_name,
            container_file_location=destination_folder,
            enforce_avid_compat=avid_compatible,
            quantize_to_frame=quantize_to_frame,
            stereo_as_multichannel=stereo_as_multichannel,
            sequence_name=sequence_name or file_name
        )
        return _check_error(result)
