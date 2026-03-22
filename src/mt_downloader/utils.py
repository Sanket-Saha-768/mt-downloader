import hashlib
from pathlib import Path


def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while buf := fh.read(1 << 20):
            h.update(buf)
    return h.hexdigest()
