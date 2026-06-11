from __future__ import annotations

import pytest

from miniagent.skills import SkillLibrary


@pytest.fixture
def library(tmp_path):
    return SkillLibrary(tmp_path / "skills")


def write_repo_skill(library, name="run-tests", repo="octo/widgets"):
    return library.write(
        name=name,
        description="How to run the test suite",
        body="## Procedure\nRun `uv run pytest`.",
        scope="repo",
        repo=repo,
    )


# --- write / index / read ----------------------------------------------------


def test_roundtrip_repo_skill(library):
    path = write_repo_skill(library)
    assert path.name == "run-tests.md"
    assert "repos/octo/widgets" in str(path)

    refs = library.index("octo/widgets")
    assert [(r.name, r.scope) for r in refs] == [("run-tests", "repo")]
    assert refs[0].description == "How to run the test suite"

    content = library.read("run-tests", "octo/widgets")
    assert content is not None
    assert content.startswith("---\nname: run-tests\n")
    assert "## Procedure" in content


def test_global_skill_visible_to_all_repos(library):
    library.write(
        name="commit-style",
        description="Conventional commits",
        body="Use imperative subject lines.",
        scope="global",
        repo=None,
    )
    assert [r.name for r in library.index("octo/widgets")] == ["commit-style"]
    assert [r.name for r in library.index(None)] == ["commit-style"]
    assert library.read("commit-style", "any/repo") is not None


def test_repo_skill_invisible_to_other_repos(library):
    write_repo_skill(library, repo="octo/widgets")
    assert library.index("other/repo") == []
    assert library.read("run-tests", "other/repo") is None


def test_all_skills_spans_repos_and_global(library):
    write_repo_skill(library, repo="octo/widgets")
    write_repo_skill(library, name="deploy", repo="acme/api")
    library.write(
        name="commit-style", description="d", body="b", scope="global", repo=None
    )
    refs = library.all_skills()
    assert [(r.name, r.scope, r.repo) for r in refs] == [
        ("deploy", "repo", "acme/api"),
        ("run-tests", "repo", "octo/widgets"),
        ("commit-style", "global", None),
    ]


# --- safety -------------------------------------------------------------------


@pytest.mark.parametrize("name", ["../../etc/passwd", "a/b", ".hidden", "UPPER", ""])
def test_read_rejects_non_slug_names(library, name):
    write_repo_skill(library)
    assert library.read(name, "octo/widgets") is None


def test_slugify():
    assert SkillLibrary.slugify("Run the Tests!") == "run-the-tests"
    assert SkillLibrary.slugify("  api__endpoint  ") == "api-endpoint"
    with pytest.raises(ValueError):
        SkillLibrary.slugify("!!!")


def test_description_forced_to_one_line(library):
    library.write(
        name="multi",
        description="line one\nline two",
        body="body",
        scope="global",
        repo=None,
    )
    assert library.index(None)[0].description == "line one line two"


# --- update semantics -----------------------------------------------------------


def test_update_overwrites_in_place_ignoring_new_scope(library):
    first = write_repo_skill(library)
    # Same slug, distiller now claims "global": must stay in the repo dir.
    second = library.write(
        name="run-tests",
        description="Updated",
        body="## Procedure\nNew steps.",
        scope="global",
        repo="octo/widgets",
    )
    assert second == first
    refs = library.index("octo/widgets")
    assert [(r.name, r.scope, r.description) for r in refs] == [
        ("run-tests", "repo", "Updated")
    ]


def test_repo_scope_without_repo_falls_back_to_global(library):
    path = library.write(
        name="orphan", description="d", body="b", scope="repo", repo=None
    )
    assert "global" in str(path)


# --- consumption: prompt block + read_skill tool ------------------------------


def make_agent(library, repo="octo/widgets"):
    from miniagent.agent import Agent
    from miniagent.llm import LLM
    from miniagent.tools.base import ToolRegistry

    return Agent(
        llm=LLM(model="test"), tools=ToolRegistry(), repo=repo, skills=library
    )


def test_skills_block_lists_index(library):
    write_repo_skill(library)
    block = make_agent(library)._skills_block()
    assert block.startswith("\n\n# Skills")
    assert "read_skill" in block
    assert "- run-tests: How to run the test suite" in block


def test_skills_block_empty_cases(library):
    assert make_agent(library)._skills_block() == ""
    agent_without_library = make_agent(library)
    agent_without_library.skills = None
    assert agent_without_library._skills_block() == ""


def test_read_skill_tool(library, sandbox):
    from miniagent.tools.skill import ReadSkillAction, ReadSkillTool

    write_repo_skill(library)
    tool = ReadSkillTool(library, "octo/widgets")

    obs = tool.execute(ReadSkillAction(name="run-tests"), sandbox)
    assert not obs.error
    assert "## Procedure" in obs.content

    obs = tool.execute(ReadSkillAction(name="nope"), sandbox)
    assert obs.error
    assert "Unknown skill: nope" in obs.content
    assert "run-tests" in obs.content  # lists what is available

    obs = tool.execute(ReadSkillAction(name="../run-tests"), sandbox)
    assert obs.error


# --- API router -----------------------------------------------------------------


def test_skills_api(library):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.deps import get_skills
    from backend.api.skills import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_skills] = lambda: library

    write_repo_skill(library)
    client = TestClient(app)

    listed = client.get("/skills").json()
    assert listed == [
        {
            "name": "run-tests",
            "description": "How to run the test suite",
            "scope": "repo",
            "repo": "octo/widgets",
        }
    ]

    body = client.get("/skills/body", params={"name": "run-tests", "repo": "octo/widgets"})
    assert body.status_code == 200
    assert "## Procedure" in body.json()["content"]

    missing = client.get("/skills/body", params={"name": "nope"})
    assert missing.status_code == 404


# --- distiller parsing ----------------------------------------------------------


def test_parse_skill_json():
    from backend.runtime.manager import _parse_skill_json

    assert _parse_skill_json('{"decision": "skip"}') == {"decision": "skip"}

    valid = (
        '{"decision": "create", "name": "run-tests", "scope": "repo",'
        ' "description": "d", "body": "## Procedure"}'
    )
    parsed = _parse_skill_json(valid)
    assert parsed is not None and parsed["name"] == "run-tests"

    fenced = f"```json\n{valid}\n```"
    assert _parse_skill_json(fenced) is not None

    assert _parse_skill_json("not json") is None
    assert _parse_skill_json('{"decision": "create"}') is None  # missing fields
    assert _parse_skill_json('{"decision": "create", "name": "x", "scope": "everywhere", "description": "d", "body": "b"}') is None
    assert _parse_skill_json('{"decision": "maybe"}') is None
    assert _parse_skill_json("[1, 2]") is None


def test_skill_transcript_includes_actions_and_respects_budget():
    from backend.runtime.manager import (
        _SKILL_TRANSCRIPT_BUDGET,
        ManagedConversation,
    )
    from miniagent.events import ActionEvent, MessageEvent, ObservationEvent

    events = [
        MessageEvent(role="user", text="fix the failing test"),
        ActionEvent(tool_name="bash", arguments={"command": "pytest"}, tool_call_id="c1"),
        ObservationEvent(tool_name="bash", content="1 failed", error=True, tool_call_id="c1"),
        MessageEvent(role="assistant", text="x" * 50_000),
    ]
    transcript = ManagedConversation._skill_transcript(
        type("Fake", (), {"conversation": type("C", (), {"events": events})()})()
    )
    assert "user: fix the failing test" in transcript
    assert 'tool bash: {"command": "pytest"}' in transcript
    assert "result[ERROR]: 1 failed" in transcript
    # budget enforced (plus the truncation marker overhead)
    assert len(transcript) < _SKILL_TRANSCRIPT_BUDGET + 100
