"""FxTwitter public posts and same-author threads, read one post at a time."""

from __future__ import annotations
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import common


def api(route, result):
    # FxTwitter only. Keyless Jina now answers 401, so there is no public fallback.
    url = "https://api.fxtwitter.com/2/" + route
    try:
        data = common.http_json(url, source="x")
    except Exception as error:
        raise common.ReaderError(f"fxtwitter: {error}")
    if not isinstance(data, dict) or data.get("code", 200) != 200:
        raise common.ReaderError(f"fxtwitter returned code {data.get('code') if isinstance(data, dict) else 'unknown'}.")
    return data


def post(data):
    value = data.get("status") or data.get("tweet")
    if not isinstance(value, dict) or not value.get("id") or value.get("type") == "tombstone":
        raise common.ReaderError("The X post is unavailable.")
    if value.get("author", {}).get("protected"):
        raise common.ReaderError("The X author requires login.", "needs-login")
    return value


def parent(value):
    reply = value.get("replying_to") or {}
    if isinstance(reply, dict):
        return str(reply.get("status") or reply.get("id") or ""), reply.get("screen_name", "")
    return str(value.get("replying_to_status") or ""), str(reply)


def handle(value):
    return (value.get("author", {}).get("screen_name") or "").lower()


def body(value):
    article = value.get("article") or {}
    if article:
        content = article.get("content") or {}
        blocks = content.get("blocks", []) if isinstance(content, dict) else []
        if blocks:
            return "\n\n".join(block.get("text", "") for block in blocks)
        raise common.ReaderError("The X article body is unavailable; its preview is not the full source.")
    return value.get("text") or value.get("raw_text", {}).get("text") or ""


def original_image(url):
    p = urlsplit(url)
    if p.hostname != "pbs.twimg.com":
        return url
    query = dict(parse_qsl(p.query))
    query["name"] = "orig"
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), p.fragment))


def read(result, directory):
    match = re.search(r"/(?:[^/]+/)?status/(\d+)", urlsplit(result["canonical_url"]).path)
    if not match:
        raise common.ReaderError("An X post URL is required.", "unsupported")
    requested_id = match.group(1)
    result["id"] = requested_id
    requested = post(api("status/" + requested_id, result))
    author = handle(requested)
    if not author:
        raise common.ReaderError("The X post has no author handle.")
    posts = {requested_id: requested}
    current = requested
    # Walk backward from a middle post until the same-author thread root is reached.
    while True:
        parent_id, parent_handle = parent(current)
        if not parent_id or parent_handle.lower() != author:
            break
        if parent_id in posts:
            raise common.ReaderError("The X thread contains a parent cycle.")
        current = post(api("status/" + parent_id, result))
        if handle(current) != author:
            raise common.ReaderError("The X thread parent author differs.")
        posts[parent_id] = current
    root_id = str(current["id"])
    result["id"] = root_id
    result["canonical_url"] = f"https://x.com/{current['author']['screen_name']}/status/{root_id}"
    result["author"] = current["author"].get("name", "")
    result["author_handle"] = current["author"]["screen_name"]
    result["published"] = common.iso(current.get("created_timestamp") or current.get("created_at"))
    result["title"] = (current.get("article") or {}).get("title") or common.title_from(body(current), f"X post {root_id}")
    # Thread endpoint finds child IDs. Fetch each ID separately to keep complete post bodies.
    thread_data = api("thread/" + root_id, result)
    thread_status = thread_data.get("status") or thread_data.get("tweet") or {}
    thread = thread_data.get("thread", thread_status.get("thread"))
    if thread is None:
        if current.get("replies", 0) or len(posts) > 1:
            result["text"] = "\n\n".join(body(p) for p in sorted(posts.values(), key=lambda p: int(p["id"])))
            raise common.ReaderError("X thread coverage is unknown; the public reader returned no thread list.")
        thread = []
    if not isinstance(thread, list):
        raise common.ReaderError("The X thread list has an unknown format.")
    for item in thread:
        if item.get("type") == "tombstone":
            raise common.ReaderError("An X thread post is unavailable.")
        item_id = str(item.get("id") or "")
        if not item_id or handle(item) != author or item_id in posts:
            continue
        value = post(api("status/" + item_id, result))
        if handle(value) == author:
            posts[item_id] = value
    # Include only the root and posts joined to it by same-author parent IDs.
    connected = {root_id}
    changed = True
    while changed:
        changed = False
        for item_id, value in posts.items():
            if item_id not in connected and parent(value)[0] in connected:
                connected.add(item_id)
                changed = True
    if requested_id not in connected:
        raise common.ReaderError("The requested X post is missing from its author thread.")
    ordered = [posts[key] for key in sorted(connected, key=int)]
    result["text"] = "\n\n".join(body(value) for value in ordered)
    result["metrics"] = {k: current.get(k) for k in ("likes", "reposts", "replies", "quotes", "views", "bookmarks")}
    result["metrics"].update(thread_post_ids=[str(value["id"]) for value in ordered], thread_reader="fxtwitter-v2")
    saved = set()
    for value in ordered:
        media = value.get("media") or {}
        for kind, field in (("image", "photos"), ("video", "videos")):
            for item in media.get(field, []):
                url = item.get("url")
                if url and kind == "image":
                    url = original_image(url)
                if url and url not in saved:
                    common.save_media(result, directory, url, kind)
                    saved.add(url)
    result["status"] = "ok"
