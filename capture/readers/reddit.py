"""Reddit's official API through a personal script app: post plus top comments."""

from __future__ import annotations
import base64
import os
import re
import shutil
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit

from . import common

# Secret references, not secrets. The values come from the secret reader at run time.
ID_REF = os.environ.get("CAPTURE_REDDIT_ID_REF", "op://Foxrun/Reddit/client_id")
SECRET_REF = os.environ.get("CAPTURE_REDDIT_SECRET_REF", "op://Foxrun/Reddit/client_secret")
OAUTH_ENDPOINT = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
NEEDS_APP = (
    "Reddit blocks anonymous reads. Make a free personal script app at "
    "https://www.reddit.com/prefs/apps, then save its client id and secret in your "
    f"secret store as {ID_REF} and {SECRET_REF}. Until then, read the post with browse "
    "and your signed-in browser cookies.")


def secret(ref):
    """Read one secret through agent-secret-read. Its value never reaches an error or stdout."""
    reader = shutil.which("agent-secret-read")
    if not reader:
        return None
    try:
        done = subprocess.run([reader, ref], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = done.stdout.strip()
    return value if done.returncode == 0 and value else None


def credentials():
    client_id, client_secret = secret(ID_REF), secret(SECRET_REF)
    if not (client_id and client_secret):
        raise common.ReaderError(NEEDS_APP, "needs-login")
    return client_id, client_secret


def token():
    client_id, client_secret = credentials()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        data = common.http_json(OAUTH_ENDPOINT, source="reddit", headers={"Authorization": "Basic " + basic},
                                data=urlencode({"grant_type": "client_credentials"}).encode())
    except HTTPError as error:
        if error.code in (400, 401, 403):
            raise common.ReaderError(f"Reddit refused the app login (HTTP {error.code}). " + NEEDS_APP, "needs-login")
        raise
    value = data.get("access_token") if isinstance(data, dict) else None
    if not value:
        raise common.ReaderError("Reddit returned no access token. " + NEEDS_APP, "needs-login")
    return value


def post_id(url):
    match = re.search(r"/comments/([a-z0-9]+)", urlsplit(url).path)
    return match.group(1) if match else None


def read(result, directory):
    url = result["canonical_url"]
    if re.search(r"/s/[^/]+/?$", urlsplit(url).path):
        try:
            _, final, _ = common.http(url, source="reddit")
        except HTTPError as error:
            # A share link can resolve to a post whose page returns 403.
            final = error.filename
            if error.code not in (401, 403) or not post_id(final or ""):
                raise
        if common.source_for(final) != "reddit":
            raise common.ReaderError("The Reddit share URL left Reddit.")
        url = common.canonicalize(final)
        result["canonical_url"] = url
    item = post_id(url)
    if not item:
        raise common.ReaderError("A Reddit post URL is required.", "unsupported")
    bearer = token()
    query = urlencode({"raw_json": 1, "sort": "top", "limit": 20})
    try:
        data = common.http_json(f"{API}/comments/{item}?{query}", source="reddit",
                                headers={"Authorization": "Bearer " + bearer})
    except HTTPError as error:
        if error.code in (401, 403):
            raise common.ReaderError(f"Reddit refused the API read (HTTP {error.code}).", "needs-login")
        raise
    if not isinstance(data, list) or len(data) < 2:
        raise common.ReaderError("Reddit returned no post and comments.")
    posts = data[0].get("data", {}).get("children", [])
    if not posts:
        raise common.ReaderError("The Reddit post is unavailable.")
    post = posts[0]["data"]
    result.update(id=str(post["id"]), title=post.get("title") or "", author=post.get("author") or "",
                  author_handle=post.get("author") or "", published=common.iso(post.get("created_utc")))
    result["canonical_url"] = common.canonicalize("https://www.reddit.com" + post["permalink"])
    # Link posts have no selftext. Preserve the source title as their body.
    result["text"] = post.get("selftext") or post.get("title") or ""
    if result["text"] in ("[removed]", "[deleted]"):
        raise common.ReaderError("The Reddit post body was removed.")
    comments = [item["data"] for item in data[1].get("data", {}).get("children", []) if item.get("kind") == "t1"]
    result["comments"] = [{"author": item.get("author") or "", "text": item.get("body") or "", "score": item.get("score", 0)}
                          for item in sorted(comments, key=lambda item: item.get("score", 0), reverse=True)[:20]]
    result["metrics"] = {"score": post.get("score", 0), "num_comments": post.get("num_comments", 0),
                          "upvote_ratio": post.get("upvote_ratio"), "subreddit": post.get("subreddit"),
                          "linked_url": post.get("url")}
    for item in (post.get("media_metadata") or {}).values():
        media = item.get("s") or {}
        if media.get("u"):
            common.save_media(result, directory, media["u"], "image", source="reddit")
    if post.get("post_hint") == "image" and post.get("url"):
        common.save_media(result, directory, post["url"], "image", source="reddit")
    result["status"] = "ok"
