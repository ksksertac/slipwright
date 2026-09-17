---
domain: backend
tags: [api, http, rest, errors, validation, pagination, versioning]
applies_to: [python, fastapi, node, go, java, any]
---

# Services and APIs

## API design

Resources are nouns in plural (`/invoices`, `/invoices/{id}`); actions that are not CRUD
are sub-resources or verbs under the resource (`/invoices/{id}/refund`). Use the HTTP
verb for intent: GET reads and is idempotent, PUT replaces, PATCH updates part, DELETE
removes, POST creates or triggers. Return 201 with the created representation, 204 with
no body for deletes, 404 for unknown ids and 409 for state conflicts (a resource that
cannot change in its current state). Never return 200 with an error inside the body.

## Request validation

Validate every request at the boundary with the framework's schema layer (pydantic,
zod, bean validation …), never by hand inside handlers. Reject unknown fields. Return
422 (or the framework's validation status) with a machine-readable list of field errors.
Business rules that need data (uniqueness, balance checks) live in the service layer and
map to 409 or 400 with a stable error code, not a free-text message.

## Error responses

Every error body has the same shape: `{"error": {"code": "invoice_not_found",
"message": "human readable", "details": {...}}}`. Codes are stable snake_case
identifiers clients can switch on; messages may change. Never leak stack traces,
SQL, or internal paths. Log the full exception server-side with a correlation id and
return that id in the response so support can find it.

## Pagination and filtering

List endpoints paginate by default (page size 50, maximum 200) using cursor pagination
for anything that can grow past a few thousand rows; offset pagination is acceptable
only for small, admin-only lists. Filters are query parameters named after the field
(`?status=open&customer_id=…`); sorting is `?sort=-created_at`. Responses carry
`next_cursor` (or `null`) so clients never guess.

## Versioning and compatibility

Add fields freely; never remove or rename a field, change its type, or change the
meaning of an existing status without a version bump. Version in the path (`/v2/`) only
when a breaking change is unavoidable, and keep the old version running until every
client is migrated. Deprecations are announced in the response (`Deprecation` header)
and in the changelog before removal.

## Idempotency and retries

Any POST that creates money movement, messages or external side effects accepts an
`Idempotency-Key` header and returns the original result for a repeated key. Outbound
calls to other services use timeouts (connect 2 s, read 10 s unless documented) and
bounded retries with exponential backoff and jitter; retry only idempotent operations
and only on transient failures (timeouts, 502/503/504, connection reset).
