import math
from mt_downloader.state import ChunkSpec

def make_chunks(total_bytes: int, n_threads: int) -> list[ChunkSpec]:
    """
    Split [0, total_bytes) into n_threads non-overlapping, contiguous ranges.
    The last chunk absorbs any remainder from integer division.
    """
    if total_bytes <= 0:
        raise ValueError(f"total_bytes must be > 0, got {total_bytes}")
    if n_threads <= 0:
        raise ValueError(f"n_threads must be >= 1, got {n_threads}")
    chunk_size = math.ceil(total_bytes / n_threads)
    chunks: list[ChunkSpec] = []
    for i in range(n_threads):
        start = i * chunk_size
        if start >= total_bytes:
            break
        end = min(start + chunk_size - 1, total_bytes - 1)
        chunks.append(ChunkSpec(index=i, start=start, end=end))
    return chunks

def assert_no_overlap(chunks: list[ChunkSpec], total_bytes: int) -> None:
    """
    Verify the chunk list is non-overlapping, contiguous, and covers [0, total).
    AssertionError here means a logic bug in make_chunks — catch it early.  [fix 7]
    """
    assert chunks,                          "Chunk list is empty"
    assert chunks[0].start == 0,           f"First chunk must start at 0, got {chunks[0].start}"
    assert chunks[-1].end == total_bytes - 1, \
        f"Last chunk must end at {total_bytes-1}, got {chunks[-1].end}"
    for a, b in zip(chunks, chunks[1:]):
        assert a.end + 1 == b.start, \
            f"Gap or overlap between {a} and {b}"
    assert sum(c.length for c in chunks) == total_bytes, \
        "Chunk lengths do not sum to total_bytes"
