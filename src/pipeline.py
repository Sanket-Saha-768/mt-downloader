"""
Reads a list of URLs from a JSON file (download_links.json located at the
project root) and runs `uv run mt-downloader <url> -t <threads>` for each
one, sequentially, so that progress output stays readable.

Usage (from the project root):
    uv run python src/pipeline.py                  # default 4 threads
    uv run python src/pipeline.py -t 8             # custom thread count
    uv run python src/pipeline.py --links my.json  # custom links file
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_links(links_file: Path) -> list[str]:
    """Parse the JSON links file and return a flat list of URLs."""
    with links_file.open() as f:
        data = json.load(f)

    # Accept either {"downloads": [...]} or a bare list at the top level.
    if isinstance(data, list):
        urls = data
    elif isinstance(data, dict):
        # Look for any key whose value is a list; fall back to all string values.
        list_values = [v for v in data.values() if isinstance(v, list)]
        if list_values:
            urls = list_values[0]
        else:
            urls = [v for v in data.values() if isinstance(v, str)]
    else:
        raise ValueError(f"Unexpected JSON structure in {links_file}")

    if not urls:
        raise ValueError(f"No URLs found in {links_file}")

    return urls


def run_download(url: str, threads: int) -> bool:
    """
    Run `uv run mt-downloader <url> -t <threads>` as a subprocess.

    Returns True on success, False on failure.
    """
    cmd = ["uv", "run", "mt-downloader", url, "-t", str(threads)]
    print(f"\n{'='*60}")
    print(f"Downloading : {url}")
    print(f"Threads     : {threads}")
    print(f"Command     : {' '.join(cmd)}")
    print(f"{'='*60}")

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print(f"✔  Done: {url}")
        return True
    else:
        print(f"✘  Failed (exit {result.returncode}): {url}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Locate the project root (two levels up from src/pipeline.py).
    project_root = Path(__file__).resolve().parent.parent
    default_links = project_root / "download_links.json"

    parser = argparse.ArgumentParser(
        description="Batch-download files using mt-downloader with multiple threads.",
    )
    parser.add_argument(
        "--links",
        type=Path,
        default=default_links,
        metavar="FILE",
        help=f"Path to the JSON links file (default: {default_links})",
    )
    parser.add_argument(
        "-t", "--threads",
        type=int,
        default=4,
        metavar="N",
        help="Number of download threads per file (default: 4)",
    )
    args = parser.parse_args()

    # Load URLs.
    try:
        urls = load_links(args.links)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error reading links file: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"PIPELINE starting — {len(urls)} file(s) to download, {args.threads} thread(s) each.\n")

    # Run downloads one at a time so output stays clean.
    results: list[tuple[str, bool]] = []
    for url in urls:
        ok = run_download(url, args.threads)
        results.append((url, ok))

    # Summary.
    print(f"\n{'='*60}")
    print("PIPELINE SUMMARY")
    print(f"{'='*60}")
    succeeded = sum(1 for _, ok in results if ok)
    failed    = len(results) - succeeded
    for url, ok in results:
        status = "✔ OK  " if ok else "✘ FAIL"
        print(f"  {status}  {url}")
    print(f"\nTotal: {len(results)}  |  Succeeded: {succeeded}  |  Failed: {failed}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
