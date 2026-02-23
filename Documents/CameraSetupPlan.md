# Camera Setup Flow Plan

Updated: 2026-02-23 00:45:33 PST

## Scope
- Implement camera setup flow in sequential blocks from `Documents/Next_task.txt`.

## Execution plan
1. Block 0: branch + baseline boot/test checks + plan note.
2. Block 1: SQLite migration for camera profile fields + `camera_views` table/indexes.
3. Block 2: backend models and DB helper layer for profile/views.
4. Block 3: admin APIs for profile/views and setup snapshot route.
5. Block 4: AI context generation endpoint with strict schema + privacy constraints.
6. Block 5: inject saved profile/view context into runtime prompt construction.
7. Block 6: admin setup wizard UI flow.
8. Block 7: tests + docs sync.
9. Block 8: end-to-end verification and runtime sanity checks.

## Validation per block
- Service boot check.
- Tests (when available in current environment).
- Commit with block-specified message.
