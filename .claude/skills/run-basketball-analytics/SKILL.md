---
name: run-basketball-analytics
description: Build, run, and drive basketball-analytics (FastAPI + Postgres + Redis backend, Vite/React frontend). Use when asked to start the app, launch the backend/frontend, take a screenshot of the UI, or verify an end-to-end flow (upload a game, live game entry, tap stats).
---

Full-stack app: a Dockerized FastAPI backend (Postgres + Redis + YOLOv8 vision
service) and a Vite/React frontend served separately. Drive it via
`.claude/skills/run-basketball-analytics/driver.mjs` — a Playwright script
that brings the stack up, then exercises the real "live game entry" flow
(create game -> add player -> record a shot -> read back stats) end-to-end
through the browser.

All paths below are relative to the repo root (`basketball-analytics/`).

## Prerequisites

- Docker Desktop (must actually be running — `docker info` fails otherwise,
  the driver's `up` command auto-launches it with `open -a Docker` and waits).
- Node.js + npm (frontend already has `node_modules` checked out; if not,
  `npm install` in `frontend/`).

No OS packages needed on macOS — the backend's system deps (`libgl1`,
`tesseract-ocr`, etc.) are installed inside the Docker image, not on the host.

## Setup

One-time, inside this skill directory:

```bash
cd .claude/skills/run-basketball-analytics
npm install                          # installs playwright
npx playwright install chromium      # downloads the browser binary (~280MB, cached after first run)
```

## Run (agent path)

From the repo root:

```bash
node .claude/skills/run-basketball-analytics/driver.mjs        # up + smoke, leaves the stack running
node .claude/skills/run-basketball-analytics/driver.mjs up     # start docker-compose + vite dev server only
node .claude/skills/run-basketball-analytics/driver.mjs smoke  # drive the already-running app
node .claude/skills/run-basketball-analytics/driver.mjs down   # stop vite + docker-compose
```

`smoke` does the following against the running app and exits non-zero if
anything fails or the browser console logs an error:

1. Navigate to `http://localhost:5173/`, confirm the Video Upload screen renders.
2. Click "Live Game Entry", create a game (hits `POST /api/games/manual`).
3. Add a player to the roster (`POST /api/players`), tap "Made Shot"
   (`POST /api/games/:id/manual-events`).
4. Wait for the Player Stats table to reflect the recorded shot (proves the
   round trip through Postgres, not just that the page rendered).

Screenshots land in `.claude/skills/run-basketball-analytics/screenshots/`:
- `1-video-upload.png` — landing page
- `2-live-game-entry.png` — after the create-game / add-player / record-shot flow, stats table visible

Backend logs: `docker logs basketball_backend`. Frontend logs: `/tmp/frontend.log`
if you redirected them yourself (the driver runs vite detached with `stdio: 'ignore'`,
so use `docker-compose logs` / re-run `npm run dev` in `frontend/` directly if you
need to see them).

## Run (human path)

```bash
open -a Docker                       # if not already running
docker-compose up -d --build         # backend: FastAPI on :8000, Postgres on :5432, Redis on :6379
cd frontend && npm run dev           # frontend on :5173
```

Stop with `docker-compose down` and killing the vite process (`lsof -ti:5173 -sTCP:LISTEN | xargs -r kill`).

## Test

Three layers of automated verification exist:

1. **Frontend unit tests** — `cd frontend && npm test` (vitest + @testing-library/react)
2. **Backend regression tests** — `cd backend && python -m pytest tests/` (unittest, requires a `basketball_regression_tests` database)
3. **E2E smoke test** — `node .claude/skills/run-basketball-analytics/driver.mjs smoke` (Playwright, drives the full create-game → add-player → record-shot → verify-stats flow)

---

## Gotchas

- **Docker Desktop not running is the default state, not an edge case.**
  `docker-compose up` fails with `dial unix .../docker.sock: connect: no such
  file or directory` if the daemon isn't up. `open -a Docker` then poll
  `docker info` until it succeeds (takes ~20-30s cold).
- **`docker-compose up -d --build` recreates `basketball_backend` every time**
  even when only `postgres`/`redis` were already healthy — normal, not a
  sign something is wrong; the healthchecks gate startup correctly.
- **The activity-log entry and the event button have the same text**
  ("Made Shot"), so `wait-for text=Made Shot` matches the button immediately
  and never proves the event was recorded. The driver waits on
  `text=Made Shot >> nth=1` (the second match, in the activity log) instead.
- **`page.fill('input[type="date"]', ...)` needs `YYYY-MM-DD`** — the visible
  `dd/mm/yyyy` placeholder is just the locale display format.
