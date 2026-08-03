#!/usr/bin/env node
// @ts-check
/**
 * Generate the custom llms.txt for docs.pipecat.ai.
 *
 * A root-level llms.txt overrides Mintlify's auto-generated file (which
 * truncates at 100,000 characters). This generator emits a structured index:
 * a hand-written orientation section, then navigation-derived sections
 * mirroring the docs.json tab/group hierarchy, with one entry per page built
 * from its frontmatter title and description.
 *
 * Usage:
 *   node scripts/gen-llms-txt.mjs            # rewrite llms.txt in place
 *   node scripts/gen-llms-txt.mjs --stdout   # print to stdout (used by the lint)
 *
 * CI check 13 in docs-meta-lint.mjs regenerates this file and fails if the
 * checked-in llms.txt differs, so run this after any page add, move, or
 * frontmatter change.
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

  for (const tab of docsJson.navigation.tabs) {
    lines.push("", `## ${tab.tab}`, "");
    for (const group of tab.groups) {
      lines.push(`### ${group.group}`, "");
      walk(group.pages, 4);
      lines.push("");
    }
  }
  lines.push(FOOTER);
  return lines.join("\n").replace(/\n{3,}/g, "\n\n");
}

const output = generate();
if (process.argv.includes("--stdout")) {
  process.stdout.write(output);
} else {
  writeFileSync(join(ROOT, "llms.txt"), output);
  console.log(
    `llms.txt written: ${[...output].length.toLocaleString("en-US")} chars`,
  );
}
