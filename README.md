# lol-balance

🇹🇷 Türkçe: [README.tr.md](README.tr.md)

For a friend group's League of Legends 5v5 custom matches: automatic data
collection from the LCU → rating (OpenSkill-based blend model) → team balancing → web UI.

## Components

| Directory | What | Technology |
|---|---|---|
| `collector/` | Captures finished custom matches from the LoL client's (LCU) local API, normalizes them, sends them to the backend | Python, httpx |
| `backend/` | REST API + static web UI serving + SQLite | FastAPI |
| `backend/rating/` | Pure rating library (no I/O): OpenSkill PlackettLuce + performance blend + team balancing | Python, openskill |
| `webui/` | Framework-free single page: roster, balancing, match history, leaderboard | Vanilla HTML/JS |
| `docs/` | **CONTRACTS — the single source of truth** (API, ingest, DB schema, rating model) | — |

## Developer guide (read this first)

1. **Contracts are frozen.** Files under `docs/` are never changed unilaterally;
   if you find a problem, write it up in `docs/CHANGE_REQUESTS.md` — the decision
   comes out of the orchestration process (see `CLAUDE.md` and `docs/ORCHESTRATION.md`).
2. **Directory boundary:** each component changes only within its own directory;
   components mock each other using the example payloads in the contracts.
3. **Tests are mandatory.** All three packages use pytest; CI runs all three on every push/PR.

## Local setup

```powershell
# Backend + collector dependencies (a single venv is enough)
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python -m pip install -r ..\collector\requirements.txt
copy .env.example .env   # fill in API_KEY

# The rating package's own test venv (includes hypothesis)
cd rating
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .[dev]
```

Note: the rating package is installed into the backend venv as a **copy**
(`pip install ./rating`); if you changed anything under `backend/rating/`,
reinstall it in the backend venv (an editable install is deliberately not used
because it conflicts with the `rating/` folder shadowing in the backend/
working directory).

## Running

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.main:app --reload   # http://127.0.0.1:8000
```
The web UI is served from the root; the API lives under `/api/v1` and requires `X-API-Key`.
For the collector, see `collector/README.md` (live mode + backfill + Task Scheduler).

## Tests

```powershell
cd backend\rating && .\.venv\Scripts\python -m pytest -q          # rating
cd backend && .\.venv\Scripts\python -m pytest tests -q            # backend
cd <repo root> && backend\.venv\Scripts\python -m pytest collector -q  # collector
```

## Deploy

- CI (`.github/workflows/ci.yml`): all three test suites on every push/PR; on push
  to `main`, a Docker image to GHCR (`backend/Dockerfile`, backend+webui in a single container).
- Kubernetes (VPS): `deploy/VPS_AGENT_BRIEF.md`.

## Privacy note

The real LCU captures under `collector/fixtures/` contain players' puuids and
Riot IDs. **The repository must remain private**; if it is ever to be made
public, the fixtures must be anonymized first.

## License

Source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE.md):
you may use, modify and share this project for any **noncommercial** purpose
(personal use, friend groups, education, research). Commercial use is not permitted.

*LoL Balance isn't endorsed by Riot Games and doesn't reflect the views or opinions
of Riot Games or anyone officially involved in producing or managing League of
Legends. League of Legends and Riot Games are trademarks or registered trademarks
of Riot Games, Inc. Champion/item images and names are fetched at build time from
Riot's Data Dragon / CommunityDragon and remain Riot Games' property — they are
not covered by this repository's license.*
