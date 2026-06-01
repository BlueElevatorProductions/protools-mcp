"""Session context tools (Group 1) and Show Profile tool (Group 6)."""

import os
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

# pt_popups lives at the package root, not under tools/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pt_popups


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

    @mcp.tool()
    def bounce_to_disk(
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
        """[WRITE] Export the active mix bus to disk — equivalent to Pro Tools'
        "Bounce to Disk". Synchronous; returns when the bounce completes.

        :param output_dir: Absolute folder path for the output file.
        :param base_name: Filename stem (Pro Tools appends the format extension).
        :param file_type: "MP3" | "WAV" | "AIFF" | "MOV" | "M4A".
        :param source_name: Bus / output name to bounce (default "Out 1-2").
        :param source_type: "Output" | "Bus" | "PhysicalOut".
        :param export_format: "Interleaved" (stereo) | "Mono" | "MultipleMono".
        :param bit_depth: 16 | 24 | 32. Ignored for MP3 (PT uses session pref).
        :param sample_rate: 44100 | 48000 | 88200 | 96000 | 176400 | 192000.
        :param offline: True for offline (faster-than-realtime) bounce.
        """
        result = bridge.bounce_to_disk(
            output_dir=output_dir,
            base_name=base_name,
            file_type=file_type,
            source_name=source_name,
            source_type=source_type,
            export_format=export_format,
            bit_depth=bit_depth,
            sample_rate=sample_rate,
            offline=offline,
        )
        return _check_error(result)

    @mcp.tool()
    def dismiss_pt_popups(
        wait_for: float = 0.0,
        dwell: float = 1.5,
    ) -> dict:
        """Detect + dismiss any modal Pro Tools popups (alerts, sheets).

        Uses macOS Accessibility (osascript) to enumerate dialog windows on
        the Pro Tools process and dismisses each. Common PT popups have
        specific button mappings (e.g., "Session Notes" → "No",
        "Missing AAX Plugins" → "OK"); unknown dialogs fall back to Return.

        Call this after long-running operations (open_session, import_audio,
        bounce_to_disk) where popups frequently appear after a delay.

        :param wait_for: How long to poll for popups (seconds). Use 5–10s
            after expensive operations; 0 for an immediate one-shot check.
        :param dwell: After each dismissal, keep watching this many extra
            seconds in case follow-up popups chain.
        :returns: {"dismissed": <count>}
        """
        n = pt_popups.dismiss_popups(wait_for=wait_for, dwell=dwell, verbose=False)
        return {"dismissed": n}
