"""Is anything recording right now?

Silencing speech during a call is the one case where clicking Pause is hardest: the
menu bar may be full and the icon out of reach. Asking CoreAudio removes the click.

The helper reports only that some input device is running - never what is recorded -
and needs no microphone permission of its own.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


def in_use(helper: Optional[Path]) -> bool:
    """True when some application is recording. False when we cannot tell."""
    if helper is None or not Path(helper).exists():
        return False
    try:
        result = subprocess.run(
            [str(helper)], capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0
