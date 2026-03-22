from mt_downloader.network import probe_server
from mt_downloader.chunking import make_chunks
from mt_downloader.worker import download_chunk
from mt_downloader.state import SharedState
from mt_downloader.monitor import progress_monitor
from mt_downloader.utils import _md5_file
from urllib.parse import urlparse
import threading, time
from pathlib import Path
import logging

log = logging.getLogger(__name__)


def download(
    url: str,
    out_path: str | None = None,
    n_threads: int = 4,
    retries: int = 3,
    timeout: int = 30,
    verify_md5: str | None = None,
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
        total_size, supports_ranges = probe_server(url, timeout)
    except Exception as exc:
        raise RuntimeError(f"HEAD request failed: {exc}") from exc

    if not supports_ranges or total_size == 0:
        log.warning(
            "Server does not support range requests; falling back to single-thread."
        )
        n_threads = 1

    log.info("File size: %s bytes | threads: %d", f"{total_size:,}", n_threads)

    # ── Output path ──────────────────────────────────────────────────────────
    if out_path is None:
        name = Path(urlparse(url).path).name or "download"
        dest = Path(name)
    else:
        dest = Path(out_path)

    dest.parent.mkdir(parents=True, exist_ok=True)

    # ── Pre-allocate output file ──────────────────────────────────────────────
    # Creates a sparse (or zero-filled) file of exactly total_size bytes.
    # Workers can then seek+write concurrently into disjoint regions.
    with open(dest, "wb") as fh:
        if total_size > 0:
            fh.seek(total_size - 1)
            fh.write(b"\x00")
    log.info("Pre-allocated %s", dest)

    # ── Partition ─────────────────────────────────────────────────────────────
    chunks = make_chunks(total_size, n_threads)

    # ── Shared state ──────────────────────────────────────────────────────────
    state = SharedState(total_size=total_size)
    for c in chunks:
        state.progress[c.index] = 0

    # ── Progress monitor ──────────────────────────────────────────────────────
    stop_monitor = threading.Event()
    monitor = threading.Thread(
        target=progress_monitor,
        args=(state, total_size, stop_monitor),
        name="ProgressMonitor",
        daemon=True,
    )
    monitor.start()

    # ── Launch worker threads (FORK) ──────────────────────────────────────────
    t_start = time.monotonic()
    workers: list[threading.Thread] = []

    for chunk in chunks:
        t = threading.Thread(
            target=download_chunk,
            args=(url, chunk, dest, state, retries, timeout),
            name=f"Worker-{chunk.index}",
        )
        workers.append(t)

    for t in workers:
        t.start()

    # ── Join (implicit Barrier — main blocks until all workers done) ──────────
    for t in workers:
        t.join()

    # ── Stop monitor ──────────────────────────────────────────────────────────
    stop_monitor.set()
    monitor.join()

    elapsed = time.monotonic() - t_start

    # ── Check for errors ──────────────────────────────────────────────────────
    if state.errors:
        dest.unlink(missing_ok=True)
        # first_err = next(iter(state.errors.values()))
        # raise RuntimeError(f"Download failed: {first_err}")
        msgs = "\n".join(str(e) for e in state.errors.values())
        raise RuntimeError(f"Download failed:\n{msgs}")

    # ── Optional integrity check ───────────────────────────────────────────────
    if verify_md5:
        log.info("Verifying MD5 …")
        digest = _md5_file(dest)
        if digest != verify_md5:
            dest.unlink(missing_ok=True)
            raise ValueError(f"MD5 mismatch: expected {verify_md5}, got {digest}")
        log.info("MD5 OK  (%s)", digest)

    speed_mb = (total_size / elapsed) / 1_048_576
    log.info(
        "Done: %s  %.2f MB  %.2f MB/s  %.1fs",
        dest,
        total_size / 1_048_576,
        speed_mb,
        elapsed,
    )

    if dest.stat().st_size != total_size:
        raise RuntimeError(
            f"File size mismatch: expected {total_size}, got {dest.stat().st_size}"
        )
    return dest
