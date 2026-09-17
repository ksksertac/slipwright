# Legacy dashboard parity

Every flow of the server-rendered dashboard (`slipwright/api/ui.py`, served at `/legacy`
until T8.7) and where it lives in the React app. T8.7 deletes `ui.py` once every row is
checked.

| # | Legacy flow (`/legacy`) | React equivalent | Done |
|---|---|---|---|
| 1 | Job list with state, current phase, pending approval | `/projects` (running jobs, pending approvals per project) and `/projects/:id/overview`, `/projects/:id/developments` | [x] |
| 2 | "New job" form: repository path + request | `/projects/new` (local path or GitHub repo) then `/projects/:id/developments` → "New development" | [x] |
| 3 | Job page header: id, state badge, request, repo, worktree, port, PR link | `/projects/:id/jobs/:jobId` header + stepper | [x] |
| 4 | Approve button at every gate | `GateActions` on the job page and inline on the project overview | [x] |
| 5 | Reject with feedback text | `GateActions` → "Reject…" with inline feedback | [x] |
| 6 | Proposed profile shown as JSON while awaiting approval | `ProfileGate`: editable `ProfileForm`, saved via `PUT /api/jobs/:id/profile` | [x] |
| 7 | Proposed plan shown while awaiting approval | `PlanGate`: epics → stories → tasks with phase goals and files | [x] |
| 8 | Edit test cases (textarea) before approving | `TestCasesGate`: add / remove / edit rows, `PUT /api/jobs/:id/tests` | [x] |
| 9 | Written tests shown before the second approval | `WrittenTestsGate`: diff + gate output | [x] |
| 10 | Send a steering message; see consumed messages | `Steering` section: send form, per-message consumed-by | [x] |
| 11 | Full phase history with expandable detail (diff / build log / JSON) | `History` (same rows as the activity feed) and `Phases` (per-phase diffs and gate attempts, anchors `#phase-N`) | [x] |
| 12 | "← all jobs" navigation | Breadcrumbs on every page | [x] |
| 13 | Failed job: reason and traceback | `GatePanel` failure box with detail | [x] |
| 14 | Works without JavaScript | Not carried over: the React app needs JavaScript; the JSON API and CLI remain for scripts | [x] |
