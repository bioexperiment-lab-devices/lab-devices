# Experiment Studio

Web UI for building and running `lab_devices` experiments. Design spec:
`docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md`.

## Dev setup

Backend (own venv; root poetry venv is separate):

    cd webapp/backend
    python3 -m venv .venv
    .venv/bin/pip install -e ../.. -e '.[dev]'
    STUDIO_DATA_DIR=data .venv/bin/python -m uvicorn --factory experiment_studio.app:create_app --reload

Frontend (proxies /api to :8000):

    cd webapp/frontend
    npm install
    npm run dev

SQLite + run artifacts land in $STUDIO_DATA_DIR (default /data; use a repo-ignored ./data in dev).

## Gates

- Backend: `.venv/bin/python -m pytest && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
- Frontend: `npm run lint && npm test && npm run build`

## Image

    docker build -f webapp/Dockerfile -t experiment-studio:dev .
    docker run --rm -p 8000:8000 experiment-studio:dev

Published on release as `ghcr.io/bioexperiment-lab-devices/experiment-studio:{version,latest}`.
