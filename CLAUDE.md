---
noindex: true
searchable: false
---

# CLAUDE.md

## Project overview

This is the documentation site for [Pipecat](https://github.com/pipecat-ai/pipecat), hosted at [docs.pipecat.ai](https://docs.pipecat.ai). It's built with [Mintlify](https://mintlify.com/) and contains several hundred MDX files covering guides, API references, and deployment docs.

## Development commands

```bash
# Install the Node version in .nvmrc, then dependencies and Git hooks
nvm install
npm install

# Start local dev server
npx mint dev

# Check for broken links (also runs in CI)
npx mint broken-links

# Lint frontmatter metadata: title/description uniqueness, lengths,
# llms.txt + llms-full.txt staleness (also runs in CI)
node scripts/docs-meta-lint.mjs

# Regenerate llms.txt (tiered index) and llms-full.txt (full content dump)
# after adding, moving, retitling, or editing pages
# (CI fails if the checked-in files are stale)
node scripts/gen-llms-txt.mjs

# Format the whole site with Prettier
npm run format
```

## Project structure

The content directories correspond one-to-one with the navigation tabs in `docs.json`:

```
docs.json          # Site config: navigation, tabs, theme, metadata
overview/          # Intro and ecosystem overview
pipecat/           # Pipecat framework docs (fundamentals, learn, features, telephony, deployment)
client/            # Client SDK docs (concepts, guides)
pipecat-flows/     # Pipecat Flows docs
pipecat-cloud/     # Pipecat Cloud docs (fundamentals, guides, security)
api-reference/     # Reference for server, client, CLI, Flows, and Cloud REST
snippets/          # Reusable MDX snippets (shared across pages)
images/ logo/ videos/   # Static assets
```

## Content conventions

### MDX frontmatter

Every page needs a `title` and a `description`. The frontmatter `title` becomes
the `<title>` tag, the H1, the llms.txt entry, and the citation label in AI
tools (Kapa, Pipecat Context Hub) — so it must be unique across the site and
self-describing without navigation context. `sidebarTitle` controls only the
sidebar label; use it to keep nav labels short when the title carries context.

```mdx
---
title: "Deepgram Speech-to-Text"
sidebarTitle: "Deepgram"
description: "Streaming STT with DeepgramSTTService and DeepgramFluxSTTService: Nova models, Flux turn detection, and SageMaker variants."
---
```

Conventions (enforced by `scripts/docs-meta-lint.mjs`, which runs in CI):

- **Titles**: short and readable — the title renders verbatim as the page H1.
  ≤ 50 chars; no ` - Pipecat` suffix (Mintlify appends it). Duplicate titles
  are tolerated (they only warn), but every page's **effective unfurl title**
  — `"og:title"` if set, else `title` — must be globally unique. When two
  pages legitimately share a short title (e.g. `Daily WebRTC Transport` across
  SDKs), add a disambiguating `"og:title"`: e.g.
  `"og:title": "Daily WebRTC Transport - iOS SDK"`. Titles over 30 chars
  require a `sidebarTitle`.
- **Descriptions**: 110–140 chars target (50–160 hard band); include the class
  names the page documents and the literal modality acronym (STT/TTS/LLM/VAD)
  where relevant; avoid boilerplate openers like "service implementation using".
- After adding, moving, retitling, or editing a page, run
  `node scripts/gen-llms-txt.mjs` to regenerate the checked-in `llms.txt` and
  `llms-full.txt` — CI fails if either is stale.

### Adding pages to navigation

All pages must be registered in `docs.json` under `navigation.tabs[].groups[].pages`. The path is relative to the repo root without the `.mdx` extension (e.g., `"overview/introduction"`).

### Mintlify components

Use Mintlify's built-in components for structured content:

- `<Tip>`, `<Note>`, `<Warning>`, `<Info>` — callout blocks
- `<Steps>`, `<Step>` — numbered step sequences
- `<Tabs>`, `<Tab>` — tabbed content (e.g., Python vs JS examples)
- `<Card>`, `<CardGroup>` — linked card grids
- `<Accordion>`, `<AccordionGroup>` — collapsible sections
- `<Frame>` — image wrapper with caption support
- `<CodeGroup>` — multi-language code block switcher

## Formatting

Prettier is configured via `.prettierrc`:

- 2-space indentation (spaces, not tabs)
- Double quotes
- Semicolons enabled

A husky pre-commit hook runs lint-staged, which formats staged files. The whole
site is Prettier-clean, so `npm run format` should be a no-op on a clean tree.

## CI/CD

A GitHub Actions workflow (`.github/workflows/broken-links.yml`) runs `mint broken-links` on PRs and pushes to `main`. It comments on PRs if broken links are detected.

## Pipecat source reference

The main Pipecat framework repo is typically located at `../pipecat` (sibling directory). Cross-reference it when documenting API behavior or verifying parameter names against source code.
