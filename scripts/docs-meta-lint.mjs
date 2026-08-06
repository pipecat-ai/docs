#!/usr/bin/env node
// @ts-check
/**
 * Frontmatter metadata lint for pipecat-docs.
 *
 * Guards the metadata that feeds four consumers of this site:
 *   - Google/SERP + social unfurls  (<title>, meta/og description)
 *   - llms.txt                      (entry = frontmatter title + description)
 *   - Pipecat Context Hub           (indexes llms-full.txt; title+description
 *                                    form each page's identity chunk)
 *   - Kapa.ai widget                (crawls rendered HTML; title is the citation label)
 *
 * Modes:
 *   --report            human-readable summary (default)
 *   --verbose           itemize every finding under the summary
 *   --json              machine-readable snapshot (metrics + per-page rows)
 *   --compare FILE      diff against a previous --json snapshot; emits a CSV of
 *                       changed sidebar labels for human review
 *   --calibrate         fetch the live llms.txt and assert the size-projection
 *                       model reproduces it within +/-2 chars
 *   --format github     add ::warning/::error annotations for GitHub Actions
 *   --root PATH         repo root (default: parent of this script's directory)
 *   --git-base REF      ref for rename/delete + redirect-change checks (default HEAD)
 *
 * Checks are numbered 1-19. ENFORCED holds the numbers that fail CI;
 * everything else reports as WARN. Duplicate raw titles are tolerated (short
 * titles make better H1s); what must stay unique are descriptions (8) and the
 * effective unfurl title (19: "og:title" falling back to title).
 *
 * Exit code: 1 if any ERROR-level finding, else 0. Zero dependencies; Node 18+.
 */

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

// --- Constants calibrated against the live site (see --calibrate) ----------
const BASE_URL = "https://docs.pipecat.ai/";
const ENTRY_PUNCT = 9; // "- [" + "](" + "): " + "\n" per llms.txt entry
const FIXED_OVERHEAD = 360; // llms.txt headers + "## OpenAPI Specs" + "## Optional"
const AUTOGEN_CAP = 100_000; // Mintlify truncates the auto-generated llms.txt here
const AUTOGEN_WARN = 95_000; // fallback-safety warning (check 12)
const CUSTOM_LLMS_WARN = 120_000; // usability ceiling for a custom llms.txt (check 14)

// Checks that fail CI. Presence (1) is enforced so no page can ship without
// a title and description - which also guarantees Mintlify always has a
// per-page og:description to generate (there is deliberately no global
// fallback in docs.json: seo.metatags values override every page, they do
// not fall back). Raw title duplicates (2, 3) are allowed and only warn:
// short titles are preferred for readable H1s, and a duplicate is acceptable
// when a page-level "og:title" disambiguates it. The enforced invariants are
// description uniqueness (8) and effective unfurl-title uniqueness (19,
// og:title falling back to title) - together they keep every page's RAG
// identity (title + description) and social/AI citation label unique.
const ENFORCED = new Set([1, 8, 13, 15, 16, 17, 18, 19]);

const EXPECTED_OPENAPI_PAGES = 24;
const EXPECTED_URL_STUBS = {
  "api-reference/server/links/server-reference":
    "https://reference-server.pipecat.ai/",
  "api-reference/client/ios/api-reference": "https://docs-ios.pipecat.ai/",
  "api-reference/client/android/api-reference": "https://docs-android.rtvi.ai/",
};
const GRANDFATHERED_PARENS = new Set([
  "api-reference/server/rtvi/introduction",
]);
/** path segment -> tokens accepted in the description (check 11) */
const ACRONYMS = {
  stt: ["STT"],
  tts: ["TTS"],
  llm: ["LLM"],
  vad: ["VAD"],
  s2s: ["S2S", "speech-to-speech", "Realtime", "realtime"],
};

const LLMS_ENTRY_RE = /^- \[(.*?)\]\((.*?)\)(?:: (.*))?$/;

/** Length in Unicode code points (matches how sizes were calibrated). */
const cplen = (s) => [...s].length;

/** @param {string} text */
function parseFrontmatter(text) {
  const m = text.match(/^---\n([\s\S]*?)\n---/);
  if (!m) return null;
  /** @type {Record<string, string>} */
  const out = {};
  for (const line of m[1].split("\n")) {
    const km = line.match(/^([A-Za-z0-9_:"'-]+):\s*(.*)$/);
    if (!km) continue;
    const key = km[1].replace(/^["']|["']$/g, "");
    let val = km[2].trim();
    if (val.length > 1 && `"'`.includes(val[0]) && val.at(-1) === val[0]) {
      val = val.slice(1, -1);
    }
    out[key] = val;
  }
  return out;
}

/**
 * @param {any} docsJson
 * @returns {Array<{slug: string, tab: string, chain: string[]}>}
 */
function walkNav(docsJson) {
  /** @type {Array<{slug: string, tab: string, chain: string[]}>} */
  const out = [];
  /** @param {any[]} pages @param {string} tab @param {string[]} chain */
  const walk = (pages, tab, chain) => {
    for (const p of pages) {
      if (typeof p === "string") out.push({ slug: p, tab, chain });
      else {
        if (p.root) out.push({ slug: p.root, tab, chain: [...chain, p.group] });
        walk(p.pages, tab, [...chain, p.group]);
      }
    }
  };
  for (const tab of docsJson.navigation.tabs) {
    if (tab.pages) walk(tab.pages, tab.tab, []);
    for (const group of tab.groups) {
      if (group.root)
        out.push({ slug: group.root, tab: tab.tab, chain: [group.group] });
      walk(group.pages, tab.tab, [group.group]);
    }
  }
  return out;
}

/** @param {string} dir @returns {string[]} */
function findMdx(dir) {
  /** @type {string[]} */
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (
        ["node_modules", ".git", "snippets", "baseline"].includes(entry.name)
      ) {
        continue;
      }
      out.push(...findMdx(join(dir, entry.name)));
    } else if (entry.name.endsWith(".mdx")) {
      out.push(join(dir, entry.name));
    }
  }
  return out;
}

/**
 * @typedef {{slug: string, tab: string, division: string, title: string,
 *   ogTitle: string | null, description: string, sidebarTitle: string | null,
 *   openapi: boolean, url: string | null}} Page
 */

/** @param {string} root */
function loadPages(root) {
  const docsJson = JSON.parse(readFileSync(join(root, "docs.json"), "utf-8"));
  /** @type {Page[]} */
  const pages = [];
  /** @type {string[]} */
  const missing = [];
  for (const { slug, tab, chain } of walkNav(docsJson)) {
    const path = join(root, `${slug}.mdx`);
    const fm = existsSync(path)
      ? parseFrontmatter(readFileSync(path, "utf-8"))
      : null;
    if (fm === null) {
      missing.push(slug);
      continue;
    }
    pages.push({
      slug,
      tab,
      division: chain.at(-1) ?? tab,
      title: fm.title ?? "",
      ogTitle: fm["og:title"] ?? null,
      description: fm.description ?? "",
      sidebarTitle: fm.sidebarTitle ?? null,
      openapi: "openapi" in fm,
      url: fm.url ?? null,
    });
  }
  const navSlugs = new Set(pages.map((p) => p.slug));
  const orphans = findMdx(root)
    .map((f) => relative(root, f).replace(/\.mdx$/, ""))
    .filter((rel) => !navSlugs.has(rel))
    .sort();
  return { docsJson, pages, orphans, missing };
}

/** @param {Page[]} pages */
function projectedAutogenSize(pages) {
  return (
    FIXED_OVERHEAD +
    pages.reduce(
      (sum, p) =>
        sum +
        cplen(BASE_URL + p.slug + ".md") +
        ENTRY_PUNCT +
        cplen(p.title) +
        cplen(p.description),
      0,
    )
  );
}

/** @param {string} text @returns {Set<string>} */
function descTokens(text) {
  return new Set(text.toLowerCase().match(/[a-z0-9][a-z0-9._-]{2,}/g) ?? []);
}

/** @param {string} root @param {string[]} args @returns {string | null} */
function git(root, ...args) {
  try {
    return execFileSync("git", ["-C", root, ...args], {
      encoding: "utf-8",
      timeout: 30_000,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch {
    return null;
  }
}

/** @typedef {[no: number, slug: string | null, msg: string]} Finding */

/**
 * @param {string} root @param {Page[]} pages @param {string[]} orphans
 * @param {string[]} missing @param {string} gitBase
 * @returns {{findings: Finding[], projected: number}}
 */
function runChecks(root, pages, orphans, missing, gitBase) {
  /** @type {Finding[]} */
  const findings = [];
  /** @param {number} no @param {string | null} slug @param {string} msg */
  const add = (no, slug, msg) => findings.push([no, slug, msg]);
  /** @template T @returns {Map<T, string[]>} */
  const groupBy = (/** @type {(p: Page) => T} */ key) => {
    /** @type {Map<T, string[]>} */
    const m = new Map();
    for (const p of pages) {
      const k = key(p);
      m.set(k, [...(m.get(k) ?? []), p.slug]);
    }
    return m;
  };

  // 1: title + description present
  for (const p of pages) {
    if (!p.title) add(1, p.slug, "missing title");
    if (!p.description) add(1, p.slug, "missing description");
  }
  for (const slug of missing) {
    add(1, slug, "page in docs.json navigation has no .mdx file");
  }

  // 2: title globally unique (warn only - acceptable when og:title disambiguates)
  for (const [title, slugs] of [...groupBy((p) => p.title)].sort()) {
    if (slugs.length > 1) {
      add(
        2,
        null,
        `duplicate title '${title}' on ${slugs.length} pages: ${slugs.join(", ")}`,
      );
    }
  }

  // 19: effective unfurl title (og:title, falling back to title) globally
  // unique - the label search results, social cards, and AI citations show.
  for (const [eff, slugs] of [...groupBy((p) => p.ogTitle || p.title)].sort()) {
    if (slugs.length > 1) {
      add(
        19,
        null,
        `duplicate effective og:title '${eff}' on ${slugs.length} pages: ${slugs.join(", ")} - add a distinct "og:title" to disambiguate`,
      );
    }
  }

  // 3: title unique within a nav division (OG image identity)
  for (const [key, slugs] of [
    ...groupBy((p) => `${p.division} ${p.title}`),
  ].sort()) {
    if (slugs.length > 1) {
      const [div, title] = key.split(" ");
      add(
        3,
        null,
        `title '${title}' collides within division '${div}': ${slugs.join(", ")}`,
      );
    }
  }

  // 4: title length
  for (const p of pages) {
    const n = cplen(p.title);
    if (n > 60) add(4, p.slug, `title is ${n} chars (hard max 60)`);
    else if (n > 50) add(4, p.slug, `title is ${n} chars (target <= 50)`);
  }

  // 5: long title needs a sidebarTitle
  for (const p of pages) {
    if (cplen(p.title) > 30 && !p.sidebarTitle) {
      add(5, p.slug, `title is ${cplen(p.title)} chars with no sidebarTitle`);
    }
  }

  // 6: sidebarTitle must differ from title
  for (const p of pages) {
    if (p.sidebarTitle !== null && p.sidebarTitle === p.title) {
      add(6, p.slug, "sidebarTitle is identical to title (drop it)");
    }
  }

  // 7: description length band (50-160 hard, 110-140 target)
  for (const p of pages) {
    const n = cplen(p.description);
    if (!n) continue;
    if (n < 50 || n > 160) {
      add(7, p.slug, `description is ${n} chars (hard band 50-160)`);
    } else if (n < 110 || n > 140) {
      add(7, p.slug, `description is ${n} chars (target 110-140)`);
    }
  }

  // 8: description globally unique
  for (const [desc, slugs] of [...groupBy((p) => p.description)].sort()) {
    if (desc && slugs.length > 1) {
      add(
        8,
        null,
        `duplicate description on ${slugs.length} pages: ${slugs.join(", ")}`,
      );
    }
  }

  // 9: no brand suffix, no parentheses
  for (const p of pages) {
    if (/\s[-|–—]\s*Pipecat\s*$/.test(p.title)) {
      add(
        9,
        p.slug,
        `title '${p.title}' carries a brand suffix (Mintlify appends it)`,
      );
    }
    if (p.title.includes("(") && !GRANDFATHERED_PARENS.has(p.slug)) {
      add(9, p.slug, `title '${p.title}' contains parentheses`);
    }
  }

  // 10: >=2 distinctive (corpus DF < 10) tokens per description
  /** @type {Map<string, number>} */
  const df = new Map();
  for (const p of pages) {
    for (const t of descTokens(p.description)) df.set(t, (df.get(t) ?? 0) + 1);
  }
  for (const p of pages) {
    if (!p.description) continue;
    let distinctive = 0;
    for (const t of descTokens(p.description)) {
      if ((df.get(t) ?? 0) < 10) distinctive += 1;
    }
    if (distinctive < 2) {
      add(
        10,
        p.slug,
        `description has ${distinctive} distinctive token(s) (need >= 2)`,
      );
    }
  }

  // 11: modality acronym present in description
  for (const p of pages) {
    for (const [seg, accepted] of Object.entries(ACRONYMS)) {
      if (`/${p.slug}/`.includes(`/${seg}/`)) {
        if (!accepted.some((a) => p.description.includes(a))) {
          add(11, p.slug, `description lacks the acronym '${accepted[0]}'`);
        }
      }
    }
  }

  // 12: projected auto-generated llms.txt size. With a custom llms.txt in
  // place this is fallback-safety only (Mintlify auto-generation resumes if
  // the custom file is deleted), so only warn once the fallback would
  // actually truncate; without a custom file, warn early at AUTOGEN_WARN.
  const projected = projectedAutogenSize(pages);
  const projectionThreshold = existsSync(join(root, "llms.txt"))
    ? AUTOGEN_CAP
    : AUTOGEN_WARN;
  if (projected > projectionThreshold) {
    add(
      12,
      null,
      `projected auto-generated llms.txt is ${projected.toLocaleString("en-US")} chars ` +
        `(threshold ${projectionThreshold.toLocaleString("en-US")}, Mintlify truncates at ${AUTOGEN_CAP.toLocaleString("en-US")})`,
    );
  }

  // 13/14: custom llms.txt + llms-full.txt staleness, llms.txt size
  // (skipped until the files ship)
  const customPath = join(root, "llms.txt");
  if (existsSync(customPath)) {
    const genPath = join(root, "scripts", "gen-llms-txt.mjs");
    if (existsSync(genPath)) {
      /** @type {Array<[flag: string, file: string]>} */
      const outputs = [
        ["--stdout", "llms.txt"],
        ["--stdout-full", "llms-full.txt"],
      ];
      for (const [flag, file] of outputs) {
        try {
          const generated = execFileSync(process.execPath, [genPath, flag], {
            encoding: "utf-8",
            timeout: 30_000,
            maxBuffer: 64 * 1024 * 1024, // llms-full.txt is several MB
          });
          const onDisk = existsSync(join(root, file))
            ? readFileSync(join(root, file), "utf-8")
            : null;
          if (generated !== onDisk) {
            add(
              13,
              null,
              `${file} is ${onDisk === null ? "missing" : "stale"}: regenerate with scripts/gen-llms-txt.mjs`,
            );
          }
        } catch (e) {
          add(13, null, `gen-llms-txt.mjs failed: ${String(e).slice(0, 200)}`);
        }
      }
    } else {
      add(
        13,
        null,
        "custom llms.txt exists but scripts/gen-llms-txt.mjs is missing",
      );
    }
    const size = cplen(readFileSync(customPath, "utf-8"));
    if (size > CUSTOM_LLMS_WARN) {
      add(
        14,
        null,
        `custom llms.txt is ${size.toLocaleString("en-US")} chars (soft ceiling ${CUSTOM_LLMS_WARN.toLocaleString("en-US")})`,
      );
    }
  }

  // 15: openapi page count + url-stub values pinned
  const nOpenapi = pages.filter((p) => p.openapi).length;
  if (nOpenapi !== EXPECTED_OPENAPI_PAGES) {
    add(
      15,
      null,
      `openapi-backed pages: ${nOpenapi} (expected ${EXPECTED_OPENAPI_PAGES})`,
    );
  }
  const stubValues = new Map(
    pages.filter((p) => p.url).map((p) => [p.slug, p.url]),
  );
  const orphanSet = new Set(orphans);
  for (const [slug, expected] of Object.entries(EXPECTED_URL_STUBS)) {
    /** @type {string | null | undefined} */
    let actual;
    if (orphanSet.has(slug)) {
      // orphan stub is outside nav; check on disk
      const fm = existsSync(join(root, `${slug}.mdx`))
        ? parseFrontmatter(readFileSync(join(root, `${slug}.mdx`), "utf-8"))
        : null;
      actual = fm?.url ?? null;
    } else {
      actual = stubValues.get(slug);
      stubValues.delete(slug);
    }
    if (actual !== expected) {
      add(15, slug, `url stub changed: '${actual}' (expected '${expected}')`);
    }
  }
  for (const [slug, val] of stubValues) {
    add(15, slug, `unexpected new url stub: '${val}'`);
  }

  // 16: redirects unchanged vs git base
  const headDocs = git(root, "show", `${gitBase}:docs.json`);
  if (headDocs !== null) {
    const oldR = JSON.parse(headDocs).redirects ?? [];
    const newR =
      JSON.parse(readFileSync(join(root, "docs.json"), "utf-8")).redirects ??
      [];
    if (JSON.stringify(oldR) !== JSON.stringify(newR)) {
      add(
        16,
        null,
        `docs.json redirects changed vs ${gitBase} ` +
          `(${oldR.length} -> ${newR.length} entries); split redirect edits into their own PR`,
      );
    }
  }

  // 17: no .mdx renames or deletes vs git base
  const status = git(root, "diff", "--name-status", gitBase, "--", "*.mdx");
  if (status) {
    for (const line of status.trim().split("\n")) {
      if (line && "RD".includes(line[0])) {
        add(17, null, `.mdx rename/delete vs ${gitBase}: ${line}`);
      }
    }
  }

  return { findings, projected };
}

async function calibrate() {
  const res = await fetch(BASE_URL + "llms.txt");
  const text = await res.text();
  const lines = text.split("\n");
  /** @type {Map<string, number>} */
  const sections = new Map();
  lines.forEach((l, i) => {
    if (l.startsWith("## ")) sections.set(l.slice(3), i);
  });
  const start = sections.get("Docs") ?? 0;
  const end = Math.min(
    ...[...sections.values()].filter((i) => i > start),
    lines.length,
  );
  let predicted = FIXED_OVERHEAD;
  let count = 0;
  lines.forEach((l, i) => {
    if (i <= start || i >= end) return;
    const m = l.match(LLMS_ENTRY_RE);
    if (!m) return;
    count += 1;
    predicted += cplen(m[2]) + ENTRY_PUNCT + cplen(m[1]) + cplen(m[3] ?? "");
  });
  const actual = cplen(text);
  const drift = predicted - actual;
  const ok = Math.abs(drift) <= 2;
  console.log(
    `live llms.txt: ${actual.toLocaleString("en-US")} chars, ${count} docs entries`,
  );
  console.log(
    `model predicts: ${predicted.toLocaleString("en-US")} chars (drift ${drift >= 0 ? "+" : ""}${drift}) ` +
      `[FIXED_OVERHEAD=${FIXED_OVERHEAD}, ENTRY_PUNCT=${ENTRY_PUNCT}]`,
  );
  console.log(
    ok
      ? "calibration OK"
      : "calibration FAILED: Mintlify's llms.txt format changed - re-measure the constants",
  );
  return ok;
}

/** @param {Page[]} pages @param {string[]} orphans @param {number} projected */
function metricsOf(pages, orphans, projected) {
  const tl = pages.map((p) => cplen(p.title));
  const dl = pages.map((p) => cplen(p.description));
  /** @param {Map<any, number>} c */
  const dupStats = (c) => {
    let values = 0;
    let members = 0;
    for (const n of c.values()) {
      if (n > 1) {
        values += 1;
        members += n;
      }
    }
    return { values, members };
  };
  /** @template T @param {(p: Page) => T} key @returns {Map<T, number>} */
  const countBy = (key) => {
    /** @type {Map<T, number>} */
    const m = new Map();
    for (const p of pages) {
      const k = key(p);
      m.set(k, (m.get(k) ?? 0) + 1);
    }
    return m;
  };
  const sum = (/** @type {number[]} */ xs) => xs.reduce((a, b) => a + b, 0);
  const titleDup = dupStats(countBy((p) => p.title));
  const descDup = dupStats(
    countBy((p) => p.description || ` ${p.slug}`), // empty descs never group
  );
  const divDup = dupStats(countBy((p) => `${p.division} ${p.title}`));
  return {
    pages: pages.length,
    dup_title_values: titleDup.values,
    pages_in_dup_title_groups: titleDup.members,
    same_division_collisions: divDup.values,
    dup_desc_values: descDup.values,
    pages_in_dup_desc_groups: descDup.members,
    title_mean: Math.round((sum(tl) / tl.length) * 10) / 10,
    title_max: Math.max(...tl),
    desc_mean: Math.round((sum(dl) / dl.length) * 10) / 10,
    desc_max: Math.max(...dl),
    desc_under_50: dl.filter((n) => n < 50).length,
    desc_under_70: dl.filter((n) => n < 70).length,
    desc_over_160: dl.filter((n) => n > 160).length,
    pages_with_sidebar_title: pages.filter((p) => p.sidebarTitle).length,
    title_desc_total: sum(tl) + sum(dl),
    projected_autogen_llms_txt: projected,
    orphans,
  };
}

const fmtInt = (/** @type {number} */ n) => n.toLocaleString("en-US");

/**
 * @param {ReturnType<typeof metricsOf>} m @param {Finding[]} findings
 * @param {boolean} verbose @param {boolean} gh
 */
function printReport(m, findings, verbose, gh) {
  const errors = findings.filter(([no]) => ENFORCED.has(no));
  const warns = findings.filter(([no]) => !ENFORCED.has(no));
  const pad = (/** @type {number} */ n) => fmtInt(n).padStart(7);
  console.log(`docs_meta_lint - ${m.pages} nav pages\n`);
  console.log("UNIQUENESS");
  console.log(
    `  duplicate title values        ${pad(m.dup_title_values)}     (${m.pages_in_dup_title_groups} pages)`,
  );
  console.log(
    `  same-division collisions      ${pad(m.same_division_collisions)}`,
  );
  console.log(
    `  duplicate description values  ${pad(m.dup_desc_values)}     (${m.pages_in_dup_desc_groups} pages)`,
  );
  console.log("LENGTH");
  console.log(`  title mean ${m.title_mean}  max ${m.title_max}`);
  console.log(`  description mean ${m.desc_mean}  max ${m.desc_max}`);
  console.log(
    `  descriptions < 70 chars       ${pad(m.desc_under_70)}     (< 50: ${m.desc_under_50}, > 160: ${m.desc_over_160})`,
  );
  console.log(
    `  pages with sidebarTitle       ${pad(m.pages_with_sidebar_title)}     (${m.pages - m.pages_with_sidebar_title} pages would have their sidebar label rewritten by a title edit)`,
  );
  console.log("BUDGET");
  console.log(
    `  projected auto-gen llms.txt   ${pad(m.projected_autogen_llms_txt)} / ${fmtInt(AUTOGEN_CAP)} cap  (warn ${fmtInt(AUTOGEN_WARN)})`,
  );
  console.log("INTEGRITY");
  const integrity = findings.filter(([no]) => [13, 15, 16, 17].includes(no));
  console.log(
    `  ${integrity.length === 0 ? "ok" : `${integrity.length} finding(s)`}   orphans ${m.orphans.length}` +
      (m.orphans.length ? ` (${m.orphans.join(", ")})  [pre-existing]` : ""),
  );
  if (verbose || errors.length) {
    const shown = verbose ? findings : errors;
    console.log("");
    for (const [no, slug, msg] of shown) {
      const level = ENFORCED.has(no) ? "ERROR" : "WARN ";
      const loc = slug ? `${slug}.mdx: ` : "";
      console.log(`  ${level} [check ${String(no).padStart(2)}] ${loc}${msg}`);
    }
  }
  if (gh) {
    for (const [no, slug, msg] of findings) {
      const level = ENFORCED.has(no) ? "error" : "warning";
      const f = slug ? ` file=${slug}.mdx` : "";
      console.log(`::${level}${f}::check ${no}: ${msg}`);
    }
  }
  console.log(`\n${warns.length} warnings, ${errors.length} errors`);
  return errors.length;
}

/**
 * @param {{metrics: Record<string, any>, pages: Page[]}} baseline
 * @param {ReturnType<typeof metricsOf>} m @param {Page[]} pages
 */
function printCompare(baseline, m, pages) {
  const keys = /** @type {const} */ ([
    "dup_title_values",
    "pages_in_dup_title_groups",
    "same_division_collisions",
    "dup_desc_values",
    "desc_under_70",
    "desc_under_50",
    "desc_over_160",
    "pages_with_sidebar_title",
    "title_desc_total",
    "projected_autogen_llms_txt",
  ]);
  const bm = baseline.metrics;
  console.log(
    `${"metric".padEnd(32)} ${"before".padStart(10)} ${"after".padStart(10)} ${"delta".padStart(8)}`,
  );
  for (const k of keys) {
    const b = bm[k];
    const a = /** @type {Record<string, any>} */ (m)[k];
    const d = a - b;
    const delta = (d >= 0 ? "+" : "") + fmtInt(d);
    console.log(
      `${k.padEnd(32)} ${fmtInt(b).padStart(10)} ${fmtInt(a).padStart(10)} ${delta.padStart(8)}`,
    );
  }
  const old = new Map(baseline.pages.map((p) => [p.slug, p]));
  /** @type {Array<[string, string, string]>} */
  const changed = [];
  for (const p of pages) {
    const prev = old.get(p.slug);
    if (!prev) continue;
    const ol = prev.sidebarTitle || prev.title;
    const nl = p.sidebarTitle || p.title;
    if (ol !== nl) changed.push([p.slug, ol, nl]);
  }
  if (changed.length) {
    console.log(`\nsidebar labels changed (${changed.length}) - review each:`);
    console.log("slug,old_label,new_label");
    for (const [slug, ol, nl] of changed) {
      console.log(`${slug},"${ol}","${nl}"`);
    }
  } else {
    console.log("\nsidebar labels: no changes");
  }
}

async function main() {
  const argv = process.argv.slice(2);
  /** @param {string} flag */
  const has = (flag) => argv.includes(flag);
  /** @param {string} flag @returns {string | undefined} */
  const opt = (flag) => {
    const i = argv.indexOf(flag);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const root = resolve(
    opt("--root") ?? join(dirname(fileURLToPath(import.meta.url)), ".."),
  );
  const gitBase = opt("--git-base") ?? "HEAD";

  // Note: set process.exitCode rather than calling process.exit() — exit()
  // truncates piped stdout that hasn't flushed yet (large --json output).
  if (has("--calibrate")) {
    process.exitCode = (await calibrate()) ? 0 : 1;
    return;
  }

  const { pages, orphans, missing } = loadPages(root);
  const { findings, projected } = runChecks(
    root,
    pages,
    orphans,
    missing,
    gitBase,
  );
  const m = metricsOf(pages, orphans, projected);
  const hasErrors = findings.some(([no]) => ENFORCED.has(no));

  if (has("--json")) {
    console.log(JSON.stringify({ metrics: m, pages }, null, 1));
    process.exitCode = hasErrors ? 1 : 0;
    return;
  }
  const comparePath = opt("--compare");
  if (comparePath) {
    const baseline = JSON.parse(readFileSync(comparePath, "utf-8"));
    printCompare(baseline, m, pages);
    console.log("");
  }
  const errors = printReport(
    m,
    findings,
    has("--verbose"),
    opt("--format") === "github",
  );
  process.exitCode = errors ? 1 : 0;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 2;
});
