"""Playback and navigation tools (Group 4)."""

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from utils import tc_subtract


def _check_error(result):
    if isinstance(result, dict) and "error" in result:
        raise ToolError(result["message"])
    return result


def register_navigation_tools(mcp: FastMCP, bridge):

    @mcp.tool()
    def get_playhead_position() -> dict:
        """Returns the current playhead (cursor) position as a timecode string."""
        result = _check_error(bridge.get_timeline_selection())
        return {"timecode": result["in_time"]}

    @mcp.tool()
    def get_current_selection() -> dict:
        """Returns the current timeline selection with start, end, duration, and selected track names."""
        sel = _check_error(bridge.get_timeline_selection())
        selected_tracks = _check_error(bridge.get_selected_tracks())

        start = sel["in_time"]
        end = sel["out_time"]

        # Calculate duration
        try:
            duration = tc_subtract(end, start) if start != end else "00:00:00:00"
        except Exception:
            duration = "00:00:00:00"

        return {
            "start": start,
            "end": end,
            "duration": duration,
            "tracks_selected": selected_tracks
        }

    @mcp.tool()
    def set_playhead(timecode: str) -> dict:
        """Moves the playhead to the specified timecode position."""
        result = bridge.set_timeline_selection(in_time=timecode)
        return _check_error(result)
