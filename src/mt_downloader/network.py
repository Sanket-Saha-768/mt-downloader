from urllib.request import urlopen, Request
from .state import ServerInfo
import logging
import re
from urllib.parse import urlparse
from pathlib import Path
from typing import Optional
import mimetypes

log = logging.getLogger(__name__)
USER_AGENT = "chunked-downloader/1.0"
CONNECT_TIMEOUT = 15  # seconds for initial TCP connect


def _make_request(url: str, **extra_headers: str) -> Request:
    return Request(url, headers={"User-Agent": USER_AGENT, **extra_headers})


def _filename_from_url(url: str) -> str:
    name = Path(urlparse(url).path).name
    return name if name else "download"


def _filename_from_content_disposition(header: str) -> Optional[str]:
    m = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', header, re.I)
    return m.group(1).strip().strip("\"'") if m else None


def _resolve_filename(url: str, content_disposition: str, content_type: str) -> str:
    # Content-Disposition header
    if content_disposition:
        name = _filename_from_content_disposition(content_disposition)
        if name:
            return name

    # URL path — only if it looks like a real filename (has an extension)
    base = _filename_from_url(url)

    # URL path with no extension — try to append one from Content-Type
    if content_type:
        mime = content_type.split(";")[0].strip()
        # Skip useless types — octet-stream and html tell us nothing meaningful
        if mime not in ("application/octet-stream", "text/html", ""):
            ext = mimetypes.guess_extension(mime)
            if ext:
                return base + ext

    # proxy name, no extension — at least the bytes are correct
    return base


def probe_server(url: str, timeout: int = 15) -> ServerInfo:
    """
    Determine file size and range support via a two-step probe.
    Step 1: HEAD request.
        - If Content-Length and Accept-Ranges: bytes are both present, done.
    Step 2: Range probe  GET bytes=0-0
        - Sent when HEAD fails or is missing Content-Length.
        - A 206 response with Content-Range: bytes 0-0/TOTAL gives us the size
        AND confirms range support in one round trip.
    """
    total_size = 0
    supports_range = False
    filename = _filename_from_url(url)

    # ── Step 1: HEAD ─────────────────────────────────────
    try:
        req = _make_request(url)
        req.method = "HEAD"
        with urlopen(req, timeout=CONNECT_TIMEOUT) as r:
            hdrs = r.headers
            cl = hdrs.get("Content-Length", "").strip()
            ar = hdrs.get("Accept-Ranges", "none").strip().lower()
            cd = hdrs.get("Content-Disposition", "")
            ct = hdrs.get("Content-Type", "")
            if cl.isdigit():
                total_size = int(cl)
            if ar == "bytes":
                supports_range = True
            filename = _resolve_filename(url, cd, ct)

    except Exception as exc:
        log.debug("HEAD failed (%s); trying range probe", exc)
        # fallback handled in step 2

    # ── Step 2: Range probe if HEAD was insufficient

    if total_size == 0 or not supports_range:
        try:
            req = _make_request(url, Range="bytes=0-0")
            with urlopen(req, timeout=CONNECT_TIMEOUT) as r:

                if r.status == 206:
                    cr = r.headers.get("Content-Range", "")
                    m = re.match(r"bytes\s+\d+-\d+/(\d+)", cr)
                    if m:
                        total_size = int(m.group(1))
                        supports_range = True
                        log.debug("Range probe ok: size=%d", total_size)
        except Exception as exc:
            log.debug("Range probe failed: %s", exc)

    if total_size == 0:
        raise RuntimeError(
            "Cannot determine file size. The server may require "
            "authentication or not support HEAD/Range requests."
        )

    return ServerInfo(
        url=url,
        total_size=total_size,
        supports_range=supports_range,
        filename=filename,
    )
