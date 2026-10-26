---
type: note
workspace: system
timestamp: 2026-10-26T14:30:00-04:00
name: git
description: "Commit, open a pull request, merge, or clean up branches under the git law in ~/.foxrun/config/git.md, and make a worktree only on a direct word. Merge always runs the law check first. Use for /git commit, /git pr, /git merge, /git clean, /git worktree, or when someone says commit this or merge it."
kind: knowledge
argument-hint: "commit | pr | merge | clean | worktree"
---

# git

One skill for git work in the Portfolio and the system home. The law is `~/.foxrun/config/git.md`; read it before a git action.
A direct word from the person wins over the law, except the secret rules.
Commit in the repo that owns the file. Other agents may share the tree, so touch only your own files.

## Steps

1. **Commit.** Run `git status` and `git diff` on your files. Stage each file by name: `git add <path> <path>`. Never `git add -A` or `git add .` in a shared tree. Write a message that starts with the task id and says what changed and why. End with the attribution line your runtime gives. Done when `git log -1 --stat` shows only your files.
2. **Pull request.** Pull before you push. Push to a branch of the person's own private repository; never force push. Open the pull request with `gh pr create`. The body says what changed, how you checked it, and the task id. Done when `gh pr view` prints the link.
3. **Merge.** Merge only when the tests pass and a second agent, not the author, read the change. Run the law check first: `python3 ~/.foxrun/base/merge_pr.py <pr number> --path <a changed path> --check-only`. A `FAIL` means the change removed protected law with no successor line. Restore the section, or add one exact line to the pull request body: `Replaces: <old heading> -> <new heading or path>` or `Retires: <old heading> — <reason>`. When the check passes, run the guard again without `--check-only`. Done when the guard merged and pulled.
4. **Clean.** List branches whose remote is gone: `git fetch --prune`, then `git branch -vv | grep ': gone]'`. Show the list. Delete a branch only when its work is merged or backed up, with `git branch -d <branch>`. Done when each gone branch is deleted or named as kept.
5. **Worktree.** The law says do not make a worktree. Make one only on the person's direct word in this session: `git worktree add <path> -b <branch>`. Remove it when the work merges. Done when the worktree exists and its path is in your reply, or the person said no.

## Gotchas

- If `~/.foxrun/base/merge_pr.py` is missing, stop and say so. Do not merge another way.
- Never use plain `gh pr merge` on a Portfolio or system repository. The guard is the only merge path.
- Never commit a secret, a `.env` file, an auth file, a key file, or a database.
- Do not run `stash`, `checkout`, `switch`, `reset`, `rebase`, or `clean` in a tree other agents use.
- Do not edit an installed file in `~/.foxrun/`. Change its source, then install it.
- Do not ask the person before a commit to a branch. Ask before a new repository, a GitHub setting, or a deploy.
