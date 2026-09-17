---
domain: testing
tags: [pytest, unit, integration, e2e, fixtures, coverage, flaky, test-cases, review]
applies_to: [python, pytest, typescript, vitest, playwright, any]
---

# Testing

## Test pyramid and what to test

Most tests are unit tests of behaviour through the public interface; integration tests
cover one real boundary at a time (the database, the HTTP layer, a queue) with fakes for
the rest; a few end-to-end tests walk the main user journeys. Do not test private
helpers directly, do not assert on log text, and do not test the framework.

## Naming and structure

Test files mirror the source tree (`tests/test_<module>.py`, `Foo.test.ts`). Names
state the behaviour and the condition: `test_refund_is_rejected_when_invoice_is_unpaid`.
Arrange–act–assert with blank lines between the three; one behaviour per test; the
assertion message explains what should have happened. Shared setup lives in fixtures,
not in module-level globals.

## Fixtures and fakes

Prefer in-process fakes over mocks for external services (a fake Jira, a fake mail
sender that records calls); mock only at the boundary you own. Every fake enforces the
same contract as the real thing (status codes, error shapes). Tests never touch the
network, the real clock or the real file system outside a temporary directory.

## Proposing test cases

When asked for test cases before code is written, list them as `name` + what it checks,
covering: the happy path, each validation rule, each error path the code declares, the
empty/zero case, boundaries (limits, pagination edges), concurrency or idempotency where
the design promises it, and permissions. One case per behaviour; no "test everything"
cases; no cases for behaviour the phase does not implement.

## Determinism and speed

No sleeps, no time-dependent assertions (inject a clock), no order dependence between
tests, no shared mutable state. A unit test runs in milliseconds; mark anything slower
than a second and keep it out of the default run. Fix flaky tests the day they appear;
never wrap them in retries.

## Coverage and gates

New code ships with tests for every branch it adds; the build gate runs the whole
suite, not a subset. Coverage is a signal, not a target: never write assertion-free
tests to move the number. A failing test is fixed by fixing the cause or, when the test
was wrong, by changing the test in the same change with the reason in the summary.

## Reviewing a change against the standards

When reviewing a diff, cite the section a violation breaks, the file and line, and a
concrete fix. Classify: `blocking` for security, data loss, broken contracts or missing
tests for new behaviour; `advisory` for naming, structure and style. Say "no
violations" when the diff is clean — do not invent findings to have something to report.
