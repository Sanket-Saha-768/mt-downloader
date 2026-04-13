import threading
import time
import sys
from mt_downloader.state import SharedState, ChunkSpec

BAR_W   = 36          # consistent width for both modes
ETA_WIN = 8.0         # seconds for sliding-window speed estimate

_UP    = lambda n: f"\033[{n}A"
_ERASE = "\033[2K\r"
_HIDE  = "\033[?25l"
_SHOW  = "\033[?25h"


class _SpeedTracker:
    """
    Sliding-window speed estimator.
    Keeps a fixed-duration window of (timestamp, bytes_done) samples
    and computes speed from the oldest to newest point in that window.
    This avoids the "ETA jumps at the end" problem caused by using the
    cumulative average from t=0.
    """
    def __init__(self, window: float = ETA_WIN):
        self._window  = window
        self._samples: list[tuple[float, int]] = []   # (timestamp, cumulative_bytes)
        self._lock    = threading.Lock()

    def record(self, t: float, total_done: int) -> None:
        with self._lock:
            self._samples.append((t, total_done))
            cutoff = t - self._window
            self._samples = [(ts, b) for ts, b in self._samples if ts >= cutoff]

    def speed_bps(self) -> float:
        """Bytes per second over the sliding window. Returns 0 if not enough data."""
        with self._lock:
            if len(self._samples) < 2:
                return 0.0
            t0, b0 = self._samples[0]
            t1, b1 = self._samples[-1]
            dt = t1 - t0
            return (b1 - b0) / dt if dt > 0 else 0.0


def _bar(pct: float, width: int = BAR_W) -> str:
    filled = int(width * pct)
    return "█" * filled + "░" * (width - filled)


def _fmt_eta(seconds: float) -> str:
    if seconds <= 0 or seconds > 3600:
        return "  --"
    if seconds < 60:
        return f"{seconds:4.0f}s"
    return f"{seconds/60:4.1f}m"


def progress_monitor(
    state:  SharedState,
    total:  int,
    stop:   threading.Event,
    chunks: list[ChunkSpec],
) -> None:
    """
    Per-thread progress display.

    TTY detection: checks sys.stderr.isatty(). If running under a process
    that pipes stderr (e.g. pipeline.py redirected to a log), falls back
    to simple line-by-line logging instead of broken \r output.

    TTY mode — redraws N+2 lines in place every 0.4s:

      Overall  [████████████░░░░░░░░░░░░░░░░░░░░░░░░]  42.3%  210.5/500.0 MB  1.2 MB/s  ETA  12s
      ─────────────────────────────────────────────────────────────────────────
      Thread 0  [████████████████████████████████████] 100.0%   125.0/125.0 MB  done
      Thread 1  [███████████████░░░░░░░░░░░░░░░░░░░░░]  41.6%    52.0/125.0 MB  ...
      Thread 2  [██████████████████████░░░░░░░░░░░░░░]  63.2%    79.0/125.0 MB  ...
      Thread 3  [████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░]  21.6%    27.0/125.0 MB  ...

    Non-TTY mode — emits one INFO log line every 5 seconds (readable in
    redirected output / log files without flooding them).
    """
    out       = sys.stderr
    is_tty    = hasattr(out, "fileno") and out.isatty()
    n         = len(chunks)
    t0        = time.monotonic()
    tracker   = _SpeedTracker()
    chunk_len = {c.index: c.length for c in chunks}

    # ── Non-TTY: sparse log lines, no \r flood ────────────────────────────────
    if not is_tty:
        last_log = t0
        LOG_INTERVAL = 5.0
        while not stop.wait(0.5):
            now = time.monotonic()
            with state.lock:
                done = sum(state.progress.values())
            tracker.record(now, done)
            if now - last_log >= LOG_INTERVAL:
                pct   = done / total * 100 if total else 0
                speed = tracker.speed_bps() / 1_048_576
                eta   = (total - done) / tracker.speed_bps() if tracker.speed_bps() > 0 else 0
                out.write(
                    f"  progress: {pct:5.1f}%  "
                    f"{done/1_048_576:.1f}/{total/1_048_576:.1f} MB  "
                    f"{speed:.2f} MB/s  ETA {_fmt_eta(eta)}\n"
                )
                out.flush()
                last_log = now
        # Final line
        with state.lock:
            done = sum(state.progress.values())
        pct = done / total * 100 if total else 0
        out.write(f"  progress: {pct:5.1f}%  {done/1_048_576:.1f}/{total/1_048_576:.1f} MB  complete\n")
        out.flush()
        return

    # ── TTY: per-thread redraws ───────────────────────────────────────────────
    total_lines = n + 2     # overall line + divider + N thread rows

    out.write(_HIDE)
    out.write("\n" * total_lines)
    out.flush()

    def _redraw(snap: dict[int, int]) -> None:
        now  = time.monotonic()
        done = sum(snap.values())
        tracker.record(now, done)

        pct   = done / total if total else 0
        speed = tracker.speed_bps()
        eta   = (total - done) / speed if speed > 0 else 0
        smb   = speed / 1_048_576

        lines: list[str] = []
        lines.append(
            f"  Overall  [{_bar(pct)}] {pct*100:5.1f}%  "
            f"{done/1_048_576:6.1f}/{total/1_048_576:.1f} MB  "
            f"{smb:.2f} MB/s  ETA {_fmt_eta(eta)}"
        )
        lines.append("  " + "─" * (BAR_W + 46))

        for c in sorted(chunks, key=lambda c: c.index):
            cdone  = snap.get(c.index, 0)
            ctotal = chunk_len[c.index]
            cpct   = cdone / ctotal if ctotal else 0
            if c.index in state.errors:
                status = "ERR"
            elif cdone >= ctotal:
                status = "done"
            else:
                status = "..."
            lines.append(
                f"  Thread {c.index:<2} [{_bar(cpct)}] {cpct*100:5.1f}%  "
                f"{cdone/1_048_576:6.1f}/{ctotal/1_048_576:.1f} MB  {status}"
            )

        out.write(_UP(total_lines))
        for line in lines:
            out.write(f"{_ERASE}{line}\n")
        out.flush()

    while not stop.wait(0.4):
        with state.lock:
            snap = dict(state.progress)
        _redraw(snap)

    with state.lock:
        snap = dict(state.progress)
    _redraw(snap)

    out.write(_SHOW)
    out.flush()