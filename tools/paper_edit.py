"""Paper Edit MCP tools — parse edited transcripts and execute cuts in Pro Tools."""

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from typing import Optional, List, Dict

import json
from pathlib import Path


def _check_error(result):
    if isinstance(result, dict) and "error" in result:
        raise ToolError(result["message"])
    return result


# Module-level state for loaded transcript
_loaded_transcript = {
    "api_words": None,
    "json_path": None,
}


def register_paper_edit_tools(mcp: FastMCP, bridge):

    @mcp.tool()
    def load_assembly_transcript(json_path: str, fps: int = 24) -> dict:
        """Loads an AssemblyAI word-level transcript JSON file. This must be called before parse_paper_edit or execute_paper_edit. Returns word count and duration summary."""
        from paper_edit import AssemblyTranscriptLoader

        loader = AssemblyTranscriptLoader()
        words = loader.load(json_path, fps=fps)
        _loaded_transcript["api_words"] = words
        _loaded_transcript["json_path"] = json_path

        duration_ms = words[-1].end_ms - words[0].start_ms if words else 0
        duration_sec = duration_ms / 1000
        speakers = list(set(w.speaker for w in words if w.speaker))

        return {
            "word_count": len(words),
            "duration_seconds": round(duration_sec, 1),
            "duration_formatted": f"{int(duration_sec // 60)}:{int(duration_sec % 60):02d}",
            "speakers": speakers,
            "first_word_tc": words[0].start_tc if words else "",
            "last_word_tc": words[-1].end_tc if words else "",
            "json_path": json_path,
        }

    @mcp.tool()
    def save_word_map(output_path: str, session_name: str = "",
                      sample_rate: int = 48000, fps: int = 24,
                      speaker_map: Optional[Dict[str, str]] = None) -> dict:
        """[WRITE] Saves the loaded transcript as a word map JSON sidecar file. Call load_assembly_transcript first."""
        from paper_edit import AssemblyTranscriptLoader

        if _loaded_transcript["api_words"] is None:
            raise ToolError("No transcript loaded. Call load_assembly_transcript first.")

        loader = AssemblyTranscriptLoader()
        path = loader.save_word_map(
            words=_loaded_transcript["api_words"],
            output_path=output_path,
            session_name=session_name,
            sample_rate=sample_rate,
            fps=fps,
            speaker_map=speaker_map,
        )
        return {"confirmed": True, "path": path, "word_count": len(_loaded_transcript["api_words"])}

    @mcp.tool()
    def parse_paper_edit(docx_path: str, fps: int = 24,
                         exclude_ranges_ms: Optional[List[List[int]]] = None) -> dict:
        """Parses an edited .docx file with strikethrough markings against the loaded AssemblyAI transcript. Returns a preview of planned cuts with timecodes and durations. Call load_assembly_transcript first.

        Parameters:
        - docx_path: Path to the edited .docx with strikethrough markings
        - fps: Frame rate (default 24)
        - exclude_ranges_ms: Optional list of [start_ms, end_ms] ranges to exclude from cuts (for moved sections handled separately)
        """
        from paper_edit import PaperEditParser, PaperEditExecutor

        if _loaded_transcript["api_words"] is None:
            raise ToolError("No transcript loaded. Call load_assembly_transcript first.")

        # Convert list of lists to list of tuples for the parser
        exclude_tuples = None
        if exclude_ranges_ms:
            exclude_tuples = [(r[0], r[1]) for r in exclude_ranges_ms]

        parser = PaperEditParser()
        result = parser.parse(docx_path, _loaded_transcript["api_words"], fps=fps,
                              exclude_ranges_ms=exclude_tuples)
        executor = PaperEditExecutor()
        preview = executor.preview(result)

        # Store result for execute step
        _loaded_transcript["last_parse_result"] = result

        return preview

    @mcp.tool()
    def execute_paper_edit(track_names: List[str],
                           fade_preset: str = "",
                           save_backup: bool = True) -> dict:
        """[WRITE] Executes the parsed paper edit cuts in Pro Tools. Sets Shuffle mode, processes cuts in reverse chronological order (for accurate ripple editing), creates crossfades at edit points, then restores the original edit mode. Call parse_paper_edit first to preview cuts before executing.

        Parameters:
        - track_names: List of all track names to edit together (synced)
        - fade_preset: Name of fade preset to use (empty = default crossfade)
        - save_backup: If true, saves session before making cuts (recommended)
        """
        from paper_edit import PaperEditExecutor

        result = _loaded_transcript.get("last_parse_result")
        if result is None:
            raise ToolError("No paper edit parsed. Call parse_paper_edit first.")

        # Save backup if requested
        if save_backup:
            save_result = bridge.save_session()
            if isinstance(save_result, dict) and "error" in save_result:
                raise ToolError(f"Failed to save backup: {save_result.get('message', '')}")

        executor = PaperEditExecutor()
        exec_result = executor.execute(
            result=result,
            bridge=bridge,
            track_names=track_names,
            fade_preset=fade_preset,
        )
        return _check_error(exec_result) if not exec_result.get("confirmed") else exec_result

    @mcp.tool()
    def set_edit_mode(mode: str) -> dict:
        """[WRITE] Sets the Pro Tools edit mode. Options: shuffle, slip, spot, grid_absolute, grid_relative."""
        result = bridge.set_edit_mode(mode=mode)
        return _check_error(result)

    @mcp.tool()
    def get_edit_mode() -> dict:
        """Returns the current Pro Tools edit mode."""
        result = bridge.get_edit_mode()
        if isinstance(result, dict) and "error" in result:
            return _check_error(result)
        return {"edit_mode": result}

    @mcp.tool()
    def undo() -> dict:
        """[WRITE] Undoes the last Pro Tools operation."""
        result = bridge.undo()
        return _check_error(result)
