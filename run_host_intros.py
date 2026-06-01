"""Host Introductions edit — parse V2 host intros docx and execute cuts.

Fresh session from raw recording, so no exclusion zones or multi-phase complexity.
Standard Phase 1: parse struck content, execute Shuffle+Clear in reverse chronological order.
"""

import sys
import time

sys.path.insert(0, "/Users/chrismcleod/Development/ClaudeAccess/AI Production Assistant/protools-mcp")

from paper_edit import AssemblyTranscriptLoader, PaperEditParser, PaperEditExecutor
from ptsl_bridge import PTSLBridge

TRANSCRIPT_PATH = "/Volumes/BE-Media (RAID 0)/Dropbox (Personal)/01 Podcasts/In The Room/ITR-01-Tawan Davis Interview/ITR-2026-03-09 Tawan Davis Interview-transcript.json"
DOCX_PATH = "/Volumes/BE-Media (RAID 0)/Offsite Download/ITR-01-Tawan Davis Transcript-Host Intros for V2.docx"


def ms_to_tc(ms):
    total_frames = round(ms * 24 / 1000)
    h = total_frames // (3600 * 24)
    r = total_frames % (3600 * 24)
    m = r // (60 * 24)
    r = r % (60 * 24)
    s = r // 24
    f = r % 24
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def main():
    print("=== Host Introductions Edit ===\n")

    # Load transcript
    loader = AssemblyTranscriptLoader()
    api_words = loader.load(TRANSCRIPT_PATH, fps=24)
    print(f"Loaded {len(api_words)} API words")

    # Parse docx
    parser = PaperEditParser()
    result = parser.parse(DOCX_PATH, api_words, fps=24)

    print(f"\nParse results:")
    print(f"  Total words: {result.total_words}")
    print(f"  Cut words: {result.cut_word_count}")
    print(f"  Keep words: {result.keep_word_count}")
    print(f"  Alignment score: {result.alignment_score:.3f}")
    print(f"  Cut regions: {len(result.cuts)}")
    print(f"  Total cut duration: {result.cut_duration_ms/1000:.1f}s ({result.cut_duration_ms/60000:.1f}m)")
    print(f"  Kept duration: {(result.total_duration_ms - result.cut_duration_ms)/1000:.1f}s")
    print()

    # Sort cuts reverse chronological for execution
    cuts = sorted(result.cuts, key=lambda c: c.start_ms, reverse=True)

    # Display all cuts
    print(f"Cut regions ({len(cuts)}, reverse chronological):")
    for i, c in enumerate(cuts, 1):
        words_preview = c.text[:60] + "..." if len(c.text) > 60 else c.text
        print(f"  {i:3d}. {c.start_tc} → {c.end_tc} ({c.duration_ms/1000:.1f}s) "
              f"[{c.speaker}] {words_preview}")
    print()

    # Show what's KEPT (gaps between cuts)
    print("Kept regions (content that will remain):")
    cuts_fwd = sorted(result.cuts, key=lambda c: c.start_ms)
    prev_end = 0
    kept_count = 0
    for c in cuts_fwd:
        if c.start_ms > prev_end + 100:  # >100ms gap = kept content
            kept_count += 1
            dur = (c.start_ms - prev_end) / 1000
            # Find words in this range
            kept_words = [w for w in api_words if w.start_ms >= prev_end and w.end_ms <= c.start_ms]
            preview = " ".join(w.text for w in kept_words[:10])
            if len(kept_words) > 10:
                preview += "..."
            print(f"  {kept_count}. {ms_to_tc(prev_end)} → {ms_to_tc(c.start_ms)} ({dur:.1f}s) {preview}")
        prev_end = max(prev_end, c.end_ms)
    # Check for kept content after last cut
    last_word = api_words[-1]
    if last_word.end_ms > prev_end + 100:
        kept_count += 1
        dur = (last_word.end_ms - prev_end) / 1000
        kept_words = [w for w in api_words if w.start_ms >= prev_end]
        preview = " ".join(w.text for w in kept_words[:10])
        if len(kept_words) > 10:
            preview += "..."
        print(f"  {kept_count}. {ms_to_tc(prev_end)} → {ms_to_tc(last_word.end_ms)} ({dur:.1f}s) {preview}")
    print()

    confirm = input("Proceed with cuts? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # Connect to Pro Tools
    bridge = PTSLBridge()
    executor = PaperEditExecutor()

    bridge.set_edit_mode(mode="shuffle")
    session_name = bridge.get_session_name()
    executor._enable_all_group(session_name)

    # Execute cuts in reverse chronological order
    total = len(cuts)
    for i, c in enumerate(cuts, 1):
        print(f"  Cut {i}/{total}: {c.start_tc} → {c.end_tc} ({c.duration_ms/1000:.1f}s)")

        bridge.set_timeline_selection(in_time=c.start_tc, out_time=c.end_tc)
        executor._trigger_all_group()
        time.sleep(0.05)

        bridge.clear_selection()
        time.sleep(0.05)

    # Create fades
    print("\nCreating fades...")
    bridge.set_timeline_selection(in_time="00:00:00:00", out_time="23:59:59:23")
    executor._trigger_all_group()
    time.sleep(0.2)
    bridge.create_fades(preset_name="", auto_adjust=True)

    bridge.save_session()
    print(f"\nHost Introductions edit complete. {total} cuts executed. Session saved.")


if __name__ == "__main__":
    main()
