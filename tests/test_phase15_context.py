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
    assert "+++" not in described["changed_files"]


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
