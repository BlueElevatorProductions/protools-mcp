"""Phase 2 — Move content sections in Pro Tools.

Moves (processed latest-to-earliest for stable timecodes):
1. "Not about me" section (1:37:00→1:45:30) → after content at ~2:08:37
2. Acclimation section (50:43→56:29) → after "ancestors gave me" at ~48:09
3. "Let him in the room" quote (7:08→7:16) → after "never met anyone like him" at ~11:46
4. Copy "We're in the room" (0:09) → start of interview section

Uses Shuffle mode Cut+Paste. After each cut, the paste destination shifts
if it was after the source. We process latest-first so earlier destinations
are unaffected.
"""

import subprocess
import sys
import time

sys.path.insert(0, "/Users/chrismcleod/Development/ClaudeAccess/AI Production Assistant/protools-mcp")

from paper_edit import AssemblyTranscriptLoader, PaperEditParser, PaperEditExecutor
from ptsl_bridge import PTSLBridge

TRANSCRIPT_PATH = "/Volumes/BE-Media (RAID 0)/Dropbox (Personal)/01 Podcasts/In The Room/ITR-01-Tawan Davis Interview/ITR-2026-03-09 Tawan Davis Interview-transcript.json"
DOCX_PATH = "/Volumes/BE-Media (RAID 0)/Offsite Download/ITR-01-Tawan Davis-V1.docx"

EXCLUDE_RANGES_MS = [
    (428500, 436500),     # "let him in the room" (cut 14)
    (3043000, 3390000),   # acclimation (cut 44)
    (5820000, 6330500),   # "not about me" (cut 56)
]


def ms_to_tc(ms):
    """Convert milliseconds to Pro Tools timecode HH:MM:SS:FF at 24fps."""
    total_frames = round(ms * 24 / 1000)
    h = total_frames // (3600 * 24)
    remainder = total_frames % (3600 * 24)
    m = remainder // (60 * 24)
    remainder = remainder % (60 * 24)
    s = remainder // 24
    f = remainder % 24
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def compute_shift(p1_cuts_sorted, original_ms):
    """Calculate how much content was removed before a given original timecode."""
    total_removed = 0
    for c in p1_cuts_sorted:
        if c.start_ms < original_ms:
            total_removed += c.duration_ms
        else:
            break
    return total_removed


def osascript_paste():
    """Paste from clipboard in Pro Tools via Cmd+V."""
    script = '''
        tell application "System Events"
            tell process "Pro Tools"
                keystroke "v" using {command down}
                delay 0.3
            end tell
        end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)


def osascript_copy():
    """Copy selection in Pro Tools via Cmd+C."""
    script = '''
        tell application "System Events"
            tell process "Pro Tools"
                keystroke "c" using {command down}
                delay 0.2
            end tell
        end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)


def main():
    print("=== Phase 2: Content Moves ===\n")

    # Load transcript and compute Phase 1 shifts
    loader = AssemblyTranscriptLoader()
    api_words = loader.load(TRANSCRIPT_PATH, fps=24)

    parser = PaperEditParser()
    p1_result = parser.parse(DOCX_PATH, api_words, fps=24, exclude_ranges_ms=EXCLUDE_RANGES_MS)
    p1_cuts = sorted(p1_result.cuts, key=lambda c: c.start_ms)

    def shift(original_ms):
        return compute_shift(p1_cuts, original_ms)

    # Find exact API word boundaries
    def find_word_end_ms(text_fragment, near_ms, window=5000):
        """Find a word near a timecode and return its end_ms."""
        for w in api_words:
            if abs(w.start_ms - near_ms) < window and text_fragment.lower() in w.text.lower():
                return w.end_ms
        return None

    # --- Compute all timecodes ---

    # Acclimation section
    accl_source_start_ms = 3043090   # word at 50:43:02
    accl_source_end_ms = 3389640     # word at 56:29:15
    # Paste after "my ancestors gave me." — word 8266 "me." at 48:09
    accl_dest_ms = None
    for w in api_words:
        if w.index == 8266:  # "me." at end of "ancestors gave me"
            accl_dest_ms = w.end_ms
            break

    # Not-about-me section
    nam_source_start_ms = 5820810    # word at 1:37:00:19
    nam_source_end_ms = 6330070      # word at 1:45:30:01
    # Paste after "at hand," — word 21605 at 2:08:37
    nam_dest_ms = None
    for w in api_words:
        if w.index == 21605:  # "hand," at 2:08:37
            nam_dest_ms = w.end_ms
            break

    # Let-him-in quote
    lhi_source_start_ms = 428690     # word at 7:08:16
    lhi_source_end_ms = 436370       # word at 7:16:08
    # Paste after "him." — word 2154 at 11:46:05
    lhi_dest_ms = None
    for w in api_words:
        if w.index == 2154:  # "him." at 11:46
            lhi_dest_ms = w.end_ms
            break

    # We're in the room (COPY, not move)
    wir_source_start_ms = None
    wir_source_end_ms = None
    for w in api_words:
        if w.index == 26:  # "We're"
            wir_source_start_ms = w.start_ms
        if w.index == 29:  # "room."
            wir_source_end_ms = w.end_ms

    # Interview start point: first content of interview = "We're excited" at 6:18
    # (word just after the struck/cut content)
    interview_start_ms = None
    for w in api_words:
        if 378000 <= w.start_ms <= 380000 and w.speaker:
            interview_start_ms = w.start_ms
            break

    print("Post-Phase-1 positions (original → shifted):")
    print()

    # Acclimation
    accl_src_shifted_start = accl_source_start_ms - shift(accl_source_start_ms)
    accl_src_shifted_end = accl_source_end_ms - shift(accl_source_end_ms)
    accl_dest_shifted = accl_dest_ms - shift(accl_dest_ms)
    print(f"Acclimation source: {ms_to_tc(accl_src_shifted_start)} → {ms_to_tc(accl_src_shifted_end)}")
    print(f"  Duration: {(accl_source_end_ms - accl_source_start_ms)/1000:.1f}s")
    print(f"Acclimation dest: {ms_to_tc(accl_dest_shifted)}")
    print()

    # Not-about-me
    nam_src_shifted_start = nam_source_start_ms - shift(nam_source_start_ms)
    nam_src_shifted_end = nam_source_end_ms - shift(nam_source_end_ms)
    nam_dest_shifted = nam_dest_ms - shift(nam_dest_ms)
    print(f"Not-about-me source: {ms_to_tc(nam_src_shifted_start)} → {ms_to_tc(nam_src_shifted_end)}")
    print(f"  Duration: {(nam_source_end_ms - nam_source_start_ms)/1000:.1f}s")
    print(f"Not-about-me dest: {ms_to_tc(nam_dest_shifted)}")
    print()

    # Let-him-in
    lhi_src_shifted_start = lhi_source_start_ms - shift(lhi_source_start_ms)
    lhi_src_shifted_end = lhi_source_end_ms - shift(lhi_source_end_ms)
    lhi_dest_shifted = lhi_dest_ms - shift(lhi_dest_ms)
    print(f"Let-him-in source: {ms_to_tc(lhi_src_shifted_start)} → {ms_to_tc(lhi_src_shifted_end)}")
    print(f"  Duration: {(lhi_source_end_ms - lhi_source_start_ms)/1000:.1f}s")
    print(f"Let-him-in dest: {ms_to_tc(lhi_dest_shifted)}")
    print()

    # We're in the room
    wir_src_shifted_start = wir_source_start_ms - shift(wir_source_start_ms)
    wir_src_shifted_end = wir_source_end_ms - shift(wir_source_end_ms)
    wir_dest_shifted = interview_start_ms - shift(interview_start_ms) if interview_start_ms else None
    print(f"We're-in-the-room source: {ms_to_tc(wir_src_shifted_start)} → {ms_to_tc(wir_src_shifted_end)}")
    print(f"We're-in-the-room dest (interview start): {ms_to_tc(wir_dest_shifted) if wir_dest_shifted else 'N/A'}")
    print()

    confirm = input("Proceed with moves? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # Connect to Pro Tools
    bridge = PTSLBridge()
    executor = PaperEditExecutor()

    # Set Shuffle mode
    bridge.set_edit_mode(mode="shuffle")
    session_name = bridge.get_session_name()
    executor._enable_all_group(session_name)

    # Track cumulative shift from moves (each move changes positions)
    # We process latest-to-earliest so earlier positions are stable.
    cumulative_shift = 0  # ms added/removed BEFORE remaining moves

    # ================================================================
    # MOVE 1: Not-about-me (latest source, at ~1:20:20 post-P1)
    # ================================================================
    print("\n--- Move 1: Not-about-me ---")
    src_start_tc = ms_to_tc(nam_src_shifted_start)
    src_end_tc = ms_to_tc(nam_src_shifted_end)
    src_duration_ms = nam_source_end_ms - nam_source_start_ms

    print(f"  Cutting {src_start_tc} → {src_end_tc} ({src_duration_ms/1000:.1f}s)")

    # Set selection on source
    bridge.set_timeline_selection(in_time=src_start_tc, out_time=src_end_tc)
    executor._trigger_all_group()
    time.sleep(0.1)

    # Cut
    bridge.cut_selection()
    time.sleep(0.3)

    # After cutting: everything after source shifts earlier by src_duration_ms
    # Dest was AFTER source, so it shifts earlier
    adjusted_dest_ms = nam_dest_shifted - src_duration_ms
    dest_tc = ms_to_tc(adjusted_dest_ms)
    print(f"  Pasting at {dest_tc} (adjusted for cut)")

    # Set insertion point at dest
    bridge.set_timeline_selection(in_time=dest_tc, out_time=dest_tc)
    executor._trigger_all_group()
    time.sleep(0.1)

    # Paste
    osascript_paste()
    time.sleep(0.5)
    print("  Done.")

    # After paste: content inserted at dest, everything after shifts later by src_duration_ms
    # Net effect on positions BEFORE source: no change
    # Net effect on positions BETWEEN dest and source: shifted later by src_duration_ms
    # Net effect on positions AFTER source: no change (shifted earlier by cut, then later by paste)

    # ================================================================
    # MOVE 2: Acclimation (source at ~36:59 post-P1)
    # ================================================================
    print("\n--- Move 2: Acclimation ---")
    src_start_tc = ms_to_tc(accl_src_shifted_start)
    src_end_tc = ms_to_tc(accl_src_shifted_end)
    src_duration_ms = accl_source_end_ms - accl_source_start_ms

    print(f"  Cutting {src_start_tc} → {src_end_tc} ({src_duration_ms/1000:.1f}s)")

    # Acclimation source is BEFORE not-about-me, unaffected by Move 1
    bridge.set_timeline_selection(in_time=src_start_tc, out_time=src_end_tc)
    executor._trigger_all_group()
    time.sleep(0.1)

    # Cut
    bridge.cut_selection()
    time.sleep(0.3)

    # Dest is BEFORE source, so NOT affected by the cut
    dest_tc = ms_to_tc(accl_dest_shifted)
    print(f"  Pasting at {dest_tc}")

    bridge.set_timeline_selection(in_time=dest_tc, out_time=dest_tc)
    executor._trigger_all_group()
    time.sleep(0.1)

    osascript_paste()
    time.sleep(0.5)
    print("  Done.")

    # ================================================================
    # MOVE 3: Let-him-in (source at ~2:25 post-P1)
    # ================================================================
    print("\n--- Move 3: Let-him-in ---")
    src_start_tc = ms_to_tc(lhi_src_shifted_start)
    src_end_tc = ms_to_tc(lhi_src_shifted_end)
    src_duration_ms = lhi_source_end_ms - lhi_source_start_ms

    print(f"  Cutting {src_start_tc} → {src_end_tc} ({src_duration_ms/1000:.1f}s)")

    bridge.set_timeline_selection(in_time=src_start_tc, out_time=src_end_tc)
    executor._trigger_all_group()
    time.sleep(0.1)

    bridge.cut_selection()
    time.sleep(0.3)

    # Dest is AFTER source, shifts earlier by src_duration_ms
    adjusted_dest_ms = lhi_dest_shifted - src_duration_ms
    dest_tc = ms_to_tc(adjusted_dest_ms)
    print(f"  Pasting at {dest_tc} (adjusted for cut)")

    bridge.set_timeline_selection(in_time=dest_tc, out_time=dest_tc)
    executor._trigger_all_group()
    time.sleep(0.1)

    osascript_paste()
    time.sleep(0.5)
    print("  Done.")

    # ================================================================
    # COPY 4: We're-in-the-room (source at ~0:01, dest at interview start)
    # ================================================================
    if wir_dest_shifted:
        print("\n--- Copy 4: We're-in-the-room ---")
        src_start_tc = ms_to_tc(wir_src_shifted_start)
        src_end_tc = ms_to_tc(wir_src_shifted_end)
        src_duration_ms = wir_source_end_ms - wir_source_start_ms

        print(f"  Copying {src_start_tc} → {src_end_tc} ({src_duration_ms/1000:.1f}s)")

        # We're-in-the-room is at ~0:01, interview start is at ~1:58
        # Moves 1-3 don't affect positions this early in the timeline
        # (all moves were after ~2:25)
        bridge.set_timeline_selection(in_time=src_start_tc, out_time=src_end_tc)
        executor._trigger_all_group()
        time.sleep(0.1)

        # Copy (not cut) via osascript Cmd+C
        osascript_copy()
        time.sleep(0.3)

        # Paste at interview start
        # The dest needs adjustment for Move 3 (let-him-in at ~2:25 was cut then pasted at ~4:50)
        # Move 3 cut at ~2:25 (before interview start ~1:58? No, 2:25 > 1:58)
        # Wait - let-him-in source was at ~2:25 which is AFTER interview start ~1:58
        # Cut at 2:25 shifts interview start? No, cut is AFTER interview start, doesn't affect it.
        # Paste at ~4:50 is also after. So interview start is unchanged.
        dest_tc = ms_to_tc(wir_dest_shifted)
        print(f"  Pasting at {dest_tc}")

        bridge.set_timeline_selection(in_time=dest_tc, out_time=dest_tc)
        executor._trigger_all_group()
        time.sleep(0.1)

        osascript_paste()
        time.sleep(0.5)
        print("  Done.")

    # ================================================================
    # Restore edit mode and create fades
    # ================================================================
    print("\n--- Creating fades ---")
    bridge.set_timeline_selection(in_time="00:00:00:00", out_time="23:59:59:23")
    executor._trigger_all_group()
    time.sleep(0.2)
    bridge.create_fades(preset_name="", auto_adjust=True)
    print("  Fades created.")

    # Save
    bridge.save_session()
    print("\nPhase 2 complete. Session saved.")


if __name__ == "__main__":
    main()
