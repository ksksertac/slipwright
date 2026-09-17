"""Legacy job dashboard: plain server-rendered HTML, kept until the React UI reaches parity (T8.7).

``GET /legacy`` lists jobs with state, current phase and pending approvals; ``GET /ui/jobs/{id}``
shows one job with its full history (diffs, build logs, proposed profile and plan). Form
posts under ``/ui/...`` call the engine exactly like the JSON API and redirect back.
"""

# ruff: noqa: E501 - inline CSS and HTML fragments are long by nature
from __future__ import annotations

import contextlib
import html
import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from slipwright.engine import Engine, NotAwaitingApproval, approval_edges
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.store import JobNotFound

router = APIRouter(prefix="/legacy", include_in_schema=False)

_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#e3e3e3;--ok:#1a7f37;--warn:#9a6700;--bad:#c62828;--wait:#0550ae;--code:#f6f8fa}
@media (prefers-color-scheme:dark){:root{--bg:#111;--fg:#e6e6e6;--muted:#9a9a9a;--line:#333;--code:#1b1b1b}}
body{font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);max-width:1100px;margin:auto}
h1,h2,h3{font-weight:600;margin:0 0 12px}h1{font-size:22px}h2{font-size:17px;margin-top:28px}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:500;font-size:13px}
a{color:inherit}code,pre{font:13px/1.45 ui-monospace,Menlo,Consolas,monospace}
pre{background:var(--code);padding:10px 12px;overflow:auto;max-height:420px;border-radius:6px;white-space:pre-wrap}
.state{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;border:1px solid var(--line)}
.s-wait{color:var(--wait);border-color:var(--wait)}.s-done{color:var(--ok);border-color:var(--ok)}
.s-failed{color:var(--bad);border-color:var(--bad)}.s-work{color:var(--warn);border-color:var(--warn)}
form{display:inline-block;margin:0 6px 6px 0}input[type=text]{padding:5px 8px;min-width:280px;border:1px solid var(--line);border-radius:4px;background:var(--bg);color:var(--fg)}
button{padding:5px 12px;border:1px solid var(--line);border-radius:4px;background:var(--code);color:var(--fg);cursor:pointer}
button.ok{border-color:var(--ok);color:var(--ok)}button.bad{border-color:var(--bad);color:var(--bad)}
details{border:1px solid var(--line);border-radius:6px;padding:8px 12px;margin:8px 0}summary{cursor:pointer}
.muted{color:var(--muted)}.gate{background:var(--code);border-left:3px solid var(--wait);padding:10px 14px;margin:12px 0;border-radius:4px}
textarea{width:100%;min-height:140px;font:13px ui-monospace,monospace;padding:8px;border:1px solid var(--line);border-radius:4px;background:var(--bg);color:var(--fg)}
"""


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _state_badge(state: JobState) -> str:
    cls = (
        "s-wait"
        if state in APPROVAL_STATES
        else "s-done"
        if state is JobState.DONE
        else "s-failed"
        if state is JobState.FAILED
        else "s-work"
    )
    return f"<span class='state {cls}'>{_e(state.value)}</span>"


def _current_phase(job: Job) -> str:
    phases = (job.data.plan or {}).get("phases", [])
    if job.state in (JobState.DEVELOPING, JobState.BUILD_GATE) and phases:
        i = min(job.data.phase_index, len(phases) - 1)
        return f"phase {i + 1}/{len(phases)}: {phases[i].get('goal', '')}"
    if job.state is JobState.QA or (
        job.state is JobState.AWAITING_TEST_APPROVAL and job.data.qa_stage
    ):
        return f"qa stage {job.data.qa_stage}"
    if job.state is JobState.DEVOPS and job.data.pr_url:
        return f"CI on {job.data.pr_url}"
    if job.history:
        return job.history[-1].note or ""
    return ""


def _pending(job: Job) -> str:
    if job.state is JobState.AWAITING_PROFILE_APPROVAL:
        return "profile"
    if job.state is JobState.AWAITING_PLAN_APPROVAL:
        return "plan"
    if job.state is JobState.AWAITING_TEST_APPROVAL:
        return "test cases" if job.data.qa_stage == 1 else "written tests"
    return ""


def _gate_forms(job: Job) -> str:
    if approval_edges(job) is None:
        return ""
    base = f"/legacy/ui/jobs/{_e(job.id)}"
    return (
        f"<form method='post' action='{base}/approve'><button class='ok'>Approve {_e(_pending(job))}</button></form>"
        f"<form method='post' action='{base}/reject'><input type='text' name='feedback' placeholder='why?' required>"
        f" <button class='bad'>Reject</button></form>"
    )


def _job_row(job: Job) -> str:
    return (
        "<tr>"
        f"<td><a href='/legacy/ui/jobs/{_e(job.id)}'><code>{_e(job.id)}</code></a></td>"
        f"<td>{_e(job.request)}</td>"
        f"<td>{_state_badge(job.state)}</td>"
        f"<td>{_e(_current_phase(job))}</td>"
        f"<td>{_gate_forms(job) or '<span class=muted>—</span>'}</td>"
        "</tr>"
    )


def _history(job: Job) -> str:
    rows = []
    for i, t in enumerate(job.history):
        head = f"<b>{_e(t.at.strftime('%Y-%m-%d %H:%M:%S'))}</b> {_e(t.from_state.value)} → {_e(t.to_state.value)}"
        if t.note:
            head += f" — {_e(t.note)}"
        if t.detail:
            rows.append(
                f"<details id='h{i}'><summary>{head}</summary><pre>{_e(t.detail)}</pre></details>"
            )
        else:
            rows.append(f"<div style='padding:8px 12px'>{head}</div>")
    return "".join(rows) or "<p class=muted>no history yet</p>"


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    engine: Engine = request.app.state.engine
    jobs = engine.store.list()
    waiting = [j for j in jobs if j.state in APPROVAL_STATES]
    body = [
        "<h1>Slipwright</h1>",
        f"<p class=muted>{len(jobs)} job(s), {len(waiting)} awaiting approval</p>",
        "<table><tr><th>job</th><th>request</th><th>state</th><th>current phase</th><th>pending approval</th></tr>",
        *(_job_row(j) for j in reversed(jobs)),
        "</table>",
        "<h2>New job</h2>",
        "<form method='post' action='/legacy/ui/jobs' style='display:block'>"
        "<input type='text' name='repo_path' placeholder='absolute path to a git repo' required> "
        "<input type='text' name='request' placeholder='what should be done?' required> "
        "<button class='ok'>Start</button></form>",
    ]
    return _page("Slipwright", "".join(body))


@router.get("/ui/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: str, request: Request) -> HTMLResponse:
    engine: Engine = request.app.state.engine
    try:
        job = engine.store.get(job_id)
    except JobNotFound:
        return HTMLResponse(_page("Not found", "<h1>job not found</h1>").body, status_code=404)

    gate = ""
    if approval_edges(job) is not None:
        extra = ""
        if job.state is JobState.AWAITING_TEST_APPROVAL and job.data.qa_stage == 1:
            cases = json.dumps(job.data.test_cases, indent=2)
            extra = (
                f"<form method='post' action='/legacy/ui/jobs/{_e(job.id)}/tests' style='display:block;margin-top:10px'>"
                f"<label>Test cases (JSON list of {{name, description}}):</label>"
                f"<textarea name='test_cases'>{_e(cases)}</textarea>"
                "<button>Save test cases</button></form>"
            )
        gate = f"<div class='gate'><b>Awaiting approval: {_e(_pending(job))}</b><br>{_gate_forms(job)}{extra}</div>"

    plan = job.data.plan or {}
    plan_html = ""
    if plan.get("phases"):
        items = "".join(
            f"<li>{'✅ ' if i < job.data.phase_index else ''}{_e(p.get('goal'))} "
            f"<span class=muted>{_e(', '.join(p.get('files', [])))}</span></li>"
            for i, p in enumerate(plan["phases"])
        )
        plan_html = f"<h2>Plan</h2><p>{_e(plan.get('summary', ''))}</p><ol>{items}</ol>"

    inbox = ""
    if job.data.inbox:
        rows = "".join(
            f"<li>{_e(m.text)} <span class=muted>({'consumed by ' + _e(m.consumed_by) if m.consumed_by else 'pending'})</span></li>"
            for m in job.data.inbox
        )
        inbox = f"<h2>Inbox</h2><ul>{rows}</ul>"

    body = [
        "<p><a href='/legacy'>← all jobs</a></p>",
        f"<h1><code>{_e(job.id)}</code> {_state_badge(job.state)}</h1>",
        f"<p>{_e(job.request)}</p>",
        "<table>",
        f"<tr><th>repo</th><td><code>{_e(job.repo_path)}</code></td></tr>",
        f"<tr><th>worktree</th><td><code>{_e(job.worktree_path or '—')}</code></td></tr>",
        f"<tr><th>branch / port</th><td><code>{_e(job.branch)}</code> / {_e(job.port or '—')}</td></tr>",
        f"<tr><th>phase</th><td>{_e(_current_phase(job))}</td></tr>",
        f"<tr><th>PR</th><td>{('<a href=' + _e(job.data.pr_url) + '>' + _e(job.data.pr_url) + '</a>') if job.data.pr_url else '—'}</td></tr>",
        "</table>",
        gate,
        plan_html,
        inbox,
        "<h2>Steer</h2>",
        f"<form method='post' action='/legacy/ui/jobs/{_e(job.id)}/message'><input type='text' name='text' placeholder='message for the next role' required> <button>Send</button></form>",
        "<h2>History</h2>",
        _history(job),
    ]
    return _page(f"Job {job.id}", "".join(body))


def _back(job_id: str) -> RedirectResponse:
    return RedirectResponse(f"/legacy/ui/jobs/{job_id}", status_code=303)


@router.post("/ui/jobs")
def ui_new(
    request: Request,
    background: BackgroundTasks,
    repo_path: str = Form(),
    req: str = Form(alias="request"),
) -> RedirectResponse:
    from pathlib import Path

    from slipwright.api import _resume

    engine: Engine = request.app.state.engine
    job = engine.create_job(req, Path(repo_path))
    engine.start(job.id, run=False)
    background.add_task(_resume, engine, job.id)
    return _back(job.id)


@router.post("/ui/jobs/{job_id}/approve")
def ui_approve(job_id: str, request: Request, background: BackgroundTasks) -> RedirectResponse:
    from slipwright.api import _resume

    engine: Engine = request.app.state.engine
    try:
        engine.approve(job_id, run=False)
    except (NotAwaitingApproval, JobNotFound):
        return _back(job_id)
    background.add_task(_resume, engine, job_id)
    return _back(job_id)


@router.post("/ui/jobs/{job_id}/reject")
def ui_reject(
    job_id: str, request: Request, background: BackgroundTasks, feedback: str = Form()
) -> RedirectResponse:
    from slipwright.api import _resume

    engine: Engine = request.app.state.engine
    try:
        engine.reject(job_id, feedback, run=False)
    except (NotAwaitingApproval, JobNotFound):
        return _back(job_id)
    background.add_task(_resume, engine, job_id)
    return _back(job_id)


@router.post("/ui/jobs/{job_id}/tests")
def ui_tests(job_id: str, request: Request, test_cases: str = Form()) -> RedirectResponse:
    engine: Engine = request.app.state.engine
    try:
        cases = json.loads(test_cases)
        if isinstance(cases, list):
            engine.set_test_cases(job_id, [c for c in cases if isinstance(c, dict)])
    except (ValueError, NotAwaitingApproval, JobNotFound):
        pass
    return _back(job_id)


@router.post("/ui/jobs/{job_id}/message")
def ui_message(job_id: str, request: Request, text: str = Form()) -> RedirectResponse:
    engine: Engine = request.app.state.engine
    with contextlib.suppress(JobNotFound):
        engine.message(job_id, text)
    return _back(job_id)


__all__ = ["router"]
