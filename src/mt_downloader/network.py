from urllib.request import urlopen, Request
from .state import ServerInfo
import logging
import re
from urllib.parse import urlparse
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
USER_AGENT = "chunked-downloader/1.0"
CONNECT_TIMEOUT = 15  # seconds for initial TCP connect


def _make_request(url: str, **extra_headers: str) -> Request:
    return Request(url, headers={"User-Agent": USER_AGENT, **extra_headers})

def _filename_from_url(url: str) -> str:
    name = Path(urlparse(url).path).name
    return name if name else "download"          # fix 16
 
 
def _filename_from_content_disposition(header: str) -> Optional[str]:
    # RFC 6266: Content-Disposition: attachment; filename="foo.bin"
    m = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', header, re.I)
    return m.group(1).strip().strip('"\'') if m else None

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
    filename       = _filename_from_url(url)

    # ── Step 1: HEAD ─────────────────────────────────────
    try:
        req = _make_request(url)
        req.method = "HEAD"
        # with urlopen(req, timeout=timeout) as resp:
        #     headers = resp.headers
        #     cl = headers.get("Content-Length")
        #     ar = headers.get("Accept-Ranges", "").lower()

        #     if cl and cl.isdigit():
        #         total_size = int(cl)

        #     if ar == "bytes":
        #         supports_range = True
        with urlopen(req, timeout=CONNECT_TIMEOUT) as r:
            hdrs = r.headers
            cl = hdrs.get("Content-Length", "").strip()
            ar = hdrs.get("Accept-Ranges", "none").strip().lower()
            cd = hdrs.get("Content-Disposition", "")
            if cl.isdigit():
                total_size = int(cl)
            if ar == "bytes":
                supports_range = True
            if cd:
                filename = _filename_from_content_disposition(cd) or filename

    except Exception as exc:
        log.debug("HEAD failed (%s); trying range probe", exc)
        pass  # fallback below

    # ── Step 2: Range probe if HEAD was insufficient

    if total_size == 0 or not supports_range:
        try: 
            req = _make_request(url, Range="bytes=0-0")
            with urlopen(req, timeout=CONNECT_TIMEOUT) as r:
                # if resp.status != 206:
                #     raise RuntimeError("Server does not support range requests")

                # cr = resp.headers.get("Content-Range")
                # if not cr or "/" not in cr:
                #     raise RuntimeError("Invalid Content-Range header")

                # total_size = int(cr.split("/")[-1])
                # supports_range = True
                if r.status == 206:
                    cr = r.headers.get("Content-Range", "")
                    m  = re.match(r"bytes\s+\d+-\d+/(\d+)", cr)
                    if m:
                        total_size     = int(m.group(1))
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
