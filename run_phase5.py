"""Phase 5 — Place markers at editorial reference points.

Uses the same position-tracing pipeline as Phase 4, then adds Phase 4
gap offsets to compute final current positions for each marker.
"""

import sys
import time

sys.path.insert(0, "/Users/chrismcleod/Development/ClaudeAccess/AI Production Assistant/protools-mcp")

from paper_edit import AssemblyTranscriptLoader, PaperEditParser
from ptsl_bridge import PTSLBridge

TRANSCRIPT_PATH = "/Volumes/BE-Media (RAID 0)/Dropbox (Personal)/01 Podcasts/In The Room/ITR-01-Tawan Davis Interview/ITR-2026-03-09 Tawan Davis Interview-transcript.json"
DOCX_PATH = "/Volumes/BE-Media (RAID 0)/Offsite Download/ITR-01-Tawan Davis-V1.docx"

EXCLUDE_RANGES_MS = [
    (428500, 436500),
    (3043000, 3390000),
    (5820000, 6330500),
]


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
    print("=== Phase 5: Place Markers ===\n")

    # Load transcript
    loader = AssemblyTranscriptLoader()
    api_words = loader.load(TRANSCRIPT_PATH, fps=24)
    word_by_idx = {w.index: w for w in api_words}

    # Parse V1 to get Phase 1 cuts
    parser = PaperEditParser()
    p1_result = parser.parse(DOCX_PATH, api_words, fps=24, exclude_ranges_ms=EXCLUDE_RANGES_MS)
    p1_cuts = sorted(p1_result.cuts, key=lambda c: c.start_ms)

    def p1_shift(orig_ms):
        total = 0
        for c in p1_cuts:
            if c.start_ms < orig_ms:
                total += c.duration_ms
            else:
                break
        return total

    def word_is_cut(w):
        for c in p1_cuts:
            if c.start_ms > w.end_ms:
                break
            if w.start_ms >= c.start_ms and w.end_ms <= c.end_ms:
                return True
        return False

    # === Phase 2 move parameters ===
    nam_src = (5820810, 6330070)
    accl_src = (3043090, 3389640)
    lhi_src = (428690, 436370)

    wir_src_start = word_by_idx[26].start_ms
    wir_src_end = word_by_idx[29].end_ms
    wir_dest_ms = None
    for w in api_words:
        if 378000 <= w.start_ms <= 380000 and w.speaker:
            wir_dest_ms = w.start_ms
            break

    moves_p2 = [
        (nam_src[0] - p1_shift(nam_src[0]), nam_src[1] - p1_shift(nam_src[1]),
         word_by_idx[21605].end_ms - p1_shift(word_by_idx[21605].end_ms), False),
        (accl_src[0] - p1_shift(accl_src[0]), accl_src[1] - p1_shift(accl_src[1]),
         word_by_idx[8266].end_ms - p1_shift(word_by_idx[8266].end_ms), False),
        (lhi_src[0] - p1_shift(lhi_src[0]), lhi_src[1] - p1_shift(lhi_src[1]),
         word_by_idx[2154].end_ms - p1_shift(word_by_idx[2154].end_ms), False),
        (wir_src_start - p1_shift(wir_src_start), wir_src_end - p1_shift(wir_src_end),
         wir_dest_ms - p1_shift(wir_dest_ms), True),
    ]

    def apply_move(pos, ss, se, dest, is_copy):
        dur = se - ss
        if is_copy:
            return pos + dur if pos >= dest else pos
        if dest > se:
            if pos < ss: return pos
            if ss <= pos < se: return (dest - dur) + (pos - ss)
            if se <= pos < dest: return pos - dur
            return pos
        else:
            if pos < dest: return pos
            if dest <= pos < ss: return pos + dur
            if ss <= pos < se: return dest + (pos - ss)
            return pos

    # Phase 3 cuts (post-P2 coordinates)
    NAM_PASTE = 5356500
    NAM_BS = 5820810
    ACCL_PASTE = 2065292
    ACCL_BS = 3043090

    p3_cuts = [
        (NAM_PASTE + (6259820 - NAM_BS), NAM_PASTE + (6330070 - NAM_BS)),
        (NAM_PASTE + (6141280 - NAM_BS), NAM_PASTE + (6180810 - NAM_BS)),
        (NAM_PASTE + (5863160 - NAM_BS), NAM_PASTE + (5876050 - NAM_BS)),
        (ACCL_PASTE + (3044690 - ACCL_BS), ACCL_PASTE + (3049170 - ACCL_BS)),
        (313950, 320480),
    ]

    def trace_to_p3(orig_ms):
        """Trace original ms through P1→P2→P3."""
        pos = orig_ms - p1_shift(orig_ms)
        for move in moves_p2:
            pos = apply_move(pos, *move)
        for cs, ce in p3_cuts:
            if pos >= ce:
                pos -= (ce - cs)
            elif pos > cs:
                pos = cs
        return pos

    # Phase 4 gap positions (post-P3 ms) and durations
    # Recompute same as Phase 4
    promo_end_w = None
    for w in api_words:
        if w.start_ms >= 378000:
            break
        if not word_is_cut(w):
            in_excl = any(es <= w.start_ms and w.end_ms <= ee for es, ee in EXCLUDE_RANGES_MS)
            if not in_excl:
                promo_end_w = w

    clip_before_w = None
    for w in api_words:
        if w.start_ms >= 968000:
            break
        if not word_is_cut(w):
            in_excl = any(es <= w.start_ms and w.end_ms <= ee for es, ee in EXCLUDE_RANGES_MS)
            if not in_excl:
                clip_before_w = w

    interview_end_w = word_by_idx[22946]  # "conversation."

    gap3_pos = trace_to_p3(promo_end_w.end_ms)   # Promo→Interview: 60s
    gap2_pos = trace_to_p3(clip_before_w.end_ms)  # Insert clip: 5s
    gap1_pos = trace_to_p3(interview_end_w.end_ms) # Interview→PostChat: 60s

    def trace_to_current(orig_ms):
        """Trace original ms through all phases (P1→P2→P3→P4) to current position."""
        p3 = trace_to_p3(orig_ms)
        shift = 0
        if p3 > gap3_pos:
            shift += 60000
        if p3 > gap2_pos:
            shift += 5000
        if p3 > gap1_pos:
            shift += 60000
        return p3 + shift

    # Helper: find nearest kept word to a timestamp
    def find_nearest_kept(target_ms, direction="after"):
        if direction == "after":
            for w in api_words:
                if w.start_ms >= target_ms and not word_is_cut(w):
                    return w
        else:  # before
            result = None
            for w in api_words:
                if w.start_ms > target_ms:
                    break
                if not word_is_cut(w):
                    result = w
            return result
        return None

    # Helper for positions within moved sections
    def nam_current_pos(orig_ms):
        """Current position of a point originally within the NAM section."""
        # NAM was pasted at NAM_PASTE in post-P2 coords
        offset = orig_ms - NAM_BS
        p2_pos = NAM_PASTE + offset
        # Apply P3 cuts
        for cs, ce in p3_cuts:
            if p2_pos >= ce:
                p2_pos -= (ce - cs)
            elif p2_pos > cs:
                p2_pos = cs
        # Apply P4 gaps
        shift = 0
        # Use the p3 position (before P4 gap shifts) to determine which gaps apply
        p3_pos = NAM_PASTE + offset
        for cs2, ce2 in p3_cuts:
            if (NAM_PASTE + offset) >= ce2:
                p3_pos -= (ce2 - cs2)
            elif (NAM_PASTE + offset) > cs2:
                p3_pos = cs2
        if p3_pos > gap3_pos:
            shift += 60000
        if p3_pos > gap2_pos:
            shift += 5000
        if p3_pos > gap1_pos:
            shift += 60000
        return p2_pos + shift

    def accl_current_pos(orig_ms):
        """Current position of a point originally within the Accl section."""
        offset = orig_ms - ACCL_BS
        p2_pos = ACCL_PASTE + offset
        for cs, ce in p3_cuts:
            if p2_pos >= ce:
                p2_pos -= (ce - cs)
            elif p2_pos > cs:
                p2_pos = cs
        p3_pos_temp = ACCL_PASTE + offset
        for cs2, ce2 in p3_cuts:
            if (ACCL_PASTE + offset) >= ce2:
                p3_pos_temp -= (ce2 - cs2)
            elif (ACCL_PASTE + offset) > cs2:
                p3_pos_temp = cs2
        shift = 0
        if p3_pos_temp > gap3_pos:
            shift += 60000
        if p3_pos_temp > gap2_pos:
            shift += 5000
        if p3_pos_temp > gap1_pos:
            shift += 60000
        return p2_pos + shift

    # === Define all markers ===
    markers = []

    # 1. Promo Start — at the beginning of content
    markers.append(("Promo Start", 0))

    # 2. End of Promo — at promo end (before the 60s gap)
    pe_current = trace_to_p3(promo_end_w.end_ms)  # No P4 shift (at gap boundary)
    markers.append(("End of Promo", pe_current))

    # 3. Beginning of Episode — after the 60s promo gap
    markers.append(("Interview", pe_current + 60000))

    # 4. Insert clip — at the clip gap point (after promo gap shift)
    ic_p3 = trace_to_p3(clip_before_w.end_ms)
    ic_current = ic_p3 + 60000  # shifted by gap3 only
    markers.append(("Insert Clip", ic_current))

    # 5. Greg Foundation Question — after acclimation section ends
    # Para 322 [48:09] = first content after acclimation. 48:09 = 2889000ms
    # But the acclimation was pasted at accl_dest (word 8266 end_ms = 2889170ms)
    # The Greg question is the original content AT 48:09, which got pushed right by accl insert
    # Find first kept word at/after 2889000ms that's NOT in acclimation zone
    greg_w = None
    for w in api_words:
        if w.start_ms >= 2889000 and not word_is_cut(w):
            in_excl = any(es <= w.start_ms and w.end_ms <= ee for es, ee in EXCLUDE_RANGES_MS)
            if not in_excl:
                greg_w = w
                break
    if greg_w:
        # This word was pushed right by acclimation insert (accl dest < source, dest <= greg < src)
        # trace_to_current handles this via apply_move
        greg_current = trace_to_current(greg_w.start_ms)
        markers.append(("Greg Foundation Question", greg_current))

    # 6. Brandon Billionaire question — Para 454 [1:19:12] = 4752000ms
    brandon_w = find_nearest_kept(4752000, "after")
    if brandon_w:
        markers.append(("Brandon Billionaire Question", trace_to_current(brandon_w.start_ms)))

    # 7. Michael question "Not about me" — start of moved NAM section
    # NAM starts at 5820810ms original, now at NAM_PASTE position
    nam_start_current = nam_current_pos(5820810)
    markers.append(("Michael Question: Not About Me", nam_start_current))

    # 8. Cut Michael question on private equity — Para 514 [1:45:30] = 6330000ms
    # This is near the end of NAM section. Phase 3 cut the tail from 6259820 to 6330070.
    # The marker should go at the cut point (where content was removed).
    # Use the last kept word before the Phase 3 NAM tail cut.
    pe_marker_pos = nam_current_pos(6259820)  # Start of the Phase 3 tail cut
    markers.append(("Cut: Michael Question on Private Equity", pe_marker_pos))

    # 9. Michael on time with Obama — Para 537 [1:58:42] = 7122000ms
    # This is AFTER the NAM zone. Check if content here is kept.
    obama_w = find_nearest_kept(7122000, "after")
    if obama_w:
        markers.append(("Michael on Time with Obama", trace_to_current(obama_w.start_ms)))
    else:
        # Content may have been cut — find nearest kept before
        obama_w = find_nearest_kept(7122000, "before")
        if obama_w:
            markers.append(("Michael on Time with Obama", trace_to_current(obama_w.end_ms)))

    # 10. End of Interview — at interview end (before the 60s gap)
    ie_p3 = trace_to_p3(interview_end_w.end_ms)
    ie_current = ie_p3 + 65000  # shifted by gap3 (+60s) and gap2 (+5s)
    markers.append(("End of Interview", ie_current))

    # 11. Post Chat — after the interview→post chat 60s gap
    markers.append(("Post Chat", ie_current + 60000))

    # 12. End of Post Chat
    pc_end_w = word_by_idx[25357]  # "room." at 9011200ms
    pc_end_current = trace_to_current(pc_end_w.end_ms)
    markers.append(("End of Post Chat", pc_end_current))

    # Sort by position
    markers.sort(key=lambda m: m[1])

    # Display planned markers
    print("Planned markers:")
    for i, (name, pos_ms) in enumerate(markers, 1):
        tc = ms_to_tc(pos_ms)
        print(f"  {i:2d}. {tc}  {name}")
    print()

    confirm = input("Proceed? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # Connect to Pro Tools and place markers
    bridge = PTSLBridge()

    placed = 0
    for name, pos_ms in markers:
        tc = ms_to_tc(pos_ms)
        print(f"  Placing marker: \"{name}\" at {tc}")
        try:
            bridge.create_marker(name=name, timecode=tc)
            placed += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"    ERROR: {e}")

    bridge.save_session()
    print(f"\nPhase 5 complete. {placed}/{len(markers)} markers placed. Session saved.")


if __name__ == "__main__":
    main()
