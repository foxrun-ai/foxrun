"""Run Instaloader in its own tool environment, with a new anonymous session."""

from __future__ import annotations
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import common


# The installed tool owns its Python dependencies. The capture pack remains stdlib-only.
# Pace every request, including Instaloader's lazy metadata calls, in the child process.
CHILD = r'''
import json, sys, time
import instaloader
import requests
last_request = 0.0
original_request = requests.sessions.Session.request
def public_request(self, *args, **kwargs):
    global last_request
    time.sleep(max(0, 10.0 - (time.monotonic() - last_request)))
    last_request = time.monotonic()
    return original_request(self, *args, **kwargs)
requests.sessions.Session.request = public_request
loader = instaloader.Instaloader(quiet=True, sleep=False, download_pictures=False,
    download_videos=False, save_metadata=False, max_connection_attempts=1, request_timeout=20)
post = instaloader.Post.from_shortcode(loader.context, sys.argv[1])
caption = post.caption or ""
username = post.owner_username
media = []
if post.typename == "GraphSidecar":
    for item in post.get_sidecar_nodes():
        media.append({"url": item.video_url if item.is_video else item.display_url,
                      "kind": "video" if item.is_video else "image"})
else:
    media.append({"url": post.video_url if post.is_video else post.url,
                  "kind": "video" if post.is_video else "image"})
print(json.dumps({"id": str(post.mediaid), "caption": caption, "username": username,
    "author": (post._node.get("owner") or {}).get("full_name") or username,
    "published": post.date_utc.isoformat() + "+00:00", "media": media,
    "metrics": {"likes": post.likes, "comments": post.comments}}))
'''


def failures():
    path = common.state_root() / "instagram.failures"
    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return 0


def read(result, directory):
    count = failures()
    if count >= 10:
        raise common.ReaderError("Instagram stopped after 10 consecutive failures. Review before restarting.")
    match = re.search(r"^/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)/?", urlsplit(result["canonical_url"]).path)
    if not match:
        raise common.ReaderError("A public Instagram post or reel URL is required.", "unsupported")
    shortcode = match.group(1)
    result["id"] = shortcode
    try:
        executable = Path(common.tool("instaloader"))
        with executable.open() as file:
            shebang = file.readline().strip()
        python = shebang.removeprefix("#!")
        if not shebang.startswith("#!/") or " " in python or not Path(python).name.startswith("python"):
            raise common.ReaderError("Instaloader needs its installed Python tool interpreter.")
        common.pace("instagram")
        try:
            data = json.loads(common.run([python, "-c", CHILD, shortcode], timeout=180))
        finally:
            # Keep the next process ten seconds away from the last child request.
            (common.state_root() / "instagram.time").write_text(str(time.time()))
        result.update(author=data.get("author") or "", author_handle=data.get("username") or "",
                      published=common.iso(data.get("published")), text=data.get("caption") or "")
        result["title"] = common.title_from(result["text"], f"Instagram post {shortcode}")
        result["metrics"] = data.get("metrics") or {}
        for media in data.get("media", []):
            if media.get("url"):
                common.save_media(result, directory, media["url"], media["kind"], source="instagram")
        if not result["text"].strip():
            raise common.ReaderError("Instagram returned no caption text.")
    except Exception as error:
        (common.state_root() / "instagram.failures").write_text(str(count + 1))
        if re.search(r"login.?required|private|401|403|429|checkpoint|challenge|please wait", str(error), re.I):
            raise common.ReaderError(f"Instagram blocked the public read: {error}", "needs-login")
        raise
    (common.state_root() / "instagram.failures").write_text("0")
    result["status"] = "ok"
