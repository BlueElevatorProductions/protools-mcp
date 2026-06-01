"""Timecode utility functions for protools-mcp."""

import re


def validate_timecode(tc: str) -> bool:
    """Validate HH:MM:SS:FF format."""
    return bool(re.match(r'^\d{2}:\d{2}:\d{2}:\d{2}$', tc))


def tc_to_frames(tc: str, fps: int = 30) -> int:
    """Convert HH:MM:SS:FF timecode string to total frames."""
    parts = tc.split(":")
    h, m, s, f = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    return ((h * 3600 + m * 60 + s) * fps) + f


def frames_to_tc(frames: int, fps: int = 30) -> str:
    """Convert total frames back to HH:MM:SS:FF timecode string."""
    f = frames % fps
    total_seconds = frames // fps
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def tc_subtract(tc1: str, tc2: str, fps: int = 30) -> str:
    """Subtract tc2 from tc1, returning duration as HH:MM:SS:FF."""
    return frames_to_tc(tc_to_frames(tc1, fps) - tc_to_frames(tc2, fps), fps)


def samples_to_timecode(samples: int, sample_rate: int = 48000, fps: int = 24) -> str:
    """Convert a sample position to HH:MM:SS:FF timecode.

    Args:
        samples: Sample position (absolute)
        sample_rate: Session sample rate (e.g. 48000)
        fps: Frame rate (e.g. 24)
    """
    total_seconds = samples / sample_rate
    frames = int((total_seconds % 1) * fps)
    total_whole_seconds = int(total_seconds)
    s = total_whole_seconds % 60
    total_minutes = total_whole_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{frames:02d}"


def is_sample_position(value: str) -> bool:
    """Check if a string looks like a raw sample position (all digits)."""
    return value.isdigit()


def ms_to_timecode(ms: int, fps: int = 24) -> str:
    """Convert milliseconds to HH:MM:SS:FF timecode."""
    total_seconds = ms / 1000.0
    frames = int((total_seconds % 1) * fps)
    total_whole_seconds = int(total_seconds)
    s = total_whole_seconds % 60
    total_minutes = total_whole_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{frames:02d}"
