"""Save public HTML and text; use optional defuddle for article extraction."""

from __future__ import annotations
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from . import common


class PlainHTML(HTMLParser):
    """Read basic page text without external programs; keep the raw HTML as evidence."""
    BLOCKS = {'p', 'div', 'article', 'section', 'main', 'li', 'br', 'h1', 'h2', 'h3', 'h4', 'tr'}
    HIDDEN = {'script', 'style', 'noscript', 'template', 'head'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.hidden = [], [], []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self.in_title = True
        if tag in self.HIDDEN:
            self.hidden.append(tag)
        if not self.hidden and tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        if tag in self.hidden:
            self.hidden = self.hidden[:self.hidden.index(tag)]
        if not self.hidden and tag in self.BLOCKS:
            self.parts.append('\n')

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        elif not self.hidden:
            self.parts.append(data)

    def result(self):
        text = '\n\n'.join(line for line in
                           (' '.join(part.split()) for part in ''.join(self.parts).splitlines()) if line)
        return {'title': ' '.join(''.join(self.title).split()), 'content': text,
                'wordCount': len(text.split())}


class LinkedImages(HTMLParser):
    """Keep the original image URLs inside HTML links."""
    def __init__(self, base_url):
        super().__init__()
        self.base_url, self.links, self.anchors = base_url, {}, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.anchors.append(urljoin(self.base_url, attrs.get("href") or ""))
        elif tag == "img" and self.anchors and attrs.get("src"):
            self.links[self.anchors[-1]] = urljoin(self.base_url, attrs["src"])

    def handle_endtag(self, tag):
        if tag == "a" and self.anchors:
            self.anchors.pop()


def repair_link_images(content, raw_html, base_url):
    # Defuddle 0.19.4 changes Discourse YouTube thumbnails into watch-page URLs.
    # Use the saved original HTML to restore the image, keeping the body words.
    images = LinkedImages(base_url)
    images.feed(raw_html)
    repaired = 0
    pattern = r"(\[\s*!\[[^\]]*\]\()([^\s)]+)(\)\s*\]\()([^\s)]+)(\))"
    def replace(match):
        nonlocal repaired
        original = images.links.get(urljoin(base_url, match[4]))
        if original and original != urljoin(base_url, match[2]):
            repaired += 1
            return match[1] + original + match[3] + match[4] + match[5]
        return match[0]
    return re.sub(pattern, replace, content), repaired


def read(result, directory):
    raw, final_url, headers = common.http(result["canonical_url"])
    if not raw:
        raise common.ReaderError("The web page returned an empty body.")
    path = common.save_bytes(directory, "source.html", raw)
    result["media"].append({"url": final_url, "path": path, "kind": "html"})
    content_type = headers.get("Content-Type", headers.get("content-type", ""))
    charset = re.search(r"charset=([^; ]+)", content_type)
    content = raw.decode(charset.group(1).strip('\"') if charset else "utf-8", errors="replace")
    try:
        extractor = common.tool("defuddle")
    except common.ReaderError:
        parser = PlainHTML()
        parser.feed(content)
        parsed = parser.result()
        result["reader"] = "html"
    else:
        parsed = json.loads(common.run([extractor, "parse", "--markdown", "--json"], input_text=content))
    result.update(title=parsed.get("title") or "", author=parsed.get("author") or "",
                  published=common.iso(parsed.get("published")), text=parsed.get("content") or "")
    result["canonical_url"] = common.canonicalize(final_url)
    result["metrics"] = {"word_count": parsed.get("wordCount"), "language": parsed.get("language")}
    result["text"], repaired = repair_link_images(result["text"], content, final_url)
    if repaired:
        result["metrics"]["repaired_image_links"] = repaired
    # Download the main image and all Markdown image URLs, preserving the article text.
    urls = [parsed.get("image")] + re.findall(r"!\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", result["text"])
    saved = set()
    for url in urls:
        if url:
            url = urljoin(final_url, url)
            if url not in saved and url.startswith(("http://", "https://")):
                common.save_media(result, directory, url, "image")
                saved.add(url)
    result["status"] = "ok"
