from dataclasses import dataclass, field
import threading

@dataclass
class ChunkSpec:
    index: int  # chunk number (0-based)
    start: int  # first byte (inclusive)
    end: int  # last byte  (inclusive)

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    def __str__(self):
        return f"chunk[{self.index}] bytes {self.start}-{self.end} ({self.length:,} B)"


@dataclass
class SharedState:
    """
    All mutable state shared across threads.
    Every field that can be written by > 1 thread is protected by `lock`.
    """

    lock: threading.Lock = field(default_factory=threading.Lock)
    cancel_event: threading.Event = field(default_factory=threading.Event)

    # per-chunk bytes downloaded so far (index -> int)
    progress: dict[int, int] = field(default_factory=dict)
    errors: dict[int, list[Exception]] = field(default_factory=dict)  
    total_size: int = 0


@dataclass
class ServerInfo:
    url:            str
    total_size:     int
    supports_range: bool
    filename:       str