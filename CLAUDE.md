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

Every page needs a `title` and optional `description`:

```mdx
---
title: "Page Title"
description: "Short description for SEO and navigation."
---
```

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
