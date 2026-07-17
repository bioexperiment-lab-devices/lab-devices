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

**An installed-but-unwired GitHub App.** `bioexperiment-release-please` (app id `3575497`) is
installed on the org, but `release-please.yml` authenticates with `secrets.GITHUB_TOKEN` and the
repo has **zero** Actions secrets. The app was set up and never connected. See §6.

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

Targets `refs/tags/v*`. Rules: `creation`, `deletion`, `non_fast_forward`. Bypass: the GitHub
Actions app (id `15368`), mode `always`, so release-please can still tag on merge.

The risk this addresses is a local `git push --tags` minting a tag that looks like a release the
changelog never recorded. Blocking `creation` is what actually prevents that; blocking deletion and
update prevents an existing release tag being silently moved.

**Fallback:** if the API rejects app `15368` as a bypass actor, drop the `creation` rule and keep
`deletion` + `non_fast_forward`, which release-please never needs to bypass. This trades away
stray-tag prevention but keeps published tags immutable.

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
2. Confirm a direct `git push` to `main` is rejected for a non-bypassing actor.
3. Re-read the ruleset and repo settings back from the API after applying.

## 6. Follow-up (not in scope — requires a human)

Wire `release-please.yml` to the installed `bioexperiment-release-please` app instead of
`GITHUB_TOKEN`, via `actions/create-github-app-token`. App-authored PRs trigger workflows normally,
which removes the `action_required` click from §2 without weakening the fork policy, and gives the
tag ruleset a first-party bypass actor. It needs the app's private key pasted into an Actions
secret, so it cannot be automated from here.
