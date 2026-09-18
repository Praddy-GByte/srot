# -*- coding: utf-8 -*-
"""HTTP helpers built on QgsBlockingNetworkRequest.

We deliberately avoid ``requests`` / ``urllib``:

* plugins.qgis.org asks plugins to use the QGIS network stack so that the
  user's proxy and authentication settings are honoured;
* it keeps the plugin dependency-free, which is the single biggest install
  problem every competing AI plugin has.

``QgsBlockingNetworkRequest`` is documented as thread safe, so every function
here is safe to call from inside a ``QgsTask.run()``.  None of them may be
called on the GUI thread for anything slow.
"""

import contextlib
import json
import time

from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager

from . import log
from .compat import ATTR_HTTP_STATUS, REQUEST_NO_ERROR

USER_AGENT = "Srot/0.1 (QGIS plugin; +https://github.com/Praddy-GByte/srot)"

#: Bodies larger than this are refused outright rather than blowing up memory
#: inside QGIS.  Bhuvan GetCapabilities alone is ~10 MB, so the ceiling is
#: generous but finite.
MAX_BODY_BYTES = 64 * 1024 * 1024

#: Public geodata services are shared infrastructure and answer intermittently:
#: a national portal drops a connection under load, a free Overpass mirror
#: returns 504, an API throttles a burst. Retrying with a widening pause turns
#: nearly all of these into a slightly slower success.
RETRY_STATUSES = (408, 425, 429, 500, 502, 503, 504)
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (1.5, 4.0)


def _should_retry(exc):
    if not isinstance(exc, HttpError):
        return False
    if exc.status is None:
        return True  # connection dropped before any reply
    return exc.status in RETRY_STATUSES


@contextlib.contextmanager
def extended_timeout(milliseconds):
    """Temporarily raise the QGIS network timeout, then put it back.

    QGIS times connections out at 60 seconds by default, which is fine for an
    API but not for Overpass: a city-sized query regularly takes longer, and
    the request dies at 59.9 s with a confusing "server closed the connection"
    rather than a server error. This raises the ceiling for one call only, so
    the user's own setting is left exactly as it was.
    """
    manager = QgsNetworkAccessManager.instance()
    previous = None
    try:
        previous = manager.timeout()
        if milliseconds > previous:
            manager.setTimeout(int(milliseconds))
    except Exception:
        previous = None
    try:
        yield
    finally:
        if previous is not None:
            try:
                manager.setTimeout(previous)
            except Exception as exc:
                log.ignored("Restoring the network timeout", exc)


class HttpError(Exception):
    """Raised for transport failures and non-2xx responses."""

    def __init__(self, message, status=None, body=None, url=None):
        super().__init__(message)
        self.status = status
        self.body = body
        self.url = url


class Response:
    """A tiny, provider-agnostic response object."""

    __slots__ = ("status", "content", "url")

    def __init__(self, status, content, url):
        self.status = status
        self.content = content  # bytes
        self.url = url

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        try:
            return json.loads(self.text)
        except ValueError as exc:
            snippet = self.text[:300]
            raise HttpError(
                "Response was not valid JSON: {0}\nFirst 300 chars: {1}".format(exc, snippet),
                status=self.status,
                body=self.text,
                url=self.url,
            )


def _build_request(url, headers=None):
    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(b"User-Agent", USER_AGENT.encode("utf-8"))
    request.setRawHeader(b"Accept-Encoding", b"identity")
    for key, value in (headers or {}).items():
        if value is None:
            continue
        request.setRawHeader(
            key.encode("utf-8"), str(value).encode("utf-8")
        )
    return request


def _finish(blocking, url, error_code):
    # QgsBlockingNetworkRequest reports ServerExceptionError for any HTTP error
    # status, but it still populates the reply. Reading the reply first is what
    # preserves the status code and the error body -- and those are exactly what
    # tells a user that their API key is wrong or that they have been rate
    # limited, rather than a generic Qt transport message.
    reply = blocking.reply()
    status = reply.attribute(ATTR_HTTP_STATUS) if reply is not None else None

    if status is None:
        # No HTTP response at all: DNS failure, TLS failure, timeout, abort.
        if error_code != REQUEST_NO_ERROR:
            raise HttpError(
                blocking.errorMessage() or "Network request failed", url=url
            )
        raise HttpError("The server closed the connection without replying", url=url)

    raw = reply.content()
    if raw.size() > MAX_BODY_BYTES:
        raise HttpError(
            "Response is {0} bytes, larger than the {1} byte limit".format(
                raw.size(), MAX_BODY_BYTES
            ),
            status=status,
            url=url,
        )
    body = bytes(raw)

    if not (200 <= int(status) < 300):
        raise HttpError(
            "HTTP {0} from {1}".format(status, url),
            status=int(status),
            body=body.decode("utf-8", errors="replace")[:2000],
            url=url,
        )
    return Response(int(status), body, url)


def _with_retries(operation, attempts=MAX_ATTEMPTS):
    """Run a request, retrying the failures that are worth retrying."""
    last = None
    for attempt in range(attempts):
        try:
            return operation()
        except HttpError as exc:
            last = exc
            if attempt == attempts - 1 or not _should_retry(exc):
                raise
            time.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
    raise last


def get(url, headers=None, feedback=None, authcfg=None, attempts=MAX_ATTEMPTS):
    """Perform a blocking GET.  Must not be called on the GUI thread."""

    def once():
        blocking = QgsBlockingNetworkRequest()
        if authcfg:
            blocking.setAuthCfg(authcfg)
        request = _build_request(url, headers)
        code = blocking.get(request, False, feedback)
        return _finish(blocking, url, code)

    return _with_retries(once, attempts)


def post(url, data, headers=None, feedback=None, authcfg=None, attempts=MAX_ATTEMPTS):
    """Perform a blocking POST.  ``data`` may be bytes or str."""
    payload = data.encode("utf-8") if isinstance(data, str) else data

    def once():
        blocking = QgsBlockingNetworkRequest()
        if authcfg:
            blocking.setAuthCfg(authcfg)
        request = _build_request(url, headers)
        code = blocking.post(request, QByteArray(payload), False, feedback)
        return _finish(blocking, url, code)

    return _with_retries(once, attempts)


def post_json(url, payload, headers=None, feedback=None, authcfg=None):
    """POST a JSON document and decode the JSON response."""
    merged = {"Content-Type": "application/json", "Accept": "application/json"}
    merged.update(headers or {})
    body = json.dumps(payload).encode("utf-8")
    return post(url, body, merged, feedback=feedback, authcfg=authcfg).json()


def post_form(url, fields, headers=None, feedback=None):
    """POST ``application/x-www-form-urlencoded`` fields."""
    from urllib.parse import urlencode

    merged = {"Content-Type": "application/x-www-form-urlencoded"}
    merged.update(headers or {})
    return post(url, urlencode(fields), merged, feedback=feedback)


def get_json(url, headers=None, feedback=None, authcfg=None):
    merged = {"Accept": "application/json"}
    merged.update(headers or {})
    return get(url, merged, feedback=feedback, authcfg=authcfg).json()


def download_to(url, destination, feedback=None, headers=None):
    """Download ``url`` and write it to ``destination``.  Returns the path."""
    response = get(url, headers=headers, feedback=feedback)
    with open(destination, "wb") as handle:
        handle.write(response.content)
    return destination
