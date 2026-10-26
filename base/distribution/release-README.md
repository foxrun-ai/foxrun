# Workspace Install

This release contains core packs at blueprint version 12. Each pack's install manifest decides whether it ships.
Cedar Shop is a made-up ecommerce sample for garden tools.
The install creates one core data.db and the sample workspace under Workspaces/cedar-shop.
Each installed-module row records its version. The data/ files are exports, never the source.

Place fetch_install.py beside manifest.json and the release archive.
Run one command from that folder:

```sh
python3 fetch_install.py --manifest manifest.json --manifest-sha256 <hash> --home /path/to/clean-home
```

Use an explicit empty home. The installer preserves changed existing files and databases.
Run the same command again to verify the same install without changes.
The fetch command checks the archive hash, file hashes, and exact file list before extraction.
--manifest-sha256 is required. Get the manifest hash from the release owner by another channel than the release address.
The command refuses a manifest with another hash, and a redirect away from HTTPS.
The install needs Python 3.11+ and SQLite 3.37+. It uses the standard library.
The optional agent-team generator needs PyYAML when you run it.
No agent identity, runtime settings, outside account, feeder, or schedule is installed.
Contract templates are shipped reference files. The sample uses its own made-up contracts.
The manifest marks files changing tonight. Rebuild and repeat the privacy sweep after their final commits.
This is in review, ready for your yes. A public release and a real second machine remain later checks.
