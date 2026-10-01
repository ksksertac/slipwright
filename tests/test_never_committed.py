"""What a package manager or a build leaves in a checkout is never the work: it is not
committed, and no role is shown it. A phase once committed all of ``node_modules`` and
QA's review went to the model at 150 million characters."""

from __future__ import annotations

from pathlib import Path

import pytest

from slipwright.workspace import git as g


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _tracked(repo: Path) -> set[str]:
    return set(g.run(repo, "ls-files").stdout.split())


def test_dependencies_and_build_output_are_not_committed(repo: Path) -> None:
    _write(
        repo,
        {
            "src/app.ts": "export const a = 1\n",
            "node_modules/typescript/lib/typescript.js": "x\n" * 100,
            "web/node_modules/vite/index.js": "y\n",
            "app/build/outputs/app.apk": "binary\n",
            ".gradle/8.14/cache.bin": "z\n",
        },
    )
    g.stage_all(repo)
    g.commit(repo, "phase 1")

    assert _tracked(repo) == {"README.md", "src/app.ts"}
    # the project's own .gitignore is not where this is kept
    assert not (repo / ".gitignore").exists()


def test_what_was_committed_by_mistake_leaves_with_the_next_commit(repo: Path) -> None:
    _write(repo, {"node_modules/left/index.js": "old\n", "src/a.py": "a = 1\n"})
    g.run(repo, "add", "-A")
    g.commit(repo, "the old way: everything")
    assert "node_modules/left/index.js" in _tracked(repo)

    _write(repo, {"src/a.py": "a = 2\n"})
    g.stage_all(repo)
    # nor is the leaving shown to a role as a change of the work
    assert "node_modules" not in g.staged_diff(repo)
    g.commit(repo, "phase 2")

    assert "node_modules/left/index.js" not in _tracked(repo)
    assert (repo / "node_modules" / "left" / "index.js").exists()  # still on disk, for the build


def test_a_diff_shown_to_a_role_leaves_dependencies_out(repo: Path) -> None:
    base = g.head_commit(repo)
    _write(repo, {"node_modules/big.js": "x\n" * 1000, "src/a.py": "a = 1\n"})
    g.run(repo, "add", "-A")
    g.commit(repo, "the old way: everything")

    shown = g.diff(repo, base)
    assert "src/a.py" in shown and "node_modules" not in shown
    assert [path for path, _, _ in g.numstat(repo, base)] == ["src/a.py"]


def test_lock_files_and_compiled_output_are_committed_but_not_shown(repo: Path) -> None:
    base = g.head_commit(repo)
    _write(
        repo,
        {
            "package-lock.json": "{}\n" * 9000,
            "web/yarn.lock": "x\n",
            "dist/data/questions.js": "compiled\n",
            "src/data/questions.ts": "export const q = []\n",
        },
    )
    g.stage_all(repo)
    g.commit(repo, "phase 1")

    assert {"package-lock.json", "web/yarn.lock", "dist/data/questions.js"} <= _tracked(repo)
    shown = g.diff(repo, base)
    assert "src/data/questions.ts" in shown
    assert "lock" not in shown and "dist/" not in shown


def test_a_diff_too_big_to_send_says_which_files_and_sends_what_fits(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(g, "MAX_DIFF_CHARS", 2_000)
    base = g.head_commit(repo)
    _write(repo, {f"src/m{i}.py": f"value = {i}\n" * 50 for i in range(10)})
    g.stage_all(repo)
    g.commit(repo, "a big phase")

    shown = g.diff(repo, base)
    assert len(shown) < 4_000
    assert "characters" in shown and "cut here" in shown
    assert all(f"src/m{i}.py" in shown for i in range(10))  # every file is named
