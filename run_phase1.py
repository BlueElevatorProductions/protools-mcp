"""Phase 1 — Execute all strikethrough cuts from V1, excluding moved-section originals.

Excluded ranges (handled in Phase 2):
- "Let him in the room" quote: 7:08 → 7:16 (cut 14)
- Acclimation section: 50:43 → 56:29 (cut 44)
- "Not about me" section: 1:37:00 → 1:45:30 (cut 56)

Runs directly against PTSL bridge (no MCP server restart needed).
"""

import sys
import json
import time

sys.path.insert(0, "/Users/chrismcleod/Development/ClaudeAccess/AI Production Assistant/protools-mcp")

from paper_edit import AssemblyTranscriptLoader, PaperEditParser, PaperEditExecutor

TRANSCRIPT_PATH = "/Volumes/BE-Media (RAID 0)/Dropbox (Personal)/01 Podcasts/In The Room/ITR-01-Tawan Davis Interview/ITR-2026-03-09 Tawan Davis Interview-transcript.json"
DOCX_PATH = "/Volumes/BE-Media (RAID 0)/Offsite Download/ITR-01-Tawan Davis-V1.docx"

# Exclusion ranges in ms — the two moved sections
# Cut 44: 00:50:43:02 → 00:56:29:15 (acclimation)
# Cut 56: 01:37:00:19 → 01:45:30:01 ("not about me" + surrounding)
EXCLUDE_RANGES_MS = [
    (428500, 436500),     # 7:08:16 to 7:16:08 ("let him in the room", cut 14 only)
    (3043000, 3390000),   # ~50:43 to ~56:30 (acclimation, cut 44)
    (5820000, 6330500),   # ~1:37:00 to ~1:45:30 ("not about me", cut 56 only)
]

def main():
    print("=== Phase 1: Strikethrough Cuts (excluding moved sections) ===\n")

    # 1. Load transcript
    print("Loading AssemblyAI transcript...")
    loader = AssemblyTranscriptLoader()
    api_words = loader.load(TRANSCRIPT_PATH, fps=24)
    print(f"  Loaded {len(api_words)} words\n")

    # 2. Parse V1 document with exclusion zones
    print("Parsing V1 document with exclusion zones...")
    parser = PaperEditParser()
    result = parser.parse(DOCX_PATH, api_words, fps=24, exclude_ranges_ms=EXCLUDE_RANGES_MS)

    print(f"  Total cuts: {result.cuts.__len__()}")
    print(f"  Words to cut: {result.cut_word_count}")
    print(f"  Words to keep: {result.keep_word_count}")
    print(f"  Alignment score: {result.alignment_score:.1%}")

    cut_duration_sec = result.cut_duration_ms / 1000
    print(f"  Duration to remove: {int(cut_duration_sec // 60)}:{int(cut_duration_sec % 60):02d}")
    print()

    # 3. Show cut details
    print("Cut list:")
    for i, cut in enumerate(result.cuts, 1):
        dur = cut.duration_ms / 1000
        preview = cut.text[:70] + ("..." if len(cut.text) > 70 else "")
        print(f"  {i:2d}. {cut.start_tc} → {cut.end_tc}  ({dur:.1f}s)  {preview}")
    print()

    # 4. Confirm before executing
    print(f"Ready to execute {len(result.cuts)} cuts in Pro Tools.")
    print("Session: ITR-01-Tawan Davis-V1 Backup")
    print("Mode: Shuffle + Clear (reverse chronological)")
    print()

    confirm = input("Proceed? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # 5. Execute
    from ptsl_bridge import PTSLBridge
    bridge = PTSLBridge()

    executor = PaperEditExecutor()
    track_names = ["Cam 1", "Cam 2", "Cam Wide", "Mic 1", "Mic 2", "Mic 3", "Mic 4"]

    print("\nExecuting cuts...")
    exec_result = executor.execute(
        result=result,
        bridge=bridge,
        track_names=track_names,
        fade_preset="",
        pause_between_cuts=0.15,
    )

    print(f"\nDone!")
    print(f"  Cuts made: {exec_result.get('cuts_made', 0)}/{exec_result.get('total_planned', 0)}")
    if exec_result.get('errors'):
        print(f"  Errors: {exec_result['errors']}")
    print(f"  Fades: {exec_result.get('fades', [])}")

    # 6. Save the result summary
    summary_path = "/tmp/phase1_result.json"
    with open(summary_path, "w") as f:
        json.dump(exec_result, f, indent=2)
    print(f"\nSummary saved to {summary_path}")


if __name__ == "__main__":
    main()
