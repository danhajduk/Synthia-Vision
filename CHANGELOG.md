# Changelog

All notable changes to this project should be documented in this file.

The format is based on Keep a Changelog, and this project uses SemVer tags (`vMAJOR.MINOR.PATCH`).

## [Unreleased] - 2026-02-28

### Added

- Guest camera status-pill toggle endpoint: `POST /api/cameras/{camera_key}/toggle`.
- Guest dashboard camera status click handler wired to toggle camera enabled state.
- Auth test coverage for guest camera toggle route.
- `synthia-workflow` local Codex skill for small-step implementation + documentation + commit workflow.

### Changed

- Guest dashboard hint text now reflects status-pill toggle behavior.
- UI guidelines updated to document the guest toggle behavior and route.
- README expanded with quick start, privacy/security boundaries, troubleshooting matrix, architecture diagram, and release-tagging guidance.

### Fixed

- Guest status pill interaction now performs a working toggle instead of silently failing due to admin-only route use.
