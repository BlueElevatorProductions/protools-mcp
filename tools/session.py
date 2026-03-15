"""Session context tools (Group 1) and Show Profile tool (Group 6)."""

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from typing import Optional


def _check_error(result):
    """If result is a dict with an 'error' key, raise ToolError."""
    if isinstance(result, dict) and "error" in result:
        raise ToolError(result["message"])
    return result


def register_session_tools(mcp: FastMCP, bridge, profile_loader):

    @mcp.tool()
    def get_session_info() -> dict:
        """Returns baseline session metadata including name, path, duration, sample rate, bit depth, timecode format, track count, and audio file count."""
        session_name = _check_error(bridge.get_session_name())
        file_path = _check_error(bridge.get_session_path())
        duration = _check_error(bridge.get_session_length())
        sample_rate = _check_error(bridge.get_session_sample_rate())
        bit_depth = _check_error(bridge.get_session_bit_depth())
        tc_format = _check_error(bridge.get_session_timecode_rate())
        track_count = _check_error(bridge.get_track_count())
        audio_clip_count = _check_error(bridge.get_audio_file_count())

        return {
            "session_name": session_name,
            "file_path": file_path,
            "duration": duration,
            "sample_rate": sample_rate,
            "bit_depth": bit_depth,
            "timecode_format": tc_format,
            "track_count": track_count,
            "audio_clip_count": audio_clip_count
        }

    @mcp.tool()
    def get_markers() -> list:
        """Returns all memory location markers in the session with index, name, timecode, and comment."""
        result = bridge.get_memory_locations()
        return _check_error(result)

    @mcp.tool()
    def get_track_list(filter: str = "all") -> list:
        """Returns all tracks with state information. Filter options: 'all', 'active', 'audio', 'inactive'."""
        result = bridge.get_track_list(track_filter=filter)
        return _check_error(result)

    @mcp.tool()
    def get_session_snapshot() -> dict:
        """Returns a unified session context object combining session info, markers, track list, and matching show profile. This is the primary tool to call at the start of any session conversation."""
        session_name = _check_error(bridge.get_session_name())
        file_path = _check_error(bridge.get_session_path())
        duration = _check_error(bridge.get_session_length())
        sample_rate = _check_error(bridge.get_session_sample_rate())
        bit_depth = _check_error(bridge.get_session_bit_depth())
        tc_format = _check_error(bridge.get_session_timecode_rate())
        track_count = _check_error(bridge.get_track_count())
        audio_clip_count = _check_error(bridge.get_audio_file_count())

        session_info = {
            "session_name": session_name,
            "file_path": file_path,
            "duration": duration,
            "sample_rate": sample_rate,
            "bit_depth": bit_depth,
            "timecode_format": tc_format,
            "track_count": track_count,
            "audio_clip_count": audio_clip_count
        }

        markers = _check_error(bridge.get_memory_locations())
        tracks = _check_error(bridge.get_track_list())

        # Match show profile by session name prefix
        show_profile = profile_loader.match_session(session_name)

        return {
            "session_info": session_info,
            "markers": markers,
            "tracks": tracks,
            "show_profile": show_profile
        }

    @mcp.tool()
    def get_show_profile(show_id: Optional[str] = None) -> dict:
        """Returns the show profile configuration. If show_id is not provided, infers from the current session name prefix."""
        if show_id:
            profile = profile_loader.get_profile(show_id)
        else:
            session_name = _check_error(bridge.get_session_name())
            profile = profile_loader.match_session(session_name)

        if profile is None:
            raise ToolError("No matching show profile found")
        return profile
