"""Full speed in the background, on Windows 11 (1.7).

Windows 11 puts a program whose window is not in front on "efficiency mode"
(EcoQoS): its threads run on the slow cores at a low clock. That made
downloads, MP3 conversion and the background listening crawl while the player
was minimised. The core and its yt-dlp processes opt out — the same call
browsers use for audio playback. Elsewhere this does nothing.
"""

from __future__ import annotations

import ctypes
import os

PROCESS_POWER_THROTTLING = 4               # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
_EXECUTION_SPEED = 0x1                     # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
_IGNORE_TIMER_RESOLUTION = 0x4


class _State(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


def no_throttling() -> bool:
    """Ask Windows not to slow this process down in the background. True when it agreed."""
    if os.name != "nt":
        return False
    try:
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        state = _State(1, _EXECUTION_SPEED | _IGNORE_TIMER_RESOLUTION, 0)   # control the speed, and turn throttling off
        return bool(k32.SetProcessInformation(k32.GetCurrentProcess(), PROCESS_POWER_THROTTLING,
                                              ctypes.byref(state), ctypes.sizeof(state)))
    except Exception:  # noqa: BLE001 - older Windows: nothing to turn off
        return False
