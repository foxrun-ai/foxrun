import sys
from pathlib import Path as _SupportPath
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[2] / "base"))
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1]))
# agents/ goes ahead of base/ so tests.support is this folder, not base/tests (collision since 9e44892 T595)
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1] / "tools"))
from tests.support import function_suite
TEST_CHAT_ID = "-" + "100" + "1234567890"
import datetime as dt
import json
import os
from pathlib import Path

import simple_yaml as yaml


def write_identity(root: Path, identity: str = "example-lead") -> None:
    agents = root
    agents.mkdir(parents=True, exist_ok=True)
    (agents / f"{identity}.md").write_text(
        "---\n" f"id: {identity}\n" "hermes_mode: profile\n"
        f"hermes_profile: {identity}\n" "---\n# Identity\n",
        encoding="utf-8",
    )


def write_topics(root: Path) -> None:
    topics = root / "execution"
    topics.mkdir(parents=True, exist_ok=True)
    (topics / "notifications.yaml").write_text(
        yaml.safe_dump({"hermes_profile": "example-lead", "topics": {1: {"return": "telegram:example-work:1"}}}),
        encoding="utf-8",
    )


def write_agent_new(root: Path, exit_code: int = 0) -> None:
    tools = root
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "agent_new.py").write_text(
        f"import sys\nprint('{{\"state\": \"fixture\"}}')\nsys.exit({exit_code})\n",
        encoding="utf-8",
    )


def write_capes(vault: Path, identity: str = "example-lead", *, complete=True) -> None:
    claude = vault / ".claude" / "agents"
    codex = vault / ".codex" / "agents"
    claude.mkdir(parents=True, exist_ok=True)
    codex.mkdir(parents=True, exist_ok=True)
    marker = "managed-by: agent-new\n"
    (claude / f"{identity}.md").write_text(marker, encoding="utf-8")
    if complete:
        (codex / f"{identity}.toml").write_text(marker, encoding="utf-8")


def make_hermes(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    hermes = bin_dir / "hermes"
    hermes.write_text(
        """#!/bin/sh
if [ "$1 $2 $3 $4 $5 $6" = "-p example-lead send --list telegram " ]; then
  echo "Example chat $TEST_CHAT_ID topic 1 General"
  exit 0
fi
if [ "$1" = "send" ]; then
  printf '%s\\n' "$*" >> "$HERMES_CAPTURE"
  exit 0
fi
exit 9
""",
        encoding="utf-8",
    )
    hermes.chmod(0o755)
    return bin_dir


def clean_probe(profile, **kwargs):
    return {
        "profile": profile,
        "tools": [{"tool": "qmd", "state": "ok", "seconds": 0.01, "note": "ok"}],
        "external_dirs": [],
        "exit_code": 0,
        "reports": {},
    }


def prepare_green(tmp_path: Path):
    root = tmp_path / "repo"
    vault = tmp_path / "vault"
    write_identity(root)
    write_topics(root)
    write_agent_new(root)
    write_capes(vault)
    return root, vault


def test_green_is_quiet_and_exits_zero(tmp_path, capsys):
    import profile_check

    root, vault = prepare_green(tmp_path)
    result = profile_check.run_checks(
        agent_team_root=root,
        vault_root=vault,
        probe_runner=clean_probe,
        utc_now=dt.datetime(2026, 9, 8, 7, 30, tzinfo=dt.timezone.utc),
        local_now=dt.datetime(2026, 9, 8, 3, 30),
    )
    assert result["state"] == "green"
    assert result["exit_code"] == 0
    assert capsys.readouterr().out == ""
    report = root / "generated" / "checks" / "2026-09-08.json"
    assert json.loads(report.read_text(encoding="utf-8"))["state"] == "green"


def test_red_on_drift_exit_three(tmp_path):
    import profile_check

    root, vault = prepare_green(tmp_path)
    write_agent_new(root, exit_code=3)
    result = profile_check.run_checks(
        agent_team_root=root, vault_root=vault, probe_runner=clean_probe
    )
    assert result["state"] == "red"
    assert result["exit_code"] == 2
    assert result["identities"][0]["drift"]["state"] == "drift"


def test_red_on_missing_cape(tmp_path):
    import profile_check

    root = tmp_path / "repo"
    vault = tmp_path / "vault"
    write_identity(root)
    write_topics(root)
    write_agent_new(root)
    write_capes(vault, complete=False)
    result = profile_check.run_checks(
        agent_team_root=root, vault_root=vault, probe_runner=clean_probe
    )
    assert result["state"] == "red"
    assert "codex cape missing" in result["identities"][0]["reasons"]


def test_not_connected_is_yellow(tmp_path):
    import profile_check

    root, vault = prepare_green(tmp_path)
    def disconnected(profile, **kwargs):
        result = clean_probe(profile)
        result["tools"] = [
            {"tool": "eden", "state": "not_connected", "seconds": 0.01, "note": "oauth"}
        ]
        return result
    result = profile_check.run_checks(
        agent_team_root=root, vault_root=vault, probe_runner=disconnected
    )
    assert result["state"] == "yellow"
    assert result["exit_code"] == 1


def test_send_line_is_bounded_and_symbolic_target_resolves(tmp_path, monkeypatch):
    import profile_check

    root, vault = prepare_green(tmp_path)
    write_agent_new(root, exit_code=3)
    capture = tmp_path / "sent.txt"
    bin_dir = make_hermes(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HERMES_CAPTURE", str(capture))
    monkeypatch.setenv("TEST_CHAT_ID", TEST_CHAT_ID)
    result = profile_check.run_checks(
        send=True,
        agent_team_root=root,
        vault_root=vault,
        probe_runner=clean_probe,
        utc_now=dt.datetime(2026, 9, 8, 7, 30, tzinfo=dt.timezone.utc),
        local_now=dt.datetime(2026, 9, 8, 3, 30),
    )
    sent = capture.read_text(encoding="utf-8")
    assert "-t telegram:" + TEST_CHAT_ID + ":1" in sent
    line = sent.split("telegram:" + TEST_CHAT_ID + ":1 ", 1)[1].strip()
    assert line.startswith("agent-team check 2026-09-08: red — example-lead: drift")
    assert len(line) <= 200
    assert result["send"]["resolved_target"] == "telegram:" + TEST_CHAT_ID + ":1"


def test_sunday_green_sends_weekly_summary(tmp_path, monkeypatch):
    import profile_check

    root, vault = prepare_green(tmp_path)
    capture = tmp_path / "sent.txt"
    bin_dir = make_hermes(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HERMES_CAPTURE", str(capture))
    monkeypatch.setenv("TEST_CHAT_ID", TEST_CHAT_ID)
    result = profile_check.run_checks(
        send=True,
        agent_team_root=root,
        vault_root=vault,
        probe_runner=clean_probe,
        utc_now=dt.datetime(2026, 9, 13, 7, 30, tzinfo=dt.timezone.utc),
        local_now=dt.datetime(2026, 9, 13, 3, 30),
    )
    assert result["state"] == "green"
    assert "agent-team weekly: 1 profiles checked, 0 drift, 0 tool failures, 0 open" in capture.read_text(encoding="utf-8")


def test_unresolved_symbolic_target_exits_five(tmp_path, monkeypatch, capsys):
    import profile_check

    root, vault = prepare_green(tmp_path)
    write_agent_new(root, exit_code=3)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    hermes = empty_bin / "hermes"
    hermes.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hermes.chmod(0o755)
    monkeypatch.setenv("PATH", f"{empty_bin}{os.pathsep}{os.environ['PATH']}")
    result = profile_check.run_checks(
        send=True,
        agent_team_root=root,
        vault_root=vault,
        probe_runner=clean_probe,
        utc_now=dt.datetime(2026, 9, 8, 7, 30, tzinfo=dt.timezone.utc),
        local_now=dt.datetime(2026, 9, 8, 3, 30),
    )
    assert result["exit_code"] == 5
    assert capsys.readouterr().out.startswith("agent-team check 2026-09-08: red")


def load_tests(loader, tests, pattern):
    return function_suite(globals(), {})
