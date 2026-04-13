import threading, logging
import time
import sys
from mt_downloader.state import SharedState, ChunkSpec
from rich.progress import (
    Progress,
    BarColumn,
    DownloadColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
    TaskID,
)
from rich.console import Console
from rich.logging import RichHandler

log = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> Console:
    """
    Wire the root logger through Rich so that log lines printed by worker
    threads appear above the progress bars without breaking the display.
    Call this once from main() before creating the Progress context.
    Returns the Console instance that monitor and logging both share.
    """
    console = Console(stderr=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[
            RichHandler(
                console=console,
                show_time=True,
                show_path=False,
                markup=False,
            )
        ],
    )
    return console


BAR_W = 36  # consistent width for both modes
ETA_WIN = 8.0  # seconds for sliding-window speed estimate

_UP = lambda n: f"\033[{n}A"
_ERASE = "\033[2K\r"
_HIDE = "\033[?25l"
_SHOW = "\033[?25h"


class _SpeedTracker:
    """
    Sliding-window speed estimator.
    Keeps a fixed-duration window of (timestamp, bytes_done) samples
    and computes speed from the oldest to newest point in that window.
    This avoids the "ETA jumps at the end" problem caused by using the
    cumulative average from t=0.
    """

    def __init__(self, window: float = ETA_WIN):
        self._window = window
        self._samples: list[tuple[float, int]] = []  # (timestamp, cumulative_bytes)
        self._lock = threading.Lock()

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
    state: SharedState,
    total: int,
    stop: threading.Event,
    chunks: list[ChunkSpec],
    console: Console | None = None,
) -> None:
    """
    Rich-based progress display with one bar per thread plus an overall bar.
    """

    if console is None:
        console = Console(stderr=True)

    chunk_len = {c.index: c.length for c in chunks}

    columns = [
        TextColumn("[bold]{task.description:<12}"),
        BarColumn(bar_width=36),
        "[progress.percentage]{task.percentage:>5.1f}%",
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    ]

    with Progress(*columns, console=console, refresh_per_second=4) as progress:

        overall_id: TaskID = progress.add_task("Overall", total=total)
        thread_ids: dict[int, TaskID] = {
            c.index: progress.add_task(f"Thread {c.index}", total=c.length)
            for c in sorted(chunks, key=lambda c: c.index)
        }

        prev_done: dict[int, int] = {idx: 0 for idx in chunk_len}
        prev_total = 0

        while not stop.wait(0.25):
            with state.lock:
                snap = dict(state.progress)

            # Advance each thread bar by the delta since last tick
            for idx, task_id in thread_ids.items():
                current = snap.get(idx, 0)
                delta = current - prev_done[idx]
                if delta > 0:
                    progress.advance(task_id, delta)
                    prev_done[idx] = current

                # Mark errored chunks visibly
                if idx in state.errors:
                    progress.update(task_id, description=f"[red]Thread {idx}[/red]")

            # Advance overall bar
            total_done = sum(snap.values())
            overall_delta = total_done - prev_total
            if overall_delta > 0:
                progress.advance(overall_id, overall_delta)
                prev_total = total_done

        # Final sync — fill any remaining delta after stop is set
        with state.lock:
            snap = dict(state.progress)
        for idx, task_id in thread_ids.items():
            delta = snap.get(idx, 0) - prev_done[idx]
            if delta > 0:
                progress.advance(task_id, delta)
        total_done = sum(snap.values())
        final_delta = total_done - prev_total
        if final_delta > 0:
            progress.advance(overall_id, final_delta)
