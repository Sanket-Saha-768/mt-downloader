from mt_downloader.state import ChunkSpec, SharedState
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import time
import logging
log = logging.getLogger(__name__)
CHUNK_READ_SIZE = 65_536  # 64 KB read buffer per thread
USER_AGENT = "chunked-downloader/1.0"


def download_chunk(
    url: str,
    chunk: ChunkSpec,
    out_path: Path,
    state: SharedState,
    retries: int = 3,
    timeout: int = 30,
) -> None:
    """
    Download one byte range and write it directly into the pre-allocated
    output file at the correct offset (seek-based, no temp files).

    OS concepts exercised:
      - File seek + partial write  (pwrite semantics via seek+write under lock)
      - Lock acquisition for shared progress counter
      - Event check for cooperative cancellation
    """
    log.info("Starting %s", chunk)

    for attempt in range(1, retries + 1):

        # ── Cooperative cancellation check ──────────────────────────────────
        if state.cancel_event.is_set():
            log.warning("%s cancelled before attempt %d", chunk, attempt)
            return
        
        with state.lock:
            state.progress[chunk.index] = 0

        try:
            req = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Range": f"bytes={chunk.start}-{chunk.end}",
                },
            )

            with urlopen(req, timeout=timeout) as resp:
                # if resp.status not in (200, 206):
                if resp.status != 206:
                    # raise HTTPError(url, resp.status, "Unexpected status", {}, None)
                    raise RuntimeError(f"{chunk}: expected 206, got {resp.status}")
                cr = resp.headers.get("Content-Range")
                if cr:
                    try:
                        rng = cr.split()[1].split("/")[0]
                        start, end = map(int, rng.split("-"))
                        if start != chunk.start or end != chunk.end:
                            raise ValueError(f"{chunk}: Content-Range mismatch")
                    except Exception:
                        raise ValueError(f"{chunk}: invalid Content-Range header")
                # Open the shared output file for writing at the correct offset.
                # Each thread writes to a disjoint region so no lock is needed
                # for the write itself — but we do lock the progress counter.
                with open(out_path, "r+b") as fh:
                    fh.seek(chunk.start)
                    bytes_written = 0

                    while True:
                        if state.cancel_event.is_set():
                            log.warning("%s cancelled mid-download", chunk)
                            return

                        buf = resp.read(CHUNK_READ_SIZE)
                        if not buf:
                            break

                        fh.write(buf)
                        bytes_written += len(buf)

                        # Update shared progress counter (protected by lock)
                        with state.lock:
                            state.progress[chunk.index] = state.progress.get(
                                chunk.index, 0
                            ) + len(buf)
                    
                    if bytes_written != chunk.length:
                        raise ValueError(
                            f"{chunk}: wrote {bytes_written}, expected {chunk.length}"
                        )

            log.info("Finished %s (%d B written)", chunk, bytes_written)
            return  # success

        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            log.warning("%s attempt %d/%d failed: %s", chunk, attempt, retries, exc)
            if attempt == retries:
                with state.lock:
                    state.errors[chunk.index] = exc
                state.cancel_event.set()  # signal other threads to stop
                return
            time.sleep(2**attempt)  # exponential back-off
