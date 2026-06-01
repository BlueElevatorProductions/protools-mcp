"""CC-26 Crystal Broj — paper edit on V2, per-track cuts.

Approach: All-group propagation isn't extending selections beyond the focused
track in this session, so we cut each track separately. The per-cut sequence:

  1. Python: select_all_clips_on_track(track) + set_timeline_selection(in,out)
  2. computer-use: PT frontmost + send Delete keystroke

Repeated for Crystal then Eve, in reverse-chronological order. Verifies the
EDL count progress every 10 cuts.

Music clips must already be locked (Cmd+L) so any stray edit-cursor lingering
on Music is harmless.
"""

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, "/Users/chrismcleod/Development/ClaudeAccess/AI Production Assistant/protools-mcp")

from paper_edit import (
    AssemblyTranscriptLoader,
    PaperEditParser,
    find_filler_cuts,
    merge_cut_lists,
)
from ptsl_bridge import PTSLBridge, parse_edl_text


TRANSCRIPT_PATH = "/tmp/CC_crystal_raw_disfluencies.json"
DOCX_PATH = "/Users/chrismcleod/Library/CloudStorage/GoogleDrive-chris@blueelevatorproductions.com/.shortcut-targets-by-id/1f8LwfbnX6bpck8xzFGrQRnuz5sqRd435/Podcasts/Cadence Conversations/Episodes/CC-26-Crystal Broj/CC-26-Crystal Broj Interview Transcript.docx"
FPS = 24
TRACKS = ["Crystal", "Eve"]


def send_delete():
    """Bring PT frontmost and send a Delete keystroke."""
    script = '''
        tell application "System Events"
            tell process "Pro Tools"
                set frontmost to true
                delay 0.05
                key code 51
            end tell
        end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)


def main():
    print("=== CC-26 Crystal Broj — per-track paper edit ===\n")

    loader = AssemblyTranscriptLoader()
    api_words = loader.load(TRANSCRIPT_PATH, fps=FPS)
    parser = PaperEditParser()
    result = parser.parse(DOCX_PATH, api_words, fps=FPS)
    manual_cuts = result.cuts
    filler_cuts = find_filler_cuts(api_words, fps=FPS)
    all_cuts = merge_cut_lists(manual_cuts, filler_cuts, fps=FPS)
    print(f"Manual cuts: {len(manual_cuts)} ({sum(c.duration_ms for c in manual_cuts)/1000:.1f}s)")
    print(f"Filler cuts: {len(filler_cuts)} ({sum(c.duration_ms for c in filler_cuts)/1000:.1f}s)")
    print(f"Merged:      {len(all_cuts)} ({sum(c.duration_ms for c in all_cuts)/1000:.1f}s)")

    cuts = sorted(all_cuts, key=lambda c: c.start_ms, reverse=True)
    total_ops = len(cuts) * len(TRACKS)
    print(f"\nWill execute {len(cuts)} cuts × {len(TRACKS)} tracks = {total_ops} operations\n")

    confirm = input("Proceed? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    bridge = PTSLBridge()
    engine = bridge._ensure_connected()

    edl_before = parse_edl_text(bridge.get_edl_text())
    print(f"\nBEFORE: " + ", ".join(f"{t}={len(edl_before.get(t, []))}" for t in TRACKS))

    op_count = 0
    for i, c in enumerate(cuts, 1):
        for track in TRACKS:
            engine.select_all_clips_on_track(track)
            time.sleep(0.05)
            bridge.set_timeline_selection(in_time=c.start_tc, out_time=c.end_tc)
            time.sleep(0.05)
            send_delete()
            time.sleep(0.05)
            op_count += 1

        if i % 10 == 0 or i == 1 or i == len(cuts):
            engine.save_session()  # critical: EDL is cached until save
            time.sleep(0.2)
            edl = parse_edl_text(bridge.get_edl_text())
            counts = ", ".join(f"{t}={len(edl.get(t, []))}" for t in TRACKS)
            print(f"  Cut {i}/{len(cuts)} ({c.start_tc} → {c.end_tc}, {c.duration_ms/1000:.2f}s)  EDL: {counts}")

    edl_after = parse_edl_text(bridge.get_edl_text())
    print(f"\nAFTER : " + ", ".join(f"{t}={len(edl_after.get(t, []))}" for t in TRACKS))

    print("\nSaving session...")
    engine.save_session()
    print("Done.")


if __name__ == "__main__":
    main()
