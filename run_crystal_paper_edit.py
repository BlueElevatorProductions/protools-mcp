"""CC-26 Crystal Broj — paper edit on V2 session.

Combines:
  - Manual strikethroughs from Chris's marked-up docx (opening chatter)
  - Auto-detected filler words (um/uh/er/ah) from disfluencies-on transcript

Phase 1 only — no moves, copies, gaps, or markers.
"""

import sys
import time

sys.path.insert(0, "/Users/chrismcleod/Development/ClaudeAccess/AI Production Assistant/protools-mcp")

from paper_edit import (
    AssemblyTranscriptLoader,
    PaperEditParser,
    PaperEditExecutor,
    find_filler_cuts,
    merge_cut_lists,
)
from ptsl_bridge import PTSLBridge


TRANSCRIPT_PATH = "/tmp/CC_crystal_raw_disfluencies.json"
DOCX_PATH = "/Users/chrismcleod/Library/CloudStorage/GoogleDrive-chris@blueelevatorproductions.com/.shortcut-targets-by-id/1f8LwfbnX6bpck8xzFGrQRnuz5sqRd435/Podcasts/Cadence Conversations/Episodes/CC-26-Crystal Broj/CC-26-Crystal Broj Interview Transcript.docx"
FPS = 24


def ms_to_tc(ms, fps=FPS):
    total_frames = round(ms * fps / 1000)
    h = total_frames // (3600 * fps)
    r = total_frames % (3600 * fps)
    m = r // (60 * fps)
    r = r % (60 * fps)
    s = r // fps
    f = r % fps
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def main():
    print("=== CC-26 Crystal Broj Paper Edit ===\n")

    loader = AssemblyTranscriptLoader()
    api_words = loader.load(TRANSCRIPT_PATH, fps=FPS)
    print(f"Loaded {len(api_words)} API words from disfluencies transcript")

    # 1. Manual strikes from docx
    parser = PaperEditParser()
    result = parser.parse(DOCX_PATH, api_words, fps=FPS)
    manual_cuts = result.cuts
    print(f"\nManual strikethrough parse:")
    print(f"  Doc total words: {result.total_words}")
    print(f"  Struck words: {result.cut_word_count}")
    print(f"  Alignment score: {result.alignment_score:.3f}")
    print(f"  Manual cuts: {len(manual_cuts)} ({sum(c.duration_ms for c in manual_cuts)/1000:.1f}s)")

    # 2. Auto filler cuts
    filler_cuts = find_filler_cuts(api_words, fps=FPS)
    print(f"\nAuto-detected filler cuts: {len(filler_cuts)} "
          f"({sum(c.duration_ms for c in filler_cuts)/1000:.1f}s)")
    if filler_cuts[:10]:
        sample = ", ".join(f"{c.start_tc}:{c.text!r}" for c in filler_cuts[:5])
        print(f"  First 5: {sample}")

    # 3. Merge
    all_cuts = merge_cut_lists(manual_cuts, filler_cuts, fps=FPS)
    print(f"\nMerged cut list: {len(all_cuts)} cuts "
          f"({sum(c.duration_ms for c in all_cuts)/1000:.1f}s total)")
    print(f"  (Manual: {len(manual_cuts)} + Filler: {len(filler_cuts)} = "
          f"{len(manual_cuts)+len(filler_cuts)} pre-merge; "
          f"{len(manual_cuts)+len(filler_cuts) - len(all_cuts)} merged into adjacents)")

    # Display first 15 + last 5 for sanity
    print(f"\nFirst 15 cuts (chronological):")
    for i, c in enumerate(sorted(all_cuts, key=lambda c: c.start_ms)[:15], 1):
        words_preview = c.text[:60] + "..." if len(c.text) > 60 else c.text
        print(f"  {i:3d}. {c.start_tc} → {c.end_tc} ({c.duration_ms/1000:.2f}s) "
              f"[{c.speaker}] {words_preview!r}")

    print(f"\nLast 5 cuts:")
    for i, c in enumerate(sorted(all_cuts, key=lambda c: c.start_ms)[-5:], len(all_cuts)-4):
        words_preview = c.text[:60] + "..." if len(c.text) > 60 else c.text
        print(f"  {i:3d}. {c.start_tc} → {c.end_tc} ({c.duration_ms/1000:.2f}s) "
              f"[{c.speaker}] {words_preview!r}")

    total_dur_ms = api_words[-1].end_ms - api_words[0].start_ms
    cut_dur_ms = sum(c.duration_ms for c in all_cuts)
    print(f"\nTotal session: {total_dur_ms/1000:.1f}s ({total_dur_ms/60000:.1f}m)")
    print(f"To cut:        {cut_dur_ms/1000:.1f}s ({cut_dur_ms/60000:.2f}m)")
    print(f"Will remain:   {(total_dur_ms-cut_dur_ms)/1000:.1f}s ({(total_dur_ms-cut_dur_ms)/60000:.1f}m)")

    confirm = input("\nProceed with cuts on V2 session? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # Sort reverse chronological for execution
    cuts = sorted(all_cuts, key=lambda c: c.start_ms, reverse=True)

    bridge = PTSLBridge()
    executor = PaperEditExecutor()

    bridge.set_edit_mode(mode="shuffle")
    session_name = bridge.get_session_name()
    print(f"\nSession: {session_name!r}")
    # NOTE: We do NOT call _enable_all_group here because we want the
    # 'Interview' edit group (Crystal + Eve only) to be the propagation target.
    # That group must already be enabled in the session before this script runs.
    # The Music/Master/Host/Guest tracks stay untouched because they're not in
    # the active edit group. _trigger_all_group still works — it just nudges
    # the cursor to make PT propagate the selection through whatever group is
    # currently enabled, regardless of name.

    total = len(cuts)
    for i, c in enumerate(cuts, 1):
        if i % 10 == 0 or i == 1 or i == total:
            print(f"  Cut {i}/{total}: {c.start_tc} → {c.end_tc} ({c.duration_ms/1000:.2f}s)")

        bridge.set_timeline_selection(in_time=c.start_tc, out_time=c.end_tc)
        executor._trigger_all_group()
        time.sleep(0.05)

        bridge.clear_selection()
        time.sleep(0.05)

    print("\nCreating fades across timeline...")
    bridge.set_timeline_selection(in_time="00:00:00:00", out_time="23:59:59:23")
    executor._trigger_all_group()
    time.sleep(0.2)
    bridge.create_fades(preset_name="", auto_adjust=True)

    bridge.save_session()
    print(f"\nDone. {total} cuts executed. V2 session saved.")


if __name__ == "__main__":
    main()
