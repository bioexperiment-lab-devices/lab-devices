# Repository governance — protect `main`, tags, and the release path

- **Date:** 2026-07-17
- **Status:** Design (approved forks settled below); applied.
- **Scope:** GitHub repository configuration for `bioexperiment-lab-devices/lab-devices`. No
  application code changes. Nothing in `lab_devices` or `webapp` is touched.
- **Applies to:** branch/tag rulesets, merge settings, GitHub Actions permissions, and the `pypi`
  deployment environment.

## 1. The problem

`main` has no protection of any kind. There is no ruleset and no classic branch protection, so
today a stray `git push --force` to `main`, a `git push --tags`, or a merge of a red PR are all one
keystroke away and nothing objects. The repo is public, publishes to PyPI on every release, and
pushes images to GHCR — the blast radius of a mistake reaches beyond the repo.

The repo is also unusual in one way that shapes every decision below: **the org has exactly one
member.** `khamitovdr` is the only collaborator and the only org owner. Governance designed for a
team — required reviews, no bypass — degrades into governance that is bypassed daily, which is
worse than none, because it teaches the bypass reflex.

## 2. Constraints discovered before designing

Three facts about the current setup constrain what can be required. All three were verified against
the live repo rather than assumed.

**CI checks that never run on a PR.** The last commit on `main` reports ten check runs:
`test (3.11)`–`test (3.14)`, `webapp-backend`, `webapp-frontend`, `webapp-image`, plus
`release-please`, `publish`, and `image`. Only the first **seven** come from `pull_request`; the
last three are `push`-to-`main` jobs from `release-please.yml`. Requiring any of those three as a
status check would block every PR forever, waiting on a check that cannot report.

**Release PR CI is held for manual approval, every time.** Attempt 1 of the CI run on every
release-please PR concludes `action_required`:

| PR | run created | attempt 1 | attempt 2 | triggered by |
|----|-------------|-----------|-----------|--------------|
| #23 | 2026-07-15 | `action_required` | `success` | `khamitovdr` |
| #26 | 2026-07-16 | `action_required` | `success` | `khamitovdr` |
| #29 | 2026-07-17 | `action_required` | `success` | `khamitovdr` |

The repo's fork-PR approval policy is `first_time_contributors`, and `github-actions[bot]` is
classified as such even though its PR is same-repo (`isCrossRepository: false`). The observed
behavior is certain; that this setting is the sole cause is probable, not proven.

The consequence is a real workflow change: **today the approval click is optional** — a release PR
can be merged with CI never having run. Once checks are required, the click becomes mandatory.
That is the intended outcome, not a regression.

**An unwired GitHub App.** At design time `release-please.yml` authenticated with
`secrets.GITHUB_TOKEN`, while `bioexperiment-release-please` (app id `3575497`) sat installed on the
org — but **not on this repo** — with its credentials (`RELEASE_PLEASE_APP_KEY`,
`RELEASE_PLEASE_APP_ID`) already org-wide and readable here. Set up, never connected. Now wired;
see §6.

## 3. Design

### 3.1 Branch ruleset — `protect-main`

Targets `~DEFAULT_BRANCH`. Rules:

- `pull_request` with `required_approving_review_count: 0`, `allowed_merge_methods: ["squash"]`.
- `required_status_checks` over exactly the seven PR checks named in §2.
- `deletion`, `non_fast_forward`, `required_linear_history`.

Bypass: `OrganizationAdmin`, mode `always`.

Two deliberate omissions:

- **No required approving review.** GitHub does not permit self-approval. On a one-person org, a
  review requirement blocks every PR its author opens, so it would be bypassed every time. A rule
  that is always bypassed is not a control; it is a habit of ignoring controls. Revisit the moment
  a second maintainer joins — this is the single setting to change then.
- **`strict_required_status_checks_policy: false`** (branches need not be up to date before
  merging). Strict mode forces a rebase-and-rerun whenever anything lands ahead of you. It guards
  against semantic conflicts between concurrently-merged PRs — a risk that needs concurrent PRs to
  exist. With one maintainer, it costs a full CI cycle per merge to guard against approximately
  nothing.

### 3.2 Tag ruleset — `protect-release-tags`

Targets `refs/tags/v*`. Rules: `creation`, `deletion`, `non_fast_forward`. Bypass:
`Integration:3575497` (the `bioexperiment-release-please` App) and `OrganizationAdmin`.

The risk this addresses is a local `git push --tags` minting a tag that looks like a release the
changelog never recorded. Blocking `creation` prevents that; blocking deletion and update prevents
an existing release tag being silently moved.

**This shipped in two stages, and the first attempt failed.** The original design named the GitHub
Actions app (`15368`) as the bypass actor, since release-please tagged via `GITHUB_TOKEN`. The API
rejected it:

```
422: Actor GitHub Actions integration must be part of the ruleset source or owner organization
```

Probing `bioexperiment-release-please` (`3575497`) returned the identical error — which read like a
generic refusal of app bypass actors, but was the literal truth: **the App was not installed on
`lab-devices`.** Confirmed by minting a token in a throwaway workflow, where
`create-github-app-token` failed with `Not Found` on `/repos/…/lab-devices/installation`. The
installation (`128865498`) is `repository_selection: "selected"` and covered `lab-bridge` and
`serialhop` only.

Granting the App access to this repo — a UI-only action; `PUT /user/installations/…/repositories/…`
returns 403 even for an org owner through an OAuth token — makes `3575497` a valid bypass actor and
`creation` enforceable. It is enforced.

The Actions app (`15368`) is still refused and probably always will be, which is why §6 is a
prerequisite for this rule rather than an optional nicety: **the tag ruleset and the App wiring must
ship together.** Blocking `creation` while release-please still tags via `GITHUB_TOKEN` would break
every release.

### 3.3 Repository settings

| Setting | From | To | Why |
|---|---|---|---|
| `allow_merge_commit` | `true` | `false` | #25 landed as a merge commit; release-please parses commit subjects, and merge commits are noise |
| `allow_rebase_merge` | `true` | `false` | one landing shape only |
| `allow_squash_merge` | `true` | `true` | — |
| `squash_merge_commit_title` | `COMMIT_OR_PR_TITLE` | `PR_TITLE` | deterministic conventional-commit input; `COMMIT_OR_PR_TITLE` varies by commit count |
| `squash_merge_commit_message` | `COMMIT_MESSAGES` | `PR_BODY` | `COMMIT_MESSAGES` replays every branch commit into the body, where release-please may re-read `BREAKING CHANGE:` footers it already counted |
| `delete_branch_on_merge` | `false` | `true` | — |
| `allow_auto_merge` | `false` | `true` | with required checks, lets a PR land on green without babysitting |
| `allow_update_branch` | `false` | `true` | opt-in freshness, since strict mode is off |

### 3.4 Actions and the release environment

- `can_approve_pull_request_reviews`: `true` → **`false`**. A workflow able to approve PRs is a
  standing hole under any future review requirement. Nothing here uses it.
- `default_workflow_permissions` stays `read` — already correct.
- **`pypi` environment** currently has `protection_rules: []` and
  `deployment_branch_policy: null` — any run reaching it can publish. Add a custom branch policy
  admitting `main` only. The `publish` job runs from `push`-to-`main`, so its ref qualifies.
  No required reviewer: the branch policy closes the "publish from an arbitrary branch" hole, and a
  human gate on every release is friction that gets clicked through unread.
- **Fork-PR approval policy stays `first_time_contributors`.** Relaxing it to `never` would remove
  the release-PR approval click, but on a public repo it is the control that stops a drive-by
  fork PR from executing workflows. The click is not worth that. §6 is the right fix.

## 4. What this explicitly does not do

- **It does not stop the maintainer.** Org-admin bypass is deliberate (§3.1). This design defends
  against accident and against a compromised workflow, not against the author.
- **Squash-only narrows release-please's input.** Individual conventional commits inside a branch
  stop reaching `main`; only the PR title survives. Current PR titles are already conventional, so
  this is a no-op today — but a sloppy PR title now becomes a sloppy changelog entry with nothing
  to catch it.

## 5. Verification

Applying config proves nothing about whether it works. The check is behavioral:

1. Open a PR from `chore/repo-governance` and confirm it reports the ruleset as blocking until the
   seven checks are green — i.e. this design's own PR is its first test case.
2. Re-read the rulesets and repo settings back from the API after applying.

**"Direct push to `main` is rejected" is not verifiable from this account.** The sole maintainer
holds `OrganizationAdmin` bypass in mode `always` (§3.1), so their push is *supposed* to succeed —
a successful push proves nothing, and a rejected one would mean the bypass is broken. Confirming the
block would need a second, non-bypassing account, which the org does not have. This is the direct
cost of the bypass decision, accepted knowingly: the rule that stops a force-push is the same rule
its only tester is exempt from.

## 6. The App wiring

`release-please.yml` authenticates as the `bioexperiment-release-please` App via
`actions/create-github-app-token@v3`, not `GITHUB_TOKEN`. This removes the `action_required` click
from §2 without weakening the fork policy, and supplies §3.2's bypass actor.

Nothing needed to be created: org secret `RELEASE_PLEASE_APP_KEY` (`visibility: all`) and org
variable `RELEASE_PLEASE_APP_ID` (`3575497`) already existed and were already readable from this
repo. The App had simply never been granted access to `lab-devices`, and the workflow had never been
pointed at it. `serialhop/.github/workflows/release-please.yml` was the working template.

Evidence the fix holds: serialhop's App-authored release PRs (#193, #195, #198) all run CI at
`attempt=1`, triggered by `bioexperiment-release-please[bot]` itself, with no approval hold — versus
`attempt=2` on every `GITHUB_TOKEN`-authored release PR here.

**One caveat this design cannot verify in advance.** `release-please.yml` runs only on push to
`main`, so no PR can exercise it — the first real proof is the next push to `main`. The failure mode
is loud (the `app-token` step fails outright and no release PR appears), and the fallback is a
one-line revert to `token: ${{ secrets.GITHUB_TOKEN }}` plus dropping §3.2's `creation` rule.

### 6.1 Open thread

The mechanism behind §2's hold is still not pinned down. This design attributes it to the
`first_time_contributors` fork policy, on the evidence that a run was *created and held*
(`action_required`). serialhop's own comment attributes it to GitHub's anti-recursion rule, under
which no run is created at all. Both point to the same fix and the fix is confirmed working, so the
discrepancy is recorded rather than resolved.
