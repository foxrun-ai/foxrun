from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

import hashlib
import importlib.util
import inspect
import json
import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class _Raises:
    def __init__(self, error, match=None):
        self.error = error
        self.match = match

    def __enter__(self):
        return self

    def __exit__(self, error_type, error, traceback):
        if error_type is None:
            raise AssertionError(f"{self.error.__name__} was not raised")
        if not issubclass(error_type, self.error):
            return False
        if self.match and not re.search(self.match, str(error)):
            raise AssertionError(f"{str(error)!r} does not match {self.match!r}")
        return True


class _Mark:
    @staticmethod
    def parametrize(name, values):
        def decorate(function):
            function._unittest_parameters = (name, values)
            return function
        return decorate


class _PytestCompatibility:
    mark = _Mark()
    raises = _Raises

    @staticmethod
    def fixture(function):
        return function


try:
    import pytest
except ImportError:
    pytest = _PytestCompatibility()


class _MonkeyPatch:
    def __init__(self):
        self.patches = []

    def setattr(self, target, name, value):
        patch = mock.patch.object(target, name, value)
        patch.start()
        self.patches.append(patch)

    def undo(self):
        for patch in reversed(self.patches):
            patch.stop()


MODULE_PATH = (Path(__file__).resolve().parent / '../../events/history_proof.py')
SPEC = importlib.util.spec_from_file_location("history_proof", MODULE_PATH)
assert SPEC and SPEC.loader
hp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hp)


SCHEMA = """
CREATE TABLE activity (
 id INTEGER PRIMARY KEY AUTOINCREMENT, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
 field TEXT, old_value TEXT, new_value TEXT, actor TEXT NOT NULL, source TEXT, at TEXT NOT NULL, note TEXT
);
CREATE TABLE approvals (
 id INTEGER PRIMARY KEY AUTOINCREMENT, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
 version TEXT, call TEXT NOT NULL CHECK (call IN ('approve','discuss','wrong','edit')),
 person_words TEXT, given_at TEXT NOT NULL, source TEXT
);
"""


def make_db(path: Path, label: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    connection.executemany(
        "INSERT INTO activity(id,subject_type,subject_id,field,old_value,new_value,actor,source,at,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
        [
            (7, "task", "shared", "status", "todo", "in-progress", label, "test", "2026-01-01T00:00:00Z", f"{label} first"),
            (9, "task", f"only-{label}", "status", None, "todo", label, "test", "2026-01-03T00:00:00Z", None),
        ],
    )
    connection.execute(
        "INSERT INTO approvals(id,subject_type,subject_id,version,call,person_words,given_at,source) VALUES(17,?,?,?,?,?,?,?)",
        ("task", "shared", "v1", "approve", f"approval {label}", "2026-01-02T00:00:00Z", "test"),
    )
    connection.commit()
    connection.close()


def make_stores(tmp_path: Path) -> dict[str, Path]:
    one = tmp_path / "one.sqlite"
    two = tmp_path / "two.sqlite"
    make_db(one, "one")
    make_db(two, "two")
    return {"one": one, "two": two}


@pytest.fixture
def stores(tmp_path: Path) -> dict[str, Path]:
    return make_stores(tmp_path)


def export(tmp_path: Path, stores: dict[str, Path]):
    bundle = tmp_path / "history.json"
    receipt = tmp_path / "receipt.json"
    result, hashes = hp.export_bundle(
        stores, [("task", "shared")],
        [("one", "approvals", 17), ("two", "approvals", 17)],
        bundle, receipt,
    )
    return bundle, receipt, result, hashes


def rewrite_bundle(path: Path, bundle: dict) -> str:
    for schema in bundle["stores"].values():
        payload = {key: value for key, value in schema.items() if key != "schema_sha256"}
        schema["schema_sha256"] = hp.sha256_bytes(hp.canonical_bytes(payload))
    for record in bundle["records"]:
        record["row_sha256"] = hp.sha256_bytes(hp.canonical_bytes(record["row"]))
    bundle["records_sha256"] = hp.sha256_bytes(hp.canonical_bytes(bundle["records"]))
    bundle["counts"] = hp._counts(bundle["records"])
    raw = hp.canonical_bytes(bundle) + b"\n"
    path.write_bytes(raw)
    return hp.sha256_bytes(raw)


def test_source_qualified_ids_preserve_collisions_and_subjects(tmp_path: Path, stores):
    bundle_path, _, receipt, hashes = export(tmp_path, stores)
    bundle = hp.read_bundle(bundle_path, receipt["expected_bundle_sha256"])
    ids = {record["qualified_id"] for record in bundle["records"]}
    assert "one:approvals:17" in ids
    assert "two:approvals:17" in ids
    assert len(bundle["records"]) == 4
    assert len(hashes) == 4
    subject = hp.bundle_subject_history(bundle, "task", "shared")
    assert {record["source_store"] for record in subject} == {"one", "two"}


def test_deterministic_order_and_repeat_dedup(tmp_path: Path, stores):
    with hp.readonly_stores(stores) as connections:
        records = hp.subject_history(connections, "task", "shared")
        assert [record["event_time"] for record in records] == sorted(record["event_time"] for record in records)
    bundle, _ = hp.build_bundle(
        stores, [("task", "shared"), ("task", "shared")],
        [("one", "approvals", 17), ("one", "approvals", 17)],
    )
    assert len(bundle["records"]) == 4


def test_bare_id_is_ambiguous_and_explicit_lookup_is_exact(stores):
    with hp.readonly_stores(stores) as connections:
        with pytest.raises(hp.HistoryError, match="ambiguous bare ID"):
            hp.lookup_bare(connections, "approvals", 17)
        one = hp.lookup_qualified(connections, "one", "approvals", 17)
        two = hp.lookup_qualified(connections, "two", "approvals", 17)
        assert one["row_sha256"] != two["row_sha256"]


def test_offline_read_matches_live_hashes_after_sources_removed(tmp_path: Path, stores):
    bundle_path, _, receipt, live_hashes = export(tmp_path, stores)
    for path in stores.values():
        path.unlink()
    bundle = hp.read_bundle(bundle_path, receipt["expected_bundle_sha256"])
    offline_hashes = {record["qualified_id"]: record["row_sha256"] for record in bundle["records"]}
    assert live_hashes == offline_hashes
    assert hp.bundle_lookup(bundle, "one:approvals:17")["row_sha256"] == live_hashes["one:approvals:17"]


def test_tampered_rehashed_payload_fails_external_digest(tmp_path: Path, stores):
    bundle_path, _, receipt, _ = export(tmp_path, stores)
    bundle = json.loads(bundle_path.read_text())
    bundle["records"][0]["row"]["note"] = "tampered"
    bundle["records"][0]["row_sha256"] = hp.sha256_bytes(hp.canonical_bytes(bundle["records"][0]["row"]))
    bundle["records_sha256"] = hp.sha256_bytes(hp.canonical_bytes(bundle["records"]))
    bundle_path.write_bytes(hp.canonical_bytes(bundle) + b"\n")
    with pytest.raises(hp.HistoryError, match="bundle digest mismatch"):
        hp.read_bundle(bundle_path, receipt["expected_bundle_sha256"])


def test_missing_or_wrong_expected_digest_is_refused(tmp_path: Path, stores):
    bundle_path, _, _, _ = export(tmp_path, stores)
    with pytest.raises(hp.HistoryError, match="expected SHA-256"):
        hp.read_bundle(bundle_path, "")
    with pytest.raises(hp.HistoryError, match="bundle digest mismatch"):
        hp.read_bundle(bundle_path, "0" * 64)


def test_export_is_no_overwrite_and_source_bytes_do_not_change(tmp_path: Path, stores):
    before = {name: hp.file_sha256(path) for name, path in stores.items()}
    bundle_path, receipt_path, _, _ = export(tmp_path, stores)
    with pytest.raises(hp.HistoryError, match="refusing to overwrite"):
        hp.export_bundle(stores, [("task", "shared")], [], bundle_path, receipt_path)
    assert before == {name: hp.file_sha256(path) for name, path in stores.items()}


def test_schema_mismatch_fails_closed(tmp_path: Path):
    bad = tmp_path / "bad.sqlite"
    connection = sqlite3.connect(bad)
    connection.execute("CREATE TABLE activity(id INTEGER PRIMARY KEY, subject_type TEXT, subject_id TEXT)")
    connection.execute("CREATE TABLE approvals(id INTEGER PRIMARY KEY, subject_type TEXT, subject_id TEXT)")
    connection.close()
    with pytest.raises(hp.HistoryError, match="unsupported activity schema"):
        hp.build_bundle({"bad": bad}, [("task", "x")], [])


def test_real_proof_has_only_safe_counts_and_hashes(tmp_path: Path, stores):
    proof = hp.run_real_proof(stores, tmp_path / "bundle.json", tmp_path / "export-receipt.json")
    encoded = json.dumps(proof, sort_keys=True)
    assert "approval one" not in encoded
    assert "approval two" not in encoded
    assert "shared" not in encoded
    assert proof["approval_17"]["distinct_qualified_rows"] is True
    assert proof["offline_verification"]["live_offline_row_hashes_equal"] is True
    assert proof["source_snapshot"]["consistency"] == (
        "per-store read transactions; not a cross-store atomic snapshot"
    )


def test_real_proof_reports_no_common_subject_without_guessing(tmp_path: Path, stores):
    connection = sqlite3.connect(stores["two"])
    connection.execute("UPDATE activity SET subject_id='different' WHERE subject_id='shared'")
    connection.execute("UPDATE approvals SET subject_id='different' WHERE subject_id='shared'")
    connection.commit()
    connection.close()
    proof = hp.run_real_proof(
        stores, tmp_path / "split-bundle.json", tmp_path / "split-export-receipt.json"
    )
    assert proof["source_snapshot"]["common_subject_across_all_stores"] is False
    assert proof["source_snapshot"]["scope_count"] == 2
    assert proof["source_snapshot"]["stores_in_scope"] == ["one", "two"]


def test_receipt_digest_is_independent_of_bundle(tmp_path: Path, stores):
    bundle_path, receipt_path, receipt, _ = export(tmp_path, stores)
    assert receipt["expected_bundle_sha256"] == hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    bundle = json.loads(bundle_path.read_text())
    assert "expected_bundle_sha256" not in bundle
    assert json.loads(receipt_path.read_text())["expected_bundle_sha256"] == receipt["expected_bundle_sha256"]


def test_hardlink_store_alias_is_rejected_at_cli_and_api_boundaries(tmp_path: Path, stores):
    alias = tmp_path / "alias.sqlite"
    os.link(stores["one"], alias)
    with pytest.raises(hp.HistoryError, match="same physical database"):
        hp.parse_store_specs([f"one={stores['one']}", f"alias={alias}"])
    with pytest.raises(hp.HistoryError, match="same physical database"):
        with hp.readonly_stores({"one": stores["one"], "alias": alias}):
            pass


def test_receipt_failure_removes_unchanged_bundle_created_by_call(tmp_path: Path, stores):
    bundle_path = tmp_path / "bundle.json"
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text("occupied")
    with pytest.raises(hp.HistoryError, match="refusing to overwrite"):
        hp.export_bundle(stores, [("task", "shared")], [], bundle_path, receipt_path)
    assert not bundle_path.exists()
    assert receipt_path.read_text() == "occupied"


@pytest.mark.parametrize("replace_inode", [False, True])
def test_receipt_failure_preserves_concurrently_changed_bundle(
    tmp_path: Path, stores, monkeypatch, replace_inode: bool,
):
    bundle_path = tmp_path / "bundle.json"
    receipt_path = tmp_path / "receipt.json"
    original_write = hp._exclusive_write

    def fail_receipt(path: Path, data: bytes):
        if Path(path).absolute() == receipt_path.absolute():
            if replace_inode:
                replacement = tmp_path / "replacement"
                replacement.write_bytes(b"concurrent replacement")
                os.replace(replacement, bundle_path)
            else:
                bundle_path.write_bytes(b"concurrent modification")
            raise hp.HistoryError("synthetic receipt failure")
        return original_write(path, data)

    monkeypatch.setattr(hp, "_exclusive_write", fail_receipt)
    with pytest.raises(hp.HistoryError, match="cleanup refused"):
        hp.export_bundle(stores, [("task", "shared")], [], bundle_path, receipt_path)
    expected = b"concurrent replacement" if replace_inode else b"concurrent modification"
    assert bundle_path.read_bytes() == expected


def test_offline_record_requires_declared_store(tmp_path: Path, stores):
    bundle_path, _, _, _ = export(tmp_path, stores)
    bundle = json.loads(bundle_path.read_text())
    record = bundle["records"][0]
    record["source_store"] = "ghost"
    record["qualified_id"] = f"ghost:{record['table']}:{record['source_id']}"
    digest = rewrite_bundle(bundle_path, bundle)
    with pytest.raises(hp.HistoryError, match="undeclared store"):
        hp.read_bundle(bundle_path, digest)


def test_offline_record_requires_table_in_declared_store_schema(tmp_path: Path, stores):
    bundle_path, _, _, _ = export(tmp_path, stores)
    bundle = json.loads(bundle_path.read_text())
    approval = next(record for record in bundle["records"] if record["table"] == "approvals")
    del bundle["stores"][approval["source_store"]]["tables"]["approvals"]
    digest = rewrite_bundle(bundle_path, bundle)
    with pytest.raises(hp.HistoryError, match="not declared"):
        hp.read_bundle(bundle_path, digest)


def test_offline_record_keys_must_match_declared_schema(tmp_path: Path, stores):
    bundle_path, _, _, _ = export(tmp_path, stores)
    bundle = json.loads(bundle_path.read_text())
    bundle["records"][0]["row"]["unexpected"] = "value"
    digest = rewrite_bundle(bundle_path, bundle)
    with pytest.raises(hp.HistoryError, match="columns do not match"):
        hp.read_bundle(bundle_path, digest)


def test_offline_event_time_must_match_source_row(tmp_path: Path, stores):
    bundle_path, _, _, _ = export(tmp_path, stores)
    bundle = json.loads(bundle_path.read_text())
    bundle["records"][0]["event_time"] = "2099-01-01T00:00:00Z"
    digest = rewrite_bundle(bundle_path, bundle)
    with pytest.raises(hp.HistoryError, match="event time"):
        hp.read_bundle(bundle_path, digest)


def test_offline_source_id_rejects_boolean(tmp_path: Path, stores):
    bundle_path, _, _, _ = export(tmp_path, stores)
    bundle = json.loads(bundle_path.read_text())
    record = bundle["records"][0]
    record["source_id"] = True
    record["row"]["id"] = True
    record["qualified_id"] = f"{record['source_store']}:{record['table']}:1"
    digest = rewrite_bundle(bundle_path, bundle)
    with pytest.raises(hp.HistoryError, match="invalid table or ID"):
        hp.read_bundle(bundle_path, digest)


def test_failed_write_preserves_concurrent_replacement(tmp_path: Path, monkeypatch):
    output = tmp_path / "capture.json"

    def fail_sync(_descriptor):
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(b"concurrent writer")
        os.replace(replacement, output)
        raise OSError("synthetic sync failure")

    monkeypatch.setattr(hp.os, "fsync", fail_sync)
    with pytest.raises(hp.HistoryError, match="retained for review"):
        hp._exclusive_write(output, b"original capture")
    assert output.read_bytes() == b"concurrent writer"


def load_tests(loader, standard_tests, pattern):
    suite = unittest.TestSuite()
    functions = [
        (name, value) for name, value in globals().items()
        if name.startswith("test_") and inspect.isfunction(value)
    ]
    for name, function in sorted(functions):
        parameters = getattr(function, "_unittest_parameters", None)
        for mark in getattr(function, "pytestmark", ()):
            if mark.name == "parametrize":
                parameters = mark.args
        cases = parameters[1] if parameters else (None,)
        for case in cases:
            label = name if parameters is None else f"{name}[{case}]"

            def run(function=function, parameters=parameters, case=case):
                patcher = _MonkeyPatch()
                try:
                    with tempfile.TemporaryDirectory(prefix="history-proof-") as temporary:
                        tmp_path = Path(temporary)
                        values = {
                            "tmp_path": tmp_path,
                            "stores": make_stores(tmp_path),
                            "monkeypatch": patcher,
                        }
                        if parameters:
                            values[parameters[0]] = case
                        accepted = inspect.signature(function).parameters
                        function(**{key: value for key, value in values.items() if key in accepted})
                finally:
                    patcher.undo()

            suite.addTest(unittest.FunctionTestCase(run, description=label))
    return suite
