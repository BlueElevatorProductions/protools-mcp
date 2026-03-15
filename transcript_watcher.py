"""Transcript watcher — CSV file cache with stat-based invalidation."""

import os
from typing import Optional, List, Dict, Any

import pandas as pd

from utils import tc_to_frames


class TranscriptWatcher:
    """Monitors and caches transcript CSV files from Pro Tools Speech-to-Text."""

    # CSV column mapping from Pro Tools export format
    CSV_COLUMNS = {
        "Track Name": "track",
        "Channel Names": "channel",
        "Speech Start Time": "start",
        "Speech End Time": "end",
        "Speech Duration": "duration",
        "Speech": "text"
    }

    def __init__(self):
        self._df: Optional[pd.DataFrame] = None
        self._csv_path: Optional[str] = None
        self._last_mtime: float = 0.0

    def configure(self, csv_path: str):
        """Set the path to the transcript CSV file."""
        self._csv_path = csv_path
        self._last_mtime = 0.0
        self._df = None

    @property
    def is_configured(self) -> bool:
        return self._csv_path is not None

    def _reload_if_needed(self) -> bool:
        """Reload the CSV if the file has been modified. Returns True if loaded."""
        if self._csv_path is None:
            return False
        if not os.path.exists(self._csv_path):
            return False

        mtime = os.path.getmtime(self._csv_path)
        if mtime > self._last_mtime or self._df is None:
            df = pd.read_csv(self._csv_path)
            df = df.rename(columns=self.CSV_COLUMNS)
            # Keep only the columns we need
            keep_cols = [c for c in ["track", "channel", "start", "end", "duration", "text"]
                         if c in df.columns]
            self._df = df[keep_cols].fillna("")
            self._last_mtime = mtime
            return True
        return False

    def get_all_rows(self) -> Any:
        """Return all transcript rows as a list of dicts."""
        self._reload_if_needed()
        if self._df is None:
            return {"error": "no_transcript",
                    "message": "No transcript file found at configured path"}
        return self._df.to_dict(orient="records")

    def search(self, query: str, track_filter: Optional[List[str]] = None,
               start_tc: Optional[str] = None, end_tc: Optional[str] = None) -> Any:
        """Search transcript text with optional filters. Returns matches with context."""
        self._reload_if_needed()
        if self._df is None:
            return {"error": "no_transcript",
                    "message": "No transcript file found at configured path"}

        df = self._df.copy()

        # Apply track filter
        if track_filter:
            df = df[df["track"].isin(track_filter)]

        # Apply time range filter
        if start_tc and "end" in df.columns:
            start_frames = tc_to_frames(start_tc)
            df = df[df["end"].apply(lambda x: tc_to_frames(str(x)) >= start_frames if x else True)]

        if end_tc and "start" in df.columns:
            end_frames = tc_to_frames(end_tc)
            df = df[df["start"].apply(lambda x: tc_to_frames(str(x)) <= end_frames if x else True)]

        # Text search (case-insensitive)
        mask = df["text"].astype(str).str.contains(query, case=False, na=False)
        matches = df[mask]

        results = []
        for idx in matches.index:
            row = matches.loc[idx]
            # Get 2 rows context before and after from the FULL dataframe
            ctx_start = max(0, idx - 2)
            ctx_end = min(len(self._df), idx + 3)
            context_rows = self._df.iloc[ctx_start:ctx_end]
            context_str = "\n".join(
                f"[{r['track']}] {r['start']}-{r['end']}: {r['text']}"
                for _, r in context_rows.iterrows()
            )
            results.append({
                "track": str(row["track"]),
                "start": str(row["start"]),
                "end": str(row["end"]),
                "text": str(row["text"]),
                "context": context_str
            })

        return results

    def get_rows_in_range(self, start_tc: str, end_tc: str) -> Any:
        """Return transcript rows within a timecode range, formatted as dialogue."""
        self._reload_if_needed()
        if self._df is None:
            return {"error": "no_transcript",
                    "message": "No transcript file found at configured path"}

        start_frames = tc_to_frames(start_tc)
        end_frames = tc_to_frames(end_tc)

        df = self._df.copy()
        # Filter: speech interval overlaps the requested range
        mask = (
            df["end"].apply(lambda x: tc_to_frames(str(x)) >= start_frames if x else False) &
            df["start"].apply(lambda x: tc_to_frames(str(x)) <= end_frames if x else False)
        )
        filtered = df[mask]

        rows = filtered.to_dict(orient="records")

        # Build dialogue string with speaker labels
        dialogue_lines = []
        for r in rows:
            speaker = str(r.get("track", "UNKNOWN")).upper()
            text = str(r.get("text", ""))
            dialogue_lines.append(f"{speaker}: {text}")

        return {
            "dialogue": "\n".join(dialogue_lines),
            "rows": rows
        }

    def find_csv_for_session(self, session_name: str, profile: Optional[dict] = None,
                             session_path: Optional[str] = None) -> Optional[str]:
        """Auto-discover a transcript CSV matching the session name.

        Search order:
        1. Show profile's transcript_export_path
        2. Session file's parent directory
        3. Session file's grandparent directory
        """
        search_paths = []

        if profile and "transcript_export_path" in profile:
            search_paths.append(profile["transcript_export_path"])

        if session_path:
            # Add session directory and its parent
            session_dir = os.path.dirname(session_path)
            search_paths.append(session_dir)
            search_paths.append(os.path.dirname(session_dir))

        for base_path in search_paths:
            if not os.path.exists(base_path):
                continue
            # Direct match: CSV filename contains the session name
            for f in os.listdir(base_path):
                if f.endswith(".csv") and session_name in f:
                    return os.path.join(base_path, f)
            # Recursive match
            for root, dirs, files in os.walk(base_path):
                for f in files:
                    if f.endswith(".csv") and session_name in f:
                        return os.path.join(root, f)

        # Try partial match (episode number) on profile path
        if profile and "transcript_export_path" in profile:
            base_path = profile["transcript_export_path"]
            if os.path.exists(base_path):
                parts = session_name.split("-")
                if len(parts) >= 2:
                    episode_num = parts[1].strip()
                    for root, dirs, files in os.walk(base_path):
                        if episode_num in os.path.basename(root):
                            for f in files:
                                if f.endswith(".csv"):
                                    return os.path.join(root, f)
        return None
