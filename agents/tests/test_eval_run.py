from __future__ import annotations
import sys
from pathlib import Path as _SupportPath
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[2] / "base"))
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1]))
# agents/ goes ahead of base/ so tests.support is this folder, not base/tests (collision since 9e44892 T595)
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1] / "tools"))

from tests.support import function_suite

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import simple_yaml as yaml

import eval_run


def completed(stdout: str = "", code: int = 0, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


class FakeRunner:
    def __init__(self, identities: list[dict[str, object]]) -> None:
        self.identities = identities
        self.drift: set[str] = set()
        self.live_failures: dict[str, str] = {}
        self.probed: list[str] = []
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0

    def __call__(self, command: list[str], **_: object) -> SimpleNamespace:
        if "unittest" in command and "-m" in command:
            return completed("Ran 31 tests in 0.42s\nOK\n")
        if "agent_new.py" in command[1]:
            action = command[2]
            if action == "list":
                return completed(json.dumps({"identities": self.identities}))
            identity = command[3]
            if action == "diff":
                if identity in self.drift:
                    return completed(json.dumps({"diff": "changed"}), 3)
                return completed(json.dumps({"diff": ""}))
            if action == "probe":
                with self._lock:
                    self.probed.append(identity)
                    self._active += 1
                    self.max_active = max(self.max_active, self._active)
                time.sleep(0.01)
                failed_runtime = self.live_failures.get(identity)
                runtimes = str(next(row["runtimes"] for row in self.identities if row["id"] == identity)).split(",")
                results = [
                    {"runtime": runtime, "ok": runtime != failed_runtime}
                    for runtime in runtimes
                ]
                with self._lock:
                    self._active -= 1
                return completed(
                    json.dumps({"id": identity, "results": results}),
                    4 if failed_runtime else 0,
                )
        raise AssertionError(f"unexpected command: {command}")


def make_world(tmp_path: Path) -> tuple[dict[str, Path], list[dict[str, object]]]:
    repo = tmp_path / "agents"
    vault = tmp_path / "vault"
    hermes = tmp_path / "hermes"
    release = tmp_path / "releases" / "release-good"
    shelf = tmp_path / "shelf"
    for path in (repo / "tests", repo / "execution", vault, hermes, release):
        path.mkdir(parents=True, exist_ok=True)
    shelf.symlink_to(release, target_is_directory=True)
    (repo / "execution" / "skills.yaml").write_text(
        yaml.safe_dump({"release": release.name}), encoding="utf-8"
    )
    identities = []
    for index in range(7):
        identity = f"agent-{index}"
        identities.append(
            {
                "id": identity,
                "hermes_mode": "profile" if index == 0 else "kanban" if index == 1 else "child",
                "runtimes": "hermes,claude,codex",
            }
        )
        for runtime, suffix in (("claude", ".md"), ("codex", ".toml")):
            # capes live where agent_new renders system seats since 4a024f1 (T740)
            cape = tmp_path / "runs/generated/agents" / runtime / f"{identity}{suffix}"
            cape.parent.mkdir(parents=True, exist_ok=True)
            cape.write_text("managed-by: agent-new\n", encoding="utf-8")
    return {"system": tmp_path, "repo": repo, "vault": vault, "hermes": hermes, "shelf": shelf}, identities


def step(result: dict[str, object], name: str) -> dict[str, object]:
    return next(item for item in result["steps"] if item["name"] == name)  # type: ignore[index]


def test_pass_writes_json_and_markdown_evidence(tmp_path: Path) -> None:
    roots, identities = make_world(tmp_path)
    result = eval_run.run_eval(runner=FakeRunner(identities), root_map=roots)

    assert result["verdict"] == "PASS"
    assert all(item["ok"] for item in result["steps"])
    assert step(result, "unit tests")["detail"] == "31 passed"
    assert step(result, "identity list")["detail"] == "7 identities"
    assert step(result, "profile drift")["detail"] == "2/2 profiles match"
    assert step(result, "managed capes")["detail"] == "14/14 capes managed"
    json_path = Path(result["reports"]["json"])
    markdown_path = Path(result["reports"]["markdown"])
    assert json.loads(json_path.read_text(encoding="utf-8"))["verdict"] == "PASS"
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "| step | ok | seconds | detail |" in markdown
    assert "Verdict: PASS" in markdown
    assert result["rerun"] in markdown


def test_drift_fails_the_eval(tmp_path: Path) -> None:
    roots, identities = make_world(tmp_path)
    runner = FakeRunner(identities)
    runner.drift.add("agent-1")

    result = eval_run.run_eval(runner=runner, root_map=roots)

    assert result["verdict"] == "FAIL"
    assert step(result, "profile drift")["ok"] is False
    assert "agent-1" in step(result, "profile drift")["detail"]


def test_missing_cape_fails_the_eval(tmp_path: Path) -> None:
    roots, identities = make_world(tmp_path)
    missing = roots["system"] / "runs/generated/agents/codex/agent-3.toml"
    missing.unlink()

    result = eval_run.run_eval(runner=FakeRunner(identities), root_map=roots)

    assert result["verdict"] == "FAIL"
    assert step(result, "managed capes")["ok"] is False
    assert "agent-3/codex missing" in step(result, "managed capes")["detail"]


def test_pin_mismatch_warns_without_failing(tmp_path: Path) -> None:
    roots, identities = make_world(tmp_path)
    (roots["repo"] / "execution" / "skills.yaml").write_text(
        yaml.safe_dump({"release": "release-old"}), encoding="utf-8"
    )

    result = eval_run.run_eval(runner=FakeRunner(identities), root_map=roots)

    pin = step(result, "skill pin")
    assert result["verdict"] == "PASS"
    assert pin["ok"] is True
    assert pin["detail"].startswith("WARN:")
    assert "release-old" in pin["detail"]
    assert "release-good" in pin["detail"]


def test_live_aggregates_every_identity_and_runtime_with_max_three_workers(tmp_path: Path) -> None:
    roots, identities = make_world(tmp_path)
    runner = FakeRunner(identities)
    runner.live_failures["agent-4"] = "codex"

    result = eval_run.run_eval(live=True, runner=runner, root_map=roots)

    live = step(result, "live probes")
    assert result["verdict"] == "FAIL"
    assert live["ok"] is False
    assert "agent-4/codex" in live["detail"]
    assert sorted(runner.probed) == sorted(str(row["id"]) for row in identities)
    assert runner.max_active <= 3


def load_tests(loader, tests, pattern):
    return function_suite(globals(), {})
