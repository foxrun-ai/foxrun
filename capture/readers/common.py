"""Reader contract, public HTTP reads, tool calls, and request pacing."""
from __future__ import annotations

import contextlib
import email.utils
import fcntl
import hashlib
from http import client as http_client
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit
from urllib.request import (HTTPHandler, HTTPRedirectHandler, HTTPSHandler, ProxyHandler,
                            Request, build_opener)

READERS = {"x": "fxtwitter", "instagram": "instaloader", "youtube": "yt-dlp",
           "github": "gh", "reddit": "reddit-api", "web": "defuddle", "pdf": "direct"}
INTERVALS = {"x": 1.0, "reddit": 2.0, "instagram": 10.0}
UA = "capture-read/1.0 (public source reader)"
MAX_BYTES = 250 * 1024 * 1024


class ReaderError(Exception):
    def __init__(self, message, status="error"):
        super().__init__(message)
        self.status = status


def source_for(url):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "web"
    host = (parsed.hostname or "").lower().removeprefix("www.")
    for domain, source in (("x.com", "x"), ("twitter.com", "x"),
                           ("instagram.com", "instagram"), ("youtube.com", "youtube"),
                           ("youtu.be", "youtube"), ("github.com", "github"),
                           ("reddit.com", "reddit")):
        if host == domain or host.endswith("." + domain):
            return source
    return "pdf" if parsed.path.lower().endswith(".pdf") else "web"


REDACTED = "[REDACTED]"
# Query or fragment keys that carry a credential. Keys are compared after camelCase splitting.
SECRET_PART = re.compile(
    r"(?:^|[_.-])(?:token|key|apikey|secret|password|passwd|auth|authorization|signature|"
    r"credential|credentials|session|sessionid|jwt|bearer|hmac)(?:$|[_.-])|^x-(?:amz|goog)-")
SECRET_WHOLE = {"code", "sig", "sid", "pwd", "pass", "otp"}
LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
# NAT64 prefixes carry an IPv4 address in their last 32 bits.
NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
MEDIA_MARKER = ".capture-read"


def _secret_key(key):
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", unquote_plus(key)).lower()
    return key in SECRET_WHOLE or bool(SECRET_PART.search(key))


def _redact_pairs(text):
    pieces = []
    for piece in text.split("&"):
        key, sep, value = piece.partition("=")
        pieces.append(key + "=" + REDACTED if sep and value and _secret_key(key) else piece)
    return "&".join(pieces)


def redact_url(url):
    """Return the URL with userinfo and credential-like query values replaced by [REDACTED]."""
    if not isinstance(url, str):
        return url
    try:
        p = urlsplit(url)
    except ValueError:
        p = None
    if p is None or not p.scheme:
        url = re.sub(r"(//)[^/?#\s]*@", r"\1" + REDACTED + "@", url)
        return re.sub(r"([?&#])([^=&#\s]+)=([^&#\s]+)",
                      lambda m: m[1] + m[2] + "=" + (REDACTED if _secret_key(m[2]) else m[3]), url)
    netloc = p.netloc
    if "@" in netloc:
        netloc = REDACTED + "@" + netloc.rpartition("@")[2]
    fragment = _redact_pairs(p.fragment) if "=" in p.fragment else p.fragment
    return urlunsplit((p.scheme, netloc, p.path, _redact_pairs(p.query), fragment))


def carries_secret(url):
    """True when the URL still holds userinfo or a credential-like query or fragment value."""
    try:
        p = urlsplit(url)
    except ValueError:
        return True
    if "@" in p.netloc and p.netloc.rpartition("@")[0] != REDACTED:
        return True
    for text in (p.query, p.fragment):
        for piece in text.split("&"):
            key, sep, value = piece.partition("=")
            if sep and value and value != REDACTED and _secret_key(key):
                return True
    return False


def redact_text(text):
    """Redact every URL inside free text, such as an error message."""
    if not isinstance(text, str):
        return text
    return re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+", lambda m: redact_url(m[0]), text)


def redact_result(result):
    """Apply URL redaction to every URL field the reader prints."""
    for key in ("url", "canonical_url"):
        result[key] = redact_url(result.get(key))
    for item in result.get("media") or []:
        if isinstance(item, dict):
            item["url"] = redact_url(item.get("url"))
    result["error"] = redact_text(result.get("error"))
    return result


def literal_address(host):
    """Parse an IP literal, including decimal, octal, and hex IPv4 spellings."""
    try:
        return ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        pass
    if re.fullmatch(r"[0-9a-fA-FxX.]+", host) and re.search(r"[0-9]", host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except (OSError, ValueError):
            return None
    return None


def blocked_address(address):
    """True for any address that is not a public unicast destination."""
    candidates = [address]
    if address.version == 6:
        if address.ipv4_mapped:
            candidates.append(address.ipv4_mapped)
        if address.sixtofour:
            candidates.append(address.sixtofour)
        if any(address in network for network in NAT64):
            candidates.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
            if address in NAT64[1]:
                return True
    for item in candidates:
        if (not item.is_global or item.is_private or item.is_loopback or item.is_link_local
                or item.is_multicast or item.is_reserved or item.is_unspecified
                or (item.version == 6 and item.is_site_local)):
            return True
    return False


def resolve_public(host, port):
    """Resolve the host and return its addresses; refuse if any one is not public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise ReaderError("The URL host did not resolve.")
    addresses = []
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if blocked_address(address):
            raise ReaderError("Private and local network addresses are unsupported.", "unsupported")
        if str(address) not in addresses:
            addresses.append(str(address))
    if not addresses:
        raise ReaderError("The URL host did not resolve.")
    return addresses


def checked_destination(url, *, resolve=True):
    """Check one URL. Return (host, port, addresses); addresses is None without resolve."""
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        raise ReaderError("A public HTTP or HTTPS URL is required.", "unsupported")
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or "@" in p.netloc:
        raise ReaderError("A public HTTP or HTTPS URL is required.", "unsupported")
    host = p.hostname.lower()
    port = port or (443 if p.scheme == "https" else 80)
    name = host.rstrip(".")
    # Reject local URLs. This reader has no reason to access machine or private-network services.
    if not name or name in LOCAL_NAMES or name.endswith(".localhost"):
        raise ReaderError("Local URLs are unsupported.", "unsupported")
    literal = literal_address(name)
    if literal is None and re.fullmatch(r"[0-9.]+", name):
        raise ReaderError("A public HTTP or HTTPS URL is required.", "unsupported")
    if literal is not None and blocked_address(literal):
        raise ReaderError("Private and local network addresses are unsupported.", "unsupported")
    # Decimal, octal, hex, and short IPv4 spellings parse differently across resolvers.
    if literal is not None and literal.version == 4 and str(literal) != name:
        raise ReaderError("Write an IPv4 address as four plain decimal numbers.", "unsupported")
    if not resolve:
        return host, port, None
    return host, port, [str(literal)] if literal is not None else resolve_public(host, port)


def public_url(url):
    """Refuse a URL unless every address its host resolves to is public."""
    checked_destination(url)
    return url


def canonicalize(url):
    # Shape and literal-address check only; the fetch resolves and checks the host.
    checked_destination(url, resolve=False)
    p = urlsplit(url)
    source = source_for(url)
    host = p.netloc.lower()
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in
             {"fbclid", "gclid", "dclid", "twclid", "igsh", "igshid", "stkn",
              "si", "feature", "g_st", "mc_cid", "mc_eid"}]
    path = p.path or "/"
    if source == "x":
        host = "x.com"
        query = []
        path = re.sub(r"/(?:photo|video)/\d+/?$", "", path).rstrip("/")
    elif source == "instagram":
        host = "www.instagram.com"
        query = []
        path = path.rstrip("/") + "/"
    elif source == "youtube":
        video_id = None
        if (p.hostname or "").removeprefix("www.") == "youtu.be":
            video_id = path.strip("/").split("/")[0]
        elif path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = path.split("/")[2]
        elif path == "/watch":
            video_id = dict(query).get("v")
        if video_id:
            host, path, query = "www.youtube.com", "/watch", [("v", video_id)]
    elif source == "github":
        host, query, path = "github.com", [], path.rstrip("/")
    elif source == "reddit":
        host = "www.reddit.com"
        path = re.sub(r"\.json$", "", path).rstrip("/") + "/"
        query = [(k, v) for k, v in query if k not in {"share_id", "share", "context"}]
    return urlunsplit(("https" if source != "web" and source != "pdf" else p.scheme,
                       host, path, urlencode(query), ""))


def iso(value):
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, timezone.utc)
        elif re.fullmatch(r"\d{8}", str(value)):
            dt = datetime.strptime(str(value), "%Y%m%d").replace(tzinfo=timezone.utc)
        else:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                dt = email.utils.parsedate_to_datetime(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def envelope(url):
    source = source_for(url)
    url = redact_url(url)
    return {"status": "error", "reader": READERS[source], "source": source,
            "url": url, "canonical_url": url, "id": hashlib.sha256(url.encode()).hexdigest()[:16],
            "title": "", "author": "", "author_handle": "", "published": None,
            "fetched_at": datetime.now().astimezone().isoformat(), "text": "",
            "transcript": None, "comments": [], "media": [], "metrics": {},
            "repo": {"stars": 0, "language": "", "licence": "", "last_commit": ""},
            "error": None}


def state_root():
    root = Path(os.environ.get("CAPTURE_READER_STATE", str(
        Path(tempfile.gettempdir()) / f"capture-read-{os.getuid()}")))
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextlib.contextmanager
def reader_lock(source):
    with (state_root() / f"{source}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReaderError(f"Another {source} reader is running.")
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def pace(source):
    if source not in INTERVALS:
        return
    path = state_root() / f"{source}.time"
    try:
        previous = float(path.read_text())
    except (OSError, ValueError):
        previous = 0.0
    time.sleep(max(0, INTERVALS[source] - (time.time() - previous)))
    path.write_text(str(time.time()))


def _pinned(base, pins):
    """A connection class that dials only an address already checked for its host."""
    class Pinned(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._create_connection = self._connect_checked

        def _connect_checked(self, address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
            host, port = address
            addresses = pins.get((str(host).lower(), int(port)))
            if not addresses:
                raise ReaderError("The connection target was not checked.", "unsupported")
            failure = None
            for ip in addresses:
                try:
                    return socket.create_connection((ip, port), timeout, source_address)
                except OSError as error:
                    failure = error
            raise failure
    return Pinned


class _PinnedHTTP(HTTPHandler):
    def __init__(self, pins):
        super().__init__()
        self.pins = pins

    def http_open(self, req):
        return self.do_open(_pinned(http_client.HTTPConnection, self.pins), req)


class _PinnedHTTPS(HTTPSHandler):
    def __init__(self, pins):
        super().__init__()
        self.pins = pins

    def https_open(self, req):
        options = {"context": self._context}
        if hasattr(self, "_check_hostname"):
            options["check_hostname"] = self._check_hostname
        # TLS still verifies the certificate against the URL host name.
        return self.do_open(_pinned(http_client.HTTPSConnection, self.pins), req, **options)


def http(url, *, source=None, headers=None, data=None):
    # Every request and redirect resolves its host once, refuses any nonpublic address,
    # and the socket connects only to those checked addresses. That pin closes DNS
    # rebinding for these reads. Environment proxies are off: a proxy would resolve the
    # host itself and skip the check. Outside programs (yt-dlp, gh, instaloader) do their
    # own resolution; they only read their fixed public service hosts.
    pins = {}

    def admit(target):
        host, port, addresses = checked_destination(target)
        pins[(host, port)] = addresses

    admit(url)
    pace(source)
    # data makes a POST; only the Reddit token request sends one.
    request = Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    class PublicRedirect(HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            admit(new_url)
            pace(source)
            return super().redirect_request(request, response, code, message, headers, new_url)
    opener = build_opener(ProxyHandler({}), _PinnedHTTP(pins), _PinnedHTTPS(pins), PublicRedirect())
    with opener.open(request, timeout=25) as response:
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ReaderError("The public file exceeds the 250 MB reader limit.")
        return body, response.geturl(), dict(response.headers)


def http_json(url, *, source=None, headers=None, data=None):
    return json.loads(http(url, source=source, headers=headers, data=data)[0])


def tool(name):
    path = shutil.which(name)
    if not path:
        raise ReaderError(f"Missing free tool: {name}.")
    return path


def run(args, *, timeout=120, input_text=None):
    try:
        result = subprocess.run(args, input=input_text, stdin=subprocess.DEVNULL if input_text is None else None,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ReaderError(f"{Path(args[0]).name} timed out after {timeout} seconds.")
    if result.returncode:
        # No tool stdout goes to the CLI stdout. Never print an environment or auth state.
        detail = re.sub(r"\x1b\[[0-9;]*m", "", result.stderr).strip()[-1500:]
        raise ReaderError(f"{Path(args[0]).name} exited {result.returncode}: {detail}")
    return result.stdout


def workspace(out):
    if out is None:
        return Path(tempfile.mkdtemp(prefix="capture-read-"))
    out = Path(out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    # Each invocation has a fresh media directory. Existing raw files remain intact.
    return Path(tempfile.mkdtemp(prefix="media-", dir=out))


def claim(directory):
    """Mark a fresh reader directory; capture-write copies media only from a marked one."""
    token = secrets.token_hex(16)
    with (Path(directory) / MEDIA_MARKER).open("x", encoding="utf-8") as marker:
        marker.write(token + "\n")
    return token


def save_bytes(directory, name, data):
    path = directory / name
    with path.open("xb") as file:
        file.write(data)
    return str(path)


def save_media(result, directory, url, kind, *, source=None, name=None):
    body, _, headers = http(url, source=source)
    if not body:
        raise ReaderError(f"Empty {kind} file.")
    content_type = headers.get("Content-Type", headers.get("content-type", "")).lower()
    if kind != "html" and ("text/html" in content_type or body.lstrip().lower().startswith(b"<!doctype html")):
        raise ReaderError(f"The {kind} URL returned an HTML page.")
    suffix = Path(urlsplit(url).path).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
        suffix = {"image": ".jpg", "video": ".mp4", "audio": ".mp3", "pdf": ".pdf", "html": ".html"}[kind]
    name = name or f"{len(result['media']) + 1:03d}{suffix}"
    path = save_bytes(directory, name, body)
    result["media"].append({"url": url, "path": path, "kind": kind})
    return Path(path)


def title_from(text, fallback):
    return next((line.strip()[:160] for line in text.splitlines() if line.strip()), fallback)
