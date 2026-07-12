# Changelog

## [0.3.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.2.0...v0.3.0) (2026-07-12)


### Features

* **studio:** sub-path portability — relative asset/API/WS URLs ([c65da46](https://github.com/bioexperiment-lab-devices/lab-devices/commit/c65da46b3d1e67e6e3ddb8b40531b7b5c76c2d20))
* **studio:** W6 — integration polish, sub-path portability, operator docs ([da19dbc](https://github.com/bioexperiment-lab-devices/lab-devices/commit/da19dbc812c59db47450ede47c2dfc4fa8ec4e6d))


### Bug Fixes

* **studio:** final-review wave — abort-idempotency wording, body-read timeout mapping, artifact-dir "." hardening ([faa57b4](https://github.com/bioexperiment-lab-devices/lab-devices/commit/faa57b43e21f26f4f1b6c1c9d1258016384e5759))
* **studio:** preflight prefill survives late roster load; pin 409-adopt path ([675ac07](https://github.com/bioexperiment-lab-devices/lab-devices/commit/675ac076a225db98be62021ee6e441547c211cdd))
* **studio:** release-please stamps experiment-studio version (health seam) ([b2c9327](https://github.com/bioexperiment-lab-devices/lab-devices/commit/b2c9327a0458036dd935c1c6981143d64f86e0a7))
* **studio:** terminal-window active() guard, artifact-dir containment, zip off-loop, /api JSON 404 ([f8dc5c9](https://github.com/bioexperiment-lab-devices/lab-devices/commit/f8dc5c960741048634191455121c0622e33f38a7))
* **studio:** viewer origin fallback, log-truncation hint, fetch timeouts, uid fallback, tsconfig strict ([8c88bc6](https://github.com/bioexperiment-lab-devices/lab-devices/commit/8c88bc6a40b3e157aae72e958511dc9c04d5a2db))


### Documentation

* W6 integration plan ([3523b53](https://github.com/bioexperiment-lab-devices/lab-devices/commit/3523b53c0e0d79de644714a2a3a76b1910f28531))
* W6 spec amendments + studio operator/deployment guide ([1ad8fd6](https://github.com/bioexperiment-lab-devices/lab-devices/commit/1ad8fd64b196d074920224099dc4994ff9c6ee8e))

## [0.2.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.1.1...v0.2.0) (2026-07-12)


### Features

* experiment-studio W1 skeleton ([2515bb9](https://github.com/bioexperiment-lab-devices/lab-devices/commit/2515bb9921a5ceb2ffe76c86baf59c9ca09eb44c))
* experiment-studio W2 experiments backend ([36c9ec7](https://github.com/bioexperiment-lab-devices/lab-devices/commit/36c9ec7d820eb18612e094054ba141d3a3ef0aae))
* public verb_catalog()/expression_functions() accessors (studio spec §4.4) ([38809e0](https://github.com/bioexperiment-lab-devices/lab-devices/commit/38809e09403b13e099a111c4f3809eec96e6e350))
* **studio:** /api/catalog from library verb/expression accessors ([7e047dd](https://github.com/bioexperiment-lab-devices/lab-devices/commit/7e047ddc68d6eb523a585a8fec32e81fbf614285))
* **studio:** /api/validate with placeholder substitution and golden fixtures ([6e6c037](https://github.com/bioexperiment-lab-devices/lab-devices/commit/6e6c037f714d035dbacdda47cfa2b429384f1104))
* **studio:** active-run view — status header, controls, event log, terminal report ([f2f8b84](https://github.com/bioexperiment-lab-devices/lab-devices/commit/f2f8b84d367268c3802a9f4f804b88e3e57ee1f9))
* **studio:** API client envelope extras + run/record wire types and REST modules ([4aff1e4](https://github.com/bioexperiment-lab-devices/lab-devices/commit/4aff1e402b12194ca9ac4e7c94eb79b05d3893a8))
* **studio:** backend package with health endpoint and SPA serving ([5086bde](https://github.com/bioexperiment-lab-devices/lab-devices/commit/5086bde1b722e759a50280b8bfff155dd745ff4e))
* **studio:** builder block-tree model and doc round-trip conversion ([e543d71](https://github.com/bioexperiment-lab-devices/lab-devices/commit/e543d7108736174716c714b81bfa3b2f3529fc11))
* **studio:** builder canvas with N-lane parallel, dnd slots, block cards ([af218d6](https://github.com/bioexperiment-lab-devices/lab-devices/commit/af218d6c7cc16ff2f6492e3dfeb1cda4796956ca))
* **studio:** builder deps, doc/catalog types, structured API client ([703caf5](https://github.com/bioexperiment-lab-devices/lab-devices/commit/703caf557b3fd5d213c8389cfccc72c5637c4bcf))
* **studio:** builder toolbar with save/load/duplicate, debounced validation, problems panel ([37ca696](https://github.com/bioexperiment-lab-devices/lab-devices/commit/37ca6968153a90875bd08c4496faf82394caf5ba))
* **studio:** devices tab with lab picker, device roster, rediscover ([c3b28f9](https://github.com/bioexperiment-lab-devices/lab-devices/commit/c3b28f9af010be466499e538e4f6307a910c7420))
* **studio:** document store with zundo undo/redo and catalog store ([c20a506](https://github.com/bioexperiment-lab-devices/lab-devices/commit/c20a506df0294e2094f0993fc080044f3ad37bd7))
* **studio:** experiment doc model and CRUD store ([93a786a](https://github.com/bioexperiment-lab-devices/lab-devices/commit/93a786ae0b8bfda66f69f370e87ff7602191363c))
* **studio:** experiments CRUD API with db lifecycle wiring ([8191942](https://github.com/bioexperiment-lab-devices/lab-devices/commit/8191942beda315e78ca967e7aa3b363d8e679c72))
* **studio:** frontend shell (Vite/React/Tailwind) with health status and tab stepper ([55887a6](https://github.com/bioexperiment-lab-devices/lab-devices/commit/55887a62876d203701ecf9957ef09dedaaedc0df))
* **studio:** inspector with catalog-generated param forms and expression help ([e8d6998](https://github.com/bioexperiment-lab-devices/lab-devices/commit/e8d699859d0dfce37d640386a78cc071beb2a5b8))
* **studio:** labs roster/devices/discover endpoints with error mapping ([ffa69fa](https://github.com/bioexperiment-lab-devices/lab-devices/commit/ffa69fa0d4ba235a88f3bb6ef35bc2ff357f2059))
* **studio:** live uPlot stream chart with aligned multi-series feed ([5b9f9fa](https://github.com/bioexperiment-lab-devices/lab-devices/commit/5b9f9fab6ba85fe16eef295904e1f2adfabb916d))
* **studio:** mapping-memory read endpoint + normalized invalid_request 422 envelope ([c77fe1f](https://github.com/bioexperiment-lab-devices/lab-devices/commit/c77fe1f66fe0908c4d4ec4563d94cfd0432665b7))
* **studio:** operator-input dialog with typed widgets and engine-mirrored validation ([01f4680](https://github.com/bioexperiment-lab-devices/lab-devices/commit/01f4680d9bb37cc91fcd150e1509374b8d2ebd1f))
* **studio:** palette with role-driven verb chips, roles and streams panels ([6500364](https://github.com/bioexperiment-lab-devices/lab-devices/commit/65003643b01bf0312abd74d7dc31dd62f0537013))
* **studio:** record viewer — chart, event log, report summary, read-only workflow snapshot ([177b34f](https://github.com/bioexperiment-lab-devices/lab-devices/commit/177b34fb03ef9e13b3ed7331e06b2fcdce3bd3ab))
* **studio:** records list — store, table with rename/delete/download, nav store ([21ed594](https://github.com/bioexperiment-lab-devices/lab-devices/commit/21ed594e47923db67b232f936f48a927bb830561))
* **studio:** records store with crash sweep, artifact readers, zip builder ([7e1b31d](https://github.com/bioexperiment-lab-devices/lab-devices/commit/7e1b31df964b64803da0dae20a42f7bed78f3657))
* **studio:** records/mappings tables, atomic migrations, store rollback hygiene ([a2b9697](https://github.com/bioexperiment-lab-devices/lab-devices/commit/a2b969793a572fb54d6764c356966a75642140be))
* **studio:** role/stream cascades, diagnostic path mapping, expression help ([d0f10e6](https://github.com/bioexperiment-lab-devices/lab-devices/commit/d0f10e6a888b66d58361a47fad7771f12e6b1e9f))
* **studio:** roles module with placeholder substitution and doc-level checks ([74c3a25](https://github.com/bioexperiment-lab-devices/lab-devices/commit/74c3a258f1db3f7595a18c5771060c07c7d3d84c))
* **studio:** run preflight — experiment picker, role mapping with prefill, start gating ([74c755d](https://github.com/bioexperiment-lab-devices/lab-devices/commit/74c755d3fca37de95bdb87af8afd26bab35a8e39))
* **studio:** run WS feed reducer + reconnecting socket wrapper ([12ea340](https://github.com/bioexperiment-lab-devices/lab-devices/commit/12ea340ab5a52257d189401bd4c40f25d3806140))
* **studio:** run-events WebSocket with seq replay and terminal close ([fab4a00](https://github.com/bioexperiment-lab-devices/lab-devices/commit/fab4a00b0d42e68ac08d5a7d46a11a787e9d1cd7))
* **studio:** RunManager start preflight, execution wrapper, terminal finalize ([e2ec419](https://github.com/bioexperiment-lab-devices/lab-devices/commit/e2ec419f249f1267dd9f66a10a64ef7f8dd55091))
* **studio:** runs + records HTTP API, payload error handlers, hardened lifespan ([9561571](https://github.com/bioexperiment-lab-devices/lab-devices/commit/95615718e9c4bd2cb120321e2b75609a44180765))
* **studio:** runStore — attach/start/controls/input/terminal lifecycle ([9de94c8](https://github.com/bioexperiment-lab-devices/lab-devices/commit/9de94c815345be0236de8977af47d76ea47cbac8))
* **studio:** single-image Dockerfile (frontend build + fastapi runtime) ([55876ec](https://github.com/bioexperiment-lab-devices/lab-devices/commit/55876ec59399e951bf5cb1d9b0f4d5573388f8f6))
* **studio:** sqlite data layer with user_version migrations ([0546b3f](https://github.com/bioexperiment-lab-devices/lab-devices/commit/0546b3f62049ec0e18fa6d86e4102908892f3173))
* **studio:** tee run-log sink with seq broadcast buffer, web input provider ([8685b85](https://github.com/bioexperiment-lab-devices/lab-devices/commit/8685b8515024fde440fc44e1a56b38335894ec2d))
* **studio:** tsconfig app/test split + FakeLab-backed dev server for the W5 gate ([289b569](https://github.com/bioexperiment-lab-devices/lab-devices/commit/289b569fb8adff92bb10b6eb66e02d93b1a56fb7))
* **studio:** W3 builder UI — palette/canvas/inspector, validation, save/load, devices tab ([3ce23c2](https://github.com/bioexperiment-lab-devices/lab-devices/commit/3ce23c2dda1a343eb422de720bcbbb9869a71c4f))
* **studio:** W4 run backend — RunManager, WebSocket events, records ([ba6fd96](https://github.com/bioexperiment-lab-devices/lab-devices/commit/ba6fd96638c08544e6e8191e505425489fb2d6bf))
* **studio:** W5 — Run + Records UI ([4705178](https://github.com/bioexperiment-lab-devices/lab-devices/commit/47051781c77605f0259f110637f5bdd9079d8592))


### Bug Fixes

* **studio:** builder carry-forwards — replaceSlot reuse, removeBlock walk, escape-cancel renames, delete-of-open-doc, save-as undo hygiene, stale-diagnostics dimming ([79f95cd](https://github.com/bioexperiment-lab-devices/lab-devices/commit/79f95cd8bec5b6443ecf829215a4a42c09dc1cc3))
* **studio:** canDrop verifies the target slot exists ([ba5a709](https://github.com/bioexperiment-lab-devices/lab-devices/commit/ba5a709f81499a336dad8fb736ff61f324039cf2))
* **studio:** devices table renders unknown connection state as em-dash ([a07b23c](https://github.com/bioexperiment-lab-devices/lab-devices/commit/a07b23c6ffff3f899ba73734ea71694182a46b26))
* **studio:** final-review fixes — save-flow integrity, undo-safe textareas, branch cascade test ([f2232e6](https://github.com/bioexperiment-lab-devices/lab-devices/commit/f2232e6ef2538ffff8d89a34416ee47d06fc7708))
* **studio:** finalize record on any start failure, harden run finalize guards ([f191319](https://github.com/bioexperiment-lab-devices/lab-devices/commit/f191319138d873ae3e1f9a2f561c1afe66aa062e))
* **studio:** guard preflight loadSelection against stale responses ([62426dd](https://github.com/bioexperiment-lab-devices/lab-devices/commit/62426dd421a7968b8286bed00d96652a46fa7aab))
* **studio:** LabError catch-all in error map; traversal test exercises the guard ([d8f2a22](https://github.com/bioexperiment-lab-devices/lab-devices/commit/d8f2a22693b133960a5c33979e1bf2c0cb35e907))
* **studio:** poll for held job before completing it in active-payload test ([e0861a1](https://github.com/bioexperiment-lab-devices/lab-devices/commit/e0861a11f4ff100a1d480758ae95ec144a4983f0))
* **studio:** preflight retry + stale start-diagnostics clear + terminal report run guard ([44ef839](https://github.com/bioexperiment-lab-devices/lab-devices/commit/44ef839ed718de032fe79c2bcdb28f72e8056298))
* **studio:** reset rename cancel latch at edit start ([2b6463c](https://github.com/bioexperiment-lab-devices/lab-devices/commit/2b6463c3f93140fc8933fdbf6c15037b9587ddae))


### Documentation

* experiment-studio webapp design spec (S1-S10 user-settled) ([0be6a57](https://github.com/bioexperiment-lab-devices/lab-devices/commit/0be6a571c6ae1762d42aa67f7e77916085d58243))
* **studio:** fix mypy gate invocation in W5 plan (no path arg) ([dbc6014](https://github.com/bioexperiment-lab-devices/lab-devices/commit/dbc601496225a1f8a2b7182c0e0034867666fbd6))
* **studio:** W2 experiments-backend TDD plan ([b19b83d](https://github.com/bioexperiment-lab-devices/lab-devices/commit/b19b83d8e232bb9f702b68dabc834a3f0536a65d))
* **studio:** W3 builder-ui implementation plan ([063da49](https://github.com/bioexperiment-lab-devices/lab-devices/commit/063da494250c14e66b21764a7f4a8f841287e620))
* **studio:** W3 spec amendments — duration grammar example, ping deferral ([bc8123c](https://github.com/bioexperiment-lab-devices/lab-devices/commit/bc8123c4537f959d0692bc8a573df122163f4379))
* **studio:** W4 run-backend implementation plan ([9247a56](https://github.com/bioexperiment-lab-devices/lab-devices/commit/9247a56cb090036e2a19d29294e0a08b5252bb12))
* **studio:** W4 spec amendments — record viewer endpoint, status seq ([50294f7](https://github.com/bioexperiment-lab-devices/lab-devices/commit/50294f7f322229258a518d001f74cfdffcc4f690))
* **studio:** W5 run + records UI implementation plan ([b530fbe](https://github.com/bioexperiment-lab-devices/lab-devices/commit/b530fbed804a171190bdcea97c75036b3c34ee62))
* W1 skeleton implementation plan (7 tasks, TDD) ([a2f967d](https://github.com/bioexperiment-lab-devices/lab-devices/commit/a2f967d783228f0bac0085e588f7253f9a8ae497))

## [0.1.1](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.1.0...v0.1.1) (2026-07-09)


### Bug Fixes

* **test:** close probe server connection so wait_closed() doesn't hang on py3.12 ([272a113](https://github.com/bioexperiment-lab-devices/lab-devices/commit/272a1132f0f9930ee846e9718c4ee225e1bc8c8e))


### Documentation

* add CI and PyPI badges to README ([13a7ecd](https://github.com/bioexperiment-lab-devices/lab-devices/commit/13a7ecd64cf290c42bf25e6e0db93bc6c2e62afc))
* design for CI + release-please + PyPI trusted publishing ([4e857cd](https://github.com/bioexperiment-lab-devices/lab-devices/commit/4e857cd97fb0cc31321a1288ae83ec8264e831e3))
* implementation plan for CI + release automation ([54c3368](https://github.com/bioexperiment-lab-devices/lab-devices/commit/54c3368c1bb1f9889540638542781c64e2fcdd49))
