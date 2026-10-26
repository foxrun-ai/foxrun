---
type: doc
workspace: system
timestamp: 2026-10-24T16:10:09-04:00
---
# Optional add-ons

Foxrun works on day one with nothing added.
Add-ons give your agents more reach: they read more, do more, and remember more.
Each row says what you get, what it costs, and where its page is.
You install the tool. Foxrun installs none of them.

## Contents

- [Research anything](#research-anything)
- [Read the web and your feeds](#read-the-web-and-your-feeds)
- [Drive your Mac and browser](#drive-your-mac-and-browser)
- [Design and record](#design-and-record)
- [Remember and find](#remember-and-find)
- [Talk and email as you](#talk-and-email-as-you)
- [Run a team of agents](#run-a-team-of-agents)
- [Keep secrets safe](#keep-secrets-safe)
- [Push a tool to a workspace](#push-a-tool-to-a-workspace)
- [Install the optional scripts](#install-the-optional-scripts)
- [Before you install one](#before-you-install-one)

## Research anything

Say the job. Your agents find the tool for it.
They search, compare the options, and check each one is safe.
They read how it works, install it on your yes, and write its page.
The [capability skill](skills/capability/SKILL.md) does this. It ships with Foxrun.
Four tools give it reach. Three are free. Firecrawl is paid.

| Tool | What it gets you | Cost | Page |
|---|---|---|---|
| Context7 | Current docs for any library, so agents stop guessing at code | Free tier | [ctx7](tools/cli/ctx7.md) |
| DeepWiki | How a public GitHub project works, before anyone reads its code | Free; nothing to install | [deepwiki-mcp](tools/mcp/deepwiki-mcp.md) |
| Firecrawl | Any page, or a whole site, as clean text | Paid: credits for each page | [firecrawl](tools/cli/firecrawl.md) |
| repomix | Pack repository files for an agent to inspect | Free | [repomix](tools/cli/repomix.md) |

## Read the web and your feeds

Hand an agent a link. It brings back the words, not the clutter.
Capture uses the tools marked "capture". Ordinary web links work without an added tool.
Other readers stop when their required tool is absent. The rest still work.

| Tool | What it gets you | Cost | Page |
|---|---|---|---|
| defuddle · capture | The article from a web page, with no menus or ads | Free | [defuddle](tools/cli/defuddle.md) |
| tweet-read | One public X post: author, text, date, and counts | Needs an X token; X plans can cost money | [tweet-read](tools/cli/tweet-read.md) |
| ig-read | Public Instagram posts, comments, profiles, and reel transcripts | Paid: ScrapeCreators credit | [ig-read](tools/cli/ig-read.md) |
| instaloader · capture | A public Instagram post's caption and media | Free | [instaloader](tools/cli/instaloader.md) |
| yt-dlp · capture | A video's details and transcript, with no download | Free | [yt-dlp](tools/cli/yt-dlp.md) |
| pdftotext · capture | The text of any PDF | Free | [pdftotext](tools/cli/pdftotext.md) |
| gh · capture | GitHub projects, issues, and pull requests, read by command | Free; your GitHub sign-in | [gh](tools/cli/gh.md) |
| FFmpeg | Convert audio and video; inspect media files | Free | [ffmpeg](tools/cli/ffmpeg.md) |
| summarize | A summary or the full text of a page, a video, a recording, or a file | Free tool; your model provider can cost money | [summarize](tools/cli/summarize.md) |

## Drive your Mac and browser

Stop doing the clicks yourself. Your agents work the apps and the web.
A send, a delete, or a form still waits for your yes.

| Tool | What it gets you | Cost | Page |
|---|---|---|---|
| macOS Automator | Agents run Notes, Finder, and other Mac apps by script | Free | [macos-automator](tools/mcp/macos-automator.md) |
| CUA | Agents see the screen, then click and type in apps with no script | Free | [cua-driver](tools/cli/cua-driver.md) |
| Playwright | Agents open pages, click, type, and fill forms in a real browser | Free | [playwright](tools/mcp/playwright.md) |
| gstack browse | A fast browser with no window: test a site, read a page, take a screenshot | Free | [gstack-browse](tools/cli/gstack-browse.md) |
| Browser Humanize | Human pauses, typing, and mouse paths, so sites do not block your agent | Free | [browser-humanize](tools/cli/browser-humanize.md) |

## Design and record

Show your agents what you mean, once. They work from it.

| Tool | What it gets you | Cost | Page |
|---|---|---|---|
| Paper | Agents read and edit your designs on a live canvas | Paper's own plans | [paper](tools/mcp/paper.md) |
| Clipy | Record your screen once; agents read the transcript and the images | Clipy's own plans; a sign-in | [clipy](tools/mcp/clipy.md) |
| bm-render | Mermaid diagrams as SVG or terminal text; wrapper setup remains separate | Free library | [bm-render](tools/cli/bm-render.md) |

## Remember and find

What you saved comes back when you need it. When you must choose, you get a straight answer.

| Tool | What it gets you | Cost | Page |
|---|---|---|---|
| qmd | Agents search your notes by words or by meaning, on this computer | Free | [qmd-mcp-cli](tools/mcp/qmd-mcp-cli.md) |
| Jev | A choice, a score, or a yes or no, with odds instead of prose | Paid: OpenRouter credit for each run | [jev](tools/service/jev.md) |

## Talk and email as you

Your agents read the thread and draft the reply in your voice.
Nothing goes out without your yes.

| Tool | What it gets you | Cost | Page |
|---|---|---|---|
| imsg | Agents read your texts and draft replies | Free | [imsg](tools/cli/imsg.md) |
| remindctl | Agents read, add, and finish your Apple Reminders (Mac only) | Free | [remindctl](tools/cli/remindctl.md) |
| gogcli | Agents search your mail and read your calendar | Free; your own Google sign-in | [gogcli](tools/cli/gogcli.md) |

## Run a team of agents

Many agents, one desk. They keep working when you walk away.

| Tool | What it gets you | Cost | Page |
|---|---|---|---|
| herdr | Many agents in one terminal; each keeps running after you leave | Free | [herdr](tools/cli/herdr.md) |
| tmux | Sessions live through a dropped connection; pick up from a phone | Free | [tmux](tools/cli/tmux.md) |
| printing-press | Name an online service; get a checked command for it | Service and model use can cost money | [printing-press](tools/cli/printing-press.md) |
| Codex plugin | Ask Codex for reviews and tasks from Claude Code | Your Codex usage limits or API charges | [codex-at-openai-codex](tools/plugin/codex-at-openai-codex.md) |

## Keep secrets safe

Your agents use your keys. No key lands on a page or in a reply.

| Tool | What it gets you | Cost | Page |
|---|---|---|---|
| 1Password CLI | Agents read one secret at a time through a secret reader, never by hand | Paid 1Password plan; the CLI is free | [op](tools/cli/op.md) |

## Push a tool to a workspace

`config/tools.yaml` holds one row for each tool and where it applies. Add a row for a tool that has none.
Set `applies_to` on its row: `global`, `off`, or a list of workspace names.
Then run `python3 "$HOME/.foxrun/base/make_workspaces_view.py"`.
Each named workspace's `TOOLS.md` then lists the tool under "From the shelf".
defuddle, yt-dlp, instaloader, gh, and the two Foxrun command pages start as `global`.
Other add-on rows start as `off`; enable a row after setup. An off row stays out of generated guides.
All optional choices remain listed on this page and in `config/optional-addons.tsv`.

## Install the optional scripts

These scripts stay in the Foxrun source folder. A fresh system home has none of them.
Their tool pages ship so you can choose and install each script later.
Set `FOXRUN_SOURCE` to the absolute path of the Foxrun source folder you used to install.
Set `FOXRUN_HOME` to your system home if you chose a different path.

```sh
FOXRUN_SOURCE=/absolute/path/to/foxrun-source
FOXRUN_HOME="${FOXRUN_HOME:-$HOME/.foxrun}"
mkdir -p "$FOXRUN_HOME/tools/bin" "$HOME/bin"
```

Install only the script you choose:

| Add-on | Copy from the source folder | Finish setup | Check |
|---|---|---|---|
| ig-read | `install -m 755 "$FOXRUN_SOURCE/tools/bin/ig-read" "$FOXRUN_HOME/tools/bin/ig-read"` | Install the ScrapeCreators CLI at a version you checked, e.g. `npm install -g @scrapecreators/cli@<version>`; `ig-read` never downloads it. Set `SCRAPECREATORS_API_KEY`, then link the script into a folder on your path. | `bash "$FOXRUN_HOME/tools/bin/ig-read" --help` |
| tweet-read | `install -m 755 "$FOXRUN_SOURCE/tools/bin/tweet-read" "$FOXRUN_HOME/tools/bin/tweet-read"` | Use Bash, curl, and Python 3. Set `X_BEARER_TOKEN`, then link the script into a folder on your path. | `bash "$FOXRUN_HOME/tools/bin/tweet-read" --help` |
| Browser Humanize | `install -m 644 "$FOXRUN_SOURCE/tools/bin/browser-humanize.js" "$FOXRUN_HOME/tools/bin/browser-humanize.js"` | Install Node.js, then load the script from your browser automation code. | `node "$FOXRUN_HOME/tools/bin/browser-humanize.js" --test` |

For `ig-read` or `tweet-read`, link the selected script, then check that `$HOME/bin` is on your path:

```sh
ln -s "$FOXRUN_HOME/tools/bin/ig-read" "$HOME/bin/ig-read"
ln -s "$FOXRUN_HOME/tools/bin/tweet-read" "$HOME/bin/tweet-read"
```

Each tool page also explains secret-store references instead of plain environment keys.
Existing local copies stay in place. Foxrun does not remove them.
Ordinary web links use the built-in HTML reader when defuddle is absent.
Install defuddle for cleaner article extraction.

## Before you install one

Read the tool's own guide and license first.
Use your own sign-in and keys. Never copy another person's.
Run the Check command on its page before you use it with your work.
Browser Humanize, ig-read, and tweet-read need a separate script copy. Follow [Install the optional scripts](#install-the-optional-scripts).
Foxrun downloads nothing, connects no account, and buys no provider credit.
Run `python3 "$HOME/.foxrun/foxrun.py" addons` for a short install list in the terminal. It installs nothing.
