# Changelog

## [1.1.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v1.0.0...v1.1.0) (2026-07-21)


### Features

* **studio:** manual device control — backend contract + persistence ([#60](https://github.com/bioexperiment-lab-devices/lab-devices/issues/60)) ([da329d3](https://github.com/bioexperiment-lab-devices/lab-devices/commit/da329d373091eacde5d2e75ee39c184a795523a8))
* **studio:** manual device control tab (UI) ([#62](https://github.com/bioexperiment-lab-devices/lab-devices/issues/62)) ([542b264](https://github.com/bioexperiment-lab-devices/lab-devices/commit/542b2640163016241f9ad8bed2ce86237890f330))

## [1.0.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.14.0...v1.0.0) (2026-07-21)


### ⚠ BREAKING CHANGES

* **experiment:** opaque units and schema v3 (Increment 10, Engine B) ([#57](https://github.com/bioexperiment-lab-devices/lab-devices/issues/57))

### Features

* **experiment:** expressions in duration/count slots (Increment 10, Engine C) ([#58](https://github.com/bioexperiment-lab-devices/lab-devices/issues/58)) ([590e5b7](https://github.com/bioexperiment-lab-devices/lab-devices/commit/590e5b72c7c7daf3cb80b708611edc11536f4e7a))
* **experiment:** opaque units and schema v3 (Increment 10, Engine B) ([#57](https://github.com/bioexperiment-lab-devices/lab-devices/issues/57)) ([9531fdb](https://github.com/bioexperiment-lab-devices/lab-devices/commit/9531fdbd3dd7611461640f480b42c299b3538c36))
* **experiment:** static type lattice for the DSL (Increment 10, Engine A) ([#55](https://github.com/bioexperiment-lab-devices/lab-devices/issues/55)) ([2313812](https://github.com/bioexperiment-lab-devices/lab-devices/commit/23138121f76b39821f7537441d9dc6b039af1183))
* **studio:** editable as unit-cast field on compute/record (Increment 10, Studio) ([#59](https://github.com/bioexperiment-lab-devices/lab-devices/issues/59)) ([dddf32a](https://github.com/bioexperiment-lab-devices/lab-devices/commit/dddf32ac38647ab547f2d58c3f8d6e53a8278600))

## [0.14.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.13.0...v0.14.0) (2026-07-21)


### Features

* **studio:** scope-aware references — a group's own params & locals in the Builder palette ([#53](https://github.com/bioexperiment-lab-devices/lab-devices/issues/53)) ([577784e](https://github.com/bioexperiment-lab-devices/lab-devices/commit/577784e16df0236fb821410da9d148cdebf855cb))

## [0.13.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.12.0...v0.13.0) (2026-07-21)


### Features

* **experiment:** typed group parameters, group-locals, and engine-owned roles (Increment 9, PR 1) ([#50](https://github.com/bioexperiment-lab-devices/lab-devices/issues/50)) ([c6fe5f0](https://github.com/bioexperiment-lab-devices/lab-devices/commit/c6fe5f0ada8dfa4b65596d13d19bdc856adb5866))

## [0.12.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.11.0...v0.12.0) (2026-07-20)


### Features

* **ci:** dispatch a studio image bump to lab-bridge on release ([#48](https://github.com/bioexperiment-lab-devices/lab-devices/issues/48)) ([08d64ce](https://github.com/bioexperiment-lab-devices/lab-devices/commit/08d64ce54d951703750c42e5c3ea074bc5769dd6))

## [0.11.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.10.0...v0.11.0) (2026-07-19)


### Features

* **studio:** persist the in-progress experiment and put UI state in the URL (W16) ([#46](https://github.com/bioexperiment-lab-devices/lab-devices/issues/46)) ([15d05d1](https://github.com/bioexperiment-lab-devices/lab-devices/commit/15d05d1d586ecc0075fb3168428866971560a606))

## [0.10.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.9.0...v0.10.0) (2026-07-18)


### Features

* **studio:** canvas visual language — construct tints, depth zebra, role swatches, hatching ([#43](https://github.com/bioexperiment-lab-devices/lab-devices/issues/43)) ([b18e778](https://github.com/bioexperiment-lab-devices/lab-devices/commit/b18e778cdcc2977b9e59a788a2b62b5eb1131e34))
* **studio:** make the Builder lab-independent and put it first ([#41](https://github.com/bioexperiment-lab-devices/lab-devices/issues/41)) ([237d0d7](https://github.com/bioexperiment-lab-devices/lab-devices/commit/237d0d7f832c3581a55c5d2129726d5783c9ea9b))
* **studio:** re-cut the Inspector settings form into intent-based sections (W15) ([#44](https://github.com/bioexperiment-lab-devices/lab-devices/issues/44)) ([3501c53](https://github.com/bioexperiment-lab-devices/lab-devices/commit/3501c53f994bf5a9f771d3795833a5f4200568f2))

## [0.9.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.8.1...v0.9.0) (2026-07-18)


### Features

* **studio:** re-cut the element library into Flow/Data/Pause/Safety ([#38](https://github.com/bioexperiment-lab-devices/lab-devices/issues/38)) ([5b58db8](https://github.com/bioexperiment-lab-devices/lab-devices/commit/5b58db8f4d075734ceebe1f76b1ab22e4a181a1c))
* **studio:** UI improvements round 2 — panel boxes, tabbed header, typed roles, empty lanes ([#40](https://github.com/bioexperiment-lab-devices/lab-devices/issues/40)) ([7d17f6b](https://github.com/bioexperiment-lab-devices/lab-devices/commit/7d17f6bcfc0f5d99c4298c6dd62bf41b62b31012))

## [0.8.1](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.8.0...v0.8.1) (2026-07-18)


### Bug Fixes

* **studio:** W11 UI improvements ([#36](https://github.com/bioexperiment-lab-devices/lab-devices/issues/36)) ([b53725e](https://github.com/bioexperiment-lab-devices/lab-devices/commit/b53725e026481dd411260ad136b329e257534072))

## [0.8.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.7.0...v0.8.0) (2026-07-18)


### Features

* **studio:** UI-audit fixes — icons, contrast, targets, dialogs (W10) ([#35](https://github.com/bioexperiment-lab-devices/lab-devices/issues/35)) ([3f32ab1](https://github.com/bioexperiment-lab-devices/lab-devices/commit/3f32ab1dce3fee0ad812eb5ad9009f3157e0fe68))


### Documentation

* UI audit of Experiment Studio 0.7.0 (fixtures + report) ([#33](https://github.com/bioexperiment-lab-devices/lab-devices/issues/33)) ([4a5e1e3](https://github.com/bioexperiment-lab-devices/lab-devices/commit/4a5e1e39e6a849111e2643e00c6ac9df1b9493c5))

## [0.7.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.6.0...v0.7.0) (2026-07-17)


### Features

* **studio:** author compute/record/abort/alarm in the builder (W8) ([#28](https://github.com/bioexperiment-lab-devices/lab-devices/issues/28)) ([93a0d1d](https://github.com/bioexperiment-lab-devices/lab-devices/commit/93a0d1da769999666225a0d812088e74f44de08b))
* **studio:** author for_each and parametrized groups in the builder (W9) ([#30](https://github.com/bioexperiment-lab-devices/lab-devices/issues/30)) ([e51a2ee](https://github.com/bioexperiment-lab-devices/lab-devices/commit/e51a2eec11f654eb8285dcdee4fe9eaa745519d3))

## [0.6.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.5.0...v0.6.0) (2026-07-16)


### Features

* **experiment:** abort block raises non-tolerable AbortSignalError -&gt; status aborted ([706613e](https://github.com/bioexperiment-lab-devices/lab-devices/commit/706613ecaf58ea3e0d929cee6c0a474db146f2a3))
* **experiment:** alarm block emits event + RunReport.alarms, run continues ([6a850eb](https://github.com/bioexperiment-lab-devices/lab-devices/commit/6a850eba27360466052b95be4953db63787ce350))
* **experiment:** AST + serialization for abort/alarm blocks ([8b26850](https://github.com/bioexperiment-lab-devices/lab-devices/commit/8b26850ea245c2ef6ff9364e74c883da9d9faf87))
* **experiment:** AST + serialization for for_each, group params, group_ref args ([5ec41aa](https://github.com/bioexperiment-lab-devices/lab-devices/commit/5ec41aa1ed4eccec18d0bec1070d4dc98734968c))
* **experiment:** execute the expanded workflow (for_each / parametrized groups) ([d3d6830](https://github.com/bioexperiment-lab-devices/lab-devices/commit/d3d6830cbb134e78aeba8fc9c9b8dd29602837b2))
* **experiment:** for_each / parametrized-group expansion engine ([6f9af93](https://github.com/bioexperiment-lab-devices/lab-devices/commit/6f9af934b9c11bfbacd6f6fcb534d4dee02c8a74))
* **experiment:** self-failing blocks — abort + alarm (Increment 8, closes limitations [#7](https://github.com/bioexperiment-lab-devices/lab-devices/issues/7)) ([b8c78e9](https://github.com/bioexperiment-lab-devices/lab-devices/commit/b8c78e915b2ee0c1948b5390555213620f5ad00b))
* **experiment:** validate abort/alarm (condition, message, on_error, freshness) ([ef895dd](https://github.com/bioexperiment-lab-devices/lab-devices/commit/ef895dd778132a77ef501f497f88f74c7b877415))
* **experiment:** validate for_each/parametrized groups via expand-then-check ([732c442](https://github.com/bioexperiment-lab-devices/lab-devices/commit/732c4424f6da311c9c3eb3ea54edc1e7842810b3))
* **studio-backend:** abort/alarm grammar parity + alarms in run report payload ([37af17f](https://github.com/bioexperiment-lab-devices/lab-devices/commit/37af17f01be202f3c59768badee363d0e5d23a3d))
* **studio-backend:** for_each grammar parity + expand before role substitution ([96a5537](https://github.com/bioexperiment-lab-devices/lab-devices/commit/96a55375003492de43e385a78f34f91179d3c737))
* **studio-frontend:** render abort/alarm events + alarm summary; builder degrades gracefully ([9143b09](https://github.com/bioexperiment-lab-devices/lab-devices/commit/9143b0930ba74abcf010a5aa329aa931be494204))
* **studio-frontend:** specific graceful message for for_each docs in the builder ([1bafb1a](https://github.com/bioexperiment-lab-devices/lab-devices/commit/1bafb1ab95e5be6a575c18ce17e01be9959ec4be))
* **studio:** export/import experiment setups (W7) ([#27](https://github.com/bioexperiment-lab-devices/lab-devices/issues/27)) ([b76e7aa](https://github.com/bioexperiment-lab-devices/lab-devices/commit/b76e7aa39172a996564dca5802cc11d60dd7ff5d))


### Bug Fixes

* **experiment:** forbid a tolerant on_error ancestor over an abort (safety hole) ([cb40695](https://github.com/bioexperiment-lab-devices/lab-devices/commit/cb40695d14cfbf27080f1979936bd936564c3ef1))
* **experiment:** let parametrized groups contain for_each (pass-through holes + residual scan) ([98f72d8](https://github.com/bioexperiment-lab-devices/lab-devices/commit/98f72d85147e87f66f08f6ddb99ff9507795c1a7))
* harden group_ref non-object body (500 fix), dedup macro defaults diagnostic, preserve Studio role diags on expand failure ([afe22fd](https://github.com/bioexperiment-lab-devices/lab-devices/commit/afe22fdcc16f86ca44bf34b2afa5ff1d60d51a21))


### Documentation

* Increment 7 design — parametrized repetition (for_each + parametrized groups) ([cda2cc5](https://github.com/bioexperiment-lab-devices/lab-devices/commit/cda2cc5c1bf1bfd4fa2c4df66a7906616a08948a))
* Increment 8 design — self-failing blocks (abort + alarm) ([dec3614](https://github.com/bioexperiment-lab-devices/lab-devices/commit/dec36141e8fa80156e8d096e220536116667ee60))
* mark limitations [#4](https://github.com/bioexperiment-lab-devices/lab-devices/issues/4) shipped; amend parent + Increment-7 specs for parametrized repetition ([07c45b6](https://github.com/bioexperiment-lab-devices/lab-devices/commit/07c45b629d37de751adc0f575ae030bcbad663c7))
* mark limitations [#7](https://github.com/bioexperiment-lab-devices/lab-devices/issues/7) shipped; amend parent design for abort/alarm ([2be983a](https://github.com/bioexperiment-lab-devices/lab-devices/commit/2be983aabd9d3c53f48f4d027c10400599af1a36))
* resolve stale parametrized-groups "deferred" references (Increment 7 shipped) ([322af79](https://github.com/bioexperiment-lab-devices/lab-devices/commit/322af793fb430b17ee10d07156a00d4a780cecf8))

## [0.5.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.4.0...v0.5.0) (2026-07-15)


### Features

* **examples:** morbidostat computes drug concentration and growth rate ([4c7a3dd](https://github.com/bioexperiment-lab-devices/lab-devices/commit/4c7a3dd416b6147f92aa87db4f3074fcbc1ce827))
* **experiment:** compute and record block AST + serialization ([59253e5](https://github.com/bioexperiment-lab-devices/lab-devices/commit/59253e500ea4f5b44a571f0484e98c80c59f2f25))
* **experiment:** computed bindings and computed streams (compute + record) ([9867809](https://github.com/bioexperiment-lab-devices/lab-devices/commit/9867809be4e35267a7c7d1d06045e75e7ed1aa67))
* **experiment:** execute compute and record blocks ([ad460b8](https://github.com/bioexperiment-lab-devices/lab-devices/commit/ad460b8f390f423a0704c6be019ea9e361481004))
* **experiment:** validate compute and record (paths, types, disjointness) ([aff9088](https://github.com/bioexperiment-lab-devices/lab-devices/commit/aff90884060a5c3f3fa4cab47f3b78bab85cff13))
* **studio:** event-log arms for binding_computed and sample_recorded ([5f6dfe6](https://github.com/bioexperiment-lab-devices/lab-devices/commit/5f6dfe65a0b61d05bb2fbb6061564da0d098560c))


### Documentation

* computed bindings and computed streams shipped ([#1](https://github.com/bioexperiment-lab-devices/lab-devices/issues/1), [#3](https://github.com/bioexperiment-lab-devices/lab-devices/issues/3)) ([6a013a6](https://github.com/bioexperiment-lab-devices/lab-devices/commit/6a013a641db022311abe496addb84c30f6fac733))
* correct mypy gate scope in plan (src/lab_devices, not tests) ([7ffa0d4](https://github.com/bioexperiment-lab-devices/lab-devices/commit/7ffa0d4c6ae29709d0864c61b074af8c4841a029))
* design spec for computed bindings and computed streams ([#1](https://github.com/bioexperiment-lab-devices/lab-devices/issues/1), [#3](https://github.com/bioexperiment-lab-devices/lab-devices/issues/3)) ([917f965](https://github.com/bioexperiment-lab-devices/lab-devices/commit/917f96507388de40ed1472c05934db9b99a37f0f))
* TDD implementation plan for computed bindings and streams ([#1](https://github.com/bioexperiment-lab-devices/lab-devices/issues/1), [#3](https://github.com/bioexperiment-lab-devices/lab-devices/issues/3)) ([d9fd286](https://github.com/bioexperiment-lab-devices/lab-devices/commit/d9fd286a796e9d5aff6060ece4cf691dbe67e141))

## [0.4.0](https://github.com/bioexperiment-lab-devices/lab-devices/compare/v0.3.0...v0.4.0) (2026-07-14)


### Features

* **examples:** morbidostat demonstration experiment + engine limitations ([#18](https://github.com/bioexperiment-lab-devices/lab-devices/issues/18)) ([d7e3955](https://github.com/bioexperiment-lab-devices/lab-devices/commit/d7e395549e2a63b28bc81f92392cc72f83cfa842))
* **examples:** morbidostat survives a transient device fault ([0e96cf0](https://github.com/bioexperiment-lab-devices/lab-devices/commit/0e96cf01f90d33488316350fb5f6fa18189933e8))
* **experiment:** declare per-verb retry_safe in the registry ([00211d4](https://github.com/bioexperiment-lab-devices/lab-devices/commit/00211d4bb1ba0dc95467f7e125e481f899bce840))
* **experiment:** engine fault tolerance — retry, on_error, per-device isolation ([27adc8d](https://github.com/bioexperiment-lab-devices/lab-devices/commit/27adc8d5939bd382db2b653da95754a29e7017ff))
* **experiment:** guard refinement for may-written streams ([841095e](https://github.com/bioexperiment-lab-devices/lab-devices/commit/841095e9f337e7c25f5e5cf341af278ec5e3cd4f))
* **experiment:** on_error tolerance and per-lane fault isolation ([7b90917](https://github.com/bioexperiment-lab-devices/lab-devices/commit/7b909170e3d8bbd0ce7b18be92d7f82fbcab4c6d))
* **experiment:** retry + on_error block schema and round-trip ([6c87cc7](https://github.com/bioexperiment-lab-devices/lab-devices/commit/6c87cc763a5aefef377799b0999d1a57936aec92))
* **experiment:** retry policy on command and measure blocks ([7188601](https://github.com/bioexperiment-lab-devices/lab-devices/commit/718860127191561c9e0a2d9bcec27da16b234701))
* **experiment:** validate retry placement, idempotency opt-in, defaults ([a5f3f71](https://github.com/bioexperiment-lab-devices/lab-devices/commit/a5f3f71e8c217fb9c587dbdf626e92a92591ca92))
* **studio:** author and display retry / on_error in the builder and run log ([702f3a3](https://github.com/bioexperiment-lab-devices/lab-devices/commit/702f3a397a1f15f6c6f33f7e02e779cef9a22b29))


### Bug Fixes

* **engine:** a raising log sink can no longer displace an in-flight abort ([0ce80fe](https://github.com/bioexperiment-lab-devices/lab-devices/commit/0ce80fe9771952bfcb7d4ddff250b30da3c29969))
* **engine:** poll a live job again instead of re-dispatching it; close the mode-guard TOCTOU ([5787521](https://github.com/bioexperiment-lab-devices/lab-devices/commit/57875215b8f2d26545b5043ebace4cf9d95a9ce6))
* **examples:** a dead sensor must not latch an open-loop drug injector ([2a2298f](https://github.com/bioexperiment-lab-devices/lab-devices/commit/2a2298f8bf0feacaed6fb7458d420066339d40af))
* **experiment:** an abort racing a lane failure is never swallowed; an orphan keeps its channels ([4d8a2db](https://github.com/bioexperiment-lab-devices/lab-devices/commit/4d8a2db18479133f941d29268cfc101c9e7934ef))
* **experiment:** close six retry-loop gaps found in review ([52fef3a](https://github.com/bioexperiment-lab-devices/lab-devices/commit/52fef3a15cb055fec41b69b74b51a29d564009e9))
* **experiment:** discriminate lane isolation, flatten masked group errors ([e95fb7d](https://github.com/bioexperiment-lab-devices/lab-devices/commit/e95fb7dd7e0ed6547b5a25bc104739024ece2395))
* **experiment:** make guard refinement window-aware (duration-window soundness hole) ([1b7fb10](https://github.com/bioexperiment-lab-devices/lab-devices/commit/1b7fb100a8660428b7c4a891bcbc23849b6ad50b))
* **experiment:** make the orphan-cancel fail-closed when a stop would kill an open mode ([7bfef3d](https://github.com/bioexperiment-lab-devices/lab-devices/commit/7bfef3d96e748308069df2aff9339a1bb2686eef))
* **experiment:** sync webapp role walker with engine block keys, export Retry/Defaults, reject defaults.on_error ([a3580ba](https://github.com/bioexperiment-lab-devices/lab-devices/commit/a3580ba1ee1ccf7e859304dfcb3e66abc4f41b1c))
* **studio:** stop cross-doc field leakage, per-stream persistence loss, stale allow_repeat ([9e6af87](https://github.com/bioexperiment-lab-devices/lab-devices/commit/9e6af87036e1aecf95b2da16318b0fb664466336))
* **studio:** stop the builder from destroying workflow.defaults/persistence on save ([849d272](https://github.com/bioexperiment-lab-devices/lab-devices/commit/849d27214651c6a7bdb6738fc30f2ad631282807))


### Documentation

* correct four claims against Task 11 real-hardware measurements ([8f7a28a](https://github.com/bioexperiment-lab-devices/lab-devices/commit/8f7a28a516b2f0845ec0c7943a463d2a1392b807))
* correct the SerialHop store race — root cause is duplicate device serials ([#20](https://github.com/bioexperiment-lab-devices/lab-devices/issues/20)) ([8be489e](https://github.com/bioexperiment-lab-devices/lab-devices/commit/8be489e0cbc69bf3698ce67d7dee50607f33d5af))
* design for engine fault tolerance (retry + on_error) ([a63138c](https://github.com/bioexperiment-lab-devices/lab-devices/commit/a63138c95b3c9aca5a6ae0cd3cf47bba9018d65b))
* engine fault tolerance shipped; retract the flaky-read warning ([2e8c477](https://github.com/bioexperiment-lab-devices/lab-devices/commit/2e8c477fa9b177ca74ddf126c236656d5e3d47a4))
* **experiment:** correct Task 2 review findings on retry_safe rationale ([7c01aab](https://github.com/bioexperiment-lab-devices/lab-devices/commit/7c01aab3c69791193e7e33d5eb3ba77f2517f55b))
* TDD plan for engine fault tolerance (11 tasks) ([ca8e319](https://github.com/bioexperiment-lab-devices/lab-devices/commit/ca8e319bd6ca36878873d0119451d856486651b0))
* the canonical example must not teach an open-loop injector ([37adbe9](https://github.com/bioexperiment-lab-devices/lab-devices/commit/37adbe9f648f16a30c90c50f672673205938bb27))

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
