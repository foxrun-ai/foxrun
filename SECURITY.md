---
type: doc
workspace: system
timestamp: 2026-10-25T03:11:17-04:00
---
# Security policy

## Report a vulnerability

Report it privately on GitHub. Do not open a public issue for a security problem.

1. Open the **Security** tab of [github.com/foxrun-ai/foxrun](https://github.com/foxrun-ai/foxrun/security).
2. Choose **Report a vulnerability**, then fill in the form.

The report stays private between you and the maintainers until a fix ships.

Include:

- Your Foxrun version (`python3 "$HOME/.foxrun/foxrun.py" version`), your operating system, and your agent app, such as Claude Code or Codex.
- The file, command, or skill involved.
- The steps to reproduce it, and what an attacker could do.

## Supported versions

Only the latest version gets security fixes.
To update, use the command for your install route in [INSTALL.md](INSTALL.md#update).

## Scope

In scope:

- The code in this repository: install, update, hookup, the tracker, the hooks, the nightly job, capture, and the shipped skills.
- The rules in `config/gates.md`. If a web page, file, or message steers an agent past a gate, report it.

Out of scope, so report it to its maker:

- Claude Code, Codex, and other agent apps.
- Outside tools that Foxrun does not install, such as the add-ons in `OPTIONAL-ADDONS.md` and the programs that capture uses.

## What Foxrun touches

- Your files: the two folders you name at install, by default `~/.foxrun` and `~/foxrun`.
- Your agent apps' folders, for each app you pick: install copies skills into `~/.claude/skills`, `~/.codex/skills`, and `~/.agents/skills`. It adds one marked Foxrun block to `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`, and keeps your other text.
- Your agent apps' settings, only on your yes:
  - `python3 "$HOME/.foxrun/foxrun.py" hookup` edits `~/.claude/settings.json`, `~/.codex/hooks.json`, and `~/.codex/config.toml`.
  - In `~/.codex/config.toml`, hookup also writes a trust row with the hash of each Foxrun hook it adds. Codex then runs those exact hooks with no prompt. A changed hook needs a new trust row.
  - `install.py --hookup` edits the same files, and `~/.hermes` config files when Hermes is there.
  - Each one copies a file to `~/.foxrun/backups/hookup-<time>-<id>/` before it changes the file. To undo a change, copy the saved file back.
  - Without either one, install prints the hook entries for you to merge.
- On macOS: install turns on two jobs in `~/Library/LaunchAgents/`, `com.foxrun.session-nightly.plist` and its watcher `com.foxrun.session-nightly-watchdog.plist`. The watcher starts at login and runs every five minutes. `install.py --no-schedule` leaves them off. To remove them, see [Remove an install](INSTALL.md#remove-an-install).
- Outside the two folders, in `~/.local/state/foxrun/` (or the folder that `FOXRUN_STATE` names):
  - `session-nightly/` holds the nightly logs and the nightly state file `state.json`.
  - The schema scripts `base/apply_dictionary.py`, `work/apply_incidents.py`, and `work/apply_program_schema.py` save database backups under it, unless you give `--backup-dir`.
  - `memory/handoff_check.py` writes its reports under `runs/`, unless you give `--out`.
- In your temporary folder: capture keeps downloaded media in a new `capture-read-*` folder when you give no `--out`. Capture does not remove it. Give `--out` to keep the media in a folder you choose.
- The network: Foxrun has no server and no account. Install and update read the product folder on your disk.
  - Capture reads a link when you ask it to.
  - The nightly job pushes `state/` only when you made `state/` a Git repository with a remote.
  - The nightly job sends a Telegram message only when you add `config/nightly.local.json`.
  - Skill release (`skillwright/tools/skill_ship.py ship`) fetches the upstream of your Skillwright `main` branch. When `main` has commits that the upstream does not have, ship pushes all of them, not only the skill you ship. It prints each commit before the push. The push happens before the release checks, so a failed ship can still leave those commits on the upstream.
  - When ship regenerates the skill manifest, it commits that one file and pushes the commit to the same upstream.
  - Before each of these pushes, ship reads every object it sends. It refuses the push when one holds a secret-looking value, or when Git cannot list or read them. `ship --dry-run` never pushes.
  - Skill backup (`skillwright/tools/skill_backup.py run`) pushes a snapshot to the `backup/` branch of the origin you configure. It has no default origin. Its commit message holds the time only.
  - `base/distribution/fetch_install.py` is a legacy sample installer, not one of the install routes in [INSTALL.md](INSTALL.md). It reads a release only from an `https:` or `file:` address you give it, and it follows a redirect only to another `https:` address. It requires `--manifest-sha256`, the manifest hash from the release owner. It runs nothing unless the downloaded manifest matches that hash.
- Update runs code from the product folder. It refuses a product folder that another user can change: a folder or file there, or a parent folder without the sticky bit. This check applies to the folder you name with `--source`, to the folder of the command you run, and to the recorded folder.

## What install copies

Three lists in the product folder name the files. Read all three to see what reaches your home.

- `product-manifest.tsv` names each product file with its size and SHA-256. Install and update copy these files. Update checks each one against the list.
- `BUILD_ONLY` in `install.py` names product files that stay in the product folder: the installer and its tests, the uv and plugin packaging files, some test fixtures, and the optional scripts `tools/bin/ig-read`, `tools/bin/tweet-read`, and `tools/bin/browser-humanize.js`.
- `STARTERS` in `install.py` names the starter files. Install copies each one once, when your home does not have it. Update never replaces a starter, because it becomes your own file. Most starters have no row in `product-manifest.tsv`, so no hash checks them. One starter is a command: `skills/orchestrate/bin/orchestrate`.

`made-at-install.tsv` names each folder and file that install makes. It holds no hashes.

## Other files

- A secret check for Git commits ships in `hooks/git/`. Install does not turn it on. To turn it on, follow [hooks/git/README.md](hooks/git/README.md).
