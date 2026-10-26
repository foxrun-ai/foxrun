from __future__ import annotations
import sys
from pathlib import Path as _SupportPath
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[2] / "base"))
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1]))
# agents/ goes ahead of base/ so tests.support is this folder, not base/tests (collision since 9e44892 T595)
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1] / "tools"))


import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import unittest
from tests.support import raises, function_suite
import simple_yaml as yaml

import agent_new


POLICY = yaml.safe_load((Path(__file__).resolve().parents[2] / 'config/models.yaml').read_text())

CORE = {
    "core": ["core-skill"],
    "exceptions": {"example-lead": {"keep": ["tp-time-tracking", "tp-weekly-review"], "disable": ["test-driven-development", "spike"]}},
}
BODY = """# {name}

{summary}

## Responsibility
- Own the work.

## Judgment
- Verify facts.

## Style
- Be direct.

## Limits
- Ask the person.

## Return
- Return evidence.
"""


def world(tmp_path, monkeypatch):
    # current behavior since 4a024f1 (T740): system writes pass the ownership guard, so the system home,
    # portfolio, and state are separate trees as installed, and one test seat owns runs/ and agents/.
    home = tmp_path / "home"
    repo = home / "agents"
    vault = tmp_path / "vault"
    hermes = tmp_path / "state" / "hermes"
    shelf = home / "skills"
    for path in (repo  , repo / "execution", repo / "execution" / "teams", repo / "generated", vault, hermes, shelf):
        path.mkdir(parents=True, exist_ok=True)
    (repo.parent / "config").mkdir(exist_ok=True)
    (repo.parent / "config" / "models.yaml").write_text(yaml.safe_dump(POLICY), encoding="utf-8")
    # Core skills and exceptions live in config/catalog.yaml since 4a024f1 (T740), not execution/core-skills.yaml.
    catalog = {"sets": {"base": {"skills": [], "tools": []}}, "exceptions": CORE["exceptions"]}
    (repo.parent / "config" / "catalog.yaml").write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")
    # name, not id: the ownership reader accepts it, and identity discovery skips the page.
    (repo / "test-owner.md").write_text('---\ntype: doc\nname: test-owner\nowns: ["runs", "agents"]\n---\n# Test owner\n', encoding="utf-8")
    monkeypatch.setenv("FOXRUN_SEAT", "test-owner")
    (repo / "execution" / "assignment.schema.json").write_text("{}", encoding="utf-8")
    (repo / "execution" / "result.schema.json").write_text("{}", encoding="utf-8")
    contract = vault / "example-work" / "AGENTS.md"
    contract.parent.mkdir(parents=True)
    contract.write_text("contract", encoding="utf-8")
    team = {"client": "example-work", "lead": "example-lead", "workspace": str(contract.parent), "contract": str(contract)}
    (repo / "execution" / "teams" / "example-work.yaml").write_text(yaml.safe_dump(team), encoding="utf-8")
    monkeypatch.setenv("FOXRUN_HOME", str(repo.parent))
    monkeypatch.setenv("FOXRUN_PORTFOLIO", str(vault))
    monkeypatch.setenv("FOXRUN_STATE", str(tmp_path / "state"))
    return SimpleNamespace(repo=repo, vault=vault, hermes=hermes, shelf=shelf)


def add_set(world, name, skills, tools):
    # Skills and tools come from reviewed catalog sets since 4a024f1 (T740).
    path = world.repo.parent / "config" / "catalog.yaml"
    catalog = yaml.safe_load(path.read_text(encoding="utf-8"))
    catalog["sets"][name] = {"skills": list(skills), "tools": list(tools)}
    path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")


def write_identity(world, agent_id="demo-agent", mode="child", tier="work", skills=None, tools=None, runtimes=None):
    data = {
        "id": agent_id, "display_name": agent_id.replace("-", " ").title(),
        "role": "Owns demo work", "summary": "Runs the demo lane.", "tier": tier,
        "shared": False, "client_default": "example-work",
        "runtimes": runtimes or ["hermes", "claude", "codex"],
        "hermes_mode": mode, "hermes_profile": agent_id if mode in {"profile", "kanban"} else None,
        "skills": skills or [], "tools": tools or [], "return_default": "telegram:example-work:7",
        "version": 1, "type": "agent-soul", "workspace": "example-work",
        "timestamp": "2026-09-08T09:00:00-04:00",
    }
    # current behavior since 4a024f1 (T740): front matter lists are replaced by set expansion,
    # so the identity's own skills and tools become its own catalog set.
    if skills or tools:
        add_set(world, agent_id, skills or [], tools or [])
        data["sets"] = [agent_id]
    body = BODY.format(name=data["display_name"], summary=data["summary"])
    path = world.repo / f"{agent_id}.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n" + body, encoding="utf-8")
    return agent_new.load_identity(agent_id, world.repo)


def fake_result(text="", code=0):
    return SimpleNamespace(returncode=code, stdout=text, stderr="")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_create_refuses_duplicate_and_has_six_sections(world, capsys):
    # current behavior since 4a024f1 (T740): a reviewed set backs --skills/--tools, a workspace client writes
    # <portfolio>/<client>/team/<id>.md, and the body is Identity / What You Own / Judgment with ### subsections.
    add_set(world, "new-work", ["one", "two"], ["qmd"])
    argv = ["create", "new-agent", "--role", "Owns new work", "--summary", "Runs new work.",
            "--tier", "work", "--skills", "one,two", "--tools", "qmd",
            "--client", "example-work", "--runtimes", "claude,codex", "--hermes-mode", "none"]
    assert agent_new.main(argv) == 0
    lines = (world.vault / "example-work" / "team" / "new-agent.md").read_text().splitlines()
    headings = ["# New Agent", "## Identity", "## What You Own", "## Judgment", "### Style", "### Limits",
                "### Return", "### How you write state", "### Boot reads"]
    assert all(heading in lines for heading in headings)
    assert [lines.index(heading) for heading in headings] == sorted(lines.index(heading) for heading in headings)
    assert not (world.repo / "new-agent.md").exists()
    assert agent_new.main(argv) == 2
    assert "already exists" in capsys.readouterr().err


def test_render_writes_marked_capes_reports_gaps_and_protects_unmarked(world, capsys):
    (world.shelf / "present").mkdir()
    (world.shelf / "present" / "SKILL.md").write_text("skill")
    write_identity(world, mode="none", runtimes=["claude", "codex"], skills=["present", "missing"], tools=["qmd"])
    assert agent_new.main(["render", "demo-agent"]) == 0
    # current behavior since 4a024f1 (T740): system identities render under runs/generated/agents/
    claude = world.repo.parent / "runs/generated/agents/claude" / "demo-agent.md"
    codex = world.repo.parent / "runs/generated/agents/codex" / "demo-agent.toml"
    assert agent_new.MARKER in claude.read_text()
    assert codex.read_text().splitlines()[0] == "# managed-by: agent-new v1"
    assert "Skill gaps: missing" in capsys.readouterr().out
    claude.write_text("# hand written\n")
    assert agent_new.main(["render", "demo-agent"]) == 2
    assert claude.read_text() == "# hand written\n"
    assert "Refusing to overwrite unmarked cape" in capsys.readouterr().err


def test_policy_and_rendered_models_match_model_file(world):
    source = yaml.safe_load((world.repo.parent / "config/models.yaml").read_text())
    assert source["tiers"] == POLICY["tiers"]
    for tier in POLICY["tiers"]:
        identity = write_identity(world, agent_id=f"agent-{tier}", tier=tier,
                                  mode="child" if tier == "code" else "profile")
        claude = agent_new.claude_cape(identity, world.repo)
        codex = agent_new.codex_cape(identity, world.repo)
        assert yaml.safe_load(claude.split("---\n", 2)[1])["model"] == POLICY["tiers"][tier]["claude"]["model"]
        assert 'model = ' + json.dumps(POLICY['tiers'][tier]['codex']['model']) in codex
        assert 'model_reasoning_effort = "high"' in codex
        assert 'service_tier = "priority"' in codex
        if tier != "code":
            rendered = agent_new.overlay(identity, world.repo, world.hermes, world.shelf)
            assert rendered["model"] == {"default": POLICY["tiers"][tier]["hermes"]["model"], "provider": POLICY["tiers"][tier]["hermes"]["provider"]}
            assert rendered["agent"] == {"reasoning_effort": "high", "service_tier": "priority"}
            assert rendered["delegation"]["model"] == POLICY["tiers"]["work"]["hermes"]["model"]


def test_overlay_replaces_old_auxiliary_model(world):
    identity = write_identity(world, mode="profile")
    config = world.hermes / "profiles/demo-agent/config.yaml"
    config.parent.mkdir(parents=True)
    tags = list(dict.fromkeys(POLICY["legacy_auxiliary_model_tags"] + POLICY["banned"]))
    auxiliary = {"legacy-" + str(index): {"model": "example-fast-" + tag} for index, tag in enumerate(tags)}
    auxiliary["compression"] = {"model": "example-fast"}
    config.write_text(yaml.safe_dump({"auxiliary": auxiliary}))
    rendered = agent_new.overlay(identity, world.repo, world.hermes, world.shelf)
    assert rendered["auxiliary"] == {"legacy-" + str(index): {"model": POLICY["tiers"]["work"]["hermes"]["model"]} for index in range(len(tags))}


def test_render_overlay_has_only_contract_keys(world):
    write_identity(world, agent_id="ellie", mode="kanban", skills=["own"], tools=["qmd"])
    config = world.hermes / "profiles" / "ellie" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(yaml.safe_dump({"mcp_servers": {"old": {"enabled": True, "command": "x"}}}))
    agent_new.render_identity(agent_new.load_identity("ellie", world.repo))
    # current behavior since 4a024f1 (T740): the overlay renders under runs/generated/agents/<id>/
    overlay = yaml.safe_load((world.repo.parent / "runs/generated/agents/ellie/config.overlay.yaml").read_text())
    assert list(overlay) == ["model", "agent", "terminal", "delegation", "skills", "mcp_servers"]
    assert overlay["mcp_servers"] == {"old": {"enabled": False}, "qmd": {"enabled": True}}


def test_disabled_skills_keeps_core_identity_and_example_lead_exceptions(world):
    # current behavior since 4a024f1 (T740): core skills are the catalog base set; exceptions come from config/catalog.yaml
    add_set(world, "base", ["core-skill"], [])
    for name in ("core-skill", "identity-skill", "other", "tp-time-tracking", "tp-weekly-review", "test-driven-development"):
        (world.shelf / name).mkdir()
    (world.hermes / "skills" / "global-extra").mkdir(parents=True)
    (world.hermes / "skills" / "global-extra" / "SKILL.md").write_text("# global-extra\n")
    (world.hermes / "profiles" / "example-lead" / "skills" / "category" / "profile-extra").mkdir(parents=True)
    (world.hermes / "profiles" / "example-lead" / "skills" / "category" / "profile-extra" / "SKILL.md").write_text("# profile-extra\n")
    identity = write_identity(world, agent_id="example-lead", mode="profile", tier="judgment", skills=["identity-skill"])
    disabled = agent_new.disabled_skills(identity, world.repo, world.hermes, world.shelf)
    assert "core-skill" not in disabled
    assert "identity-skill" not in disabled
    assert "tp-time-tracking" not in disabled
    assert "tp-weekly-review" not in disabled
    assert {"other", "global-extra", "profile-extra", "test-driven-development", "spike"} <= set(disabled)
    assert disabled == sorted(set(disabled))


def test_diff_exit_codes_and_soul_comparison(world):
    identity = write_identity(world, agent_id="ellie", mode="kanban", tools=["qmd"])
    code, result = agent_new.diff_data(identity)
    assert code == 2 and result["profile_missing"]
    profile = world.hermes / "profiles" / "ellie"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("other: kept\n")
    code, result = agent_new.diff_data(identity)
    assert code == 3
    assert result["keys_changed"]
    proposed = agent_new.overlay(identity, world.repo, world.hermes, world.shelf)
    (profile / "config.yaml").write_text(yaml.safe_dump({"other": "kept", **proposed}, sort_keys=False))
    generated = world.repo / "generated" / "hermes" / "ellie" / "SOUL.md"
    generated.parent.mkdir(parents=True)
    generated.write_text(agent_new.desired_soul(identity))
    (profile / "SOUL.md").write_text(generated.read_text())
    code, result = agent_new.diff_data(identity)
    assert code == 0
    assert result["soul"] == "same"


def test_probe_fake_runner_success_and_failure(world, capsys):
    # current behavior since 4a024f1 (T740): the probe command is held at the CLI; probe_command still scores runs
    write_identity(world, mode="none", runtimes=["claude", "codex"])
    def success(cmd, **kwargs):
        return fake_result("IDENTITY demo-agent READY")
    assert agent_new.main(["probe", "demo-agent", "--runtimes", "hermes"], runner=success) == 2
    assert agent_new.main(["probe", "demo-agent", "--runtimes", "claude,codex"], runner=success) == 2
    assert "Probe held" in capsys.readouterr().err
    assert not list((world.repo / "generated" / "probes").glob("demo-agent-*.json"))
    args = agent_new.parser().parse_args(["probe", "demo-agent", "--runtimes", "claude,codex"])
    assert agent_new.probe_command(args, success)[0] == 0
    reports = list((world.repo / "generated" / "probes").glob("demo-agent-*.json"))
    assert reports
    result = json.loads(reports[-1].read_text())
    assert all(item["ok"] for item in result["results"])
    def failure(cmd, **kwargs):
        return fake_result("wrong reply")
    args = agent_new.parser().parse_args(["probe", "demo-agent", "--runtimes", "claude"])
    assert agent_new.probe_command(args, failure)[0] == 4


def test_apply_without_literal_confirmation_refuses(world, capsys):
    write_identity(world, agent_id="ellie", mode="kanban")
    called = False
    def runner(cmd, **kwargs):
        nonlocal called
        called = True
        return fake_result()
    assert agent_new.main(["apply", "ellie"], runner=runner) == 2
    assert not called
    assert "Claude and Codex on day one." in capsys.readouterr().out


# Removed since 4a024f1 (T740): test_apply_isolation_changes_only_selected_profile and
# test_apply_creates_missing_profile_with_injected_runner. Hermes profile apply left the product:
# main refuses apply, --hermes-mode accepts only none, and FOXRUN_STATE/hermes is outside the write homes.


def test_json_and_list_include_gap_counts(world, capsys):
    write_identity(world, skills=["missing"])
    assert agent_new.main(["list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["identities"][0]["id"] == "demo-agent"
    assert payload["identities"][0]["gaps"] == 1


V2_BODY = """# {name}

{summary}

## Who you are
You own the named lane.

## Responsibility
- Own the work.

## Judgment
- Verify facts.
"""
BASE_SOUL = """## Culture
- Protect source truth.

## Vibe
- Stay calm.

## How you communicate
- Lead with the result.
"""


def write_v2_identity(world, agent_id="v2-agent", base=True):
    identity = write_identity(world, agent_id=agent_id)
    path = identity.path
    text = path.read_text()
    front = text[4:].split("\n---\n", 1)[0]
    body = V2_BODY.format(name=identity.data["display_name"], summary=identity.data["summary"])
    path.write_text("---\n" + front + "\n---\n" + body, encoding="utf-8")
    if base:
        (world.repo).mkdir(exist_ok=True)
        (world.repo / "soul.md").write_text(BASE_SOUL, encoding="utf-8")
    return agent_new.load_identity(agent_id, world.repo)


def assignment_yaml(text):
    block = text.split("```yaml\n", 1)[1].split("```", 1)[0]
    return yaml.safe_load(block)


def test_assignment_brief_v2_appends_exact_base_once_and_preserves_assignment(world):
    identity = write_v2_identity(world)
    brief = agent_new.assignment_brief(identity, world.repo)
    assert brief.count(BASE_SOUL) == 1
    assert brief.startswith(identity.body.rstrip("\n") + "\n\n" + BASE_SOUL)
    assert [heading for heading in ("## Who you are", "## Responsibility", "## Judgment",
                                     "## Culture", "## Vibe", "## How you communicate")
            if brief.count(heading) == 1] == [
                "## Who you are", "## Responsibility", "## Judgment",
                "## Culture", "## Vibe", "## How you communicate",
            ]
    assert assignment_yaml(brief) == {
        "identity": "v2-agent", "identity_version": 1, "client": "example-work",
        "task": "<assignment>", "inputs": [], "skills": [], "output": "<finished result>",
        "limits": {"timeout_seconds": 600, "cost_usd": 0, "tools": []},
        "return_to": "telegram:example-work:7", "origin_topic": "<origin topic>",
    }


def test_assignment_brief_v1_preserves_previous_bytes(world):
    identity = write_identity(world)
    assignment = {
        "identity": identity.data["id"], "identity_version": identity.data["version"],
        "client": identity.data["client_default"], "task": "<assignment>",
        "inputs": [], "skills": identity.data["skills"], "output": "<finished result>",
        "limits": {"timeout_seconds": 600, "cost_usd": 0, "tools": identity.data["tools"]},
        "return_to": identity.data["return_default"], "origin_topic": "<origin topic>",
    }
    expected = identity.body.rstrip() + "\n\n## Assignment\n\n```yaml\n" + agent_new.yaml_text(assignment) + "```\n"
    assert agent_new.assignment_brief(identity, world.repo) == expected


def test_v2_missing_base_matches_established_omission(world):
    identity = write_v2_identity(world, base=False)
    soul = agent_new.desired_soul(identity)
    brief = agent_new.assignment_brief(identity, world.repo)
    assert "## Culture" not in soul
    assert "## Culture" not in brief
    assert brief.startswith(identity.body.rstrip() + "\n\n## Assignment")
    assert assignment_yaml(brief)["identity"] == "v2-agent"


def test_v2_identity_accepts_boot_reads_after_judgment_and_soul_carries_it(world):
    identity = write_v2_identity(world)
    identity.path.write_text(identity.path.read_text() + "\n## Boot reads\n1. `sqlite3 -readonly db.sqlite`\n", encoding="utf-8")
    loaded = agent_new.load_identity("v2-agent", world.repo)
    soul = agent_new.desired_soul(loaded)
    assert soul.index("## Judgment") < soul.index("## Boot reads") < soul.index("## Culture")


def test_boot_reads_before_judgment_is_refused(world):
    identity = write_v2_identity(world)
    text = identity.path.read_text().replace("## Judgment", "## Boot reads\n1. read\n\n## Judgment")
    identity.path.write_text(text, encoding="utf-8")
    with raises(agent_new.AgentNewError, match="Boot reads must come after"):
        agent_new.load_identity("v2-agent", world.repo)


def test_identity_uses_schema_frontmatter_and_refuses_created_with_timestamp(world):
    identity = write_identity(world, agent_id="page-agent")
    assert identity.data["type"] == "agent-soul" and "created" not in identity.data
    for change, message in (({"created": "2026-09-08"}, "one timestamp"),
                            ({"timestamp": "2026-09-08"}, "ISO 8601"),
                            ({"workspace": ""}, "workspace must be")):
        data = dict(identity.data, **change)
        with raises(agent_new.AgentNewError, message):
            agent_new.validate_identity(agent_new.Identity(data, identity.body, identity.path), world.repo)
    legacy = {k: v for k, v in identity.data.items() if k not in ("type", "workspace", "timestamp")}
    agent_new.validate_identity(agent_new.Identity(dict(legacy, created="2026-09-08"), identity.body, identity.path), world.repo)
    with raises(agent_new.AgentNewError, "timestamp"):
        agent_new.validate_identity(agent_new.Identity(legacy, identity.body, identity.path), world.repo)


def test_create_writes_type_workspace_timestamp_and_no_created(world, capsys):
    argv = ["create", "dated-agent", "--role", "Owns dated work", "--summary", "Runs dated work.",
            "--tier", "work", "--skills", "", "--tools", "", "--client", "example-work",
            "--runtimes", "claude,codex", "--hermes-mode", "none"]
    assert agent_new.main(argv + ["--dry-run", "--json"]) == 0
    page = json.loads(capsys.readouterr().out)["page"]
    assert not (world.repo / "dated-agent.md").exists()
    front, _ = agent_new.split_identity(page)
    assert front["type"] == "agent-soul" and front["workspace"] == "example-work"
    assert agent_new.ISO_OFFSET_RE.fullmatch(front["timestamp"]) and "created" not in front


# Shared state-writing section.
REPO = Path(__file__).resolve().parents[1]


def test_create_scaffolds_write_state_verbatim_before_boot_reads(world):
    # current behavior since 4a024f1 (T740): a reviewed set backs --skills/--tools, and the section nests as ###;
    # a system client keeps the template commands verbatim (a workspace client swaps in --workspace).
    add_set(world, "state-work", ["one"], ["qmd"])
    argv = ["create", "state-agent", "--role", "Owns state work", "--summary", "Runs state work.",
            "--tier", "work", "--skills", "one", "--tools", "qmd", "--client", "system",
            "--runtimes", "claude,codex", "--hermes-mode", "none"]
    assert agent_new.main(argv) == 0
    text = (world.repo / "state-agent.md").read_text()
    assert agent_new.WRITE_STATE_SECTION.replace("## ", "### ") in text
    assert text.index("### Return") < text.index("### How you write state") < text.index("### Boot reads")
    agent_new.load_identity("state-agent", world.repo)


def test_write_state_section_is_short_and_carries_the_seven_moves():
    section = agent_new.WRITE_STATE_SECTION
    assert len(section.rstrip().splitlines()) <= agent_new.WRITE_STATE_MAX_LINES
    assert "--db ${FOXRUN_HOME:-$HOME/.foxrun}/data.db --receipt-root ${FOXRUN_HOME:-$HOME/.foxrun}" in section
    assert "--by <id>" in section
    # current behavior since e77ff32 (T708): no separate accept move ("Another seat accepts it.");
    # since b7e8752 (T630): the comment prefix is the person's name and a colon, from config/person.json.
    moves = ["create ", "claim ", "run-start ", "comment ", "run-end ", "done ",
             "bug-open ", "approval-add ", "decision-add "]
    positions = [section.index("`" + move) for move in moves]
    assert positions == sorted(positions)
    assert "Another seat accepts it." in section
    assert "starts with their name and a colon" in section and "`~/.foxrun/config/person.json`" in section


REPLACES_RULE = [
    "A newer ruling kills the older version.",
    "When you write or read a decision row with a replaces field, the replaced statement is dead: "
    "drop it from your working picture and never present it again as settled.",
    "Before you call anything settled, check decisions.replaces for a newer row.",
]


def test_write_state_section_carries_the_replaces_rule_after_same_turn():
    lines = agent_new.WRITE_STATE_SECTION.splitlines()
    same_turn = lines.index("The row comes first. The answer comes second.")
    assert lines[same_turn + 1:same_turn + 4] == REPLACES_RULE
    assert lines.index("Same turn, a row: see `~/.foxrun/profile/AGENTS.md`.") < same_turn

def _v2_with_write_state(world, where):
    identity = write_v2_identity(world)
    text = identity.path.read_text() + "\n## Boot reads\n1. `sqlite3 -readonly db.sqlite`\n"
    section = agent_new.WRITE_STATE_SECTION
    if where == "valid":
        text = text.replace("\n## Boot reads\n", "\n" + section + "\n## Boot reads\n")
    elif where == "before-judgment":
        text = text.replace("## Judgment", section + "\n## Judgment")
    elif where == "after-boot-reads":
        text = text + "\n" + section
    elif where == "too-long":
        long = section.rstrip("\n") + "\n" + "\n".join(f"Extra line {n}." for n in range(10)) + "\n"
        text = text.replace("\n## Boot reads\n", "\n" + long + "\n## Boot reads\n")
    identity.path.write_text(text, encoding="utf-8")


def test_write_state_between_judgment_and_boot_reads_is_accepted_and_soul_carries_it(world):
    _v2_with_write_state(world, "valid")
    loaded = agent_new.load_identity("v2-agent", world.repo)
    soul = agent_new.desired_soul(loaded)
    assert soul.index("## Judgment") < soul.index("## How you write state") < soul.index("## Boot reads")


def test_write_state_out_of_order_or_too_long_is_refused(world, where, message):
    _v2_with_write_state(world, where)
    with raises(agent_new.AgentNewError, match=message):
        agent_new.load_identity("v2-agent", world.repo)


def test_seats_carry_the_template_section_verbatim(seat):
    # current behavior since 4a024f1 (T740): seats nest the section as ### under ## Judgment
    text = (REPO / f"{seat}.md").read_text(encoding="utf-8")
    section = agent_new.WRITE_STATE_SECTION.replace("## ", "### ")
    # Both seats carry the section verbatim, with the install home as the receipt root.
    assert section in text
    body = text.split("\n---\n", 1)[1]
    assert body.index("## Judgment") < body.index("### How you write state") < body.index("### Boot reads")


def test_team_file_falls_back_to_the_client_workspace(world):
    identity = write_identity(world, mode="child", runtimes=["claude", "codex"])
    product = world.repo / "execution" / "teams" / "example-work.yaml"
    assert agent_new.team_data(identity, world.repo)["lead"] == "example-lead"
    product.unlink()
    with raises(agent_new.AgentNewError, match="Team file not found"):
        agent_new.team_data(identity, world.repo)
    own = world.vault / "example-work" / "config" / "agents" / "execution-teams-example-work.yaml"
    own.parent.mkdir(parents=True)
    own.write_text(yaml.safe_dump({"client": "example-work", "lead": "workspace-lead"}), encoding="utf-8")
    assert agent_new.team_data(identity, world.repo)["lead"] == "workspace-lead"
    assert agent_new.lead_for(identity, world.repo) == "workspace-lead"
    product.write_text(yaml.safe_dump({"client": "example-work", "lead": "product-lead"}), encoding="utf-8")
    assert agent_new.team_data(identity, world.repo)["lead"] == "product-lead"


def test_readme_and_typed_pages_are_not_identities(world, capsys):
    identity = write_identity(world, agent_id="seat-agent", runtimes=["claude", "codex"])
    readme = world.repo / "README.md"
    readme.write_text("---\ntype: doc\nworkspace: system\ntimestamp: 2026-10-19T17:20:41-04:00\n---\n# Agents\n", encoding="utf-8")
    soul = world.repo / "soul.md"
    soul.write_text("---\ntype: base-soul\nworkspace: system\ntimestamp: 2026-10-19T17:20:41-04:00\n---\n## Core\n", encoding="utf-8")
    plain = world.repo / "notes.md"
    plain.write_text("# Notes\n", encoding="utf-8")
    assert agent_new.is_identity_page(identity.path)
    assert not any(agent_new.is_identity_page(page) for page in (readme, soul, plain))
    legacy = world.repo / "legacy-agent.md"
    legacy.write_text("---\n{\"id\": \"legacy-agent\"}\n---\n# Legacy\n", encoding="utf-8")
    assert agent_new.is_identity_page(legacy)
    assert agent_new.main(["list", "--json"]) == 0
    ids = [row["id"] for row in json.loads(capsys.readouterr().out)["identities"]]
    assert ids == ["seat-agent"]



CREATE_ARGV = ["create", "half-agent", "--role", "Owns half work", "--summary", "Runs half work.",
               "--tier", "work", "--client", "example-work", "--runtimes", "claude,codex", "--hermes-mode", "none"]


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_create_render_failure_leaves_no_half_made_agent(world, monkeypatch, capsys):
    # A render that fails after the team file and capes are written removes exactly what this run wrote.
    team = world.vault / "example-work" / "team"
    team.mkdir()
    (team / "keep.md").write_text("not this run's file\n", encoding="utf-8")
    stale = team / "claude" / "half-agent.md"
    stale.parent.mkdir()
    stale.write_text("<!-- " + agent_new.MARKER + " -->\nan older managed cape\n", encoding="utf-8")
    before_vault, before_home = tree(world.vault), tree(world.repo.parent)
    real = agent_new.write_text
    def failing(path, text, journal=None):
        if path.name == "render.json":
            raise agent_new.AgentNewError("forced render failure")
        real(path, text, journal)
    monkeypatch.setattr(agent_new, "write_text", failing)
    assert agent_new.main(CREATE_ARGV) == 2
    assert "forced render failure" in capsys.readouterr().err
    assert not (team / "half-agent.md").exists()
    assert not (team / "codex").exists() and not (team / "codex" / "half-agent.toml").exists()
    assert stale.read_text(encoding="utf-8").endswith("an older managed cape\n")  # restored, not deleted
    assert (team / "keep.md").read_text(encoding="utf-8") == "not this run's file\n"
    assert tree(world.vault) == before_vault and tree(world.repo.parent) == before_home
    monkeypatch.setattr(agent_new, "write_text", real)
    assert agent_new.main(CREATE_ARGV) == 0  # no leftover blocks the next try


def test_create_refused_write_is_checked_before_the_team_file(world, monkeypatch, capsys):
    # The render report lives in the system home; a seat that may not write it stops create before any write.
    monkeypatch.setenv("FOXRUN_SEAT", "someone-else")
    before_vault, before_home = tree(world.vault), tree(world.repo.parent)
    assert agent_new.main(CREATE_ARGV) == 2
    assert "ALARM" in capsys.readouterr().err
    assert tree(world.vault) == before_vault and tree(world.repo.parent) == before_home


def test_create_works_when_the_homes_sit_behind_a_link(world, monkeypatch, tmp_path):
    # macOS temp folders are /var -> /private/var; the ownership guard must map the declared home itself.
    link = tmp_path.parent / (tmp_path.name + "-link")
    link.symlink_to(tmp_path)
    try:
        monkeypatch.setenv("FOXRUN_HOME", str(link / "home"))
        monkeypatch.setenv("FOXRUN_PORTFOLIO", str(link / "vault"))
        assert agent_new.main(CREATE_ARGV) == 0
        assert (world.vault / "example-work" / "team" / "half-agent.md").is_file()
        assert (world.repo.parent / "runs/generated/agents/workspaces/example-work/half-agent/render.json").is_file()
    finally:
        link.unlink()

# comms-lead dropped from the seat cases: it left the core in b7e8752 (T630: four seats leave the core).
def load_tests(loader, tests, pattern):
    return function_suite(globals(), {'test_write_state_out_of_order_or_too_long_is_refused': [{'where': 'before-judgment', 'message': 'must come after ## Judgment'}, {'where': 'after-boot-reads', 'message': 'must come before ## Boot reads'}, {'where': 'too-long', 'message': 'exceeds 25 lines'}], 'test_seats_carry_the_template_section_verbatim': [{'seat': 'architect'}, {'seat': 'chief-of-staff'}]})
