---
type: doc
workspace: system
timestamp: 2026-10-25T03:11:17-04:00
---
# Install Foxrun

You need Python 3.9 or newer.
The commands below cover macOS, Linux, and Windows PowerShell.
You also need Claude Code or Codex to use an agent.
Check Python in Terminal on macOS:

```sh
/usr/bin/python3 --version
```

On Linux, run `python3 --version`.
On Windows, open PowerShell and check the Python launcher:

```powershell
py -3 --version
```

## Get the product folder

You need a copy of the product folder for the three commands below. The uv and plugin routes need no copy.
Clone it into a folder named `foxrun-source`:

```sh
git clone https://github.com/foxrun-ai/foxrun.git "$HOME/foxrun-source"
cd "$HOME/foxrun-source"
```

The same two commands work in Windows PowerShell.
Do not clone into your home folder with a plain `git clone`. That makes `~/foxrun`, the portfolio folder, and install refuses it.

## Three commands

Open Terminal or PowerShell in the Foxrun product folder.
Use `avery` and `cedar-shop`, or replace them with your names.
Use one name without spaces for the person, such as `avery` or `avery-lee`.
Use lowercase letters, digits, and dashes for workspace names.
The system and portfolio folders must be empty or absent.

```sh
python3 install.py --home "$HOME/.foxrun" --portfolio "$HOME/foxrun" --yes --person avery --workspace cedar-shop --runtime both
python3 "$HOME/.foxrun/foxrun.py" doctor
python3 "$HOME/.foxrun/foxrun.py" start --workspace cedar-shop
```

On Windows PowerShell, use these three commands:

```powershell
py -3 install.py --home "$HOME/.foxrun" --portfolio "$HOME/foxrun" --yes --person avery --workspace cedar-shop --runtime both
py -3 "$HOME/.foxrun/foxrun.py" doctor
py -3 "$HOME/.foxrun/foxrun.py" start --workspace cedar-shop
```

Install names the two folders, the workspace, and its lead.
On macOS, install also turns on two nightly jobs. Add `--no-schedule` to the install command to leave them off.
[SECURITY.md](SECURITY.md#what-foxrun-touches) names each file that Foxrun writes outside the two folders.
It also prints hook entries for your runtime settings. To connect them, see [Connect hooks](#connect-hooks).
Doctor succeeds with `Doctor: 0 failed`.
Start names `avery`, `cedar-shop`, and the files to read.
Exit code 0 means success.
Continue with [GUIDE.md](GUIDE.md).

## Install with uv

You can install Foxrun without a copy of the product folder.
You need [uv](https://docs.astral.sh/uv/) for this route.
Its `install` command takes the same options as `install.py`.

```sh
uv tool install git+https://github.com/foxrun-ai/foxrun
foxrun install --home "$HOME/.foxrun" --portfolio "$HOME/foxrun" --yes --person avery --workspace cedar-shop --runtime both
python3 "$HOME/.foxrun/foxrun.py" doctor
```

To run it once without a kept `foxrun` command, use `uvx`:

```sh
uvx --from git+https://github.com/foxrun-ai/foxrun foxrun install --home "$HOME/.foxrun" --portfolio "$HOME/foxrun" --yes --person avery --workspace cedar-shop --runtime both
```

## Install with the plugin

The plugin adds the `foxrun-setup`, `thread`, and `foxrun-help` skills to Claude Code or Codex.
Run `setup` first. It gives you the uv commands above and installs the core on your yes.
In Claude Code, type these commands:

```text
/plugin marketplace add foxrun-ai/foxrun
/plugin install foxrun@foxrun
```

In Terminal, for Codex:

```sh
codex plugin marketplace add foxrun-ai/foxrun
codex plugin add foxrun@foxrun
```

## Update

Close agent sessions before an update. Keep the source folder separate from your installed home.
Update refreshes product files and applies the repeatable database migration.
It keeps your workspaces, tasks, soul, profile, personal files, and every `.local` setting.
It does not reconnect hooks, refresh runtime skill copies, or change schedules. To connect hooks, see [Connect hooks](#connect-hooks).
It saves previous files and a database backup under `~/.foxrun/backups/update-<time>-<id>/`.
After a successful update, it keeps the 3 newest `update-*` backups and removes older ones. It never removes anything else in `backups/`.
Update checks each product file against the installed list before it replaces the file.
If you changed a product file, update keeps your copy beside the new file as `<file>.local-edit-<time>`. Only you can read the copy.
Update still installs the new file, and it prints each kept copy. Move your change into a `.local` file.
A new release can ship a path your home already holds. If your file has the same bytes, update adds it to the installed list.
If your file differs, update keeps your copy the same way, installs the new file, and prints the copy.
`skillwright/manifests/shipped.yaml` is your own release record. Install makes it once, and update never replaces it.
After you run skill-ship, `~/.foxrun/skills` is a link to a frozen release in `skillwright/skill-releases/`.
Update never writes through that link. It makes a new release the way skill-ship does:
- It copies the active release and puts the new product skill files in the copy.
- Your own skills stay byte-identical. A product skill name that your release marks as yours stays yours.
- It moves the link to the new release, then updates `shipped.yaml`, `agents/execution/skills.yaml`, and the release state.
- It keeps the previous release. A failed doctor moves the link back to it.
- It writes a ship receipt in `skillwright/skill-state/ships/`, so skill-ship can see the new release.
- To go back to the old product skills, run update again from the old product folder.
  `skill-ship rollback` alone moves the link back, but the installed list still names the new files, so doctor fails.
- When no product skill changed, it makes no release.
Update refuses before any change when the shelf link is not a valid skill-ship release, or a skill-ship transaction is open.
It also refuses when another user can write `skillwright/skill-releases`, the linked release, or `skillwright/skill-state`.
It checks that each copied skill still matches the release record before it adds a new file.
It removes the `.update-*` folders that a stopped update left in `skillwright/skill-releases`.
Update refuses any other link on an update path, as before.
A new product skill reaches Claude and Codex at its next skill-ship.
Update never treats `.local` files, starter files, or your portfolio as product files.
A failed migration stops before file changes. A failed doctor restores the previous files and rolls back the database.
Other database writers wait until the update commits or rolls back.
Keep the printed backup path if an update stops.

For a clone, open the product folder, pull the new source, then update:

```sh
git pull
python3 foxrun.py update --home "$HOME/.foxrun"
```

For uv, upgrade the tool, then update your home:

```sh
uv tool upgrade foxrun
foxrun update --home "$HOME/.foxrun"
```

The uv command updates from the product inside the upgraded package.

The plugin refreshes its three skills only. Run `foxrun-setup` after a plugin upgrade.
Setup tells you to run both commands in the uv block above.
A plugin upgrade alone does not update your Foxrun home.

Install and each update record their product folder in `~/.foxrun/config/product-source.json`.
The installed launcher uses that folder when you leave out `--source`:

```sh
python3 "$HOME/.foxrun/foxrun.py" update --home "$HOME/.foxrun"
```

Update finds the source in this order: `--source`, the folder of the command you run, then the recorded folder.
If none holds the product, update stops with exit code 1. It changes nothing and prints the commands for each route.
Update also stops when another user can change the source folder, a file in it, or a parent folder without the sticky bit.
This check runs before any code from the source runs, for each of the three ways update finds the source.
To use another product folder, name it:

```sh
python3 "$HOME/.foxrun/foxrun.py" update --source /absolute/path/to/foxrun --home "$HOME/.foxrun"
```

Replace the source path with the product folder that contains `install.py` and `product-manifest.tsv`.
For a custom install, replace `--home` with its path. Update reads its portfolio setting from `config/person.json`.
On Windows PowerShell, use `py -3` in place of `python3`.
Success ends with `Doctor: 0 failed`. A refusal or failed doctor returns exit code 1.

## Connect hooks

Hooks print your start page when a session starts and after each compact. Before a compact, a hook saves a handoff.
The uv, plugin, and paste routes install without hooks. Connect them to an existing install with one command:

```sh
python3 "$HOME/.foxrun/foxrun.py" hookup --runtime both
```

Use `--runtime claude` or `--runtime codex` for one app. On Windows PowerShell, use `py -3` in place of `python3`.
If you installed with uv, the `foxrun` command takes `hookup` with the same options.
The command adds four hooks: session-start, after-compact, before-compact, and session-end.
It edits `~/.claude/settings.json` for Claude Code, and `~/.codex/hooks.json` and `~/.codex/config.toml` for Codex.
It reads `CLAUDE_CONFIG_DIR` and `CODEX_HOME` when you set them. Add `--runtime-home <folder>` to use another settings folder.
It keeps every other entry in those files and adds only the Foxrun entries that are missing.
It removes the start-rules entry that older Foxrun installs wrote for Claude and Codex. It removes only that exact entry.
Before it changes a file, it copies the file to `~/.foxrun/backups/hookup-<time>-<id>/`. Its `sources.json` names where each copy came from.
To undo, copy each saved file back to that path.
A second run finds every hook and prints `Nothing changed.` Open a new session after it connects the hooks.
The `foxrun-setup` skill runs this command when you answer yes to its memory question.
For a custom install, add `--home` with its path.

## Answer questions or connect hooks at install

Omit `--yes` to answer the name, workspace, and runtime questions.
Use `--runtime claude` or `--runtime codex` for one runtime.
Add `--hookup` to let install merge hook entries into runtime settings.
Add `--runtime-home "$HOME/foxrun-runtime"` to use separate trial settings.
These options also work in PowerShell:

```powershell
py -3 install.py --home "$HOME/.foxrun" --portfolio "$HOME/foxrun" --person avery --workspace cedar-shop --runtime both --hookup --runtime-home "$HOME/foxrun-runtime"
```

With `both`, the trial folder has separate `claude` and `codex` folders.
[Connect your agent](GUIDE.md#connect-claude-code-or-codex) explains the runtime check.

## If install stops

A refusal can mean a folder contains files or a path is not absolute.
Keep those files and choose another empty folder with an absolute path.
Foxrun also refuses folder links and overlapping system and portfolio folders.
A refusal or failed doctor returns exit code 1.
Keep the error output for the repair trail.

## Remove an install

Save the work you want to keep first.
Remove the Foxrun hook entries from your runtime settings.
Keep other hook entries and valid JSON punctuation.
Use the settings paths that your install printed.
If you installed with uv, run `uv tool uninstall foxrun`.
On macOS, turn off the two nightly jobs:

```sh
launchctl bootout "gui/$(id -u)/com.foxrun.session-nightly"
launchctl bootout "gui/$(id -u)/com.foxrun.session-nightly-watchdog"
```

Then move these files and folders to Trash:

- `~/Library/LaunchAgents/com.foxrun.session-nightly.plist` and `~/Library/LaunchAgents/com.foxrun.session-nightly-watchdog.plist`.
- `~/.local/state/foxrun/`. It holds the nightly logs and state, and database backups from the schema scripts.
- The skills that install copied into `~/.claude/skills`, `~/.codex/skills`, and `~/.agents/skills`. Each one has the same name as a folder in `~/.foxrun/skills`.

Remove the marked Foxrun block from `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`. Keep your other text.
Move your system and portfolio folders to Trash with Finder on macOS.
Use your file manager on Linux or File Explorer on Windows.
The portfolio folder contains your work, so this removes that work too.

## Optional add-ons

Read [Optional add-ons](OPTIONAL-ADDONS.md) for requirements, costs, licenses, and setup links.
Run `python3 "$HOME/.foxrun/foxrun.py" addons` to show the installer-readable list.
Run `python3 install.py --list-addons` from the source folder before installation.
On Windows PowerShell, use:

```powershell
py -3 "$HOME/.foxrun/foxrun.py" addons
py -3 install.py --list-addons
```

The installer shows the list and installs none of these tools.
Unverified licenses mean install-yourself. Jev and unnamed tools remain unavailable.
Foxrun has not checked these licenses online. Check a license yourself before you install the tool.

## Programs that capture uses

Capture reads ordinary web links with its built-in reader. Other links use free outside programs.
Install brings none of them. Install the ones you need yourself.
Ordinary web links, X links, and Reddit links need no outside program.

| Program | Used for | How to get it |
|---|---|---|
| `defuddle` | The `web` reader in capture. Optional cleaner article extraction. The `web` reader uses built-in HTML text when defuddle is absent. | `npm install -g defuddle` |
| `yt-dlp` | The `youtube` reader in capture. Reads a YouTube video's details and its transcript. | `brew install yt-dlp` |
| `instaloader` | The `instagram` reader in capture. Reads a public Instagram post and its media. | `uv tool install instaloader` |
| `gh` | The `github` reader in capture. Reads a public GitHub project's README, details, and files. Sign in once with `gh auth login`. | `brew install gh` |
| `pdftotext` | The `pdf` reader in capture. Reads the text of a PDF. It comes with poppler. | `brew install poppler` |

A missing required program stops only its own reader.
That reader returns an error that names the program.
