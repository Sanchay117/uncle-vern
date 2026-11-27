"""Tiny JSON-over-HTTPS helper (stdlib only)."""
import json
import time
import urllib.error
import urllib.request


class HttpError(Exception):
    def __init__(self, status, body, url):
        super().__init__(f"HTTP {status} from {url}: {body[:300]}")
        self.status = status
        self.body = body
        self.url = url


RETRY_STATUS = {429, 500, 502, 503, 504, 529}


def request(method, url, body=None, headers=None, timeout=60, retries=2):
    """Send a request. Returns parsed JSON, raw bytes for non-JSON, or {} when empty."""
    hdrs = {"Accept": "application/json", "User-Agent": "uncle-vern/1.0"}
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if not raw:
                    return {}
                ctype = r.headers.get("Content-Type", "")
                if "json" in ctype or raw[:1] in (b"{", b"["):
                    return json.loads(raw)
                return raw
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            last = HttpError(e.code, text, url)
            if e.code in RETRY_STATUS and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last from None
        except urllib.error.URLError as e:
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last
