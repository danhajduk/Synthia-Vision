## Discovery Note

### UI entrypoints/templates/static discovered
- `src/api/server.py` (`/ui/login`, `/ui/admin`, `/ui/setup`, `/ui/events`, `/ui/errors`)
- `src/ui/templates/login.html`
- `src/ui/templates/admin.html`
- `src/ui/templates/setup.html`
- `src/ui/templates/events.html`
- `src/ui/templates/errors.html`
- `src/ui/static/app.js`
- `src/ui/static/app.css`

### Existing auth endpoints/middleware discovered and used
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- Cookie/session guard in `src/api/server.py` via `SessionManager`, `_require_admin`, `_ui_admin_or_redirect`

### Existing admin/config/events/errors endpoints discovered and used
- Config/runtime/persist (existing endpoints used):
  - `GET /api/admin/settings`
  - `POST /api/admin/settings/apply`
  - `POST /api/admin/settings/save`
  - `GET /api/admin/cameras`
  - `POST /api/admin/cameras/{camera_key}/apply`
  - `POST /api/admin/cameras/{camera_key}/save`
  - `GET/PUT /api/admin/cameras/{camera_key}/profile`
  - `GET/PUT /api/admin/cameras/{camera_key}/views...`
- Events (existing endpoint used):
  - `GET /api/events`
  - `GET /api/events/{event_id}`
  - `GET /api/events/{event_id}/snapshot.jpg`
- Errors (existing endpoint used):
  - `GET /api/errors`
- Added summary endpoint:
  - `GET /api/admin/summary`

## Block Sign-Off
- Discovery complete: 2026-02-25 00:49:49 PST
- Auth/session + remember-me complete: 2026-02-25 00:49:49 PST
- Admin summary UI/API wiring complete: 2026-02-25 00:49:49 PST
- Setup modal + dirty tracking wiring complete: 2026-02-25 00:49:49 PST
- Events/errors pagination + detail modal wiring complete: 2026-02-25 00:49:49 PST
