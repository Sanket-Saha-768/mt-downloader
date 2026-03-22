from urllib.request import urlopen, Request
USER_AGENT = "chunked-downloader/1.0"

def probe_server(url: str, timeout: int = 15) -> tuple[int, bool]:
    """
    Send a HEAD request.
    Returns (content_length, supports_ranges).
    Raises RuntimeError if the server won't cooperate.
    """
    req = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        headers = resp.headers
        content_len = int(headers.get("Content-Length", 0))
        accept_ranges = headers.get("Accept-Ranges", "none").lower() == "bytes"
    return content_len, accept_ranges
