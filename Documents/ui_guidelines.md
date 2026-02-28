# Synthia Vision UI Guidelines (Codex Reference)

Goal: build a **self-hosted, HA-friendly UI** served by the Synthia Vision service (FastAPI + Jinja), matching the **Synthia dashboard look** while keeping the guest view safe for iframe embedding in Home Assistant.

This document is written to minimize guesswork: **use it as an implementation contract**.

---

## Source of truth mock
Use the static HTML/CSS mock bundle as the visual reference:

- `synthia_vision_ui_mock_v3.zip` (provided alongside this file)
- Focus page: `index.html` (Guest / HA embed)

The mock is intentionally static. Live updates will be added later via polling/SSE/HTMX.

---

## UX Rules

### Guest (HA iframe) view
- Must be **iframe-friendly** (do not block embedding via `X-Frame-Options`).
- **No sidebar** (avoid "website inside a website" feel in HA).
- Guest view is **read-only**:
  - shows system stats + camera summaries
  - only one lightweight control is allowed: clicking a camera status pill toggles camera enabled state
  - no other controls/toggles
  - no raw prompts, no user list
  - token totals may be shown as KPI telemetry
- Embedded mode behavior for HA iframe:
  - hide guest header/top bar
  - hide guest footer
  - show only a small floating `Admin` link to `/ui/login` (open in new tab)

### Admin view
- Can be full UI (may use nav/side menu) because it's not embedded in HA.
- Admin has Setup / Cameras / Events / Errors pages.
- Admin-only shows explainability details and control actions.

---

## Layout Contract (Guest `/ui`)

### Row 1 (Top Bar)
Left:
- Primary title: **Synthia Vision**
- Secondary title: configurable (from config/kv), e.g. site/home name or tagline

Right:
- **Login** button (links to `/ui/login`)

Notes:
- Keep it compact and single-row in desktop; wraps cleanly on small width.

### Row 2 (KPIs)
Four KPI cards, in this exact order:

1) **Health**
   - Big: `Healthy` / `Degraded` / `Disabled` / `Budget Blocked`
   - Small: heartbeat timestamp or uptime

2) **Queue**
   - Big: queue depth number
   - Badge: `current/max` (max = 50)
   - Small: drops today

3) **Cost Today**
   - Big: `$X.XX`
   - Small: **Month-to-date** `$Y.YY` + **Avg/event** `$Z.ZZ`

4) **AI Calls**
   - Label must be **AI Calls** (not "OpenAI")
   - Big: calls today (or period)
   - Small line 1: **Tokens today** `N`
   - Small line 2: **Avg tokens/event** `N`
   - Rationale: future multi-provider AI services

Responsive behavior:
- Desktop: 4 columns
- Medium: 2 columns
- Small: 1 column

### Row 3 (Cameras)
- Section header: **Cameras**
- Right side hint (optional): "Guest view: summaries only. Click camera status to toggle."
- Grid of camera cards uses responsive auto-fit/min width logic in CSS; card count per row is viewport-dependent.

Each camera card:
- Title: `display_name`
- Header layout:
  - first line: camera title left, status pill right
  - second line: `Enabled: Yes/No • Last seen: ...`
- Status pill behavior:
  - clicking the status pill toggles camera enabled state
  - route: `POST /api/cameras/{camera_key}/toggle`
  - keep interaction simple (single click, no modal)
- Thumbnail placeholder area (optional; can be blank or last snapshot if safe)
- Key/value:
  - Last action + confidence (if available)
  - Month-to-date cost

Security rule:
- If a camera is `enabled=false`, show it as disabled but still list it.

Guest preview behavior:
- Preview image route: `/api/cameras/{camera_key}/preview.jpg`
- Preview appears only when both are true:
  - global `kv ui.preview_enabled=1`
  - camera `cameras.guest_preview_enabled=1`
- Refresh cadence:
  - enabled cameras: `ui.preview_enabled_interval_s` (default 2s)
  - disabled cameras: `ui.preview_disabled_interval_s` (default 60s / 1m)
- Visibility guard:
  - refresh only while camera card is visible in viewport
  - stop refresh when card leaves viewport
- Concurrency guard:
  - maximum active refreshers: `ui.preview_max_active` (default 1)
  - if multiple are visible and max is 1, pick first visible card in DOM order
- Add small scheduling jitter (±300ms) to avoid synchronized spikes.
- Avoid large centered "Preview off" text in cards; if preview is disabled, keep area subtle and optional small corner label only.
- Timestamp formatting rule:
  - today: `HH:MM`
  - older dates: `YYYY-MM-DD HH:MM`
  - missing/invalid: `—`
  - use browser local timezone when formatting in JS.

---

## Styling Contract

- Use the **Synthia dashboard dark gradient** aesthetic:
  - soft glass panels
  - subtle borders
  - no harsh separators
- Keep typography:
  - headings bold, small caps optional
  - metrics large
  - supporting text muted
- Avoid bright colors; use small status dots/pills.

Implementation detail:
- Prefer a single CSS file (e.g. `static/app.css`).
- Use CSS variables for theme values.

---

## Routing + Templates (FastAPI + Jinja)

### Public/Guest routes
- `GET /ui` -> guest dashboard (this layout)
- `GET /api/status`
- `GET /api/metrics/summary`
- `GET /api/cameras/summary`
- `POST /api/cameras/{camera_key}/toggle`

### Auth routes
- `GET /ui/login`
- `POST /ui/login`
- `POST /ui/logout`

### Admin routes
- `GET /ui/admin`
- `GET /ui/setup`
- `GET /ui/events`
- `GET /ui/events/{id}`
- `GET /ui/errors`

Role gating:
- Guest must not access admin pages or admin APIs.
- Admin routes require authenticated session.

Iframe compatibility:
- Do **not** set `X-Frame-Options: DENY/SAMEORIGIN` on guest `/ui` unless you explicitly allow HA.
- If adding CSP later, include a `frame-ancestors` that allows HA origins.

---

## Data Binding Contract (what the UI expects)

Guest `/ui` template needs:
- `title` (string): "Synthia Vision"
- `subtitle` (string): configurable tagline (from config/kv)
- `kpis`:
  - health label + badge
  - heartbeat_ts or uptime
  - queue_depth + queue_max + drops_today
  - cost_today + cost_mtd + avg_cost_per_event
  - ai_calls_today + tokens_today_total + avg_tokens_per_event
- `cameras[]` list:
  - `camera_key`
  - `display_name`
  - `enabled`
  - `status` (ok/degraded/disabled)
  - `last_seen_ts`
  - `last_action`
  - `last_confidence`
  - `mtd_cost`

If a value is missing, render `—` and do not break layout.

---

## “Done” Acceptance Criteria
- Guest `/ui` matches mock layout (rows 1–3) and is readable inside HA iframe.
- Responsive behavior matches: 4→2→1 KPI columns and 3→2→1 camera columns.
- No sidebar in guest view.
- Login button present in top bar.
- No sensitive/admin-only data exposed on guest view.

---

## Appendix: Mock assets
- This workspace includes `synthia_vision_ui_mock_v3.zip`.
- Use it only as a visual reference; runtime UI will be Jinja templates.
