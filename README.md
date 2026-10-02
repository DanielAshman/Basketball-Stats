# Basketball Analytics

Local React/FastAPI/PostgreSQL app with video analysis and live manual stat entry.

## Current status

- Manual entry records 1-, 2-, and 3-point makes, missed shots, rebounds, turnovers and assists, with undo.
- Each game has Home and Away rosters. The same jersey number can appear on both teams or in different games without sharing player identity.
- Rosters persist even when a player has no events. Reload and resume a game to continue recording.
- Video uploads extract frames and detect people and balls. Coaches mark the hoop and tag players, including their team. Shot and rebound estimates remain experimental; automatic assists and turnovers are not implemented.
- Legacy player references are copied into game-specific Home rosters on startup. Original player rows and event totals are retained. Historical team membership cannot be inferred from the old data.

## Run locally

Start Docker Desktop, then from this directory:

```sh
docker compose up -d --build
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The API is at http://localhost:8000/docs.

## Verification

Frontend component regression tests, build and lint:

```sh
cd frontend
npm test
npm run build
npm run lint
```

Backend tests require a separate PostgreSQL database. Create it once from the repository root:

```sh
docker compose exec postgres psql -U basketball_user -d postgres -c 'CREATE DATABASE basketball_regression_tests'
```

Then run:

```sh
docker compose exec -T -e DATABASE_URL=postgresql://basketball_user:dev_password_123@postgres:5432/basketball_regression_tests backend python -m unittest discover -s tests -v
```

Tests cover game/team identity, roster resumption, cross-game validation, undo and legacy migration. Test fixtures roll back and the suite refuses to use the regular app database.

Browser verification on 2026-09-18 also exercised creating a game, both teams wearing #23, reloading before any events, recording events, reloading/resuming, undo and checking database totals against an isolated test API.

## Remaining work

- Benchmark video events against a hand-scored clip; no accuracy claim has been established.
- Isolate the shared video tracker across overlapping uploads.
- Add a way to correct team membership for historical manual entries.
- Resolve the existing three frame-viewer lint warnings.
