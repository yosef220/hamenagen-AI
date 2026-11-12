"""Running yt-dlp as a separate process the app can always stop.

What running behind NetFree (an Israeli content filter) taught the Tune
Grabber project, kept here:

1. **TLS inspection.** The filter re-signs every HTTPS connection with its
   own root certificate, which it installs in Windows' store; Python's
   bundled certifi list does not have it. yt-dlp.exe (a separate frozen
   program) could not be pointed at Windows' store, which is why Tune Grabber
   had to turn its check off. Here yt-dlp runs inside the app's own Python,
   so the process verifies with Windows' store (truststore, and
   ``--compat-options no-certifi``) and the check stays on. If Windows does
   not trust the certificate either, the listener is told to install the
   filter's certificate — the check is never skipped.
2. **Searching is blocked.** ``ytsearch`` answers HTTP 418 "Blocked by
   NetFree", and so do the search engines and mirrors one could go through.
   The app does not work around the filter: it says so, opens the search in
   the listener's browser and takes the pasted link.
3. **A block page can loop yt-dlp.** A filter page answered with 200 once
   sent yt-dlp, running inside the program, into a loop that took 12 GB and
   froze the computer; a thread cannot stop it. So yt-dlp always runs as its
   own process with a time limit, a no-output limit and a memory limit, and
   is killed when one is passed (on Windows also by a job object that dies
   with the app).
4. **Videos are filtered one by one.** An allowed song downloads; another is
   refused with 418. That is reported for the song, not as "YouTube is
   blocked".
5. **YouTube changes.** When every player client fails to extract, the
   engine is updated once (the newest wheel from PyPI, unpacked into the data
   folder) and the download is tried again.
"""

from __future__ import annotations

import ctypes
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Player clients to try in turn when YouTube refuses one (Tune Grabber's order).
CLIENT_SETS: list[str | None] = [
    None,  # yt-dlp's own default — the best while the engine is current
    "android_vr,android,web",
    "tv,mweb,web_safari",
    "ios,tv_embedded",
]

MEMORY_LIMIT_MB = 1500
PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"

# What went wrong, as far as the listener is concerned.
MESSAGES = {
    "netfree": "הרשת במחשב הזה (נטפרי או סינון דומה) חוסמת את הבקשה הזו.",
    "certificate": ("החיבור המאובטח ליוטיוב לא אומת, ולכן לא הורדנו. אם המחשב מאחורי נטפרי או סינון דומה, "
                    "צריך להתקין את תעודת האבטחה שלהם ב-Windows (כמו שעושים לדפדפן)."),
    "extract": "יוטיוב לא מסר את השיר לאף אחד מסוגי הנגנים שניסינו.",
    "unavailable": "הסרטון אינו זמין (הוסר, פרטי או מוגבל).",
    "network": "אין כרגע חיבור לרשת, או שהשרת לא ענה.",
    "bad_link": "זה לא קישור יוטיוב שאפשר להוריד ממנו.",
    "timeout": "הפעולה לקחה יותר מדי זמן ונעצרה.",
    "stalled": "ההורדה נתקעה ונעצרה.",
    "memory": "מנוע ההורדה התחיל לצרוך זיכרון בלי סוף (כנראה דף חסימה) ונעצר.",
    "cancelled": "ההורדה בוטלה.",
    "not_installed": "רכיב ההורדה (yt-dlp) לא מותקן בגרסה הזו.",
    "other": "הפעולה נכשלה.",
}


def classify_error(text: str) -> str:
    """Name the failure in yt-dlp's output (see :data:`MESSAGES`)."""
    t = (text or "").lower()
    if "netfree" in t or "http error 418" in t or " 418:" in t:
        return "netfree"
    if "certificate verify failed" in t or "certificate_verify_failed" in t:
        return "certificate"
    if any(k in t for k in ("video unavailable", "private video", "this video has been removed",
                            "account associated with this video has been terminated",
                            "members-only", "this live event will begin")):
        return "unavailable"
    if any(k in t for k in ("failed to extract any player response", "unable to extract",
                            "requested format is not available", "no video formats",
                            "sign in to confirm", "403: forbidden", "unable to download video data",
                            "fragment 1 not found")):
        return "extract"
    if any(k in t for k in ("is not a valid url", "unsupported url", "no such file", "incomplete youtube id")):
        return "bad_link"
    if any(k in t for k in ("getaddrinfo", "name or service not known", "timed out", "connection refused",
                            "network is unreachable", "urlopen error", "no route to host", "connection reset",
                            "temporary failure in name resolution", "nodename nor servname",
                            "unable to download webpage", "unable to download api page")):
        return "network"
    return "other"


def message_for(code: str, detail: str = "") -> str:
    base = MESSAGES.get(code, MESSAGES["other"])
    if code == "other" and detail:
        line = next((ln for ln in detail.splitlines() if ln.startswith("ERROR:")), "")
        return f"{base} {line.replace('ERROR:', '').strip()[:160]}".strip()
    return base


@dataclass
class RunResult:
    rc: int
    out: str = ""
    err: str = ""
    killed: str = ""    # "" | "timeout" | "stalled" | "memory" | "cancelled"

    @property
    def ok(self) -> bool:
        return self.rc == 0 and not self.killed

    @property
    def code(self) -> str:
        if self.killed:
            return self.killed
        return "" if self.ok else classify_error(f"{self.err}\n{self.out}")

    @property
    def message(self) -> str:
        return "" if self.ok else message_for(self.code, f"{self.err}\n{self.out}")


# ------------------------------------------------------------------ process guards
def _rss_mb(pid: int) -> float:
    """Memory a process uses, in MB (0 when it cannot be read)."""
    try:
        if os.name == "nt":  # pragma: no cover - Windows only
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            k32 = ctypes.windll.kernel32
            k32.OpenProcess.restype = wintypes.HANDLE
            handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return 0.0
            try:
                pmc = PMC()
                pmc.cb = ctypes.sizeof(PMC)
                if k32.K32GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                    return max(pmc.WorkingSetSize, pmc.PagefileUsage) / 1e6
            finally:
                k32.CloseHandle(handle)
            return 0.0
        with open(f"/proc/{pid}/status", encoding="ascii", errors="ignore") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1000
    except Exception:
        return 0.0
    return 0.0


class _JobObject:  # pragma: no cover - Windows only
    """A Windows job: every yt-dlp process in it dies with the app, and none
    may take more than the memory limit."""

    def __init__(self, memory_mb: int):
        self.handle = None
        if os.name != "nt":
            return
        try:
            from ctypes import wintypes

            class BASIC(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class IOC(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

            class EXT(ctypes.Structure):
                _fields_ = [("Basic", BASIC), ("Io", IOC), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k32 = ctypes.windll.kernel32
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            job = k32.CreateJobObjectW(None, None)
            info = EXT()
            # KILL_ON_JOB_CLOSE (0x2000) | PROCESS_MEMORY (0x100)
            info.Basic.LimitFlags = 0x2000 | 0x100
            info.ProcessMemoryLimit = memory_mb * 1024 * 1024
            if job and k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                self.handle = job
        except Exception:
            self.handle = None

    def add(self, proc: subprocess.Popen) -> None:
        if self.handle is None:
            return
        try:
            ctypes.windll.kernel32.AssignProcessToJobObject(self.handle, int(proc._handle))  # type: ignore[attr-defined]
        except Exception:
            pass


# ------------------------------------------------------------------ the runner
class YtDlpRunner:
    """Starts ``python -m hamenagen.ytdlp_child`` (yt-dlp with the Windows
    certificate store) and watches it."""

    def __init__(self, *, python: str | None = None, engine_dir: str | Path | None = None,
                 ffmpeg: str | Path | None = None, backend_dir: str | Path | None = None,
                 memory_mb: int = MEMORY_LIMIT_MB):
        self.python = python or sys.executable
        self.engine_dir = Path(engine_dir) if engine_dir else None
        self.ffmpeg = str(ffmpeg) if ffmpeg else ""
        self.backend_dir = str(backend_dir or Path(__file__).resolve().parents[1])
        self.memory_mb = memory_mb
        self.updated = False           # the engine was updated in this session
        self._job = _JobObject(memory_mb)
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()

    # -- what is installed --------------------------------------------------
    def _engine_has_package(self) -> bool:
        return bool(self.engine_dir) and (self.engine_dir / "yt_dlp" / "__init__.py").exists()

    def available(self) -> bool:
        return self._engine_has_package() or importlib.util.find_spec("yt_dlp") is not None

    def version(self) -> str | None:
        if self._engine_has_package():
            text = (self.engine_dir / "yt_dlp" / "version.py").read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", text)
            if m:
                return m.group(1)
        try:
            import yt_dlp.version  # type: ignore

            return yt_dlp.version.__version__
        except Exception:
            return None

    # -- running ------------------------------------------------------------
    def command(self, args: list[str], client: str | None = None) -> list[str]:
        common = ["--ignore-config", "--no-warnings", "--encoding", "utf-8",
                  "--extractor-retries", "1", "--socket-timeout", "10"]
        common += ["--compat-options", "no-certifi"]  # verify with the system store (see 1. above)
        if self.ffmpeg:
            common += ["--ffmpeg-location", self.ffmpeg]
        if client:
            common += ["--extractor-args", f"youtube:player_client={client}"]
        return [self.python, "-m", "hamenagen.ytdlp_child", *common, *args]

    def _env(self) -> dict:
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = os.pathsep.join(p for p in (self.backend_dir, env.get("PYTHONPATH", "")) if p)
        env["HAMENAGEN_ENGINE_DIR"] = str(self.engine_dir or "")
        return env

    def _start(self, cmd: list[str], *, merge_err: bool) -> subprocess.Popen:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT if merge_err else subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", bufsize=1,
            env=self._env(), creationflags=CREATE_NO_WINDOW,
        )
        self._job.add(proc)
        with self._lock:
            self._procs.add(proc)
        return proc

    def _forget(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.discard(proc)

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        try:
            proc.kill()
        except Exception:
            pass

    def stop_all(self) -> None:
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            self._kill(p)

    def _watch(self, proc, state: dict, *, timeout: float | None, stall: float | None,
               cancel: threading.Event | None) -> None:
        start = time.monotonic()
        while proc.poll() is None:
            time.sleep(0.5)
            now = time.monotonic()
            reason = ""
            if cancel is not None and cancel.is_set():
                reason = "cancelled"
            elif timeout and now - start > timeout:
                reason = "timeout"
            elif stall and now - state["last"] > stall:
                reason = "stalled"
            elif _rss_mb(proc.pid) > self.memory_mb:
                reason = "memory"
            if reason:
                state["killed"] = reason
                self._kill(proc)
                return

    def run(self, args: list[str], *, timeout: float = 30, client: str | None = None,
            cancel: threading.Event | None = None) -> RunResult:
        """Run to the end and return what it printed (stdout and stderr apart)."""
        return self._run_once(args, timeout=timeout, client=client, cancel=cancel)

    def _run_once(self, args, *, timeout, client, cancel) -> RunResult:
        try:
            proc = self._start(self.command(args, client), merge_err=False)
        except OSError as exc:
            return RunResult(-1, err=str(exc))
        state = {"last": time.monotonic(), "killed": ""}
        watcher = threading.Thread(target=self._watch, args=(proc, state),
                                   kwargs={"timeout": timeout, "stall": None, "cancel": cancel}, daemon=True)
        watcher.start()
        try:
            out, err = proc.communicate()
        finally:
            self._forget(proc)
        return RunResult(proc.returncode if proc.returncode is not None else -9, out or "", err or "",
                         state["killed"])

    def stream(self, args: list[str], on_line, *, stall: float = 90, timeout: float | None = None,
               client: str | None = None, cancel: threading.Event | None = None) -> RunResult:
        """Run and hand every output line to ``on_line`` as it comes; killed
        after ``stall`` seconds without a line."""
        return self._stream_once(args, on_line, stall=stall, timeout=timeout, client=client, cancel=cancel)

    def _stream_once(self, args, on_line, *, stall, timeout, client, cancel) -> RunResult:
        try:
            proc = self._start(self.command(args, client), merge_err=True)
        except OSError as exc:
            return RunResult(-1, err=str(exc))
        state = {"last": time.monotonic(), "killed": ""}
        watcher = threading.Thread(target=self._watch, args=(proc, state),
                                   kwargs={"timeout": timeout, "stall": stall, "cancel": cancel}, daemon=True)
        watcher.start()
        lines: list[str] = []
        try:
            for raw in iter(proc.stdout.readline, ""):
                line = raw.rstrip("\r\n")
                state["last"] = time.monotonic()
                if not line:
                    continue
                lines.append(line)
                if len(lines) > 400:
                    del lines[:200]
                try:
                    on_line(line)
                except Exception:
                    pass
            proc.stdout.close()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._kill(proc)
                proc.wait()
        finally:
            self._forget(proc)
        text = "\n".join(lines)
        return RunResult(proc.returncode if proc.returncode is not None else -9, out=text, err=text,
                         killed=state["killed"])

    def json_lines(self, result: RunResult) -> list[dict]:
        out = []
        for line in (result.out or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out

    # -- keeping the engine current ----------------------------------------
    def update_engine(self, *, timeout: float = 120) -> dict:
        """Put the newest yt-dlp (a pure-Python wheel from PyPI) in the data
        folder; the next run uses it. Never touches the bundled copy."""
        if self.engine_dir is None:
            return {"ok": False, "message": "אין תיקייה לעדכון"}
        try:
            req = urllib.request.Request(PYPI_URL, headers={"User-Agent": "engine-update/1.2", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                meta = json.loads(resp.read().decode("utf-8"))
            latest = meta["info"]["version"]
            current = self.version()
            if current and _version_key(current) >= _version_key(latest):
                return {"ok": True, "updated": False, "version": current}
            wheel = next(u for u in meta["urls"] if u["filename"].endswith("-py3-none-any.whl"))
            req = urllib.request.Request(wheel["url"], headers={"User-Agent": "engine-update/1.2"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read(30_000_000)
            import hashlib

            if wheel.get("digests", {}).get("sha256") and hashlib.sha256(data).hexdigest() != wheel["digests"]["sha256"]:
                return {"ok": False, "message": "הקובץ שהורד לא תאם את החתימה"}
            tmp = self.engine_dir.with_name(self.engine_dir.name + ".new")
            if tmp.exists():
                import shutil

                shutil.rmtree(tmp, ignore_errors=True)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                members = [m for m in zf.namelist() if m.startswith("yt_dlp/")]
                zf.extractall(tmp, members)
            if not (tmp / "yt_dlp" / "__init__.py").exists():
                return {"ok": False, "message": "חבילת העדכון לא תקינה"}
            import shutil

            old = self.engine_dir.with_name(self.engine_dir.name + ".old")
            shutil.rmtree(old, ignore_errors=True)
            if self.engine_dir.exists():
                self.engine_dir.rename(old)
            tmp.rename(self.engine_dir)
            shutil.rmtree(old, ignore_errors=True)
            self.updated = True
            return {"ok": True, "updated": True, "version": latest}
        except Exception as exc:
            return {"ok": False, "message": f"עדכון מנוע ההורדה נכשל: {type(exc).__name__}"}


def _version_key(v: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", v))
