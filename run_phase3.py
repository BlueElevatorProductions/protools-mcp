"""Phase 3 — Internal cuts within moved sections + space cut directive.

Cuts (processed latest-to-earliest):
1. NAM tail: last kept word "be." → end of block (~71s)
2. NAM Paras 592-593: fully struck 1:42:21→1:43:00 (~39s)
3. NAM Para 589: struck part "How do you push through..." (~13s)
4. Acclimation Para 295: struck part "I have two questions..." (~4.5s)
5. Space directive: silence between "There he is." and Tawan's "How you doing?" (~7s)
"""

import subprocess
import sys
import time

sys.path.insert(0, "/Users/chrismcleod/Development/ClaudeAccess/AI Production Assistant/protools-mcp")

from paper_edit import PaperEditExecutor
from ptsl_bridge import PTSLBridge


def ms_to_tc(ms):
    total_frames = round(ms * 24 / 1000)
    h = total_frames // (3600 * 24)
    remainder = total_frames % (3600 * 24)
    m = remainder // (60 * 24)
    remainder = remainder % (60 * 24)
    s = remainder // 24
    f = remainder % 24
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


# Block paste positions from Phase 2 output
NAM_PASTE_TC = "01:29:16:12"
NAM_PASTE_MS = 5356500  # 1*3600+29*60+16 = 5356s + 0.5s
NAM_BLOCK_START_MS = 5820810  # original start of excluded zone

ACCL_PASTE_TC = "00:34:25:07"
ACCL_PASTE_MS = 2065292  # 34*60+25 = 2065s + 7/24s
ACCL_BLOCK_START_MS = 3043090  # original start of excluded zone


def nam_pos(original_ms):
    """Convert an original timecode within the NAM block to current timeline position."""
    offset = original_ms - NAM_BLOCK_START_MS
    return NAM_PASTE_MS + offset


def accl_pos(original_ms):
    """Convert an original timecode within the acclimation block to current timeline position."""
    offset = original_ms - ACCL_BLOCK_START_MS
    return ACCL_PASTE_MS + offset


def main():
    print("=== Phase 3: Internal Cuts ===\n")

    # Define cuts using exact API word ms values
    cuts = []

    # 1. NAM tail: after "be." (word 17889 end=6259820) → end of block (word 18139 end=6330070)
    cuts.append({
        "name": "NAM tail (after last kept content)",
        "start_ms": nam_pos(6259820),   # end of "be." - start cutting here
        "end_ms": nam_pos(6330070),     # end of block
        "duration_s": (6330070 - 6259820) / 1000,
    })

    # 2. NAM Paras 592-593: word 17509 "Sounds" start=6141280 → word 17640 "about." end=6180810
    cuts.append({
        "name": "NAM Paras 592-593 (Michael/Tawan at 1:42:21)",
        "start_ms": nam_pos(6141280),
        "end_ms": nam_pos(6180810),
        "duration_s": (6180810 - 6141280) / 1000,
    })

    # 3. NAM Para 589 struck: "How do you push..." word 16601 start=5863160 → word 16641 "needed." end=5876050
    cuts.append({
        "name": "NAM Para 589 (Michael's Napoleon tangent)",
        "start_ms": nam_pos(5863160),
        "end_ms": nam_pos(5876050),
        "duration_s": (5876050 - 5863160) / 1000,
    })

    # 4. Acclimation Para 295: "I have two questions..." word 8648 start=3044690 → word 8666 "room." end=3049170
    cuts.append({
        "name": "Acclimation Para 295 (Michael's preamble)",
        "start_ms": accl_pos(3044690),
        "end_ms": accl_pos(3049170),
        "duration_s": (3049170 - 3044690) / 1000,
    })

    # 5. Space cut directive: between "There he is." end and "How you doing?" start
    #    Need post-Phase-1+2 positions.
    #    "is." (word 2222) end_ms ≈ 737750 in original
    #    "How" (word 2223) start_ms ≈ 744458 in original
    #    Phase 1 shift at this point: ~424700ms
    #    Phase 2 net effect: +0.9s (from we're-in-room copy paste at 1:58)
    #    Post-P1: 737750 - 424700 = 313050
    #    Post-P2: 313050 + 900 = 313950 (start of silence)
    #    "How" post-P2: (744458 - 424700) + 900 = 320658 (end of silence)
    #    Using exact API values:
    space_cut_start = 313050 + 900   # approximate, after "is." end
    space_cut_end = 319580 + 900     # approximate, before "How" start
    cuts.append({
        "name": "Space cut (silence between 'There he is' and Tawan)",
        "start_ms": space_cut_start,
        "end_ms": space_cut_end,
        "duration_s": (space_cut_end - space_cut_start) / 1000,
    })

    # Sort reverse chronological (latest first)
    cuts.sort(key=lambda c: c["start_ms"], reverse=True)

    print("Planned cuts:")
    for i, cut in enumerate(cuts, 1):
        tc_start = ms_to_tc(cut["start_ms"])
        tc_end = ms_to_tc(cut["end_ms"])
        print(f"  {i}. {cut['name']}")
        print(f"     {tc_start} → {tc_end} ({cut['duration_s']:.1f}s)")
    print()

    total_dur = sum(c["duration_s"] for c in cuts)
    print(f"Total to remove: {total_dur:.1f}s ({int(total_dur//60)}:{int(total_dur%60):02d})")
    print()

    confirm = input("Proceed? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # Connect and execute
    bridge = PTSLBridge()
    executor = PaperEditExecutor()

    bridge.set_edit_mode(mode="shuffle")
    session_name = bridge.get_session_name()
    executor._enable_all_group(session_name)

    cuts_made = 0
    for cut in cuts:
        tc_start = ms_to_tc(cut["start_ms"])
        tc_end = ms_to_tc(cut["end_ms"])
        print(f"\nCutting: {cut['name']}")
        print(f"  {tc_start} → {tc_end}")

        bridge.set_timeline_selection(in_time=tc_start, out_time=tc_end)
        executor._trigger_all_group()
        time.sleep(0.1)

        result = bridge.clear_selection()
        if isinstance(result, dict) and "error" in result:
            print(f"  ERROR: {result.get('message', '')}")
            break

        cuts_made += 1
        time.sleep(0.15)
        print("  Done.")

    # Fades
    print("\nCreating fades...")
    bridge.set_timeline_selection(in_time="00:00:00:00", out_time="23:59:59:23")
    executor._trigger_all_group()
    time.sleep(0.2)
    bridge.create_fades(preset_name="", auto_adjust=True)

    bridge.save_session()
    print(f"\nPhase 3 complete. {cuts_made}/{len(cuts)} cuts made. Session saved.")


if __name__ == "__main__":
    main()
