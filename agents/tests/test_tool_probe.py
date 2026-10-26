import sys
from pathlib import Path as _SupportPath
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[2] / "base"))
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1]))
# agents/ goes ahead of base/ so tests.support is this folder, not base/tests (collision since 9e44892 T595)
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1] / "tools"))
from tests.support import function_suite
import datetime as dt
import json
import os
from pathlib import Path

import simple_yaml as yaml


def make_hermes(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    hermes = bin_dir / "hermes"
    hermes.write_text(
        """#!/bin/sh
name="$5"
case "$name" in
  healthy) echo "connection healthy"; exit 0 ;;
  broken) echo "server failed" >&2; exit 7 ;;
  oauth) echo "OAuth login required: not authenticated"; exit 1 ;;
  slow) sleep 1; echo "late"; exit 0 ;;
esac
exit 9
""",
        encoding="utf-8",
    )
    hermes.chmod(0o755)
    return bin_dir


def write_profile(home: Path, external_dir: Path) -> None:
    profile = home / "profiles" / "example-lead"
    profile.mkdir(parents=True)
    config = {
        "mcp_servers": {
            "healthy": {"enabled": True},
            "broken": {"enabled": True},
            "oauth": {"enabled": True},
            "slow": {"enabled": True},
            "parked": {"enabled": False},
        },
        "skills": {"external_dirs": [str(external_dir), str(home / "absent")]},
    }
    (profile / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


def test_classifies_all_states_and_writes_reports(tmp_path, monkeypatch):
    import tool_probe

    home = tmp_path / "state" / "hermes"
    skills = tmp_path / "skills"
    (skills / "one").mkdir(parents=True)
    (skills / "two").mkdir()
    (skills / "one" / "SKILL.md").write_text("one", encoding="utf-8")
    (skills / "two" / "SKILL.md").write_text("two", encoding="utf-8")
    write_profile(home, skills)
    bin_dir = make_hermes(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    result = tool_probe.probe_profile(
        "example-lead",
        timeout=0.3,
        hermes_home=home,
        agent_team_root=tmp_path,
        now=dt.datetime(2026, 9, 8, 7, 30, tzinfo=dt.timezone.utc),
    )

    states = {item["tool"]: item["state"] for item in result["tools"]}
    assert states == {
        "healthy": "ok",
        "broken": "failed",
        "oauth": "not_connected",
        "slow": "timeout",
        "parked": "disabled",
    }
    assert result["exit_code"] == 4
    assert result["external_dirs"][0]["skill_count"] == 2
    assert result["external_dirs"][1]["exists"] is False
    json_path = Path(result["reports"]["json"])
    md_path = Path(result["reports"]["markdown"])
    assert json.loads(json_path.read_text(encoding="utf-8"))["profile"] == "example-lead"
    markdown = md_path.read_text(encoding="utf-8")
    assert "| tool | state | seconds | note |" in markdown
    assert "not connected" in markdown
    assert "not claimed working" in markdown


def test_exit_zero_when_only_allowed_states(tmp_path, monkeypatch):
    import tool_probe

    home = tmp_path / "state" / "hermes"
    profile = home / "profiles" / "example-lead"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text(
        yaml.safe_dump({"mcp_servers": {
            "healthy": {"enabled": True},
            "oauth": {"enabled": True},
            "parked": {"enabled": False},
        }}),
        encoding="utf-8",
    )
    bin_dir = make_hermes(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    result = tool_probe.probe_profile(
        "example-lead", hermes_home=home, agent_team_root=tmp_path
    )
    assert result["exit_code"] == 0


def test_cli_json_output(tmp_path, monkeypatch, capsys):
    import tool_probe

    home = tmp_path / "state" / "hermes"
    profile = home / "profiles" / "example-lead"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("mcp_servers: {}\n", encoding="utf-8")
    monkeypatch.setenv("FOXRUN_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FOXRUN_HOME", str(tmp_path))
    code = tool_probe.main(["example-lead", "--json"])
    assert code == 2
    assert capsys.readouterr().out == "Claude and Codex on day one.\n"


def test_missing_config_exits_four(tmp_path, monkeypatch, capsys):
    import tool_probe

    monkeypatch.setenv("FOXRUN_STATE", str(tmp_path / "missing"))
    monkeypatch.setenv("FOXRUN_HOME", str(tmp_path))
    assert tool_probe.main(["ghost"]) == 2
    assert capsys.readouterr().out == "Claude and Codex on day one.\n"


def load_tests(loader, tests, pattern):
    return function_suite(globals(), {})
