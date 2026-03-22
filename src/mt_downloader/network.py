from urllib.request import urlopen, Request
USER_AGENT = "chunked-downloader/1.0"

def probe_server(url: str, timeout: int = 15) -> tuple[int, bool]:
    """
    Send a HEAD request.
    Returns (content_length, supports_ranges).
    Raises RuntimeError if the server won't cooperate.
    """
    total_size = 0
    supports_range = False

    # ── Step 1: HEAD ─────────────────────────────────────
    try:
        req = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=timeout) as resp:
            headers = resp.headers
            cl = headers.get("Content-Length")
            ar = headers.get("Accept-Ranges", "").lower()

            if cl and cl.isdigit():
                total_size = int(cl)

            if ar == "bytes":
                supports_range = True

    except Exception:
        pass  # fallback below

    # ── Step 2: Fallback if needed ────────────────────────
    if total_size == 0 or not supports_range:
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Range": "bytes=0-0",
            },
        )
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 206:
                raise RuntimeError("Server does not support range requests")

            cr = resp.headers.get("Content-Range")
            if not cr or "/" not in cr:
                raise RuntimeError("Invalid Content-Range header")

            total_size = int(cr.split("/")[-1])
            supports_range = True

    if total_size == 0:
        raise RuntimeError("Could not determine file size")

    return total_size, supports_range
