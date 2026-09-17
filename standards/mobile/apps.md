---
domain: mobile
tags: [flutter, react-native, ios, android, navigation, offline, sync, permissions, releases]
applies_to: [flutter, react-native, swift, kotlin, any]
---

# Mobile apps

## Project structure

Feature-first folders (`features/invoices/{screens,widgets,state,api}`) over layer-first.
Shared UI primitives, theme and networking live under `core/`. One screen per file; a
screen composes widgets and holds no business logic — that lives in the feature's state
layer (bloc/provider/store) so it can be unit-tested without a device.

## Navigation

Every screen has a route name and typed parameters; deep links map to the same routes.
Back behaviour follows the platform: Android hardware back pops the stack, iOS uses the
navigation bar. Never push the same screen twice on a double tap — guard navigation
calls. Preserve scroll position and form input across rotation and backgrounding.

## Networking and offline

All API access goes through one client with a base URL from build configuration, auth
header injection, timeouts (connect 5 s, read 15 s) and a single place that maps HTTP
errors to typed failures. Reads are cache-first with a stale indicator; writes that must
survive a dead network are queued locally with an idempotency key and replayed in order
when connectivity returns. Show connectivity state to the user; never fail silently.

## State and data

Immutable models generated from the API schema; parse at the boundary, never pass raw
JSON around. Local persistence (SQLite / secure storage) is behind a repository
interface. Secrets and tokens go in the platform secure store (Keychain / EncryptedShared
Preferences), never in plain preferences or files.

## Permissions and privacy

Ask for a permission at the moment it is needed with a one-sentence reason the user
would accept; handle "denied" and "denied forever" with a path to settings. Collect the
minimum data, declare it in the store listings, and never log personal data. Analytics
events are named `<screen>_<action>` and reviewed like code.

## Platform conventions

Follow Material on Android and Human Interface Guidelines on iOS for controls, spacing
and typography unless the design system explicitly overrides them. Respect system font
scaling, dark mode, safe areas and right-to-left layouts. Touch targets are at least
44×44 pt. Test on the smallest supported screen.

## Builds and releases

Debug/staging/production flavours differ only in configuration (base URL, keys, feature
flags), never in code paths. Version and build number are bumped by CI. Crash reporting
is on in every non-debug build with symbol upload. A release checklist (screenshots,
permissions text, changelog) is part of the repository.
