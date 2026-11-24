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


last_error = 0


def no_throttling() -> bool:
    """Ask Windows not to slow this process down in the background. True when it agreed."""
    global last_error
    if os.name != "nt":
        return False
    try:
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        # 64-bit handles: without these the pseudo handle of this process is cut to 32 bits.
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetProcessInformation.restype = wintypes.BOOL
        me = k32.GetCurrentProcess()
        # Control the speed (and, where Windows knows it, the timer resolution) and turn throttling off;
        # an older Windows that does not know the second flag is asked for the speed alone.
        for mask in (_EXECUTION_SPEED | _IGNORE_TIMER_RESOLUTION, _EXECUTION_SPEED):
            state = _State(1, mask, 0)
            if k32.SetProcessInformation(me, PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state)):
                return True
            last_error = ctypes.get_last_error()
        return False
    except Exception:  # noqa: BLE001 - older Windows: nothing to turn off
        return False
