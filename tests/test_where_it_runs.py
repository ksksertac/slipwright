"""Every role that writes code or tests is told where they run.

Only the Architect was. QA, never told, wrote a mobile app's tests to launch the APK on two
emulators and read it with a screen reader -- on a server with no device, no emulator and
nothing it may install -- and the build gate failed the same way three times running.
"""

from __future__ import annotations

from slipwright.roles import qa
from slipwright.roles.specialists import DEVELOPER_ROLES
from slipwright.schemas.job import APPROVAL_STATES, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider
from tests.test_phase15_context import _context


def test_qa_and_the_developers_are_told_there_is_no_device_and_nothing_to_install(
    store: JobStore,
    repo,
    worktrees_root,
    seed: Profile,  # type: ignore[no-untyped-def]
) -> None:
    provider = full_provider(seed, phases=2)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)
    for _ in range(40):
        if job.state not in APPROVAL_STATES:
            break
        job = engine.approve(job.id)
    assert job.state is JobState.DONE

    told = {
        r.role: _context(r)["where_it_runs"]
        for r in provider.requests
        if (r.role in (RoleName.QA, RoleName.DEVOPS) or r.role in DEVELOPER_ROLES)
        and "where_it_runs" in _context(r)
    }
    assert RoleName.QA in told and RoleName.DEVOPS in told
    assert any(role in DEVELOPER_ROLES for role in told), "a developer"
    for where in told.values():
        assert "no device, emulator or simulator" in where["rules"]
        assert "nothing can be installed" in where["rules"]
        assert isinstance(where["installed"], list)


def test_qa_proposes_no_case_a_device_is_needed_for_and_rewrites_a_test_that_needs_one() -> None:
    # stage 1: such a check goes to a person, not into the list
    assert "is not a test case here" in qa.STAGE_ONE and "by hand" in qa.STAGE_ONE
    # stage 2: never written
    assert "Never write one that needs a device" in qa.STAGE_TWO
    # and a test that needs one is the test's fault, which QA mends, not the code's
    assert "`where_it_runs` says is not there" in qa.GATE_TRIAGE
