# Public readers

Run `capture/capture-read <url> [--out <dir>]`.
It prints one JSON object. Exit 0 means `status: ok`; other statuses exit 1.
The reader saves media in a new directory under `--out`.
Without `--out`, it keeps media in a new temporary directory.
It never writes capture Markdown, rows, tags, or a GitHub summary.
`capture-write` owns those later steps.

## Safety rules

- Each read resolves the host and checks every address with Python's `ipaddress`.
  It refuses private, loopback, link-local, multicast, reserved, and unspecified addresses, IPv4 and IPv6.
  IPv4 inside IPv6 (`::ffff:`, 6to4, NAT64) gets the same check.
- It refuses decimal, octal, hex, and short IPv4 spellings, such as `2130706433` or `0177.0.0.1`.
- The check runs on the first request, on every redirect, and on every media URL.
- The connection goes only to the checked address, so a second DNS answer cannot change it.
  Environment proxies are not used.
- `yt-dlp`, `gh`, and `instaloader` resolve their own fixed public service hosts.
- The printed JSON replaces userinfo and credential-like query values with `[REDACTED]`.
  The full URL stays in memory for the fetch only. A failure prints the redacted URL too.
- The media directory holds a `.capture-read` marker. The JSON names it in `media_dir` and `media_token`.
  `capture-write` copies media only from that directory, and leaves the reader's files in place.

| Source | Reader | Text |
| --- | --- | --- |
| X | FxTwitter v2 (`api.fxtwitter.com`), free and keyless | Same-author posts in order |
| Instagram | Instaloader in its tool environment | Public caption |
| YouTube | yt-dlp | Description and human or original automatic transcript |
| GitHub | gh | Verbatim README, metadata, and tree in `repo` |
| Reddit | Reddit's official API through a personal script app | Post and top 20 comments |
| Web | defuddle | Markdown and original HTML |
| PDF | Direct download and pdftotext | PDF text |

`capture/install.json` lists each reader's outside program under `needs`.
The install guide shows that list. Install brings none of these programs.
Install the free tools with `npm install -g defuddle` and `uv tool install instaloader`.
`yt-dlp`, `gh`, and `pdftotext` must also be on `PATH`.

## Routes checked on 10.26

| Route | Result | What the readers do |
| --- | --- | --- |
| Reddit anonymous `.json`, on reddit.com and old.reddit.com | HTTP 403 | Not used. The Reddit reader uses the official API. |
| FxTwitter (`api.fxtwitter.com`) | 200 | The X reader. It has no second route. |
| Jina Reader (`r.jina.ai`) without a key | 401 | Not in the free ladder. `capture-recover` uses it only when `JINA_API_KEY` is set. |
| Wayback availability API | 200 | The first rung of `capture-recover`. |
| Instaloader 4.15.5 | Installed | The Instagram reader. |

## Reddit

Reddit blocks anonymous reads. The reader uses Reddit's official API with a free personal "script" app.
Make the app once at https://www.reddit.com/prefs/apps. Save its client id and secret in your secret store.
The reader reads them with `agent-secret-read`, from `op://Foxrun/Reddit/client_id` and `op://Foxrun/Reddit/client_secret`.
`CAPTURE_REDDIT_ID_REF` and `CAPTURE_REDDIT_SECRET_REF` change those references.
It asks `https://www.reddit.com/api/v1/access_token` for an app-only token, then reads `https://oauth.reddit.com/comments/<id>`.
Until the app exists, the read returns `needs-login`, and its error names these steps.
The first fallback needs no setup: read the post with browse and the person's signed-in browser cookies.
The secret values never reach the JSON, an error, or a log.

## Blocked pages

`capture/capture-recover <url> [--out FILE]` finds a copy of a page that answers 403, 429, or a bot wall.
It tries Wayback, then archive.today, then Jina when `JINA_API_KEY` is set. It checks each body before it counts.
It prints one JSON object with `route`, `provenance`, and `snapshot_timestamp`. A `snapshot` is an old copy; cite it with its date.
When every rung fails, it exits 1 and names browse as the next step.
It is ported from Hermes Agent's blocked-page-recovery skill under the MIT License.
`capture-read` never calls it. A capture saves the live source only.

These readers were tested with these versions:

| Tool | Version |
| --- | --- |
| defuddle | 0.19.4 |
| instaloader | 4.15.5 |

These readers need no login reader. The reader's JSON for a link proves the read.

`CAPTURE_READER_STATE` sets the shared request state directory.
The default is a temporary directory named `capture-read-<uid>`.
Use one state directory for the whole run, including separate CLI processes.
The reader locks each source to prevent simultaneous reads.
X requests wait one second; Reddit requests wait two seconds, including HTTP redirects and the token request.
Instagram requests wait ten seconds, including requests inside the tool.
Instagram stops after ten consecutive failures.
Start a new state directory only after a human reviews those failures.

The pack uses Python 3.10 or later and the standard library.
Instaloader uses its own installed Python environment through a subprocess.
Each tool runs without browser cookies or login prompts.
yt-dlp ignores saved configuration.
`gh` uses its existing tool authentication and reads public repositories only.

X first reads the requested post and walks its same-author parents.
It asks `/2/thread/<id>` for child IDs, then reads each post separately.
It excludes quotes and replies by other authors.
A failed or unknown thread list returns an error, with any text already read.
The readers never use cookie-based X backends.

`metrics.subtitles_auto` marks automatic YouTube subtitles.
`metrics.subtitle_language` names the chosen language.
The reader prefers original automatic tracks over translated automatic tracks.
Translated automatic tracks can return HTTP 429 when the original track still works.
The transcript removes timing markup and repeated rolling caption prefixes.
The original VTT file remains beside the downloaded media.
Missing or empty subtitles return an error.

A Reddit share link resolves first, even when the target page returns HTTP 403.
Every Reddit request uses the same plain User-Agent.

Web media includes the original HTML as `kind: html`.
Defuddle 0.19.4 can turn a linked YouTube thumbnail into an invalid watch-page image URL.
The web reader restores that image URL from the saved original HTML.
It keeps the body words and enclosing video link.
This extends the example contract's media list, which omitted HTML.
PDFs with no extractable text return an error; this pack does not add OCR.
Media download failures return an error and retain completed files.

## What a public read can return

In testing, public X, Instagram, YouTube, GitHub, and PDF links returned `ok`.
Reddit returns `needs-login` until the Reddit app exists.
Some web sites refuse a public read with HTTP 403. That read returns `error`.
The offline tests in `capture/tests/readers/` check each reader against saved fixtures, with no network.

References:

- [FxTwitter public thread API](https://docs.fxembed.com/api/twitter/operations/2threadid/)
- [defuddle CLI](https://github.com/kepano/defuddle#cli)
- [Reddit OAuth2 for script apps](https://github.com/reddit-archive/reddit/wiki/OAuth2)
- [Hermes Agent blocked-page-recovery](https://github.com/NousResearch/hermes-agent)
