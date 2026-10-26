---
type: doc
workspace: system
timestamp: 2026-10-24T16:10:09-04:00
---
# Retained history proof

This is a bounded migration proof helper, not a production write or routing command.
It reads the existing `activity` and `approvals` schemas from explicit SQLite stores.
History identity is `(source_store, table, source_id)`; ambiguous bare IDs fail.
Two aliases for the same physical source file fail, including hardlinks.

Each store has its own read transaction. The result is not a cross-store atomic snapshot.
The helper preserves exact selected rows in a new bundle and a separate digest receipt.
Existing output files are never overwritten. Source rows never change.
The caller must choose a private output directory outside the vault and Git repositories.
This helper does not enforce that directory policy or install an automatic route.
Use a directory with mode `0700`; created payload files use mode `0600`.

```text
python3 history_proof.py export --store one=/private/path/one.sqlite \
  --store two=/private/path/two.sqlite --scope task=example \
  --qualified one:approvals:17 --qualified two:approvals:17 \
  --bundle /private/path/output/history.json \
  --receipt /private/path/output/export-receipt.json
python3 history_proof.py verify --bundle /private/path/output/history.json \
  --expected-sha256 <independently-retained-sha256>
```

Export requires actual source identities; these names and IDs are examples.
Keep the expected whole-bundle digest separately from the bundle.
An embedded hash alone cannot detect a modified payload whose hashes were recomputed.
Hashes detect drift. They are not signatures, approval, or authentication.

`lookup` requires a qualified ID and writes an exact row into a new private output file.
It prints identity and hash metadata, not history bodies.
`real-proof` is the narrowly scoped two-store dependency check for this foundation run.
It checks each store's approval ID 17 and one deterministic subject scope per store.
If the stores have no common subject, it records that limit instead of inventing one.
Synthetic tests cover a shared subject across stores and offline reads after source removal.

On write failure, preserve the reported output paths for review.
Receipt failure removes the bundle only while its checked inode and content still match.
Concurrent changes cause refusal and remain preserved; no multi-file atomicity is claimed.
Keep these outputs in a private directory with no concurrent writers.

The foundation review of 2026-09-20 records the tested revision and limits. That review stays in Foxrun HQ and does not ship.
No database split, history migration, consumer transition, task acceptance, or live deployment follows from this proof.
