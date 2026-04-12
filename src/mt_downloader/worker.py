import logging
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mt_downloader.state import ChunkSpec, SharedState

from .network import _make_request

log = logging.getLogger(__name__)

CHUNK_READ_SIZE = 65_536  # 64 KB read buffer per thread
USER_AGENT = "chunked-downloader/1.0"
READ_TIMEOUT = 30  # seconds between successive data reads


def _worker_range(
    url: str, chunk: ChunkSpec, out_fd: int, state: SharedState, retries: int
) -> None:
    """Download one byte range and write it directly into the pre-allocated
    output file at the correct byte offset."""
    for attempt in range(1, retries + 1):

        # Cooperative cancellation check
        if state.cancel_event.is_set():
            log.warning("%s cancelled before attempt %d", chunk, attempt)
            return

        # Reset progress on retry so the monitor doesn't double-count
        with state.lock:
            state.progress[chunk.index] = 0

        try:
            req = _make_request(url, Range=f"bytes={chunk.start}-{chunk.end}")
            with urlopen(req, timeout=READ_TIMEOUT) as resp:
                if resp.status != 206:
                    # raise HTTPError(url, resp.status, "Unexpected status", {}, None)
                    raise RuntimeError(
                        f"Expected 206 Partial Content, got {resp.status}. "
                        "Server may be ignoring the Range header, which would "
                        "cause multiple threads to write full-file data at "
                        "wrong offsets (corruption).",
                    )
                _validate_content_range(resp.headers.get("Content-Range", ""), chunk)
                # chunk.start <= offset <= chunk.end + 1
                offset = chunk.start
                bytes_written = 0

                while True:
                    if state.cancel_event.is_set():
                        log.warning("%s cancelled mid-download", chunk)
                        return
                    buf = resp.read(CHUNK_READ_SIZE) # what you hae to write
                    if not buf: #if emtpy - end loop
                        break
                    if offset > chunk.end: # validity of chunk
                        raise ValueError(f"{chunk}: server sent too much data")
                    remaining = chunk.end - offset + 1
                    buf = buf[:remaining]

                    written = os.pwrite(out_fd, buf, offset)
                    if written != len(buf):
                        raise OSError(f"Short write: {written}/{len(buf)} bytes")
                    offset += written
                    bytes_written += written
                    with state.lock:
                        state.progress[chunk.index] += written

                # verify completeness
                if bytes_written != chunk.length:
                    raise ValueError(
                        f"{chunk}: received {bytes_written}, expected {chunk.length}"
                    )

            log.info("Done  %s", chunk)
            return  # success — exit retry loop

        except Exception as exc:
            log.warning("%s attempt %d/%d failed: %s", chunk, attempt, retries, exc)
            with state.lock:
                state.errors.setdefault(chunk.index, []).append(exc)  # fix 18: append
            if attempt == retries:
                state.cancel_event.set()  # signal siblings to stop
                return
            time.sleep(min(2**attempt, 30))


def _validate_content_range(header: str, chunk: ChunkSpec) -> None:
    """Parse Content-Range and assert it matches our request.  [fix 2]"""
    if not header:
        # Some CDNs omit this even on 206 — tolerate but warn.
        log.debug("No Content-Range header in 206 response for %s", chunk)
        return
    m = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", header.strip(), re.I)
    if not m:
        raise ValueError(f"Malformed Content-Range header: '{header}'")
    resp_start, resp_end = int(m.group(1)), int(m.group(2))
    if resp_start != chunk.start or resp_end != chunk.end:
        raise ValueError(
            f"Content-Range mismatch for {chunk}: "
            f"server returned bytes {resp_start}-{resp_end}"
        )


def _worker_single(
    url: str,
    out_path: Path,
    state: SharedState,
    retries: int,
) -> None:
    """
    Plain GET with no Range header.
    Used when the server does not advertise Accept-Ranges: bytes. This is a completely separate code path — the Range header is never sent, so there is no risk of offset-based corruption.
    """
    for attempt in range(1, retries + 1):
        if state.cancel_event.is_set():
            return
        try:
            with (
                urlopen(_make_request(url), timeout=READ_TIMEOUT) as resp,
                open(out_path, "wb") as fh,
            ):
                if resp.status != 200:
                    # raise HTTPError(url, resp.status, "Non-200 on plain GET", {}, None)
                    raise RuntimeError(f"Expected 200, got {resp.status}")
                while True:
                    buf = resp.read(CHUNK_READ_SIZE)
                    if not buf:
                        break
                    fh.write(buf)
                    with state.lock:
                        state.progress[0] = state.progress.get(0, 0) + len(buf)
            log.info("Single-thread download complete")
            return
        except Exception as exc:
            log.warning("Single-thread attempt %d/%d: %s", attempt, retries, exc)
            with state.lock:
                state.errors.setdefault(0, []).append(exc)
            if attempt == retries:
                state.cancel_event.set()
                return
            time.sleep(min(2**attempt, 30))


# def download_chunk(
#     url: str,
#     chunk: ChunkSpec,
#     out_path: Path,
#     state: SharedState,
#     retries: int = 3,
#     timeout: int = 30,
# ) -> None:
#     """
#     Download one byte range and write it directly into the pre-allocated
#     output file at the correct offset (seek-based, no temp files).

#     OS concepts exercised:
#         - File seek + partial write  (pwrite semantics via seek+write under lock)
#         - Lock acquisition for shared progress counter
#         - Event check for cooperative cancellation
#     """
#     log.info("Starting %s", chunk)

#     for attempt in range(1, retries + 1):

#         # Cooperative cancellation check
#         if state.cancel_event.is_set():
#             log.warning("%s cancelled before attempt %d", chunk, attempt)
#             return

#         # Reset progress on retry so the monitor doesn't double-count
#         with state.lock:
#             state.progress[chunk.index] = 0

#         try:
#             req = _make_request(url, Range=f"bytes={chunk.start}-{chunk.end}")

#             with urlopen(req, timeout=timeout) as resp:
#                 # if resp.status not in (200, 206):
#                 if resp.status != 206:
#                     # raise HTTPError(url, resp.status, "Unexpected status", {}, None)
#                     raise RuntimeError(f"{chunk}: expected 206, got {resp.status}")
#                 cr = resp.headers.get("Content-Range")
#                 if cr:
#                     try:
#                         rng = cr.split()[1].split("/")[0]
#                         start, end = map(int, rng.split("-"))
#                         if start != chunk.start or end != chunk.end:
#                             raise ValueError(f"{chunk}: Content-Range mismatch")
#                     except Exception:
#                         raise ValueError(f"{chunk}: invalid Content-Range header")
#                 # Open the shared output file for writing at the correct offset.
#                 # Each thread writes to a disjoint region so no lock is needed
#                 # for the write itself — but we do lock the progress counter.
#                 with open(out_path, "r+b") as fh:
#                     fh.seek(chunk.start)
#                     bytes_written = 0

#                     while True:
#                         if state.cancel_event.is_set():
#                             log.warning("%s cancelled mid-download", chunk)
#                             return

#                         buf = resp.read(CHUNK_READ_SIZE)
#                         if not buf:
#                             break

#                         fh.write(buf)
#                         bytes_written += len(buf)

#                         # Update shared progress counter (protected by lock)
#                         with state.lock:
#                             state.progress[chunk.index] = state.progress.get(
#                                 chunk.index, 0
#                             ) + len(buf)

#                     if bytes_written != chunk.length:
#                         raise ValueError(
#                             f"{chunk}: wrote {bytes_written}, expected {chunk.length}"
#                         )

#             log.info("Finished %s (%d B written)", chunk, bytes_written)
#             return  # success

#         except (HTTPError, URLError, OSError, TimeoutError) as exc:
#             log.warning("%s attempt %d/%d failed: %s", chunk, attempt, retries, exc)
#             if attempt == retries:
#                 with state.lock:
#                     state.errors[chunk.index] = exc
#                 state.cancel_event.set()  # signal other threads to stop
#                 return
#             time.sleep(2**attempt)  # exponential back-off
