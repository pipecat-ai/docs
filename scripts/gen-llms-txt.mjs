#!/usr/bin/env node
// @ts-check
/**
 * Generate the custom llms.txt and llms-full.txt for docs.pipecat.ai.
 *
 * Root-level files override Mintlify's auto-generated ones (which truncate at
 * 100,000 characters). Two outputs share the same hand-written orientation
 * preamble:
 *   - llms.txt       a structured index: navigation-derived sections mirroring
 *                    the docs.json tab/group hierarchy, one entry per page
 *                    built from its frontmatter title and description.
 *   - llms-full.txt  the complete dump: every navigation page's full MDX body
 *                    in nav order. Snippet imports and their component usages
 *                    are stripped (we cannot render them outside Mintlify);
 *                    OpenAPI-backed pages contribute their operation line and
 *                    description (the schema tables are Mintlify-rendered).
 *
 * Usage:
 *   node scripts/gen-llms-txt.mjs                # rewrite both files in place
 *   node scripts/gen-llms-txt.mjs --stdout       # print llms.txt (used by the lint)
 *   node scripts/gen-llms-txt.mjs --stdout-full  # print llms-full.txt (used by the lint)
 *
 * CI check 13 in docs-meta-lint.mjs regenerates both files and fails if the
 * checked-in copies differ, so run this after any page add, move, retitle, or
 * content edit.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const BASE = "https://docs.pipecat.ai/";

const PREAMBLE = `# Pipecat

> Pipecat is an open source ecosystem for building voice and multimodal AI
> agents. Build with the Python framework, connect users with the client SDKs,
> structure conversations with Pipecat Flows, and deploy to production on
> Pipecat Cloud.

## About Pipecat

Pipecat is an open source framework and hosted platform for real-time voice
and multimodal AI agents. Its primary components:

- **Pipecat framework**: An open source Python framework that orchestrates AI
  services (STT, LLM, TTS, and more) into real-time pipelines. Start with the
  [quickstart](${BASE}pipecat/get-started/quickstart.md).
- **Pipecat client SDKs**: JavaScript, React, React Native, iOS, Android, and
  C++ SDKs that connect users to agents over WebRTC or WebSockets. See the
  [client introduction](${BASE}client/introduction.md).
- **Pipecat Flows**: A framework for structured conversations - define
  conversation paths as nodes with functions and actions. See the
  [Flows introduction](${BASE}pipecat-flows/introduction.md).
- **Pipecat Cloud**: Managed infrastructure for deploying and scaling agents,
  run by the Pipecat team. See the
  [Cloud introduction](${BASE}pipecat-cloud/introduction.md).
- **Pipecat Enterprise**: The same Pipecat Cloud control plane, with agents
  running in a Kubernetes cluster you operate. See the
  [Enterprise overview](${BASE}enterprise/overview.md).
- **Pipecat CLI**: Scaffold projects, run evals, and deploy from the terminal.
  See the [CLI overview](${BASE}api-reference/cli/overview.md).

Server API reference lives under \`api-reference/server/\`: services (STT, TTS,
LLM, transports, serializers), pipelines, frames, workers, and utilities.
`;

const FOOTER = `
## Optional

- [Pipecat Events](https://pipecat.ai/events)
- [Community](https://discord.gg/pipecat)
- [GitHub](https://github.com/pipecat-ai/pipecat)
- [Changelog](https://github.com/pipecat-ai/pipecat/blob/main/CHANGELOG.md)
`;

/** @param {string} text */
function frontmatter(text) {
  const m = text.match(/^---\n([\s\S]*?)\n---/);
  /** @type {Record<string, string>} */
  const out = {};
  if (!m) return out;
  for (const line of m[1].split("\n")) {
    const km = line.match(/^([A-Za-z0-9_:"'-]+):\s*(.*)$/);
    if (!km) continue;
    let val = km[2].trim();
    if (val.length > 1 && `"'`.includes(val[0]) && val.at(-1) === val[0]) {
      val = val.slice(1, -1);
    }
    out[km[1].replace(/^["']|["']$/g, "")] = val;
  }
  return out;
}

/** Flat list of page slugs in navigation order. @param {any} docsJson */
function navSlugs(docsJson) {
  /** @type {string[]} */
  const slugs = [];
  /** @param {any[]} pages */
  const walk = (pages) => {
    for (const p of pages) {
      if (typeof p === "string") slugs.push(p);
      else {
        if (p.root) slugs.push(p.root);
        walk(p.pages);
      }
    }
  };
  for (const tab of docsJson.navigation.tabs) {
    if (tab.pages)
      for (const p of tab.pages) if (typeof p === "string") slugs.push(p);
    for (const group of tab.groups) {
      if (group.root) slugs.push(group.root);
      walk(group.pages);
    }
  }
  return slugs;
}

const SNIPPET_IMPORT_RE =
  /^import\s+(?:\{([^}]*)\}|(\w+))\s+from\s+["']\/snippets\/[^"']+["'];?[^\S\n]*\n?/gm;

/**
 * Page body with frontmatter, snippet imports, and self-closing usages of
 * snippet-imported components stripped. No whitespace collapsing beyond the
 * stripped spans - code examples may contain intentional blank runs.
 * @param {string} text
 */
function pageBody(text) {
  let body = text.replace(/^---\n[\s\S]*?\n---\n?/, "");
  /** @type {string[]} */
  const snippetNames = [];
  body = body.replace(SNIPPET_IMPORT_RE, (_, named, dflt) => {
    const ids = named ? named.split(",") : [dflt];
    snippetNames.push(...ids.map((s) => s.trim()).filter(Boolean));
    return "";
  });
  for (const name of snippetNames) {
    body = body.replace(new RegExp(`\\n?<${name}\\b[\\s\\S]*?/>\\n?`, "g"), "");
  }
  return body.trim();
}

function generateFull() {
  const docsJson = JSON.parse(readFileSync(join(ROOT, "docs.json"), "utf-8"));
  /** @type {string[]} */
  const parts = [PREAMBLE];
  for (const slug of navSlugs(docsJson)) {
    const raw = readFileSync(join(ROOT, `${slug}.mdx`), "utf-8");
    const fm = frontmatter(raw);
    // url-stub pages are external links; point Source at the real target
    let page = `# ${fm.title}\nSource: ${fm.url ?? `${BASE}${slug}.md`}\n`;
    if (fm.description) page += `\n${fm.description}\n`;
    if (fm.openapi) page += `\nOpenAPI operation: \`${fm.openapi}\`\n`;
    const body = pageBody(raw);
    if (body) page += `\n${body}\n`;
    parts.push(page);
  }
  return parts.join("\n");
}

function generate() {
  const docsJson = JSON.parse(readFileSync(join(ROOT, "docs.json"), "utf-8"));
  /** @type {string[]} */
  const lines = [PREAMBLE];

  /** @param {any[]} pages @param {number} depth */
  const walk = (pages, depth) => {
    for (const p of pages) {
      if (typeof p === "string") {
        const fm = frontmatter(readFileSync(join(ROOT, `${p}.mdx`), "utf-8"));
        const desc = fm.description ? `: ${fm.description}` : "";
        lines.push(`- [${fm.title}](${BASE}${p}.md)${desc}`);
      } else {
        lines.push("", `${"#".repeat(Math.min(depth, 6))} ${p.group}`, "");
        walk(p.pages, depth + 1);
      }
    }
  };

  const entry = (p) => {
    const fm = frontmatter(readFileSync(join(ROOT, `${p}.mdx`), "utf-8"));
    const desc = fm.description ? `: ${fm.description}` : "";
    lines.push(`- [${fm.title}](${BASE}${p}.md)${desc}`);
  };
  for (const tab of docsJson.navigation.tabs) {
    lines.push("", `## ${tab.tab}`, "");
    if (tab.pages) {
      for (const p of tab.pages) if (typeof p === "string") entry(p);
      lines.push("");
    }
    for (const group of tab.groups) {
      lines.push(`### ${group.group}`, "");
      if (group.root) entry(group.root);
      walk(group.pages, 4);
      lines.push("");
    }
  }
  lines.push(FOOTER);
  return lines.join("\n").replace(/\n{3,}/g, "\n\n");
}

if (process.argv.includes("--stdout")) {
  process.stdout.write(generate());
} else if (process.argv.includes("--stdout-full")) {
  process.stdout.write(generateFull());
} else {
  for (const [file, output] of [
    ["llms.txt", generate()],
    ["llms-full.txt", generateFull()],
  ]) {
    writeFileSync(join(ROOT, file), output);
    console.log(
      `${file} written: ${[...output].length.toLocaleString("en-US")} chars`,
    );
  }
}
