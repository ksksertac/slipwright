"""The pipeline's phase cards say what T16 does: which phases are ready, which are being
written alongside, and the commit each one was recorded in."""

from __future__ import annotations

from pathlib import Path

from slipwright.pipeline import lane_for
from slipwright.schemas.job import Job, JobState


def _job(repo: Path) -> Job:
    job = Job(request="x", repo_path=repo)
    job.state = JobState.DEVELOPING
    job.data.plan = {
        "phases": [
            {"goal": "api", "task_id": "t1", "depends_on": []},
            {"goal": "web", "task_id": "t2", "depends_on": [1]},
            {"goal": "docs", "task_id": "t3", "depends_on": []},
            {"goal": "all", "task_id": "t4", "depends_on": [2, 3]},
        ]
    }
    job.data.phase_index = 1  # phase 1 is built, phase 2 is being built
    job.data.ahead = {"3": {"role": "backend", "started_at": "2026-10-02T10:00:00+00:00"}}
    job.data.phase_commits = {"1": "abc1234def"}
    job.data.draft_pr_url = "https://github.com/acme/app/pull/7"
    return job


def test_the_cards_say_ready_alongside_and_the_commit(repo: Path) -> None:
    lane = lane_for(_job(repo))
    cards = {c.phase: c for c in lane.steps if c.key.startswith("phase:")}
    assert cards[1].commit == "abc1234def"
    assert cards[1].commit_url == "https://github.com/acme/app/commit/abc1234def"
    assert cards[3].ahead and cards[3].ready  # needs nothing; being written now
    assert not cards[4].ready  # needs 2, which is not built yet
