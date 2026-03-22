import math
from mt_downloader.state import ChunkSpec

def make_chunks(total_bytes: int, n_threads: int) -> list[ChunkSpec]:
    """
    Split [0, total_bytes) into n_threads non-overlapping, contiguous ranges.
    The last chunk absorbs any remainder from integer division.
    """
    chunk_size = math.ceil(total_bytes / n_threads)
    chunks = []
    for i in range(n_threads):
        start = i * chunk_size
        end = min(start + chunk_size - 1, total_bytes - 1)
        if start > total_bytes - 1:
            break
        chunks.append(ChunkSpec(index=i, start=start, end=end))
    return chunks
