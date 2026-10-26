"""yt-dlp metadata and human or automatic subtitles, without cookies."""

from __future__ import annotations
import html
import json
import re
from urllib.parse import parse_qs, urlsplit

from . import common


def transcript_text(content):
    """Remove VTT timing/markup and repeated rolling caption prefixes."""
    previous = []
    words = []
    for block in re.split(r"\n\s*\n", content.replace("\r", "")):
        lines = block.splitlines()
        if not any("-->" in line for line in lines):
            continue
        text = " ".join(line for line in lines if "-->" not in line and not line.isdigit())
        current = html.unescape(re.sub(r"<[^>]*>", "", text)).strip().split()
        overlap = 0
        for count in range(min(len(previous), len(current)), 0, -1):
            if previous[-count:] == current[:count]:
                overlap = count
                break
        words.extend(current[overlap:])
        previous = current
    return " ".join(words)


def select_subtitle(info):
    for automatic, key in ((False, "subtitles"), (True, "automatic_captions")):
        choices = info.get(key) or {}
        # Original tracks avoid YouTube's translated-track 429 responses.
        languages = sorted(choices, key=lambda lang: (
            lang != "en-orig", not lang.endswith("-orig") if automatic else False,
            lang != "en", not lang.startswith("en"), lang))
        for language in languages:
            for entry in choices[language]:
                if entry.get("ext") == "vtt" and entry.get("url"):
                    return language, automatic, entry
    raise common.ReaderError("YouTube returned no readable subtitles.")


def read(result, directory):
    url = result["canonical_url"]
    video_id = parse_qs(urlsplit(url).query).get("v", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise common.ReaderError("A YouTube video URL is required.", "unsupported")
    result["id"] = video_id
    raw = common.run([common.tool("yt-dlp"), "--ignore-config", "--no-playlist", "--skip-download",
                      "--no-warnings", "--socket-timeout", "20", "--retries", "0", "--extractor-retries", "0",
                      "--dump-single-json", url])
    info = json.loads(raw)
    result.update(title=info.get("title") or "", author=info.get("uploader") or info.get("channel") or "",
                  author_handle=info.get("uploader_id") or info.get("channel_id") or "",
                  published=common.iso(info.get("timestamp") or info.get("upload_date")),
                  text=info.get("description") or "")
    result["metrics"] = {k: info.get(k) for k in ("view_count", "like_count", "comment_count", "duration")}
    language, automatic, subtitle = select_subtitle(info)
    # URLs and formats come from yt-dlp. Download the chosen track without a second metadata request.
    headers = subtitle.get("http_headers") or info.get("http_headers") or {}
    headers = {key: value for key, value in headers.items()
               if key.lower() in ("user-agent", "referer", "accept", "accept-language")}
    content = common.http(subtitle["url"], headers=headers)[0]
    common.save_bytes(directory, f"{video_id}.{language}.vtt", content)
    result["transcript"] = transcript_text(content.decode("utf-8-sig"))
    result["metrics"].update(subtitle_language=language, subtitles_auto=automatic, transcript_source="yt-dlp-subtitles")
    if not result["transcript"].strip():
        raise common.ReaderError("YouTube subtitles contain no text.")
    if not result["text"].strip():
        result["text"] = result["transcript"]
        result["metrics"]["body_source"] = "transcript"
    if info.get("thumbnail"):
        common.save_media(result, directory, info["thumbnail"], "image")
    result["status"] = "ok"
