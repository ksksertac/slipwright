"""T15.2 and T15.3: a model is sent what its step needs. DevOps describes a pull request
from the files that changed, not the whole branch's diff; the developer's file tree shows
the code before the pictures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slipwright.roles.common import list_tree
from slipwright.schemas.job import APPROVAL_STATES, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from slipwright.workspace import git as g
from tests.pipeline import full_engine, full_provider


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _context(request: Any) -> dict[str, Any]:
    text = request.prompt
    body = text[text.index("Context:\n") + len("Context:\n") : text.index("\nRespond with")]
    return dict(json.loads(body))


# -- T15.2: DevOps --------------------------------------------------------------------------


def test_changed_files_name_every_file_and_carry_no_lines(repo: Path) -> None:
    base = g.head_commit(repo)
    _write(repo, {"src/deep/folder/with/a/long/name/module.py": "value = 1\n" * 500})
    g.stage_all(repo)
    g.commit(repo, "phase")

    listed = g.changed_files(repo, base)
    assert "src/deep/folder/with/a/long/name/module.py" in listed  # whole, not "..."
    assert "500" in listed and "value = 1" not in listed


def test_devops_is_sent_the_changed_files_not_the_branch_diff(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=2)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)
    for _ in range(40):
        if job.state not in APPROVAL_STATES:
            break
        job = engine.approve(job.id)
    assert job.state is JobState.DONE

    devops = [_context(r) for r in provider.requests if r.role is RoleName.DEVOPS]
    described = next(c for c in devops if "draft" in c)
    assert "branch_diff" not in described
    assert "OK" in described["changed_files"]  # the file the phases wrote
    # names and counts, not lines: no diff header and no hunk. Not a bare "+++", which is
    # also what --stat draws for a file with three lines added -- the README the Architect
    # writes before the pull request is one
    assert "+++ b/" not in described["changed_files"]
    assert "@@" not in described["changed_files"]


# -- T15.3: the developer's tree ------------------------------------------------------------


def test_the_code_is_listed_before_the_pictures(tmp_path: Path) -> None:
    _write(tmp_path, {f"public/images/pic{i:03}.png": "" for i in range(500)})
    _write(tmp_path, {f"assets/a{i:03}.txt": "" for i in range(300)})
    _write(tmp_path, {f"src/m{i}.ts": "" for i in range(30)})
    _write(tmp_path, {"package.json": "{}", "public/favicon.ico": ""})

    tree = list_tree(tmp_path, limit=100)

    assert all(f"src/m{i}.ts" in tree for i in range(30))
    assert "package.json" in tree
    assert "public/images/ (500 files: .png)" in tree
    assert not any(e.startswith("public/images/pic") for e in tree)
    assert "public/favicon.ico" in tree  # a folder with only a few is still listed
    # what did not fit is said, and where it was
    assert tree[-1].startswith("... (") and "assets/" in tree[-1]
    assert len(tree) == 101


def test_the_folders_a_phase_touches_come_first(tmp_path: Path) -> None:
    _write(tmp_path, {f"lib/a{i:03}.py": "" for i in range(50)})
    _write(tmp_path, {"zeta/screens/home.tsx": "", "zeta/screens/parts/card.tsx": ""})

    tree = list_tree(tmp_path, limit=10, first=["zeta/screens/settings.tsx"])

    assert tree[:2] == ["zeta/screens/home.tsx", "zeta/screens/parts/card.tsx"]


def test_a_small_tree_is_listed_whole_as_before(tmp_path: Path) -> None:
    _write(tmp_path, {"README.md": "", "src/app.py": "", "tests/test_app.py": ""})
    assert sorted(list_tree(tmp_path)) == ["README.md", "src/app.py", "tests/test_app.py"]


# -- T15.7: a compact prompt ----------------------------------------------------------------


def test_the_prompt_is_sent_compact_and_reads_back_the_same() -> None:
    from slipwright.invoke import _user_prompt

    context = {
        "request": "Yarışma sonucunu ve kupayı göster",
        "plan": {"phases": [{"number": i, "goal": "çözüm üret"} for i in range(20)]},
    }
    prompt = _user_prompt(context, {"type": "object"})
    body = prompt[prompt.index("Context:\n") + 9 : prompt.index("\n\nRespond with")]

    assert json.loads(body) == context
    assert "Yarışma sonucunu ve kupayı göster" in prompt  # letters, not \u escapes
    indented = len(json.dumps(context, indent=2, sort_keys=True))
    assert len(body) < indented * 0.9


# -- T15.8: the errors of a failed build ----------------------------------------------------


def test_a_long_failed_build_reaches_the_developer_as_its_errors() -> None:
    from slipwright.gates import MAX_MODEL_CHARS, GateResult

    progress = [f"> Task :app:step{i} UP-TO-DATE" for i in range(1800)]
    errors = [
        "> Task :app:compileDebugKotlin",
        "e: file:///work/app/src/main/java/com/x/App.kt:12:5 Unresolved reference: Trophy",
        "e: file:///work/app/src/main/java/com/x/Room.kt:40:9 Type mismatch",
        "> Task :app:compileDebugKotlin FAILED",
    ]
    output = "\n".join(progress[:900] + errors + progress[900:] + ["BUILD FAILED in 41s"])
    gate = GateResult(ok=False, output=output)

    sent = gate.for_model
    assert len(output) > 50_000 and len(sent) <= MAX_MODEL_CHARS + 300
    assert "App.kt:12:5 Unresolved reference: Trophy" in sent
    assert "Room.kt:40:9 Type mismatch" in sent
    assert "BUILD FAILED in 41s" in sent  # and how the run ended
    assert len(gate.tail) > len(sent)  # the person still has the long version


def test_a_failure_with_no_error_line_falls_back_to_its_end() -> None:
    from slipwright.gates import condensed

    output = "\n".join(f"step {i} ok" for i in range(3000)) + "\nexit status 2"
    sent = condensed(output, limit=1000)
    assert sent.endswith("exit status 2") and "were cut" in sent
    assert condensed("short", limit=1000) == "short"


# -- T15.6: the plan, as much as a step needs -----------------------------------------------


def test_a_developer_is_given_the_other_phases_by_their_heading() -> None:
    from slipwright.roles.common import plan_outline

    plan = {
        "summary": "A quiz game",
        "stack": ["React Native"],
        "decisions": [f"decision {i}: binding on every phase" for i in range(12)],
        "phases": [
            {
                "goal": f"Phase {i} heading: " + "what it verifies in detail. " * 12,
                "domain": "mobile",
            }
            for i in range(8)
        ],
    }
    full = plan_outline(plan)
    mine = plan_outline(plan, current=2)
    assert full is not None and mine is not None

    assert mine["decisions"] == plan["decisions"]  # every decision, whole
    assert [p["goal"] for p in mine["phases"]] == [f"Phase {i} heading" for i in range(8)]
    assert [p.get("this_phase", False) for p in mine["phases"]] == [i == 2 for i in range(8)]
    assert len(json.dumps(mine["phases"])) < len(json.dumps(full["phases"])) / 3


# -- T15.4: a file the developer must rewrite is given whole --------------------------------


def _big(lines: int) -> str:
    return "".join(f"const line{i} = {i}; // keep me\n" for i in range(lines))


def test_a_phase_is_shown_a_30_kb_file_whole(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    (repo / "OK").write_bytes(_big(1000).encode())  # ~33 KB
    g.run(repo, "add", "OK")
    g.run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "big")
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)
    engine.approve(engine.approve(job.id).id)

    request = next(r for r in provider.requests if r.role is RoleName.BACKEND)
    assert _context(request)["files"]["OK"] == _big(1000)  # whole, not cut at 12 KB
    assert "files_cut" not in _context(request)


def test_a_file_too_big_to_show_is_changed_by_edits_until_one_fits(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    (repo / "OK").write_bytes(_big(4000).encode())  # ~136 KB, past what is sent whole
    g.run(repo, "add", "OK")
    g.run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "big")
    provider = full_provider(seed, phases=1)
    answers = [
        # whole contents of a file it was shown cut: refused, it would lose the rest
        {"summary": "rewrote", "changes": [{"path": "OK", "content": "only this\n"}]},
        # an edit whose text is not in the file: refused, with the real lines shown
        {
            "summary": "edit",
            "changes": [
                {
                    "path": "OK",
                    "content": None,
                    "edits": [{"find": "const line7 = 8;", "replace": "x"}],
                },
                {"path": "NEW", "content": "never written\n"},
            ],
        },
        {
            "summary": "edit",
            "changes": [
                {
                    "path": "OK",
                    "content": None,
                    "edits": [{"find": "const line7 = 7;", "replace": "const line7 = 70;"}],
                }
            ],
        },
    ]
    provider.replies[RoleName.BACKEND] = lambda _req: answers.pop(0)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)
    engine.approve(engine.approve(job.id).id)

    requests = [r for r in provider.requests if r.role is RoleName.BACKEND]
    asked = [_context(r) for r in requests]
    assert len(asked) == 3 and asked[0]["files_cut"] == ["OK"]
    assert "`edits`" in requests[0].prompt.split("Context:")[0]  # told how to change it
    assert "truncated" in asked[0]["files"]["OK"][-200:]
    assert "was shown cut" in asked[1]["continuation"]["edit_failed"]
    failed = asked[2]["continuation"]["edit_failed"]
    assert "is not in it" in failed and "    8| const line7 = 7; // keep me" in failed
    worktree = store.get(job.id).worktree_path
    assert worktree is not None
    text = (worktree / "OK").read_bytes().decode()
    assert "const line7 = 70;" in text and text.count("// keep me") == 4000  # nothing lost
    assert not (worktree / "NEW").exists()  # a refused answer writes none of itself


# -- T15.5: one budget for a phase ------------------------------------------------------------


def test_a_phase_whose_build_never_passes_stops_at_its_budget_and_waits_for_words(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    import pytest

    from slipwright.engine import EmptyApproval
    from tests.pipeline import FALSE

    broken = seed.model_copy(update={"test_cmd": FALSE})
    provider = full_provider(broken, phases=1)
    written = iter(range(1000))
    provider.replies[RoleName.BACKEND] = lambda _req: {
        "summary": "another try",
        "changes": [{"path": "OK", "content": f"try {next(written)}\n"}],
    }

    def qa(req: Any) -> dict[str, Any]:
        if "spent its budget" in req.prompt:
            return {"summary": "it loops", "recommendation": "Split the phase in two."}
        return {"summary": "the code", "gate_verdict": "code_is_wrong"}

    provider.replies[RoleName.QA] = qa
    engine = full_engine(store, worktrees_root, broken, provider, max_build_attempts=50)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(engine.approve(job.id).id)

    assert job.state is JobState.AWAITING_DECISION
    assert job.data.decision_kind == "phase_budget"
    assert job.data.recommendation == "Split the phase in two."
    # eight calls, developer and triage alike, then the recommendation as the last allowance
    assert job.data.phase_calls == 9
    before = len(provider.requests)

    with pytest.raises(EmptyApproval):
        engine.approve(job.id)  # a plain yes would spend another budget the same way
    assert len(provider.requests) == before

    job = engine.reject(job.id, "Only make the OK file say yes.")
    asked = [r for r in provider.requests[before:] if r.role is RoleName.BACKEND]
    assert asked and _context(asked[0])["messages_from_human"] == ["Only make the OK file say yes."]
    assert store.get(job.id).data.decision_kind == "phase_budget"  # and stopped again, fresh
