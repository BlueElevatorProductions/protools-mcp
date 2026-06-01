"""Pro Tools popup detection + dismissal helper (v2).

Improvements over v1:
  - Known-popup table maps dialog name → button label (e.g. Session Notes → No)
  - Polls for `wait_for` seconds so popups that arrive AFTER an action are caught
  - "Dwell" period after a dismissal in case follow-up popups chain
  - Falls back to Return key for unknown dialogs
"""

import subprocess
import time
from typing import Dict, Tuple


# Known PT popups → which button to click. Add as we encounter them.
# Default behavior for unknown dialogs is to press Return.
KNOWN_BUTTONS: Dict[str, str] = {
    "Session Notes": "No",          # opening sessions saved with notes prompt
    "Missing AAX Plugins": "OK",    # plugins that aren't installed on this Mac
    # extend below as we hit new ones
}


DETECT_SCRIPT = '''
tell application "System Events"
    if not (exists process "Pro Tools") then return "0|"
    tell process "Pro Tools"
        set total to 0
        set names to ""
        try
            set dlgs to (every window whose subrole is "AXDialog")
            repeat with w in dlgs
                set total to total + 1
                set names to names & (name of w as string) & ";"
            end repeat
        end try
        repeat with w in windows
            try
                set sh to (every sheet of w)
                repeat with s in sh
                    set total to total + 1
                    set names to names & "SHEET-of-" & (name of w as string) & ";"
                end repeat
            end try
        end repeat
        return (total as string) & "|" & names
    end tell
end tell
'''


def detect_popups() -> Tuple[int, list]:
    """Return (count, [name1, name2, ...])."""
    result = subprocess.run(
        ["osascript", "-e", DETECT_SCRIPT],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
        return (-1, [f"osascript error: {result.stderr.strip()}"])
    raw = result.stdout.strip()
    parts = raw.split("|", 1)
    try:
        count = int(parts[0])
    except ValueError:
        return (-1, [f"unexpected output: {raw!r}"])
    names = [n for n in (parts[1] if len(parts) > 1 else "").split(";") if n]
    return (count, names)


def _click_known(name: str, button: str) -> bool:
    script = f'''
    tell application "System Events"
        tell process "Pro Tools"
            try
                click button "{button}" of (first window whose name is "{name}")
                return "ok"
            on error errMsg
                return "err:" & errMsg
            end try
        end tell
    end tell
    '''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
    return result.stdout.strip() == "ok"


def _press_return() -> None:
    subprocess.run(
        ["osascript", "-e",
         'tell application "Pro Tools" to activate\n'
         'delay 0.1\n'
         'tell application "System Events" to keystroke return'],
        capture_output=True, timeout=5,
    )


def dismiss_popups(
    wait_for: float = 0.0,
    dwell: float = 1.5,
    poll: float = 0.4,
    max_dismissals: int = 10,
    verbose: bool = True,
) -> int:
    """Detect + dismiss any visible PT popups.

    Strategy:
      1. Poll for `wait_for` seconds, looking for any popup. If one appears, dismiss it.
      2. After each dismissal, keep polling for `dwell` more seconds — popups often chain
         (e.g., Session Notes → Missing Plugins → Save reminder).
      3. Use KNOWN_BUTTONS table when the dialog name matches; otherwise press Return.

    :param wait_for: initial wait window for popups to appear (use ~5–10s after expensive ops)
    :param dwell:    extra wait after each dismissal (catches chained popups)
    :param poll:     poll interval
    :param max_dismissals: hard cap to defend against unkillable loops
    :param verbose:  print what got dismissed

    Returns count of dismissed popups.
    """
    deadline = time.time() + wait_for
    dismissed = 0

    while time.time() < deadline or dismissed == 0:
        count, names = detect_popups()
        if count > 0:
            for name in names:
                if dismissed >= max_dismissals:
                    if verbose:
                        print(f"  [popup helper] hit max_dismissals={max_dismissals}, stopping", flush=True)
                    return dismissed
                button = KNOWN_BUTTONS.get(name)
                if button:
                    ok = _click_known(name, button)
                    if verbose:
                        print(f"  [popup helper] dialog={name!r} → click {button!r} ({'ok' if ok else 'failed'})", flush=True)
                    if not ok:
                        # Fallback to Return
                        _press_return()
                else:
                    if verbose:
                        print(f"  [popup helper] dialog={name!r} → unknown, pressing Return", flush=True)
                    _press_return()
                dismissed += 1
                time.sleep(0.4)
            # Extend deadline after a dismissal — chained popups often follow
            deadline = max(deadline, time.time() + dwell)
        else:
            if dismissed == 0 and time.time() >= deadline:
                # Initial wait expired with nothing seen — done
                break
            time.sleep(poll)

    if verbose and dismissed:
        print(f"  [popup helper] total dismissed: {dismissed}", flush=True)
    return dismissed


if __name__ == "__main__":
    import sys
    wait = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    print(f"detect_popups: {detect_popups()}")
    if wait > 0:
        print(f"\nDismissing with wait_for={wait}s...")
        n = dismiss_popups(wait_for=wait)
        print(f"Dismissed: {n}")
