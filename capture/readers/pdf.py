"""Public PDF file plus pdftotext output. No Python PDF package is needed."""

from __future__ import annotations
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import common


def read(result, directory):
    url = result["canonical_url"]
    path = common.save_media(result, directory, url, "pdf", name="source.pdf")
    with path.open("rb") as file:
        if not file.read(1024).lstrip().startswith(b"%PDF-"):
            raise common.ReaderError("The source did not return a PDF file.")
    result["title"] = unquote(Path(urlsplit(url).path).name)
    result["text"] = common.run([common.tool("pdftotext"), "-layout", str(path), "-"])
    result["metrics"] = {"text_reader": "pdftotext", "file_bytes": path.stat().st_size}
    result["status"] = "ok"
