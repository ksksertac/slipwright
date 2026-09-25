"""T11 — a job written by a newer build still loads in an older one.

Two builds share a database whenever a deploy is rolled back, or while one process is
being replaced by another. The fields the newer build added must survive that: refusing
them takes the whole server down, and dropping them loses work that has already happened.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select, update

from slipwright.schemas.job import Job, JobData, JobState
from slipwright.store import JobStore
from slipwright.store.schema import jobs


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
    with store.db.connect() as conn:
        raw = conn.execute(
            select(jobs.c.data_json).where(jobs.c.id == job.id)
        ).scalar_one()
    payload = json.loads(raw)
    payload["cost_usd"] = 0.42
    payload["a_field_from_the_future"] = {"kept": True}
    with store.db.begin() as conn:
        conn.execute(
            update(jobs).where(jobs.c.id == job.id).values(data_json=json.dumps(payload))
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
