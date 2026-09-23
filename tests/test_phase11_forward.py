"""T11 — a job written by a newer build still loads in an older one.

Two builds share a database whenever a deploy is rolled back, or while one process is
being replaced by another. The fields the newer build added must survive that: refusing
them takes the whole server down, and dropping them loses work that has already happened.
"""

from __future__ import annotations

import json
from pathlib import Path

from slipwright.schemas.job import Job, JobData, JobState
from slipwright.store import JobStore


def test_unknown_fields_are_kept_rather_than_refused() -> None:
    data = JobData.model_validate(
        {"language": "tr", "cost_usd": 0.11, "deploy": {"target": "aws"}, "deploy_written": []}
    )
    assert data.language == "tr"
    dumped = data.model_dump(mode="json")
    assert dumped["cost_usd"] == 0.11
    assert dumped["deploy"] == {"target": "aws"}
    assert dumped["deploy_written"] == []


def test_a_job_row_from_a_newer_build_loads_and_keeps_its_fields(
    store: JobStore, repo: Path
) -> None:
    job = store.create(Job(request="x", repo_path=repo))
    # what a newer build would have written into this row, straight into the database
    raw = store._conn.execute(  # noqa: SLF001 - the point is what a foreign writer left
        "SELECT data_json FROM jobs WHERE id = ?", (job.id,)
    ).fetchone()[0]
    payload = json.loads(raw)
    payload["cost_usd"] = 0.42
    payload["a_field_from_the_future"] = {"kept": True}
    store._conn.execute(  # noqa: SLF001
        "UPDATE jobs SET data_json = ? WHERE id = ?", (json.dumps(payload), job.id)
    )

    again = store.get(job.id)
    assert again.state is JobState.CREATED
    assert again.data.model_dump(mode="json")["cost_usd"] == 0.42

    # and a save from this build does not throw the unknown fields away
    again.data.feedback = "note"
    store.save(again)
    once_more = store.get(job.id)
    dumped = once_more.data.model_dump(mode="json")
    assert dumped["feedback"] == "note"
    assert dumped["a_field_from_the_future"] == {"kept": True}
