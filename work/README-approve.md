---
type: doc
workspace: system
timestamp: 2026-10-19T19:35:51-04:00
---
# Document approval command

This command promotes explicit Markdown drafts within one supplied root.
It records the exact approved file hash in an existing compatible work database.
It does not authenticate consent or send an approval request.
An explicit identity-source mode supports canonical agent-team identity Markdown only.

The external caller must already possess the required approver's approval for the exact plan and proposed versions.
Person approves contracts. A project lead can approve its specs under the existing contract.
No flag grants approval or replaces that existing authority.
`--confirm-digest`, `--actor`, and approval text only record that external attestation.

## Commands

Run these examples from `foxrun/modules/work`.
Use private-control mode when drafts or prior target bytes are private.
The plan embeds proposed and prior bytes as base64.
The v1 default stores archives and journals below the document root.
That default is suitable only for an explicit sandbox whose contents are already private.

Create a sealed plan and print its complete readable diff:

```sh
python3 tools/approve.py plan \
  --root /explicit/sandbox/root \
  --control-root /explicit/sealed/private-control \
  --db /explicit/existing/work.sqlite \
  --item 'drafts/AGENTS.md::AGENTS.md::remove-staged-tag' \
  --archive-root archives \
  --journal journals/run.json \
  --output /explicit/sealed/private-control/plans/run.json
```

Apply only after the caller verifies the printed diff and holds the exact approval:

```sh
python3 tools/approve.py apply \
  --root /explicit/sandbox/root \
  --control-root /explicit/sealed/private-control \
  --db /explicit/existing/work.sqlite \
  --plan /explicit/sealed/private-control/plans/run.json \
  --confirm-digest PLAN_SHA256 \
  --actor RECORDED_ACTOR \
  --approval-ref EVIDENCE_REFERENCE \
  --approval-text 'Exact approval words or bounded attestation'
```

Read-only lint checks explicit live files against path-bound and SHA-256-bound approval rows:

```sh
python3 tools/approve.py lint \
  --root /explicit/sandbox/root \
  --db /explicit/existing/work.sqlite \
  --path AGENTS.md \
  --approval-source-output /explicit/private/approval-source.json
```

Recover a caught partial filesystem apply before any retry:

```sh
python3 tools/approve.py recover \
  --root /explicit/sandbox/root \
  --control-root /explicit/sealed/private-control \
  --plan /explicit/sealed/private-control/plans/run.json \
  --confirm-digest PLAN_SHA256
```

Plan an agent-team identity-source approval with the required private control root:

```sh
python3 tools/approve.py plan \
  --identity-source \
  --root /explicit/checkout/agent-team \
  --control-root /explicit/sealed/private-control \
  --db /explicit/existing/work.sqlite \
  --item 'drafts/designer.md::agents/designer.md' \
  --archive-root archives \
  --journal journals/designer.json \
  --output /explicit/sealed/private-control/plans/designer.json
```

Apply, recover, and lint that plan with the same `--identity-source` and `--control-root` values.

## Exact behavior

- The plan binds draft, target, prior bytes, proposed bytes, paths, identities, hashes, database schema, approval state, and foreign-key findings.
- Apply revalidates the exact plan structure and all field types.
- Apply recomputes each transform, proposed payload, archive path, and displayed diff from the sealed draft and prior bytes.
- Recomputing a plan digest cannot authorize forged bytes or misleading diff text.
- Apply rechecks every document before its write. It also rechecks the database before its transaction.
- A prior target is copied byte-for-byte to an exclusive archive before replacement.
- Draft sources remain unchanged.
- Each document gets one `approvals` row and one `activity` row in one SQLite transaction.
- Successful exact replay returns `duplicate`. It adds no rows.
- Lint emits the existing `{"approvals":[{"file", "sha256", "approval"}]}` source shape.
- Existing foreign-key defects stay unchanged. New or changed findings invalidate the plan.
- Only the reviewed work-module approvals and activity table definitions are supported.
- Their definitions and indexes are bound into the schema hash.
- Any write-side trigger on those tables is refused. The selected current database has no such trigger.
- A plan accepts 1 through 64 documents. A 40-document promotion is tested.

## Private-control mode

`--control-root` selects the `v2-private-control` plan format.
Drafts, archives, journals, and the CLI plan output stay below that control root.
Live document paths stay below `--root`.
The two roots must be existing, physical, non-symlink, and non-overlapping directories.
The plan binds both root paths and directory identities.
Apply, replay, and recovery require the exact bound control root.
They recheck draft, archive, journal, and live paths through their respective roots.
The CLI refuses a private plan file or output outside the control root.
Files cannot cross either boundary through symlinks or hardlinks.

Plans with format `foxrun-document-approval-plan/v1` keep their original same-root meaning.
Passing `--control-root` with a v1 plan fails instead of changing its meaning.
A private-control plan also fails when `--control-root` is absent.

## Agent identity-source mode

`--identity-source` selects `foxrun-agent-team-identity-approval-plan/v1-private-control`.
The repository root must be named `agent-team`.
Each target must be one exact `agents/<safe-id>.md` source path.
The command records `subject_type=contract`.
The canonical subject ID is `agent-team/agents/<safe-id>.md`.
The version is the full proposed file SHA-256.
Draft, target, archive, journal, database, and control-root bindings remain sealed.
The mode permits no metadata transform.
It does not parse identity meaning; the existing agent-team parser owns that check.
It does not render, activate, or write SOUL, cape, profile, config, or runtime files.
Exact source approval does not authorize runtime application.

Identity-source mode is required on plan, apply, recovery, and lint commands.
A document plan cannot target an `agent-team/agents/<safe-id>.md` source.
This prevents a contract subject from becoming a document subject through plan reinterpretation.
Existing contract approvals remain unchanged.
Legacy version labels such as `v5 cbe0e34` do not satisfy exact SHA-256 lint.
Their separate source and commit evidence remains outside this command.

The default transform is `none`. It preserves all draft metadata.
`remove-status` removes one simple top-level `status` field only.
`remove-staged-tag` removes only an exact top-level `tags: [staged]` field.
Each transform appears as its own source-to-proposed diff before the live-file diff.
Multiline or ambiguous metadata fails closed.

## Recovery limit

Filesystem writes and SQLite commits are not one atomic operation.
The persistent journal records preparation, each completed target, errors, database commit detection, recovery, and completion.
Caught failures preserve a reviewable partial state.
Recovery restores only candidate-written target identities and preserves concurrent changes.

A hard process or power loss can occur after a filesystem mutation and before the next journal update.
Recovery now compares every live path with its sealed prior and proposed states.
An unrecorded candidate write returns `manual review`; it never returns `recovered`.
Recovery repeats the recorded target identity and hash check at the mutation point.
It rereads and rehashes each archive before restoring prior bytes.
New-target removal checks the complete recorded identity and proposed hash.

Items that failed before any archive or target write use an `untouched` journal state.
Repeated recovery does not invent a missing archive for those items.

The candidate rechecks a live file after archive and journal writes.
It verifies every written target and archive before approval inserts and again before commit.
A non-cooperating writer can still change that file between the final check and atomic replacement.
The CLI cannot provide a universal no-loss guarantee without shared locking.

The plan hashes every existing `activity` and `approvals` row.
An unrelated activity append invalidates the plan.
This conservative behavior is a known usability limit.

This command supports explicit Markdown documents and the narrow agent-team identity-source mode.
This delivery excludes runtime files, rendered native identities, configurations, and financial data.
Path checks are not a general authorization system; the caller must enforce those scope boundaries.
The command writes only approval and activity database rows.
It creates no database and performs no migration.

## Retained fixture rehearsal

`approve_rehearsal.py` uses labeled fixture documents below the supplied vault's `foxrun/scratch/`.
It keeps its fixture database, drafts, archives, plan, journal, and receipt below a separate supplied run root.
Its consent always says `SIMULATED CONSENT`. It grants no real approval.
The rehearsal checks the diff, confirmation refusal, preserved bytes, exact rows, lint, and repeated application.
It retains every fixture. The staging core database remains separate from this fixture database.

```sh
python3 tools/approve_rehearsal.py --vault /absolute/staging/vault --run-root /absolute/staging/test-runs
```

Approval lint exits 1 when any selected document lacks an exact approval binding.
It exits 0 only when every selected document has that binding. Run errors exit 2.

Use `lint --discover` to select every active contract and every live Markdown spec under `docs/specs/`.
It uses the contract lint rule file. Drafts, `.new` documents, history, and protected paths stay outside discovery.
`--discover` cannot combine explicit paths or identity-source mode.
The rehearsal plants an unapproved live spec without naming it in the command.
