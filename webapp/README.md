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

## Links and unsaved work

The address bar tracks what you have open, as a hash (`#/...`) rather than a normal
path — the app is served behind a prefix-stripping proxy and needs a relative asset
base, which only a hash fragment supports without breaking.

| Hash | Opens |
|---|---|
| `#/builder?exp=<id>` | an experiment in the Builder |
| `#/builder?exp=<id>&scope=<group>` | ...scoped to a group |
| `#/builder?exp=<id>&scope=<group>&sel=<path>` | ...with a block selected |
| `#/records/<id>` | a run record |
| `#/run` | the Run tab |
| `#/devices` | the Devices tab |

A shared or bookmarked link reopens the same tab, document, scope, and selected
block. The selected block is encoded as its position in the tree, not an internal
id — internal ids are re-minted every time a document loads, so an id in a link
would mean nothing to whoever opens it.

Switching tab, document, record, or group scope is a real Back/Forward step;
moving the selection is not — it replaces the current step rather than adding one,
so Back after clicking through several blocks skips past all of them at once.

**Unsaved work survives refresh, but for one document at a time.** The Builder
mirrors your in-progress edits to the browser about half a second after you stop
changing anything. Refresh, a crash, or a browser restart brings them back, with a
dismissible notice showing when they're from ("Restored unsaved changes from
14:32") — which is also why there is no "leave site?" prompt on refresh: refresh
no longer loses anything, so warning about it would be lying. New, Load, Import,
and Duplicate clear this safety net for the document you're leaving, after the
usual "discard unsaved changes?" confirmation.

The safety net holds **one document's edits at a time**. Opening a different
experiment — by following a link, or by pressing Back across two documents —
overwrites whatever unsaved edits were held for the previous one; a notice names
the document that lost its edits ("Opening this document replaced unsaved changes
to *X*"). This is a warning, not a prevention — the edits are already gone by the
time you read it. Keep two experiments open in two separate browser tabs if you
need to edit both without this trade-off: each tab keeps its own copy.

A link to a deleted (or never-existing) experiment behaves differently depending
on when it's found: opened fresh, it lands on a new blank document with a notice;
reached via Back/Forward while something else is already open, it leaves that
document alone rather than blanking your screen, with a notice explaining why.
