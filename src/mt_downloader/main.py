"""
Multi-threaded chunked file downloader
======================================
OS course project — demonstrates:
    - Thread creation and lifecycle management
    - Shared state with Locks (progress counters)
    - Thread synchronization with Barrier (assemble only after all chunks done)
    - Inter-thread signalling with Event (cancellation)
    - Seek-based in-place file assembly (no extra temp files needed)
    - Range requests (HTTP/1.1 Accept-Ranges: bytes)

Usage:
    uv run mt-downloader  <url> [--threads N] [--out filename]

Example:
    uv run mt-downloader https://speed.hetzner.de/100MB.bin --threads 8
"""

import logging, argparse, sys
from mt_downloader.core import download
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)-16s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
MAX_THREADS = 64

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-threaded chunked file downloader"
    )
    parser.add_argument("url", help="URL to download")
    parser.add_argument(
        "--threads",
        "-t",
        type=int,
        default=4,
        help=f"Parallel threads 1-{MAX_THREADS} (default: 4)",
    )
    parser.add_argument(
        "--out", "-o", default=None, help="Output filename (default: inferred from URL)"
    )
    parser.add_argument(
        "--retries",
        "-r",
        type=int,
        default=3,
        help="Per-chunk retry attempts (default: 3)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Socket timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--md5", default=None, help="Expected MD5 digest for integrity verification"
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--sha256", default=None, help="Expected SHA-256 hex digest")

    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not (1 <= args.threads <= MAX_THREADS):
        parser.error(f"--threads must be between 1 and {MAX_THREADS}")
    try:
        path = download(
            url=args.url,
            out_path=args.out,
            n_threads=args.threads,
            retries=args.retries,
            verify_md5=args.md5,
            verify_sha256=args.sha256
        )
        print(f"\nSaved to: {path}")
    except (RuntimeError, ValueError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()