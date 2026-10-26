"""gh metadata, verbatim README, and repository tree through one child level."""

from __future__ import annotations
import base64
import json
import re
from urllib.parse import quote, urlsplit

from . import common


def api(endpoint):
    return json.loads(common.run([common.tool("gh"), "api", "--method", "GET", endpoint]))


def read(result, directory):
    parts = urlsplit(result["canonical_url"]).path.strip("/").split("/")
    if len(parts) < 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in parts[:2]):
        raise common.ReaderError("A GitHub repository URL is required.", "unsupported")
    owner, name = parts[:2]
    name = name.removesuffix(".git")
    repo_name = f"{owner}/{name}"
    endpoint = "repos/" + repo_name
    result["id"] = repo_name
    metadata = api(endpoint)
    if metadata.get("private"):
        raise common.ReaderError("Only public GitHub repositories are supported.", "needs-login")
    result.update(title=metadata.get("full_name", repo_name), author=metadata.get("owner", {}).get("login", owner),
                  author_handle=metadata.get("owner", {}).get("login", owner), published=common.iso(metadata.get("created_at")))
    result["repo"].update(stars=metadata.get("stargazers_count", 0), language=metadata.get("language") or "",
                          licence=(metadata.get("license") or {}).get("spdx_id") or "",
                          description=metadata.get("description") or "", default_branch=metadata.get("default_branch") or "",
                          url=metadata.get("html_url") or f"https://github.com/{repo_name}")
    commits = api(endpoint + "/commits?per_page=1")
    if commits:
        result["repo"]["last_commit"] = common.iso(commits[0].get("commit", {}).get("committer", {}).get("date")) or ""
        result["repo"]["commit_sha"] = commits[0]["sha"]
    readme = api(endpoint + "/readme")
    if readme.get("encoding") != "base64" or not readme.get("content"):
        raise common.ReaderError("GitHub returned no README body.")
    result["text"] = base64.b64decode(readme["content"]).decode("utf-8")
    result["repo"]["readme_path"] = readme.get("path", "")
    ref = result["repo"].get("commit_sha") or result["repo"]["default_branch"]
    root = api(endpoint + "/git/trees/" + quote(ref, safe=""))
    if root.get("truncated"):
        raise common.ReaderError("GitHub truncated the root tree.")
    tree = []
    for item in root.get("tree", []):
        tree.append({"path": item["path"], "type": item["type"], "sha": item["sha"]})
        if item["type"] == "tree":
            child = api(endpoint + "/git/trees/" + item["sha"])
            if child.get("truncated"):
                raise common.ReaderError(f"GitHub truncated the tree for {item['path']}.")
            for entry in child.get("tree", []):
                tree.append({"path": item["path"] + "/" + entry["path"], "type": entry["type"], "sha": entry["sha"]})
    result["repo"]["tree"] = sorted(tree, key=lambda item: item["path"])
    result["metrics"] = {"forks": metadata.get("forks_count", 0), "open_issues": metadata.get("open_issues_count", 0)}
    # capture-write owns the later summary. The README here remains verbatim.
    result["status"] = "ok"
