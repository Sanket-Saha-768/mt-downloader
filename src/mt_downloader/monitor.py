import threading, time, sys
from mt_downloader.state import SharedState

def progress_monitor(state: SharedState, total: int, stop: threading.Event) -> None:
    """
    Periodically prints a progress bar to stderr.
    Runs as a daemon thread; stopped via the `stop` Event.
    """
    bar_width = 40
    start_time = time.monotonic()

    while not stop.wait(timeout=0.5):
        with state.lock:
            downloaded = sum(state.progress.values())

        elapsed = max(time.monotonic() - start_time, 0.001)
        pct = downloaded / total if total else 0
        filled = int(bar_width * pct)
        bar = "█" * filled + "░" * (bar_width - filled)
        speed_mb = (downloaded / elapsed) / 1_048_576
        eta = (total - downloaded) / (downloaded / elapsed) if downloaded else 0

        sys.stderr.write(
            f"\r  [{bar}] {pct*100:5.1f}%  "
            f"{downloaded/1_048_576:6.1f}/{total/1_048_576:.1f} MB  "
            f"{speed_mb:.2f} MB/s  ETA {eta:.0f}s   "
        )
        sys.stderr.flush()

    sys.stderr.write("\n")