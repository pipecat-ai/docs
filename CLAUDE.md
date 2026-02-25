# CLAUDE.md

## Project overview

This is the documentation site for [Pipecat](https://github.com/pipecat-ai/pipecat), hosted at [docs.pipecat.ai](https://docs.pipecat.ai). It's built with [Mintlify](https://mintlify.com/) and contains ~314 MDX files covering guides, API references, and deployment docs.

## Development commands

```bash
# Start local dev server
mint dev

# Check for broken links (also runs in CI)
mint broken-links

# Format files with Prettier
npx prettier --write .
```

## Project structure

```
docs.json          # Site config: navigation, tabs, theme, metadata
getting-started/   # Intro, quickstart, ecosystem overview
guides/            # Learning guides, feature how-tos
server/            # Server-side framework reference (pipelines, services, utilities)
client/            # Client SDK docs (JS, React, React Native, etc.)
cli/               # Pipecat CLI reference
deployment/        # Pipecat Cloud deployment docs
snippets/          # Reusable MDX snippets (shared across pages)
images/            # Static images
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

All pages must be registered in `docs.json` under `navigation.tabs[].groups[].pages`. The path is relative to the repo root without the `.mdx` extension (e.g., `"guides/learn/overview"`).

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

## CI/CD

A GitHub Actions workflow (`.github/workflows/broken-links.yml`) runs `mint broken-links` on PRs and pushes to `main`. It comments on PRs if broken links are detected.

## Pipecat source reference

The main Pipecat framework repo is typically located at `../pipecat` (sibling directory). Cross-reference it when documenting API behavior or verifying parameter names against source code.
