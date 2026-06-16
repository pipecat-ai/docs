# Deployment & Release Process

## Overview

Two branches map to two environments:

| Branch       | Environment | URL                             | Updated by                        |
| ------------ | ----------- | ------------------------------- | --------------------------------- |
| `production` | Production  | https://docs.pipecat.ai         | Promotion from `main` (see below) |
| `main`       | Staging     | https://daily-main.mintlify.app | Every merge into `main`           |

Mintlify's **deployment branch** is set to `production` (Dashboard → Settings →
Deployment → Git Settings). Mintlify builds the live site from that branch
only. As a result, merging a PR into `main` does **not** touch production — it
updates staging. "Merged" means "in staging," not "live."

## Staging

- Merging any PR into `main` triggers the **Mintlify Preview** workflow, which
  redeploys the stable staging preview at **https://daily-main.mintlify.app**.
  Staging always reflects the current tip of `main`.
- Open pull requests targeting `main` get their own per-branch preview
  (URL pattern `https://daily-<branch>.mintlify.app`, with slashes replaced by
  dashes). The workflow posts and keeps updated a single preview-link comment on
  the PR.

## Releasing to production

Production is published by advancing `production` to the current `main`. This
is a **manual** action: Actions → **Release to Production** → Run workflow.

The workflow fast-forwards `production` to `main` with a non-force push. Because
production only ever moves through this workflow, the push is always a
fast-forward. If `production` has diverged from `main` (for example, a commit
pushed directly to `production` that is not in `main`), the push fails
deliberately rather than overwriting history.

## Workflows

- `.github/workflows/mintlify-preview.yml` — staging and per-PR previews via the
  Mintlify preview API.
- `.github/workflows/promote-to-production.yml` (display name: **Release to
  Production**) — promotes `main` → `production`.

## Configuration

Repository → Settings → Secrets and variables → Actions:

- **Secret** `MINTLIFY_API_KEY` — Mintlify admin API key (prefixed `mint_`).
- **Variable** `MINTLIFY_PROJECT_ID` — Mintlify project ID.

Both values come from the Mintlify dashboard's API keys page. The preview
workflow fails if either is missing.

## Common tasks

- **Publish current `main` to production** — Actions → **Release to Production** →
  Run workflow.
- **View staging** — https://daily-main.mintlify.app
- **View a PR's preview** — see the preview comment on the PR, or visit
  `https://daily-<branch>.mintlify.app`.
- **Roll back production** — revert the offending commit(s) on `main`, then run
  **Release to Production**. Do not push directly to `production`; doing so
  diverges it from `main` and the next promotion will fail.
