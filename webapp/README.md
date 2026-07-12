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

## Deployment

One container serves API + SPA on port 8000. Persistent state lives entirely under
`STUDIO_DATA_DIR` (SQLite + run artifacts) — mount a volume there.

| Env | Default | Meaning |
|---|---|---|
| `STUDIO_DATA_DIR` | `/data` | SQLite db + `runs/<id>/` artifact dirs |
| `STUDIO_STATIC_DIR` | set in-image | built SPA; unset = API only (dev) |
| `LAB_DEVICES_DISCOVERY_URL` | `http://siteapp:8000/api/clients/` | lab roster endpoint |

All URLs the SPA emits are relative: the app works at `/` and behind a
prefix-stripping reverse proxy (lab-bridge serves it at `/studio/` — see that repo's
`docs/superpowers/specs/2026-07-12-experiment-studio-integration.md`). The app is
single-user: one active run per instance (second start → 409); auth belongs to the
proxy edge. Run exactly one replica per data dir.

## Operating (the four tabs)

1. **Devices** — pick the lab (persisted), inspect its device roster, or Rediscover
   (live bus rescan; refused with 409 while that lab runs an experiment).
2. **Builder** — define roles (name + device type) and streams (name + units), then
   drag verbs/structure blocks onto the canvas. Save/validate as you go: diagnostics
   badge blocks running, never saving.
3. **Run** — pick a saved experiment, map every role to a live device (pre-filled
   from the last run on that lab), Start. Live chart + event log + pause/resume/abort;
   operator-input prompts pop a dialog. A finished run shows its report and links to
   the record.
4. **Records** — one record per run: rename, delete, download zip (doc, workflow,
   run log, report, stream CSVs), or open the viewer (chart, log, report, read-only
   workflow snapshot).
