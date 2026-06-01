"""Paper Edit — parse edited transcripts and execute cuts in Pro Tools.

Workflow:
1. Load AssemblyAI word-level transcript JSON
2. Parse a .docx with strikethrough markings (user's edit decisions)
3. Align .docx words with AssemblyAI words to get precise timecodes
4. Execute cuts in Pro Tools using Shuffle mode + Clear
"""

import json
import subprocess
import time
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from docx import Document

from utils import ms_to_timecode, tc_to_frames, frames_to_tc
from ptsl_bridge import parse_edl_text


@dataclass
class WordEntry:
    """A single word from AssemblyAI with timing data."""
    index: int
    text: str
    start_ms: int
    end_ms: int
    start_tc: str
    end_tc: str
    speaker: str


@dataclass
class DocWord:
    """A word extracted from the .docx with strikethrough status."""
    text: str
    is_struck: bool
    paragraph_index: int
    word_index: int  # global index across entire document


@dataclass
class CutRegion:
    """A contiguous region to be cut from the timeline."""
    start_tc: str
    end_tc: str
    start_ms: int
    end_ms: int
    words: List[str]
    speaker: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def text(self) -> str:
        return " ".join(self.words)


@dataclass
class PaperEditResult:
    """Result of parsing a paper edit document."""
    cuts: List[CutRegion]
    total_words: int
    cut_word_count: int
    keep_word_count: int
    total_duration_ms: int
    cut_duration_ms: int
    alignment_score: float
    unmatched_doc_words: int
    unmatched_api_words: int


class AssemblyTranscriptLoader:
    """Loads and processes AssemblyAI word-level transcript JSON."""

    def load(self, json_path: str, fps: int = 24) -> List[WordEntry]:
        """Load AssemblyAI JSON and convert to WordEntry list with timecodes."""
        path = Path(json_path)
        with open(path, "r") as f:
            data = json.load(f)

        words_data = data.get("words", [])
        if not words_data:
            raise ValueError(f"No words found in AssemblyAI transcript: {json_path}")

        words = []
        for i, w in enumerate(words_data):
            words.append(WordEntry(
                index=i,
                text=w["text"],
                start_ms=w["start"],
                end_ms=w["end"],
                start_tc=ms_to_timecode(w["start"], fps=fps),
                end_tc=ms_to_timecode(w["end"], fps=fps),
                speaker=w.get("speaker", ""),
            ))

        return words

    def save_word_map(self, words: List[WordEntry], output_path: str,
                      session_name: str = "", sample_rate: int = 48000,
                      fps: int = 24, speaker_map: Optional[Dict[str, str]] = None):
        """Save word map as JSON sidecar file."""
        word_map = {
            "session_name": session_name,
            "sample_rate": sample_rate,
            "fps": fps,
            "speaker_map": speaker_map or {},
            "word_count": len(words),
            "words": [
                {
                    "index": w.index,
                    "text": w.text,
                    "start_ms": w.start_ms,
                    "end_ms": w.end_ms,
                    "start_tc": w.start_tc,
                    "end_tc": w.end_tc,
                    "speaker": w.speaker,
                }
                for w in words
            ]
        }
        with open(output_path, "w") as f:
            json.dump(word_map, f, indent=2)
        return output_path


class PaperEditParser:
    """Parses a .docx with strikethrough and aligns with AssemblyAI words."""

    def extract_doc_words(self, docx_path: str) -> List[DocWord]:
        """Extract all words from a .docx, tracking strikethrough per word."""
        doc = Document(docx_path)
        doc_words = []
        global_word_index = 0

        for para_idx, paragraph in enumerate(doc.paragraphs):
            # Skip empty paragraphs
            if not paragraph.text.strip():
                continue

            for run in paragraph.runs:
                is_struck = bool(run.font.strike)
                # Split run text into words
                run_words = run.text.split()
                for word in run_words:
                    cleaned = word.strip()
                    if cleaned:
                        doc_words.append(DocWord(
                            text=cleaned,
                            is_struck=is_struck,
                            paragraph_index=para_idx,
                            word_index=global_word_index,
                        ))
                        global_word_index += 1

        return doc_words

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize a word for fuzzy matching."""
        return re.sub(r'[^\w]', '', text.lower())

    def align_words(self, doc_words: List[DocWord],
                    api_words: List[WordEntry]) -> List[Tuple[Optional[DocWord], Optional[WordEntry]]]:
        """Align document words with API words using sequence matching.

        Returns a list of (doc_word, api_word) pairs. Either may be None
        if unmatched.
        """
        doc_normalized = [self._normalize(w.text) for w in doc_words]
        api_normalized = [self._normalize(w.text) for w in api_words]

        matcher = SequenceMatcher(None, doc_normalized, api_normalized)
        aligned = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for di, ai in zip(range(i1, i2), range(j1, j2)):
                    aligned.append((doc_words[di], api_words[ai]))
            elif tag == "replace":
                # Pair them up as best we can
                doc_range = list(range(i1, i2))
                api_range = list(range(j1, j2))
                for k in range(max(len(doc_range), len(api_range))):
                    dw = doc_words[doc_range[k]] if k < len(doc_range) else None
                    aw = api_words[api_range[k]] if k < len(api_range) else None
                    aligned.append((dw, aw))
            elif tag == "delete":
                # Words in doc but not in API
                for di in range(i1, i2):
                    aligned.append((doc_words[di], None))
            elif tag == "insert":
                # Words in API but not in doc
                for ai in range(j1, j2):
                    aligned.append((None, api_words[ai]))

        return aligned

    def parse(self, docx_path: str, api_words: List[WordEntry],
              fps: int = 24,
              exclude_ranges_ms: Optional[List[Tuple[int, int]]] = None) -> PaperEditResult:
        """Parse the edited .docx and produce cut regions.

        Args:
            docx_path: Path to the edited .docx with strikethrough
            api_words: Word list from AssemblyAI (with timecodes)
            fps: Frame rate for timecode calculations
            exclude_ranges_ms: Optional list of (start_ms, end_ms) ranges to exclude
                from cuts. Used to skip moved-section originals that will be handled
                in a separate phase.
        """
        doc_words = self.extract_doc_words(docx_path)
        aligned = self.align_words(doc_words, api_words)

        # Count alignment quality
        matched = sum(1 for dw, aw in aligned if dw is not None and aw is not None)
        unmatched_doc = sum(1 for dw, aw in aligned if dw is not None and aw is None)
        unmatched_api = sum(1 for dw, aw in aligned if dw is None and aw is not None)
        total = len(aligned)
        alignment_score = matched / total if total > 0 else 0.0

        # Build cut regions from consecutive struck-through words that have API matches
        cuts: List[CutRegion] = []
        current_cut_words: List[str] = []
        current_cut_start_ms: Optional[int] = None
        current_cut_end_ms: Optional[int] = None
        current_cut_start_tc: Optional[str] = None
        current_cut_end_tc: Optional[str] = None
        current_cut_speaker: str = ""

        total_word_count = sum(1 for dw, _ in aligned if dw is not None)
        cut_word_count = 0

        def flush_cut():
            nonlocal current_cut_words, current_cut_start_ms, current_cut_end_ms
            nonlocal current_cut_start_tc, current_cut_end_tc, current_cut_speaker
            if current_cut_words and current_cut_start_tc and current_cut_end_tc:
                cuts.append(CutRegion(
                    start_tc=current_cut_start_tc,
                    end_tc=current_cut_end_tc,
                    start_ms=current_cut_start_ms,
                    end_ms=current_cut_end_ms,
                    words=list(current_cut_words),
                    speaker=current_cut_speaker,
                ))
            current_cut_words = []
            current_cut_start_ms = None
            current_cut_end_ms = None
            current_cut_start_tc = None
            current_cut_end_tc = None
            current_cut_speaker = ""

        for dw, aw in aligned:
            if dw is not None and dw.is_struck:
                # This word is struck through — part of a cut region
                cut_word_count += 1
                if aw is not None:
                    # We have timing data — set or extend the region boundaries
                    if current_cut_start_ms is None:
                        current_cut_start_ms = aw.start_ms
                        current_cut_start_tc = aw.start_tc
                        current_cut_speaker = aw.speaker
                    current_cut_end_ms = aw.end_ms
                    current_cut_end_tc = aw.end_tc
                current_cut_words.append(dw.text if dw else "")
            elif dw is None and aw is not None and current_cut_start_ms is not None:
                # API word with no doc match inside a struck region — extend the cut
                # to cover gaps between matched words (breaths, small sounds, etc.)
                current_cut_end_ms = aw.end_ms
                current_cut_end_tc = aw.end_tc
            else:
                # Non-struck word — flush the current cut region
                flush_cut()

        flush_cut()  # Don't forget the last region

        # Filter out cuts that overlap with exclusion zones (moved sections)
        if exclude_ranges_ms:
            filtered_cuts = []
            for cut in cuts:
                excluded = False
                for ex_start, ex_end in exclude_ranges_ms:
                    # Exclude if the cut overlaps with the exclusion zone
                    if cut.start_ms < ex_end and cut.end_ms > ex_start:
                        excluded = True
                        break
                if not excluded:
                    filtered_cuts.append(cut)
            excluded_count = len(cuts) - len(filtered_cuts)
            cuts = filtered_cuts
        else:
            excluded_count = 0

        # Calculate durations
        total_duration_ms = 0
        if api_words:
            total_duration_ms = api_words[-1].end_ms - api_words[0].start_ms
        cut_duration_ms = sum(c.duration_ms for c in cuts)

        return PaperEditResult(
            cuts=cuts,
            total_words=total_word_count,
            cut_word_count=cut_word_count,
            keep_word_count=total_word_count - cut_word_count,
            total_duration_ms=total_duration_ms,
            cut_duration_ms=cut_duration_ms,
            alignment_score=alignment_score,
            unmatched_doc_words=unmatched_doc,
            unmatched_api_words=unmatched_api,
        )


# ============================================================
# Filler-word (disfluency) auto-detection
# ============================================================
# These run on the AssemblyAI words[] list — only useful when the transcription
# was requested with `disfluencies: true`. Otherwise AssemblyAI strips fillers
# before returning the word list, and there's nothing to detect.

DEFAULT_FILLER_PATTERNS = [
    r"^um[.,!?]?$",
    r"^umm+[.,!?]?$",
    r"^uh[.,!?]?$",
    r"^uhh+[.,!?]?$",
    r"^uhm+[.,!?]?$",
    r"^er[.,!?]?$",
    r"^err+[.,!?]?$",
    r"^ah[.,!?]?$",
]

# Affirmation sounds that look filler-ish but carry meaning. Skip these.
DEFAULT_FILLER_EXCLUDE_PATTERNS = [
    r"^mm[- ]?hmm[.,!?]?$",
    r"^uh[- ]?huh[.,!?]?$",
    r"^mhm+[.,!?]?$",
]


def find_filler_cuts(
    api_words: List[WordEntry],
    patterns: Optional[List[str]] = None,
    excluded: Optional[List[str]] = None,
    pad_before_ms: int = 30,
    pad_after_ms: int = 60,
    merge_window_ms: int = 200,
    fps: int = 24,
) -> List[CutRegion]:
    """Detect filler words in the AssemblyAI word list and return CutRegions.

    Catches: um, umm, uh, uhh, uhm, er, ah (case-insensitive, with optional
    trailing punctuation). Excludes affirmations like "mm-hmm" / "uh-huh".

    Adjacent fillers within `merge_window_ms` are merged into a single cut.
    Padding is added before/after each cut to capture breath/transition sounds.
    Pass the same `fps` you use for the rest of the paper edit so timecodes
    on the returned CutRegions are consistent with the manual cuts.

    REQUIREMENT: the transcription must have been done with
    `disfluencies: true` (see transcribe-audio skill's `KEEP_DISFLUENCIES`
    flag). Otherwise this returns an empty list — AssemblyAI strips
    fillers before they reach the word list.
    """
    pat_re = [re.compile(p, re.IGNORECASE) for p in (patterns or DEFAULT_FILLER_PATTERNS)]
    excl_re = [re.compile(p, re.IGNORECASE) for p in (excluded or DEFAULT_FILLER_EXCLUDE_PATTERNS)]

    raw_hits: List[WordEntry] = []
    for w in api_words:
        text = w.text.strip()
        if any(r.match(text) for r in excl_re):
            continue
        if any(r.match(text) for r in pat_re):
            raw_hits.append(w)

    if not raw_hits:
        return []

    # Merge adjacent hits (e.g. "um, uh,") into one cut
    groups: List[List[WordEntry]] = [[raw_hits[0]]]
    for w in raw_hits[1:]:
        prev = groups[-1][-1]
        if w.start_ms - prev.end_ms <= merge_window_ms:
            groups[-1].append(w)
        else:
            groups.append([w])

    cuts: List[CutRegion] = []
    for group in groups:
        first, last = group[0], group[-1]
        start_ms = max(0, first.start_ms - pad_before_ms)
        end_ms = last.end_ms + pad_after_ms
        cuts.append(CutRegion(
            start_tc=ms_to_timecode(start_ms, fps=fps),
            end_tc=ms_to_timecode(end_ms, fps=fps),
            start_ms=start_ms,
            end_ms=end_ms,
            words=[w.text for w in group],
            speaker=first.speaker,
        ))

    return cuts


def merge_cut_lists(*cut_lists: List[CutRegion], fps: int = 24) -> List[CutRegion]:
    """Merge multiple CutRegion lists, combining overlapping/touching regions.

    Use this to combine manual strikethrough cuts (from PaperEditParser.parse())
    with auto-detected filler cuts (from find_filler_cuts()). Overlapping cuts
    are coalesced — words concatenate, time bounds widen, the earlier cut's
    speaker is retained.

    Returns a list sorted by start_ms.
    """
    all_cuts: List[CutRegion] = []
    for cl in cut_lists:
        all_cuts.extend(cl)
    if not all_cuts:
        return []

    all_cuts.sort(key=lambda c: c.start_ms)
    merged: List[CutRegion] = [all_cuts[0]]
    for c in all_cuts[1:]:
        last = merged[-1]
        if c.start_ms <= last.end_ms:
            new_end_ms = max(last.end_ms, c.end_ms)
            merged[-1] = CutRegion(
                start_tc=last.start_tc,
                end_tc=ms_to_timecode(new_end_ms, fps=fps),
                start_ms=last.start_ms,
                end_ms=new_end_ms,
                words=last.words + c.words,
                speaker=last.speaker,
            )
        else:
            merged.append(c)

    return merged


def execute_cuts_per_track(
    bridge,
    engine,
    cuts: List[CutRegion],
    interview_tracks: List[str],
    save_every: int = 10,
    delete_keystroke_fn=None,
) -> dict:
    """Run a list of cuts as Delete-keystroke operations, one track at a time.

    This is the validated CC-26 Crystal Broj pattern (2026-04-30). Use this for
    paper edits where the active edit group's propagation can't be relied on
    to extend selections across multiple tracks. Cuts each interview track
    separately at the same timecodes — Shuffle keeps them in sync because both
    tracks compact equally.

    Lessons from CC-26 baked in:
      - PTSL ops.Clear() / ops.Cut() silently no-op when no real edit selection
        exists. Delete keystroke (after PT focused) is the reliable path.
      - get_edl_text() is cached until session save; verification reads that
        return the pre-cut state otherwise. We save_session() before each
        progress check.
      - Multi-track group propagation isn't reliable; per-track is dependable.
      - select_all_clips_on_track(name) is the cleanest way to focus a track
        for editing — it puts the edit-cursor on that unlocked track.

    Args:
        bridge: PTSLBridge instance.
        engine: py-ptsl Engine (typically `bridge._ensure_connected()`).
        cuts: List of CutRegion in any order — sorted reverse-chronologically here.
        interview_tracks: Track names to cut at each timecode (e.g. ["Crystal","Eve"]).
        save_every: Save + EDL-verify every N cuts (also at start and end).
        delete_keystroke_fn: Callable taking no args that brings PT frontmost
            and sends a Delete keystroke. If None, uses an osascript fallback.
            Pass a computer-use-driven version for higher reliability.

    Returns:
        dict with start/end clip counts per track and total cuts executed.

    Pre-conditions (caller must set up):
      - PT session open in Shuffle mode
      - Placeholder/template clips on non-interview tracks LOCKED (Cmd+L)
      - Computer-use access granted to "Pro Tools"
    """
    import time as _time

    if delete_keystroke_fn is None:
        def _osascript_delete():
            import subprocess
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
        delete_keystroke_fn = _osascript_delete

    sorted_cuts = sorted(cuts, key=lambda c: c.start_ms, reverse=True)

    # ─────────────────────────────────────────────────────────────────────────
    # LAYER 1 — Pre-flight assertions
    # Prevent silent no-op runs (the CC-26 trap).
    # ─────────────────────────────────────────────────────────────────────────
    ready = verify_session_ready_for_cuts(
        bridge, engine, interview_tracks, expected_shuffle=True,
    )
    if not ready["ok"]:
        raise RuntimeError(
            f"Pre-flight check failed before cut run: {ready['errors']}. "
            f"Fix these and rerun. (Pre-flight details: {ready})"
        )

    before_counts = ready["before_counts"]
    print(f"BEFORE: " + ", ".join(f"{t}={n}" for t, n in before_counts.items()))

    # ─────────────────────────────────────────────────────────────────────────
    # Cut loop (per-track Delete keystroke in Shuffle mode)
    # ─────────────────────────────────────────────────────────────────────────
    op_count = 0
    early_abort_checked = False
    last_counts = dict(before_counts)

    for i, cut in enumerate(sorted_cuts, 1):
        for track in interview_tracks:
            engine.select_all_clips_on_track(track)
            _time.sleep(0.05)
            bridge.set_timeline_selection(in_time=cut.start_tc, out_time=cut.end_tc)
            _time.sleep(0.05)
            delete_keystroke_fn()
            _time.sleep(0.05)
            op_count += 1

        if i % save_every == 0 or i == 1 or i == len(sorted_cuts):
            engine.save_session()
            _time.sleep(0.2)
            # CRITICAL: invalidate the bridge's 30s EDL cache before reading,
            # otherwise we get stale pre-cut data and false-negative aborts.
            if hasattr(bridge, "invalidate_edl_cache"):
                bridge.invalidate_edl_cache()
            edl = parse_edl_text(bridge.get_edl_text())
            counts_dict = {t: len(edl.get(t, [])) for t in interview_tracks}
            counts = ", ".join(f"{t}={counts_dict[t]}" for t in interview_tracks)
            print(f"  Cut {i}/{len(sorted_cuts)} ({cut.start_tc} → {cut.end_tc}, "
                  f"{cut.duration_ms/1000:.2f}s)  EDL: {counts}")

            # ─────────────────────────────────────────────────────────────────
            # LAYER 2 — Early-abort if first save_every batch shows no progress
            # ─────────────────────────────────────────────────────────────────
            if not early_abort_checked and i >= save_every:
                no_progress_tracks = [
                    t for t in interview_tracks
                    if counts_dict[t] <= before_counts[t]
                ]
                if no_progress_tracks:
                    raise RuntimeError(
                        f"EARLY ABORT after {i} cuts: EDL clip counts did not "
                        f"increase on tracks {no_progress_tracks}. "
                        f"Before={before_counts}, After {i} cuts={counts_dict}. "
                        f"This is the CC-26 trap: cuts aren't landing. "
                        f"Likely causes: edit cursor on a locked/wrong track, "
                        f"Shuffle mode disabled, or PT lost focus. "
                        f"Aborted to prevent a 10-minute no-op run."
                    )
                early_abort_checked = True
            last_counts = counts_dict

    # ─────────────────────────────────────────────────────────────────────────
    # LAYER 3 — Final reconciliation
    # ─────────────────────────────────────────────────────────────────────────
    engine.save_session()
    _time.sleep(0.2)
    if hasattr(bridge, "invalidate_edl_cache"):
        bridge.invalidate_edl_cache()
    edl_after = parse_edl_text(bridge.get_edl_text())
    after_counts = {t: len(edl_after.get(t, [])) for t in interview_tracks}
    print(f"AFTER : " + ", ".join(f"{t}={n}" for t, n in after_counts.items()))

    # Expected: per track, each cut adds ~1-2 clip boundaries (Shuffle deletes
    # a region, leaving 2 clips on either side where there was 1). On an
    # already-multi-clip track the math varies, but the floor is the cut should
    # be observable somewhere.
    deltas = {t: after_counts[t] - before_counts[t] for t in interview_tracks}
    n_cuts = len(sorted_cuts)
    underperform = {
        t: d for t, d in deltas.items()
        if d < max(1, int(0.5 * n_cuts))
    }
    if underperform:
        print(
            f"\n⚠️  POST-RUN WARN: Some tracks under-performed.\n"
            f"   Expected ≥{max(1, int(0.5 * n_cuts))} new clip boundaries per track ({n_cuts} cuts × ≥0.5 floor).\n"
            f"   Actual deltas: {deltas}\n"
            f"   Under-performing tracks (likely didn't accept cuts): {underperform}\n"
            f"   Inspect Pro Tools visually before continuing."
        )

    return {
        "before_counts": before_counts,
        "after_counts": after_counts,
        "deltas": deltas,
        "ops_total": op_count,
        "cuts_planned": len(sorted_cuts),
        "underperforming_tracks": list(underperform.keys()),
    }


def verify_session_ready_for_cuts(
    bridge,
    engine,
    interview_tracks: List[str],
    expected_shuffle: bool = True,
) -> dict:
    """Pre-flight check before running execute_cuts_per_track().

    Catches the CC-26 trap (cuts silently no-op) by asserting the session is
    in a state where Delete-keystroke cuts can actually land:
      • All interview tracks exist in the open session
      • Edit mode is Shuffle (delete-and-compact behavior)
      • At least one interview track has clips to cut

    Returns dict with `ok: bool`, `errors: list[str]`, plus snapshot data
    (before_counts, edit_mode, track_list_sample). On `ok: False`, fix the
    flagged issues before running the cut loop — don't proceed.
    """
    import time as _time

    errors: List[str] = []
    track_list = []
    try:
        # Track list via PTSL
        from ptsl import ops
        # If get_track_list exists on bridge, use it; otherwise fall back
        if hasattr(bridge, "get_track_list"):
            tl = bridge.get_track_list(track_filter="audio")
            if isinstance(tl, list):
                track_list = [t.get("name") if isinstance(t, dict) else getattr(t, "name", None) for t in tl]
        else:
            # Best-effort: try engine
            track_list = []
    except Exception as e:
        errors.append(f"Could not enumerate tracks: {e}")

    missing = [t for t in interview_tracks if track_list and t not in track_list]
    if missing:
        errors.append(
            f"Interview tracks missing from session: {missing}. "
            f"Available: {track_list}"
        )

    # Edit mode check — soft-fail in py-ptsl 601 where GetEditMode op is missing.
    edit_mode = None
    try:
        if hasattr(bridge, "get_edit_mode"):
            em_result = bridge.get_edit_mode()
            # Bridge returns error dict if the op is missing; treat as "unknown".
            if isinstance(em_result, dict) and em_result.get("error"):
                edit_mode = f"unknown ({em_result.get('error')})"
                # Don't fail — caller must verify mode visually before running.
            else:
                edit_mode = str(em_result)
                if expected_shuffle and "shuffle" not in edit_mode.lower():
                    errors.append(
                        f"Edit mode is '{edit_mode}', expected Shuffle. "
                        f"Set Shuffle in PT toolbar before running."
                    )
    except Exception as e:
        edit_mode = f"unknown ({e})"

    # Initial EDL snapshot
    before_counts: Dict[str, int] = {}
    try:
        engine.save_session()
        _time.sleep(0.2)
        if hasattr(bridge, "invalidate_edl_cache"):
            bridge.invalidate_edl_cache()
        edl_before = parse_edl_text(bridge.get_edl_text())
        before_counts = {t: len(edl_before.get(t, [])) for t in interview_tracks}
        empty_tracks = [t for t, n in before_counts.items() if n == 0]
        if len(empty_tracks) == len(interview_tracks):
            errors.append(
                f"All interview tracks {interview_tracks} appear empty (no clips). "
                f"Either tracks have wrong names or no audio was imported."
            )
    except Exception as e:
        errors.append(f"Could not read initial EDL: {e}")

    return {
        "ok": not errors,
        "errors": errors,
        "before_counts": before_counts,
        "edit_mode": edit_mode,
        "track_list_sample": track_list[:20],
    }


class PaperEditExecutor:
    """Executes paper edit cuts in Pro Tools via the PTSL bridge.

    NOTE: The All-group + Ctrl+; / Ctrl+P trick implemented here only works
    reliably when the All edit group is active AND the focused track is in
    that group AND PT is frontmost. For sessions where those conditions
    can't be guaranteed (e.g. CC episodes with locked Music template clips),
    prefer `execute_cuts_per_track()` above which uses Delete keystrokes
    per-track and verifies via save_session + EDL re-read.
    """

    @staticmethod
    def _trigger_all_group():
        """Send Control+; then Control+P to Pro Tools via osascript.

        This moves the edit cursor down one track and back up, which triggers
        Pro Tools' All edit group to extend the selection across all tracks.
        PTSL's SetTimelineSelection alone only sets the selection on the
        focused track — this keyboard nudge is required for multi-track edits.
        """
        script = '''
            tell application "System Events"
                tell process "Pro Tools"
                    keystroke ";" using {control down}
                    delay 0.05
                    keystroke "p" using {control down}
                    delay 0.05
                end tell
            end tell
        '''
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)

    @staticmethod
    def _enable_all_group(session_name: str):
        """Enable the All edit group in Pro Tools via osascript UI click.

        Finds the Group List table in the Edit window and clicks the All group
        button if it's not already enabled. Checks the state button value for
        "Selected" to determine current state (avoids toggling off if already on).
        """
        script = f'''
            tell application "System Events"
                tell process "Pro Tools"
                    set frontmost to true
                    delay 0.2
                    set editWin to window "Edit: {session_name}"
                    set grpTable to table "Group List" of editWin
                    set r to row 1 of grpTable
                    set stateBtn to button 1 of UI element 1 of r
                    set stateVal to value of stateBtn
                    if stateVal does not contain "Selected" then
                        set allBtn to button 1 of UI element 2 of r
                        click allBtn
                        delay 0.1
                    end if
                end tell
            end tell
        '''
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)

    def preview(self, result: PaperEditResult) -> dict:
        """Return a human-readable summary of planned cuts."""
        cut_secs = result.cut_duration_ms / 1000
        total_secs = result.total_duration_ms / 1000
        keep_secs = total_secs - cut_secs

        cut_min = int(cut_secs // 60)
        cut_sec = int(cut_secs % 60)
        keep_min = int(keep_secs // 60)
        keep_sec = int(keep_secs % 60)

        cut_details = []
        for i, c in enumerate(result.cuts, 1):
            cut_details.append({
                "cut_number": i,
                "start": c.start_tc,
                "end": c.end_tc,
                "duration_sec": round(c.duration_ms / 1000, 2),
                "word_count": len(c.words),
                "preview_text": c.text[:80] + ("..." if len(c.text) > 80 else ""),
                "speaker": c.speaker,
            })

        return {
            "total_cuts": len(result.cuts),
            "words_to_cut": result.cut_word_count,
            "words_to_keep": result.keep_word_count,
            "duration_to_remove": f"{cut_min}:{cut_sec:02d}",
            "estimated_final_duration": f"{keep_min}:{keep_sec:02d}",
            "alignment_score": f"{result.alignment_score:.1%}",
            "unmatched_doc_words": result.unmatched_doc_words,
            "unmatched_api_words": result.unmatched_api_words,
            "cuts": cut_details,
        }

    def execute(self, result: PaperEditResult, bridge, track_names: List[str],
                fade_preset: str = "", pause_between_cuts: float = 0.15) -> dict:
        """Execute the paper edit cuts in Pro Tools.

        Args:
            result: Parsed paper edit with cut regions
            bridge: PTSLBridge instance
            track_names: Track names to select (all edited together)
            fade_preset: Fade preset name (empty = default)
            pause_between_cuts: Seconds to wait between cuts
        """
        if not result.cuts:
            return {"confirmed": True, "message": "No cuts to execute", "cuts_made": 0}

        # 1. Store current edit mode
        original_mode = bridge.get_edit_mode()
        if isinstance(original_mode, dict) and "error" in original_mode:
            return original_mode

        # 2. Set Shuffle mode
        mode_result = bridge.set_edit_mode(mode="shuffle")
        if isinstance(mode_result, dict) and "error" in mode_result:
            return mode_result

        # 3. Ensure All edit group is enabled (PTSL commands can deactivate it)
        session_name = bridge.get_session_name()
        if isinstance(session_name, dict) and "error" in session_name:
            return session_name
        self._enable_all_group(session_name)

        # 4. Sort cuts in reverse chronological order (latest first)
        sorted_cuts = sorted(result.cuts, key=lambda c: c.start_ms, reverse=True)

        # 5. Execute each cut using PTSL selection + osascript keyboard trigger
        #    PTSL SetTimelineSelection only sets the edit selection on the focused track.
        #    Sending Control+; then Control+P via osascript triggers Pro Tools' All group
        #    to extend the selection across all tracks before clearing.
        cuts_made = 0
        errors = []
        for i, cut in enumerate(sorted_cuts):
            # Set timeline selection via PTSL
            sel = bridge.set_timeline_selection(in_time=cut.start_tc, out_time=cut.end_tc)
            if isinstance(sel, dict) and "error" in sel:
                errors.append(f"Cut {i+1}: timeline selection failed - {sel.get('message', '')}")
                break

            # Trigger All group extension via osascript keyboard shortcut
            self._trigger_all_group()

            # Clear the selection (Shuffle mode = ripple, now across all tracks)
            clr = bridge.clear_selection()
            if isinstance(clr, dict) and "error" in clr:
                errors.append(f"Cut {i+1}: clear failed - {clr.get('message', '')}")
                break

            cuts_made += 1
            time.sleep(pause_between_cuts)

        # 6. Create fades at all edit points
        fade_results = []
        if cuts_made > 0 and not errors:
            # Select the entire timeline across all tracks, then apply fades.
            # Pro Tools' CreateFadesBasedOnPreset creates fades at clip boundaries
            # within the current selection.
            bridge.set_timeline_selection(in_time="00:00:00:00", out_time="23:59:59:23")
            self._trigger_all_group()  # Extend selection to all tracks
            time.sleep(0.2)
            fade_result = bridge.create_fades(preset_name=fade_preset, auto_adjust=True)
            if isinstance(fade_result, dict) and "error" in fade_result:
                fade_results.append(f"Fade creation: {fade_result.get('message', '')}")
            else:
                fade_results.append("Fades created successfully")

        # 7. Restore original edit mode
        if isinstance(original_mode, str):
            # Convert enum name back to simple name
            mode_name = original_mode.replace("EMode_", "").lower()
            bridge.set_edit_mode(mode=mode_name)

        summary = {
            "confirmed": True,
            "cuts_made": cuts_made,
            "total_planned": len(result.cuts),
            "duration_removed_ms": sum(c.duration_ms for c in sorted_cuts[:cuts_made]),
            "fades": fade_results,
        }
        if errors:
            summary["errors"] = errors
            summary["confirmed"] = cuts_made > 0  # Partial success

        return summary
