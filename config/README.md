---
type: doc
workspace: system
---
# Config

| File | Purpose |
|---|---|
| `README.md` | Explains the settings in this folder. |
| `orchestrate.local.json` | Names the Hermes profiles checked on this installation; it stays local. |
| `workspaces.local.json` | Lists your workspaces that keep their own layout; only the shape check skips them. It stays local. |
| `folder-purposes.tsv` | One purpose line for each folder kind that no shared table covers; the index builder reads it. |
| `models.yaml` | Names allowed and banned models per tier and runtime; squad roles own effort. |
| `squads/dev-lean.yaml` | Sets development roles, tiers, and effort when Claude quota is low. |
| `squads/dev-mid.yaml` | Sets contract review roles, tiers, and effort. |
| `templates/profile/AGENTS.md` | Supplies the starter global contract; the installer keeps an existing profile contract. |
| `templates/workspace/AGENTS.md` | Supplies the workspace contract template. |
| `templates/workspace-lead/SKILL.md` | Supplies the generic workspace lead boot; install fills its paths and keeps a taken skill name. |
| `templates/chief/SKILL.md` | Supplies the chief seat boot; install fills the person name and keeps a taken skill name. |
| `templates/chief/replays/read-seat-boot.json` | Checks the chief seat boot reads. |
| `templates/architect/SKILL.md` | Supplies the architect seat boot; install fills the person name and keeps a taken skill name. |
| `templates/architect/replays/read-seat-boot.json` | Checks the architect seat boot reads. |
| `templates/keeper/SKILL.md` | Supplies the keeper seat boot; install fills the person name and keeps a taken skill name. |
| `templates/keeper/replays/read-purpose.json` | Checks the keeper seat boot reads. |
| `templates/toolsmith/SKILL.md` | Supplies the toolsmith seat boot; install fills the person name and keeps a taken skill name. |
| `templates/toolsmith/replays/read-purpose.json` | Checks the toolsmith seat boot reads. |
| `templates/skillwright/SKILL.md` | Supplies the skillwright seat boot; install fills the person name and keeps a taken skill name. |
| `templates/skillwright/replays/read-purpose.json` | Checks the skillwright seat boot reads. |
| `templates/scout/SKILL.md` | Supplies the scout seat boot; install fills the person name and keeps a taken skill name. |
| `templates/scout/replays/read-purpose.json` | Checks the scout seat boot reads. |
| `templates/adviser/SKILL.md` | Supplies the adviser seat boot; install fills the person name and keeps a taken skill name. |
| `templates/adviser/replays/read-purpose.json` | Checks the adviser seat boot reads. |
| `templates/workspace/home.md` | Supplies the workspace overview template. |
