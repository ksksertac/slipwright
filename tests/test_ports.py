import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from slipwright.schemas.job import Job
from slipwright.workspace import NoFreePort, PortAllocator, Workspace, WorktreeError
from slipwright.workspace import git as g


def test_allocate_returns_distinct_bindable_ports() -> None:
    alloc = PortAllocator(start=8100, end=8199)
    ports = [alloc.allocate() for _ in range(5)]
    assert len(set(ports)) == 5
    assert all(8100 <= p <= 8199 for p in ports)
    assert alloc.reserved == frozenset(ports)


def test_release_makes_port_available_again() -> None:
    alloc = PortAllocator(start=8100, end=8101)
    a = alloc.allocate()
    b = alloc.allocate()
    with pytest.raises(NoFreePort):
        alloc.allocate()
    alloc.release(a)
    assert alloc.allocate() == a
    alloc.release(None)  # tolerated
    assert alloc.reserved == {a, b}


def test_skips_ports_already_bound_by_someone_else() -> None:
    alloc = PortAllocator(start=8100, end=8110)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 8100))
        blocker.listen()
        assert alloc.allocate() == 8101


def test_reserve_seeds_from_persisted_jobs() -> None:
    alloc = PortAllocator(start=8100, end=8105)
    alloc.reserve([8100, 8101])
    assert alloc.allocate() == 8102


def test_invalid_range_rejected() -> None:
    with pytest.raises(ValueError):
        PortAllocator(start=80, end=90)
    with pytest.raises(ValueError):
        PortAllocator(start=9000, end=8000)


def test_ten_concurrent_jobs_get_distinct_ports(repo: Path, worktrees_root: Path) -> None:
    ws = Workspace(worktrees_root, PortAllocator(start=8100, end=8199))
    jobs = [Job(request=f"job {i}", repo_path=repo) for i in range(10)]
    with ThreadPoolExecutor(max_workers=10) as pool:
        created = list(pool.map(ws.create, jobs))

    ports = [j.port for j in created]
    assert None not in ports
    assert len(set(ports)) == 10
    assert ws.ports.reserved == frozenset(p for p in ports if p is not None)


def test_destroy_releases_port(repo: Path, worktrees_root: Path) -> None:
    ws = Workspace(worktrees_root, PortAllocator(start=8100, end=8100))
    job = ws.create(Job(request="x", repo_path=repo))
    assert job.port == 8100
    with pytest.raises(NoFreePort):
        ws.create(Job(request="y", repo_path=repo))

    ws.destroy(job)
    assert job.port is None
    assert ws.ports.reserved == frozenset()
    again = ws.create(Job(request="y", repo_path=repo))
    assert again.port == 8100


def test_worktree_failure_releases_port(repo: Path, worktrees_root: Path) -> None:
    ws = Workspace(worktrees_root, PortAllocator(start=8100, end=8100))
    job = Job(request="x", repo_path=repo)
    g.run(repo, "branch", job.branch)  # make worktree creation fail
    with pytest.raises(WorktreeError):
        ws.create(job)
    assert job.port is None
    assert ws.ports.reserved == frozenset()


def test_reserve_ports_from_jobs_after_restart(repo: Path, worktrees_root: Path) -> None:
    first = Workspace(worktrees_root, PortAllocator(start=8100, end=8105))
    survivors = [first.create(Job(request=f"j{i}", repo_path=repo)) for i in range(2)]

    # "restart": a fresh Workspace knows nothing until seeded from the store
    second = Workspace(worktrees_root, PortAllocator(start=8100, end=8105))
    second.reserve_ports(survivors)
    fresh = second.create(Job(request="new", repo_path=repo))
    assert fresh.port not in {j.port for j in survivors}
