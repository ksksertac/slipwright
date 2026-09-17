---
domain: web
tags: [react, components, state, styling, accessibility, forms, api-client, performance]
applies_to: [react, typescript, vite, nextjs, vue, any]
---

# Web front-end

## Components and files

One component per file, named like the file, exported by name. Pages compose feature
components; feature components compose UI primitives from the shared `components/`
folder — never copy a primitive's markup into a page. Props are typed explicitly; avoid
`any`. Keep components under ~250 lines; split by responsibility, not by size.

## State

Server data lives in the query layer (TanStack Query or the project's equivalent), keyed
so that live updates can invalidate exactly what changed; never copy server data into
local state to edit it unless the user is editing (then track `dirty` and follow the
server value until they do). Local UI state stays in the component. Global stores only
for cross-cutting concerns (session, theme). No state derived from props via effects —
derive during render.

## API access

All calls go through the typed client generated from the API's OpenAPI schema; no raw
`fetch` in components. Handle the three states explicitly: loading (skeleton, not a
spinner over the whole page), error (inline callout with the server's message), empty
(a sentence that says what to do next). Mutations show pending state on the button and
a toast on success or failure.

## Styling and theming

Colours, spacing, radii and fonts come from the design tokens in `styles.css`; never
hard-code a hex value in a component. Support light and dark themes through the tokens.
Layouts must work at 360 px width with a 16 px gutter and no horizontal scroll. Prefer
CSS classes over inline styles except for one-off sizes.

## Accessibility

Every interactive element is a `button` or `a` (not a `div` with `onClick`), has a
visible focus ring and an accessible name; icon-only buttons carry `aria-label`. Forms
use `label` bound to the input by `id`. Colour never carries meaning alone — pair it with
text or an icon. Modals trap focus and close on Escape. Test with keyboard only before
calling a page done.

## Forms

Validate on submit and show field-level errors next to the field; disable the submit
button while pending, never silently ignore a click. Preserve what the user typed when a
request fails. Password and token fields are `type="password"`, `autocomplete="off"`
for secrets, and never echo a stored secret back into the input.

## Performance

Code-split by route; lazy-load heavy views (editors, charts). Avoid re-rendering large
lists on every keystroke — debounce searches, key lists by stable ids, memoize expensive
derivations. Images carry width/height. Measure with the browser profiler before
optimising; do not add memoization speculatively.
