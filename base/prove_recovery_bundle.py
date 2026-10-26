#!/usr/bin/env python3
"""Create and retain one full synthetic private recovery proof under /tmp."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from contextlib import closing

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
support = None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    import argparse, importlib.util
    global support
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture-support', type=Path, default=Path(__file__).resolve().parent / 'tests/test_recovery_bundle.py')
    args = parser.parse_args()
    if not args.fixture_support.is_file():
        print('Synthetic fixture support is missing. Supply --fixture-support PATH to test_recovery_bundle.py.', file=sys.stderr)
        return 2
    spec = importlib.util.spec_from_file_location('recovery_proof_support', args.fixture_support)
    support = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = support
    spec.loader.exec_module(support)
    root = Path(tempfile.mkdtemp(prefix="private-recovery-proof-")).resolve()
    source = support.full_source(root)
    bundle = root / "private-bundle"
    created = support.recovery.create_bundle(
        source,
        bundle,
        support.ALL_MODULES,
        build_tool=support.build_database,
    )
    target = root / "restored.sqlite"
    restored = support.recovery.restore_bundle(
        bundle,
        target,
        support.ALL_MODULES,
        build_tool=support.build_database,
    )
    rows_equal = support.logical_rows(source) == support.logical_rows(target)
    with (
        closing(_fox_person.connect(source)) as source_db,
        closing(_fox_person.connect(target)) as target_db,
    ):
        source_db.row_factory = sqlite3.Row
        target_db.row_factory = sqlite3.Row
        schema_equal = (
            support.recovery._schema_entries(source_db)
            == support.recovery._schema_entries(target_db)
        )
        metadata_equal = (
            support.recovery._sqlite_metadata(source_db)
            == support.recovery._sqlite_metadata(target_db)
        )
        foreign_keys = [tuple(row) for row in target_db.execute("PRAGMA foreign_key_check")]
        integrity = target_db.execute("PRAGMA integrity_check").fetchone()[0]
        mirror_counts = {
            table: target_db.execute(
                "SELECT COUNT(*) FROM " + support.recovery.core.quote_identifier(table)
            ).fetchone()[0]
            for table in (
                "messages",
                "products",
                "orders",
                "order_lines",
                "shipments",
                "stock_levels",
                "customer_reviews",
                "listings",
                "ads_campaigns",
                "media_files",
                "tiktok_orders",
            )
        }
        proposal_count = target_db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        trigger_history = [
            tuple(row)
            for row in target_db.execute(
                "SELECT id,item_id,action FROM runtime_item_history ORDER BY id"
            )
        ]
        sparse_rowids = [
            tuple(row)
            for row in target_db.execute(
                "SELECT rowid,label FROM runtime_sparse ORDER BY rowid"
            )
        ]
        payload = target_db.execute(
            "SELECT hex(payload),note,typeof(payload) FROM runtime_payloads"
        ).fetchone()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    result = {
        "fixture_root": str(root),
        "source": str(source),
        "source_sha256": sha256(source),
        "bundle": str(bundle),
        "manifest": str(bundle / "manifest.json"),
        "manifest_sha256": manifest["manifest_sha256"],
        "target": str(target),
        "target_sha256": sha256(target),
        "logical_rows_equal": rows_equal,
        "schema_equal": schema_equal,
        "sparse_rowids": sparse_rowids,
        "metadata_equal": metadata_equal,
        "foreign_key_violations": foreign_keys,
        "integrity": integrity,
        "mirror_counts": mirror_counts,
        "proposal_count": proposal_count,
        "trigger_history": trigger_history,
        "runtime_blob": tuple(payload),
        "created": created,
        "restored": restored,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    passed = (
        rows_equal
        and schema_equal
        and metadata_equal
        and not foreign_keys
        and integrity == "ok"
        and all(count > 0 for count in mirror_counts.values())
        and proposal_count == 1
        and trigger_history == [(1, 1, "created")]
        and sparse_rowids == [(3, "three"), (19, "nineteen")]
        and payload[2] == "blob"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
