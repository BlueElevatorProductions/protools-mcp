"""Track and clip detail tools (Group 2)."""

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from typing import Optional, List

from ptsl_bridge import parse_edl_text
from utils import tc_to_frames


def _check_error(result):
    if isinstance(result, dict) and "error" in result:
        raise ToolError(result["message"])
    return result


def register_track_tools(mcp: FastMCP, bridge):

    @mcp.tool()
    def get_track_edl(track_name: str) -> list:
        """Returns the full clip list for a single track (active playlist only) with clip name, start, end, duration, and state."""
        text = _check_error(bridge.get_edl_text())
        all_tracks = parse_edl_text(text)

        if track_name not in all_tracks:
            # Try case-insensitive match
            for name in all_tracks:
                if name.lower() == track_name.lower():
                    return all_tracks[name]
            raise ToolError(f"Track '{track_name}' not found in EDL export. Available tracks: {list(all_tracks.keys())}")

        return all_tracks[track_name]

    @mcp.tool()
    def get_track_playlists(track_name: str) -> list:
        """Returns all playlists on a track, including inactive alternates, with name, active status, and clip count."""
        result = bridge.get_track_playlists(track_name=track_name)
        return _check_error(result)

    @mcp.tool()
    def get_clips_in_range(start_timecode: str, end_timecode: str,
                           track_filter: Optional[List[str]] = None) -> list:
        """Returns all clips across tracks within a timecode range. Useful for 'what's happening around this moment' queries."""
        text = _check_error(bridge.get_edl_text())
        all_tracks = parse_edl_text(text)

        start_frames = tc_to_frames(start_timecode)
        end_frames = tc_to_frames(end_timecode)

        results = []
        for track_name, clips in all_tracks.items():
            # Apply track filter if provided
            if track_filter and track_name not in track_filter:
                continue

            for clip in clips:
                # Check if clip overlaps the requested range
                try:
                    clip_start = tc_to_frames(clip["start"])
                    clip_end = tc_to_frames(clip["end"])
                    if clip_end >= start_frames and clip_start <= end_frames:
                        results.append({
                            "track_name": track_name,
                            "clip_name": clip["clip_name"],
                            "start": clip["start"],
                            "end": clip["end"]
                        })
                except (ValueError, KeyError):
                    continue

        return results

    @mcp.tool()
    def import_audio(file_paths: List[str]) -> dict:
        """[WRITE] Import one or more audio files into the currently-open session.
        Imported files create new tracks at session start (or are spotted to existing
        tracks when names match). Useful for assembling raw interview material into a
        production session.

        :param file_paths: Absolute paths to .wav / .aif / .mp3 / etc files on disk.
        """
        result = bridge.import_audio_files(file_list=file_paths)
        return _check_error(result)

    @mcp.tool()
    def set_track_name(old_name: str, new_name: str) -> dict:
        """[WRITE] Rename a track in the currently-open session by its current name.

        :param old_name: The track's current name as shown in Pro Tools.
        :param new_name: The new name to apply.
        """
        result = bridge.rename_track(old_name=old_name, new_name=new_name)
        return _check_error(result)
