"""Transcript tools (Group 3)."""

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from typing import Optional, List


def _check_error(result):
    if isinstance(result, dict) and "error" in result:
        raise ToolError(result["message"])
    return result


def register_transcript_tools(mcp: FastMCP, transcript_watcher, bridge, profile_loader):

    def _ensure_transcript_configured():
        """Auto-discover and configure transcript CSV if not yet configured."""
        if not transcript_watcher.is_configured:
            session_name = bridge.get_session_name()
            if isinstance(session_name, dict) and "error" in session_name:
                raise ToolError(session_name["message"])
            profile = profile_loader.match_session(session_name)
            # Get session file path for directory-based CSV discovery
            session_path = bridge.get_session_path()
            if isinstance(session_path, dict) and "error" in session_path:
                session_path = None
            csv_path = transcript_watcher.find_csv_for_session(
                session_name, profile, session_path=session_path)
            if csv_path:
                transcript_watcher.configure(csv_path)
            else:
                raise ToolError("No transcript CSV file found. Check transcript_export_path in show profile.")

    @mcp.tool()
    def get_transcript() -> list:
        """Returns the full transcript from the cached CSV with track, start, end, duration, and text for each row."""
        _ensure_transcript_configured()
        result = transcript_watcher.get_all_rows()
        return _check_error(result)

    @mcp.tool()
    def search_transcript(query: str, track_filter: Optional[List[str]] = None,
                          start_timecode: Optional[str] = None,
                          end_timecode: Optional[str] = None) -> list:
        """Searches transcript text by keyword. Returns matching rows with 2 rows of surrounding context. Optionally filter by track names or timecode range."""
        _ensure_transcript_configured()
        result = transcript_watcher.search(
            query=query,
            track_filter=track_filter,
            start_tc=start_timecode,
            end_tc=end_timecode
        )
        return _check_error(result)

    @mcp.tool()
    def get_transcript_for_range(start_timecode: str, end_timecode: str) -> dict:
        """Returns transcript rows within a timecode range, assembled as readable dialogue with speaker labels plus raw rows for programmatic use."""
        _ensure_transcript_configured()
        result = transcript_watcher.get_rows_in_range(start_timecode, end_timecode)
        return _check_error(result)
