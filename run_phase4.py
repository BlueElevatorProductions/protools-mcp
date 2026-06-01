"""Phase 4 — Insert gaps between sections + insert clip directive gap.

Gaps (processed latest-to-earliest):
1. Interview → Post Chat: 60s
2. Insert clip point: 5s
3. Promo → Interview: 60s

Host Introductions is entirely struck through — no gap needed after Post Chat.

Technique: In Shuffle mode, select from gap point to end of timeline,
Cut, move cursor forward by gap duration, Paste. This inserts silence.
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
    total_frames = round(ms * 24 / 1000)
    h = total_frames // (3600 * 24)
    remainder = total_frames % (3600 * 24)
    m = remainder // (60 * 24)
    remainder = remainder % (60 * 24)
    s = remainder // 24
    f = remainder % 24
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


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


def main():
    print("=== Phase 4: Insert Section Gaps ===\n")

    # Load transcript
    loader = AssemblyTranscriptLoader()
    api_words = loader.load(TRANSCRIPT_PATH, fps=24)
    word_by_idx = {w.index: w for w in api_words}

    # Parse V1 to get Phase 1 cuts
    parser = PaperEditParser()
    p1_result = parser.parse(DOCX_PATH, api_words, fps=24, exclude_ranges_ms=EXCLUDE_RANGES_MS)
    p1_cuts = sorted(p1_result.cuts, key=lambda c: c.start_ms)

    def p1_shift(orig_ms):
        """Total ms removed by Phase 1 cuts before orig_ms."""
        total = 0
        for c in p1_cuts:
            if c.start_ms < orig_ms:
                total += c.duration_ms
            else:
                break
        return total

    def word_is_cut(w):
        """Check if a word falls within a Phase 1 cut region."""
        for c in p1_cuts:
            if c.start_ms > w.end_ms:
                break
            if w.start_ms >= c.start_ms and w.end_ms <= c.end_ms:
                return True
        return False

    def word_in_exclusion(w):
        """Check if a word is in a Phase 2 exclusion zone (moved content)."""
        for es, ee in EXCLUDE_RANGES_MS:
            if w.start_ms >= es and w.end_ms <= ee:
                return True
        return False

    # === Phase 2 move parameters ===
    nam_src = (5820810, 6330070)
    nam_dest_ms = word_by_idx[21605].end_ms  # "hand," at ~2:08:37

    accl_src = (3043090, 3389640)
    accl_dest_ms = word_by_idx[8266].end_ms  # "me." at ~48:09

    lhi_src = (428690, 436370)
    lhi_dest_ms = word_by_idx[2154].end_ms  # "him." at ~11:46

    wir_src_start = word_by_idx[26].start_ms  # "We're" 9120ms
    wir_src_end = word_by_idx[29].end_ms      # "room." 10000ms
    wir_dur = wir_src_end - wir_src_start     # ~880ms

    wir_dest_ms = None
    for w in api_words:
        if 378000 <= w.start_ms <= 380000 and w.speaker:
            wir_dest_ms = w.start_ms
            break

    print(f"WIR copy duration: {wir_dur}ms ({wir_dur/1000:.1f}s)")

    # Build P2 moves: (src_start_p1, src_end_p1, dest_p1, is_copy)
    moves_p2 = [
        # Move 1: NAM (dest > source)
        (nam_src[0] - p1_shift(nam_src[0]), nam_src[1] - p1_shift(nam_src[1]),
         nam_dest_ms - p1_shift(nam_dest_ms), False),
        # Move 2: Accl (dest < source)
        (accl_src[0] - p1_shift(accl_src[0]), accl_src[1] - p1_shift(accl_src[1]),
         accl_dest_ms - p1_shift(accl_dest_ms), False),
        # Move 3: LHI (dest > source)
        (lhi_src[0] - p1_shift(lhi_src[0]), lhi_src[1] - p1_shift(lhi_src[1]),
         lhi_dest_ms - p1_shift(lhi_dest_ms), False),
        # Copy 4: WIR
        (wir_src_start - p1_shift(wir_src_start), wir_src_end - p1_shift(wir_src_end),
         wir_dest_ms - p1_shift(wir_dest_ms), True),
    ]

    def apply_move(pos, ss, se, dest, is_copy):
        """Apply a Phase 2 Shuffle move to a position."""
        dur = se - ss
        if is_copy:
            return pos + dur if pos >= dest else pos
        if dest > se:  # dest after source
            if pos < ss:
                return pos
            if ss <= pos < se:
                return (dest - dur) + (pos - ss)
            if se <= pos < dest:
                return pos - dur
            return pos
        else:  # dest before source
            if pos < dest:
                return pos
            if dest <= pos < ss:
                return pos + dur
            if ss <= pos < se:
                return dest + (pos - ss)
            return pos

    # Phase 3 cuts (post-P2 coordinates as used in Phase 3 script)
    NAM_PASTE = 5356500
    NAM_BS = 5820810
    ACCL_PASTE = 2065292
    ACCL_BS = 3043090

    p3_cuts = [
        (NAM_PASTE + (6259820 - NAM_BS), NAM_PASTE + (6330070 - NAM_BS)),   # NAM tail
        (NAM_PASTE + (6141280 - NAM_BS), NAM_PASTE + (6180810 - NAM_BS)),   # NAM 592-593
        (NAM_PASTE + (5863160 - NAM_BS), NAM_PASTE + (5876050 - NAM_BS)),   # NAM 589
        (ACCL_PASTE + (3044690 - ACCL_BS), ACCL_PASTE + (3049170 - ACCL_BS)),  # Accl 295
        (313950, 320480),                                                     # Space cut
    ]

    def trace_position(orig_ms):
        """Trace an original ms position through P1→P2→P3 to get current position."""
        pos = orig_ms - p1_shift(orig_ms)
        for move in moves_p2:
            pos = apply_move(pos, *move)
        for cs, ce in p3_cuts:
            if pos >= ce:
                pos -= (ce - cs)
            elif pos > cs:
                pos = cs  # within a cut
        return pos

    # === Find boundary words ===

    # Promo end: last non-cut, non-excluded word before interview start (~378000ms)
    promo_end_w = None
    for w in api_words:
        if w.start_ms >= 378000:
            break
        if not word_is_cut(w) and not word_in_exclusion(w):
            promo_end_w = w

    # Interview start: first non-cut, non-excluded word at/after ~378000ms
    interview_start_w = None
    for w in api_words:
        if w.start_ms >= 378000 and not word_is_cut(w) and not word_in_exclusion(w):
            interview_start_w = w
            break

    # Insert clip: gap between Para 182 (~15:46=946000ms) and Para 185 (~16:08=968000ms)
    # Find last kept word before 968000ms and first kept after
    clip_before_w = None
    for w in api_words:
        if w.start_ms >= 968000:
            break
        if not word_is_cut(w) and not word_in_exclusion(w):
            clip_before_w = w

    clip_after_w = None
    for w in api_words:
        if w.start_ms >= 968000 and not word_is_cut(w) and not word_in_exclusion(w):
            clip_after_w = w
            break

    # Interview end: word 22946 "conversation." at 8186450-8187170ms
    # (confirmed from transcript search)
    interview_end_w = word_by_idx[22946]  # "conversation."

    # Post chat start: word 23004 "Yeah," at 8224430ms
    post_chat_start_w = word_by_idx[23004]  # "Yeah,"

    # Display boundary words
    print("\nBoundary words found:")
    boundaries = [
        ("Promo end", promo_end_w, True),
        ("Interview start", interview_start_w, False),
        ("Insert clip (before)", clip_before_w, True),
        ("Insert clip (after)", clip_after_w, False),
        ("Interview end [22946]", interview_end_w, True),
        ("Post chat start [23004]", post_chat_start_w, False),
    ]

    for name, w, use_end in boundaries:
        if w:
            ref_ms = w.end_ms if use_end else w.start_ms
            cur = trace_position(ref_ms)
            orig_tc = w.end_tc if use_end else w.start_tc
            print(f"  {name}: [{w.index}] \"{w.text}\" @ {orig_tc} orig → {ms_to_tc(cur)} current")
        else:
            print(f"  {name}: NOT FOUND")
    print()

    # Show gap between insert clip words (to verify it's a real section break)
    if clip_before_w and clip_after_w:
        orig_gap = clip_after_w.start_ms - clip_before_w.end_ms
        print(f"  Insert clip gap in original: {orig_gap}ms between "
              f"\"{clip_before_w.text}\" and \"{clip_after_w.text}\"")

    # Show gap between interview end and post chat start
    ie_cur = trace_position(interview_end_w.end_ms)
    pc_cur = trace_position(post_chat_start_w.start_ms)
    print(f"  Interview→PostChat current gap: {pc_cur - ie_cur}ms "
          f"({(pc_cur - ie_cur)/1000:.1f}s)")
    print()

    # === Define gaps ===
    gaps = []

    # Gap 1: Promo/Interview boundary (60s)
    if promo_end_w:
        gap_pos = trace_position(promo_end_w.end_ms)
        gaps.append({
            "name": "Promo → Interview",
            "position_ms": gap_pos,
            "duration_ms": 60000,
        })

    # Gap 2: Insert clip (5s)
    if clip_before_w:
        gap_pos = trace_position(clip_before_w.end_ms)
        gaps.append({
            "name": "Insert clip point",
            "position_ms": gap_pos,
            "duration_ms": 5000,
        })

    # Gap 3: Interview/Post Chat boundary (60s)
    gap_pos = trace_position(interview_end_w.end_ms)
    gaps.append({
        "name": "Interview → Post Chat",
        "position_ms": gap_pos,
        "duration_ms": 60000,
    })

    # Sort latest-first for execution
    gaps.sort(key=lambda g: g["position_ms"], reverse=True)

    print("Planned gap insertions (latest first):")
    for i, gap in enumerate(gaps, 1):
        tc = ms_to_tc(gap["position_ms"])
        dur_s = gap["duration_ms"] / 1000
        print(f"  {i}. {gap['name']}: {dur_s:.0f}s gap at {tc}")
    print()

    confirm = input("Proceed? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # Connect to Pro Tools
    bridge = PTSLBridge()
    executor = PaperEditExecutor()

    bridge.set_edit_mode(mode="shuffle")
    session_name = bridge.get_session_name()
    executor._enable_all_group(session_name)

    gaps_done = 0
    for gap in gaps:
        tc = ms_to_tc(gap["position_ms"])
        paste_tc = ms_to_tc(gap["position_ms"] + gap["duration_ms"])
        dur_s = gap["duration_ms"] / 1000

        print(f"\nInserting {dur_s:.0f}s gap: {gap['name']}")
        print(f"  Cut from {tc} → end of timeline")

        # Select from gap point to end of timeline
        bridge.set_timeline_selection(in_time=tc, out_time="23:59:59:23")
        executor._trigger_all_group()
        time.sleep(0.1)

        # Cut
        bridge.cut_selection()
        time.sleep(0.5)

        # Set insertion point at gap_position + gap_duration
        print(f"  Paste at {paste_tc}")
        bridge.set_timeline_selection(in_time=paste_tc, out_time=paste_tc)
        executor._trigger_all_group()
        time.sleep(0.1)

        # Paste
        osascript_paste()
        time.sleep(0.5)

        gaps_done += 1
        print("  Done.")

    # Create fades at edit points
    print("\nCreating fades...")
    bridge.set_timeline_selection(in_time="00:00:00:00", out_time="23:59:59:23")
    executor._trigger_all_group()
    time.sleep(0.2)
    bridge.create_fades(preset_name="", auto_adjust=True)

    bridge.save_session()
    print(f"\nPhase 4 complete. {gaps_done}/{len(gaps)} gaps inserted. Session saved.")


if __name__ == "__main__":
    main()
