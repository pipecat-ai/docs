# Contributing to Pipecat Documentation

Welcome! This is the documentation repository for [Pipecat](https://github.com/pipecat-ai/pipecat), hosted at [docs.pipecat.ai](https://docs.pipecat.ai). Whether you're fixing a typo, adding a new section, or improving readability, your help is appreciated.

## Code of Conduct

This project follows the [Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct.html). Please treat everyone with respect. Unacceptable behavior can be reported to [pipecat-ai@daily.co](mailto:pipecat-ai@daily.co).

## Getting Started

### Prerequisites

[nvm](https://github.com/nvm-sh/nvm), or another way to install the Node version pinned in `.nvmrc`.

### Setup

1. Fork this repository and clone your fork:

   ```bash
   git clone https://github.com/your-username/docs
   cd docs
   ```

2. Install and switch to the Node version this repo targets (see `.nvmrc`):

   ```bash
   nvm install
   ```

3. Install dependencies. This also installs the Git hooks that format your changes on commit:

   ```bash
   npm install
   ```

4. Start the local dev server:

   ```bash
   npx mint dev
   ```

5. Open `https://localhost:3000` in your browser to preview changes.

### Troubleshooting

- **Mintlify dev isn't running** — Run `npx mint update` to get the latest version.
- **Page loads as a 404** — Make sure you are running in a folder with `docs.json`.

## Making a Contribution

1. **Create a branch** for your changes:

   ```bash
   git checkout -b your-branch-name
   ```

2. **Make your edits.** See the [Content Guidelines](#content-guidelines) below.

3. **Check for broken links:**

   ```bash
   npx mint broken-links
   ```

4. **Commit your changes** with a meaningful message. A pre-commit hook formats
   the files you staged:

   ```bash
   git commit -m "Description of your changes"
   ```

5. **Push your branch** and open a Pull Request against `main`:

   ```bash
   git push origin your-branch-name
   ```

Our maintainers will review your PR, and once everything looks good, your contributions will be merged!

## Content Guidelines

### MDX Frontmatter

Every page needs a `title` (required) and `description` (recommended):

```mdx
---
title: "Page Title"
description: "Short description for SEO and navigation."
---
```

### Adding Pages to Navigation

All pages must be registered in `docs.json` under `navigation.tabs[].groups[].pages`. The path is relative to the repo root without the `.mdx` extension:

```
"overview/introduction"
```

### Project Structure

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

### Mintlify Components

Use Mintlify's [built-in components](https://mintlify.com/docs/content/components/) for structured content:

| Component                                | Purpose                            |
| ---------------------------------------- | ---------------------------------- |
| `<Tip>`, `<Note>`, `<Warning>`, `<Info>` | Callout blocks                     |
| `<Steps>`, `<Step>`                      | Numbered step sequences            |
| `<Tabs>`, `<Tab>`                        | Tabbed content (e.g., Python/JS)   |
| `<Card>`, `<CardGroup>`                  | Linked card grids                  |
| `<Accordion>`, `<AccordionGroup>`        | Collapsible sections               |
| `<Frame>`                                | Image wrapper with caption support |
| `<CodeGroup>`                            | Multi-language code block switcher |

### Formatting

Prettier is configured via `.prettierrc`:

- 2-space indentation (spaces, not tabs)
- Double quotes
- Semicolons enabled

A pre-commit hook (husky + lint-staged) formats staged files, so formatting is
usually taken care of for you. To format the whole site by hand:

```bash
npm run format
```

## Continuous Integration

A GitHub Actions workflow runs `mint broken-links` on every PR and push to `main`. If broken links are detected, the workflow will fail and post a comment on your PR. You can run the same check locally:

```bash
npx mint broken-links
```

## Getting Help

- **GitHub Issues**: [pipecat-ai/docs/issues](https://github.com/pipecat-ai/docs/issues)
- **Discord**: [discord.gg/pipecat](https://discord.gg/pipecat)
