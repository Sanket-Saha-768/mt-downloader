from mt_downloader.network import probe_server
from mt_downloader.chunking import make_chunks, assert_no_overlap
from mt_downloader.worker import _worker_range, _worker_single
from mt_downloader.state import SharedState
from mt_downloader.monitor import progress_monitor
from mt_downloader.utils import _md5_file, _verify_integrity
from urllib.parse import urlparse
import threading, time
from pathlib import Path
import logging
import os
import shutil
log = logging.getLogger(__name__)


def download(
    url: str,
    out_path: str | None = None,
    n_threads: int = 4,
    retries: int = 3,
    verify_md5: str | None = None,
    verify_sha256: str | None = None,
) -> Path:
    """
    Download `url` in parallel using `n_threads` threads.

    Threading model
    ───────────────
    • One thread per chunk, all started together (fork step).
    • Main thread joins all workers (join step).
    • A separate daemon thread prints progress.
    • Cancellation is cooperative via a shared threading.Event.
    • A Barrier ensures assembly only begins after every chunk is done.
        (In this implementation join() is the barrier — shown explicitly below.)

    File model
    ──────────
    • Output file is pre-allocated to `total_size` bytes with truncate().
    • Each worker seeks to its chunk.start offset and writes in place.
    • Disjoint write regions → no lock needed for file I/O, only for counters.
    """
    # ── Probe ────────────────────────────────────────────────────────────────
    log.info("Probing %s …", url)
    try:
        info = probe_server(url)
        total_size = info.total_size
        supports_ranges = info.supports_range
    except Exception as exc:
        raise RuntimeError(f"HEAD request failed: {exc}") from exc

    log.info("File size: %s bytes | threads: %d", f"{total_size:,}", n_threads)

    # Output path 
    if out_path is None:
        dest = Path(info.filename)
    else:
        dest = Path(out_path)

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Disk space check
    free = shutil.disk_usage(dest.parent).free
    if free < total_size:
        raise RuntimeError(f"Not enough disk space: need {total_size}, have {free}")
    
    if not supports_ranges or n_threads == 1:
        log.info("Single-thread mode (no Range support)")

        state = SharedState(total_size=total_size)
        state.progress[0] = 0

        stop_monitor = threading.Event()
        monitor = threading.Thread(
            target=progress_monitor,
            args=(state, total_size, stop_monitor),
            daemon=True,
            name="ProgressMonitor",
        )
        monitor.start()

        _worker_single(url, dest, state, retries)

        stop_monitor.set()
        monitor.join()

        if state.errors:
            errs = [str(e) for el in state.errors.values() for e in el]
            raise RuntimeError("Download failed:\n" + "\n".join(errs))
        _verify_integrity(dest, verify_md5, verify_sha256)
        return dest

    # ── Pre-allocate output file ──────────────────────────────────────────────
    # Creates a sparse (or zero-filled) file of exactly total_size bytes.
    # Workers can then seek+write concurrently into disjoint regions.
    with open(dest, "wb") as fh:
        if total_size > 0:
            fh.seek(total_size - 1)
            fh.write(b"\x00")
        else:
            raise RuntimeError(f"Total file size is 0")
    log.info("Pre-allocated %s", dest)

    # Partition
    chunks = make_chunks(total_size, n_threads)
    assert_no_overlap(chunks, total_size)


    # Shared file descriptor and state
    out_fd = os.open(dest, os.O_RDWR)
    state = SharedState(total_size=total_size)
    for c in chunks:
        state.progress[c.index] = 0

    # Progress monitor
    stop_monitor = threading.Event()
    monitor = threading.Thread(
        target=progress_monitor,
        args=(state, total_size, stop_monitor),
        name="ProgressMonitor",
        daemon=True,
    )
    monitor.start()

    # Worker threads
    t_start = time.monotonic()
    workers: list[threading.Thread] = [
        threading.Thread(
            target=_worker_range,
            args=(url, chunk, out_fd, state, retries),
            name=f"Worker-{chunk.index}",
        )
        for chunk in chunks
    ]

    for t in workers:
        t.start()

    for t in workers:
        t.join()

    # Stop monitor
    stop_monitor.set()
    monitor.join()

    os.fsync(out_fd)
    os.close(out_fd)

    elapsed = time.monotonic() - t_start

    # Error Handling
    if state.errors:
        dest.unlink(missing_ok=True)
        # first_err = next(iter(state.errors.values()))
        # raise RuntimeError(f"Download failed: {first_err}")
        msgs = [
            f"chunk[{idx}]: " + "; ".join(str(e) for e in errs)
            for idx, errs in state.errors.items()
        ]
        raise RuntimeError("Download failed:\n" + "\n".join(msgs))

    # File Integrity Check

    actual = dest.stat().st_size
    if actual != total_size:
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"File size mismatch: expected {total_size}, got {actual}"
        )
    
    _verify_integrity(dest, verify_md5, verify_sha256)

    speed_mb = (total_size / elapsed) / 1_048_576
    log.info(
        "Done: %s  %.2f MB  %.2f MB/s  %.1fs",
        dest,
        total_size / 1_048_576,
        speed_mb,
        elapsed,
    )

    return dest
