import hashlib
from pathlib import Path
from typing import Optional
import logging

log = logging.getLogger(__name__)


def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        while buf := fh.read(1 << 20):
            h.update(buf)
    return h.hexdigest()


def _hash_file(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as fh:
        while buf := fh.read(1 << 20):
            h.update(buf)
    return h.hexdigest()


def _verify_integrity(
    dest: Path,
    verify_md5: Optional[str],
    verify_sha256: Optional[str],
) -> None:
    if verify_md5:
        digest = _hash_file(dest, "md5")
        if digest != verify_md5:
            dest.unlink(missing_ok=True)
            raise ValueError(f"MD5 mismatch: expected {verify_md5}, got {digest}")
        log.info("MD5 OK (%s)", digest)
    if verify_sha256:
        digest = _hash_file(dest, "sha256")
        if digest != verify_sha256:
            dest.unlink(missing_ok=True)
            raise ValueError(
                f"SHA-256 mismatch: expected {verify_sha256}, got {digest}"
            )
        log.info("SHA-256 OK (%s)", digest)
