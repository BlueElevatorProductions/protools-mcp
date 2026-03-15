# protools-mcp

A local MCP (Model Context Protocol) server that connects Claude Code to a live Pro Tools session via the PTSL (Pro Tools Scripting Library) API.

## What It Does

Exposes 25+ tools across 7 groups that let Claude read session context, search transcripts, navigate timelines, manage sessions, and execute edit operations in Pro Tools:

| Group | Tools | Description |
|-------|-------|-------------|
| **Session** | `get_session_info`, `get_markers`, `get_track_list`, `get_session_snapshot`, `get_show_profile` | Session metadata, tracks, markers, show profiles |
| **Tracks** | `get_track_edl`, `get_track_playlists`, `get_clips_in_range` | Clip-level detail, playlists, time-range queries |
| **Transcript** | `get_transcript`, `search_transcript`, `get_transcript_for_range` | Speech-to-text CSV search with context and speaker labels |
| **Navigation** | `get_playhead_position`, `get_current_selection`, `set_playhead` | Playhead and selection state |
| **Edit** | `select_region`, `create_marker`, `mute_track`, `unmute_track`, `solo_track`, `consolidate_clip` | Session modifications (Claude confirms before calling) |
| **Session Mgmt** | `save_session`, `close_session`, `open_session`, `save_session_as` | Save, close, open, and version sessions |
| **Export** | `export_tracks_as_aaf` | AAF export with configurable format, bit depth, copy option |
| **Profile** | Show profile auto-matching via session name prefix | Per-show config (hosts, tracks, naming conventions) |

## Prerequisites

- **macOS** with Pro Tools running (PTSL listens on `localhost:31416`)
- **Python 3.11+** (tested with 3.11)
- **py-ptsl** installed system-wide or in the venv
- **Claude Desktop** or **Claude Code** (for MCP integration)
- **Accessibility permission** for Claude/terminal (required for AAF export dialog automation)

## Setup

1. **Clone / copy** this directory to your machine.

2. **Create virtual environment** (if not already created):
   ```bash
   cd protools-mcp
   python3 -m venv venv --system-site-packages
   source venv/bin/activate
   pip install -r requirements.txt --no-cache-dir
   ```
   The `--system-site-packages` flag reuses your system-wide `py-ptsl` and `grpcio` installs.

3. **Configure `.env`** (optional — defaults shown):
   ```
   PTSL_HOST=localhost
   PTSL_PORT=31416
   ```

4. **Add show profiles** (optional):
   Place JSON files in `show_profiles/`. See `show_profiles/holy_uncertain.json` for the format.

5. **Register with Claude Desktop** — add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "protools-mcp": {
         "command": "/path/to/protools-mcp/venv/bin/python",
         "args": ["/path/to/protools-mcp/server.py"]
       }
     }
   }
   ```
   This makes the server available in Claude Desktop Chat, Cowork, and Code sessions.

   For Claude Code CLI only, use:
   ```bash
   claude mcp add protools-mcp -s user -- /path/to/protools-mcp/venv/bin/python /path/to/protools-mcp/server.py
   ```

6. **Grant Accessibility access** (for AAF export automation):
   System Settings > Privacy & Security > Accessibility — enable Claude Desktop and/or your terminal app.

7. **Start Pro Tools** with a session open, then use Claude normally. The server connects lazily on first tool call.

## Tool Reference

### Session Context (read-only)

- **`get_session_info()`** — Returns session name, path, sample rate, bit depth, timecode format, track count, audio file count.
- **`get_markers()`** — Returns all memory location markers with index, name, timecode, and comment.
- **`get_track_list(filter="all")`** — Returns tracks with active, muted, soloed, hidden state. Filter: `all`, `active`, `audio`, `inactive`.
- **`get_session_snapshot()`** — Composite: session info + markers + tracks + auto-matched show profile. **Best tool to call first in any session.**
- **`get_show_profile(show_id?)`** — Returns the show profile config. Auto-infers from session name if no ID given.

### Track Detail (read-only)

- **`get_track_edl(track_name)`** — Full clip list for a track with clip name, start/end timecodes, duration, state.
- **`get_track_playlists(track_name)`** — Lists all playlists on a track including inactive alternates.
- **`get_clips_in_range(start_timecode, end_timecode, track_filter?)`** — All clips across tracks within a time range.

### Transcript (read-only)

- **`get_transcript()`** — Full transcript from Pro Tools Speech-to-Text CSV export.
- **`search_transcript(query, track_filter?, start_timecode?, end_timecode?)`** — Keyword search with 2-row context window.
- **`get_transcript_for_range(start_timecode, end_timecode)`** — Transcript rows in a time range, formatted as `SPEAKER: text` dialogue.

### Navigation

- **`get_playhead_position()`** — Current playhead timecode.
- **`get_current_selection()`** — Start, end, duration, and selected track names.
- **`set_playhead(timecode)`** — Moves playhead to a timecode position.

### Edit Operations (write)

All edit tools are prefixed with `[WRITE]` in their descriptions. Claude should describe the operation and confirm before calling.

- **`select_region(start_timecode, end_timecode, track_names?)`** — Sets timeline selection. Non-destructive.
- **`create_marker(name, timecode, comment?)`** — Adds a memory location marker.
- **`mute_track(track_name)`** / **`unmute_track(track_name)`** — Toggles track mute state.
- **`solo_track(track_name)`** — Solos a track.
- **`consolidate_clip(track_name, start_timecode, end_timecode)`** — Consolidates a region into a single clip. **Creates new audio file on disk.**

### Session Management (write)

- **`save_session()`** — Saves the current session to disk.
- **`save_session_as(session_name, session_location)`** — Saves with a new name. `session_name` is filename without extension, `session_location` is the directory.
- **`close_session(save_before_close=True)`** — Closes the session. Optionally saves first.
- **`open_session(session_path)`** — Opens a `.ptx` or `.ptf` session file.

### Export (write)

- **`export_tracks_as_aaf(track_names, destination_folder, file_name, ...)`** — Exports selected tracks as AAF. Handles the Pro Tools folder dialog automatically via osascript.
  - `audio_format`: `WAV` (default), `AIFF`, `MXF`, `Embedded`
  - `bit_depth`: `24` (default), `16`
  - `copy_option`: `copy` (default), `consolidate`, `link`
  - `quantize_to_frame`: `true` (default) — quantize edits to frame boundaries
  - `avid_compatible`: `false` (default) — enforce Media Composer compatibility
  - `stereo_as_multichannel`: `false` (default)
  - `sequence_name`: defaults to `file_name`

## Architecture

```
Claude Desktop  ──stdio──▶  server.py (FastMCP)
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              PTSLBridge    Transcript     ShowProfile
              (gRPC)        Watcher        Loader
                  │             │              │
                  ▼             ▼              ▼
              Pro Tools     CSV files      JSON files
              :31416
```

- **PTSLBridge** — Lazy gRPC connection with auto-reconnect. The `@ptsl_command` decorator handles errors uniformly. Custom Operation subclasses for PTSL commands not in py-ptsl's ops module.
- **TranscriptWatcher** — Stat-based CSV cache. Reloads only when the file's mtime changes. Auto-discovers CSV by searching session directory.
- **ShowProfileLoader** — Reads `show_profiles/*.json` once, matches sessions by prefix.
- **osascript integration** — For PTSL commands that trigger Pro Tools dialogs (e.g., AAF export), the bridge runs the command in a background thread and uses osascript/System Events to dismiss the dialog automatically. Requires Accessibility permission.

## Show Profile Format

```json
{
  "show_id": "HU",
  "show_name": "Holy Uncertain",
  "session_name_prefix": "HU-",
  "hosts": ["Chris", "Lauren"],
  "dialogue_tracks": ["Chris", "Lauren Int R", "Chris Int R"],
  "guest_tracks": ["Randy Int R"],
  "music_tracks": ["Music"],
  "transcript_export_path": "/path/to/episodes/",
  "naming_conventions": {
    "session": "HU-{episode_number}-{guest_last_name}-V{version}",
    "export": "HU-{episode_number}-{guest_last_name}-MIX-V{version}"
  }
}
```

## Error Handling

All PTSL errors return structured dicts before being raised as `ToolError`:

| Error Key | Meaning |
|-----------|---------|
| `ptsl_unavailable` | Pro Tools not running or gRPC connection lost |
| `no_session` | No session is open in Pro Tools |
| `ptsl_command_error` | PTSL command failed (details in message) |
| `no_transcript` | No transcript CSV found or configured |
| `dialog_waiting` | AAF export dialog needs manual confirmation (Accessibility not granted) |

## Key Implementation Notes

- **Timecode format**: Pro Tools uses `HH:MM:SS:FF`. Markers return raw sample positions internally; the bridge converts using `samples_to_timecode(samples, sample_rate, fps)`.
- **Track `active` field**: Derived from `is_inactive == TAState_None` on TrackAttributes. Distinct from muted/hidden.
- **EDL text**: Parsed from Pro Tools' tab-delimited text export with columns: CHANNEL, EVENT, CLIP NAME, START TIME, END TIME, DURATION, STATE.
- **Pro Tools quirks**: `SaveSessionAs` and directory paths require a trailing `/`. Some commands (GetTrackPlaylists, GetPlaylistElements) need `CId_` prefixed command IDs. Empty `track_id` fields must be stripped from JSON to avoid "only one of track_id/track_name" errors.
- **Connection management**: gRPC connections can go stale between calls. The `@ptsl_command` decorator catches `grpc.RpcError` and resets the connection automatically.

## Troubleshooting

- **"Pro Tools is not running"** — Make sure Pro Tools is open with a session loaded. PTSL listens on port 31416.
- **Transcript not found** — Set `transcript_export_path` in your show profile, or place the CSV next to the session file.
- **Stale data** — EDL cache expires after 30 seconds. Transcript reloads on file modification. Call tools again for fresh data.
- **AAF export hangs** — Grant Accessibility access in System Settings > Privacy & Security > Accessibility for the app running the MCP server.
- **"only one of track_id and track_name"** — This is handled internally by `json_messup()` overrides on custom Operations.
