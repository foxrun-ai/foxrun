---
type: doc
workspace: system
timestamp: 2026-10-19T19:30:13-04:00
---

# Git

How agents save work in git.
Read this page before a git action.
A direct word from the person wins over this page.

## Where history lives

- The system home is `~/.foxrun/`. The portfolio is `~/foxrun/`. Each workspace and each app can be its own repo.
- Commit in the repo that owns the file.
- Do not edit an installed file in `~/.foxrun/`. An update replaces it.
- A starter file, such as this page, belongs to the person after install. A local file is the person's only and never ships.
- No program saves for you. Commit your own work.

## Act

- Commit finished, checked work. Put the task id in the message.
- Do not ask the person about a commit.
- Stage each file by its name.
- Pull before you push.
- Push to a branch of the person's own private repositories.
- Merge when the tests pass and a second agent, not the author, read the change. The lead of the work merges.

## Ask first

- A new GitHub repository, or a change to a GitHub setting.
- A deploy. Deploy only committed code, from a clean copy.

## Do not

Only a direct word from the person in the session overrides this list.

- Force push.
- In a tree other agents use: `git add -A`, `git add .`, `stash`, `checkout`, `switch`, `reset`, `rebase`, or `clean`.
- Make a worktree.
- Commit a secret, a `.env` file, an auth file, a key file, or a database.
- Delete work that you did not make. Archive it.

## Skills

Skills change only through `skillify` and `skill-ship`.
`skill-ship` runs the checks and makes the release.

## Heading guard scope

`law_file_guard.py` and `merge_pr.py` read this section.
A merge through `merge_pr.py` needs a GitHub remote and a pull request.

- Any `AGENTS.md`.
- Root `CLAUDE.md`, `RESOLVER.md`, `GLOSSARY.md`, and `SCHEMA.md`.
- Every Markdown file under `~/.foxrun/config/`, `~/.foxrun/profile/`, and `~/.foxrun/skillwright/standards/`, except `drafts/` and `scratch/`.
- Exclude `outputs/`, `handoffs/`, `state/`, `inbox/`, `scratch/`, and `archive/`.

## Recovery

- Find a version: `git log -- <file>` in the repo that owns it.
- Get it back: `git show <commit>:<file>`.
- A task's backups are in `~/.foxrun/backups/`.

Your own git rules: `config/git.local.md`.
