#!/usr/bin/env node

// Compare these public schemas with actual API serialization. Use an API
// checkout containing the eval contract, with its dependencies installed:
// node scripts/check-cloud-eval-responses.mjs /path/to/sandbox/api
//
// Ajv supports OAS 3.0 nullable, including enum constraints:
// https://ajv.js.org/json-schema.html#nullable-openapi
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const apiRoot = process.argv[2];
if (!apiRoot) {
  throw new Error(
    "Usage: node scripts/check-cloud-eval-responses.mjs API_ROOT",
  );
}
const apiRequire = createRequire(path.resolve(apiRoot, "package.json"));
apiRequire("ts-node").register({
  project: path.resolve(apiRoot, "tsconfig.test.json"),
  transpileOnly: true,
});
const { default: Ajv } = apiRequire("ajv");
const { parse: parseYaml } = apiRequire("yaml");
const { evalRunSummary, evalRunView } = apiRequire(
  "./src/services/evals/view.ts",
);
const { verdictOfEnd } = apiRequire("./src/services/evals/runs.ts");
const { evalOutcome } = apiRequire("./test/helpers/evalOutcomes.ts");
const { evalSuiteRunView } = apiRequire("./src/services/evalSuites/view.ts");
const {
  evalBundleView,
  evalBundleRevisionSummary,
  evalBundleRevisionView,
  evalBundleRevisionDetail,
} = apiRequire("./src/services/evalBundles/view.ts");
const { organizationEvalDiscovery, agentEvalCapabilities } = apiRequire(
  "./src/services/evals/availability.ts",
);
const {
  EVAL_CAPABILITY_AUDIO,
  EVAL_CAPABILITY_BUNDLE_CHECK,
  EVAL_CAPABILITY_CONVERSATION_REF,
} = apiRequire("./src/services/evalExecutor/contract.ts");
const docsRoot = fileURLToPath(new URL("../", import.meta.url));
const document = JSON.parse(
  readFileSync(
    path.join(
      docsRoot,
      "api-reference/pipecat-cloud/rest-reference/openapi.json",
    ),
    "utf8",
  ),
);
const apiDocument = parseYaml(
  readFileSync(path.resolve(apiRoot, "src/docs/oas.yaml"), "utf8"),
);

// OAS 3.0 uses boolean exclusive bounds; Ajv uses draft-7 numeric bounds.
// Preserve nullable enums and composition so invalid null responses fail.
function jsonSchemaBounds(value) {
  if (!value || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map(jsonSchemaBounds);
  const result = Object.fromEntries(
    Object.entries(value).map(([key, child]) => [key, jsonSchemaBounds(child)]),
  );
  for (const [exclusive, bound] of [
    ["exclusiveMinimum", "minimum"],
    ["exclusiveMaximum", "maximum"],
  ]) {
    if (typeof result[exclusive] === "boolean") {
      if (result[exclusive]) result[exclusive] = result[bound];
      else delete result[exclusive];
    }
  }
  return result;
}

const ajv = new Ajv({ strict: false, allErrors: true, validateFormats: false });
function validator(schema, components = document.components) {
  return ajv.compile({
    components: jsonSchemaBounds(components),
    ...schema,
  });
}
// Each named schema, compiled against the public reference and against the
// API's own contract, so a response must satisfy both.
const compiled = new Map();
function validators(name) {
  if (!compiled.has(name)) {
    const ref = { $ref: `#/components/schemas/${name}` };
    compiled.set(name, [
      ["public", validator(ref)],
      ["API", validator(ref, apiDocument.components)],
    ]);
  }
  return compiled.get(name);
}
// Responses are checked as a client reads them: JSON, with Dates as strings.
function asJson(value) {
  return JSON.parse(JSON.stringify(value));
}
let validated = 0;
function check(name, value, label, { api = true } = {}) {
  const body = asJson(value);
  for (const [which, validate] of validators(name)) {
    if (which === "API" && !api) continue;
    assert.equal(
      validate(body),
      true,
      `${label} (${which} ${name}): ${ajv.errorsText(validate.errors)}`,
    );
  }
  validated += 1;
  return body;
}

// Every route the API documents for evals is public, with the same methods
// and status codes, except the organization-wide run list and read.
const NOT_PUBLIC = new Set([
  "/organizations/{organizationName}/eval-runs",
  "/organizations/{organizationName}/eval-runs/{runId}",
]);
const METHODS = ["get", "post", "put", "patch", "delete"];
const responsesOf = (operation) => Object.keys(operation.responses).sort();
let routes = 0;
for (const [apiPath, apiItem] of Object.entries(apiDocument.paths)) {
  if (!/eval-/.test(apiPath) || NOT_PUBLIC.has(apiPath)) continue;
  const publicPath = apiPath.replace("{serviceName}", "{agentName}");
  const item = document.paths[publicPath];
  assert.ok(item, `The public reference is missing ${publicPath}`);
  for (const method of METHODS) {
    assert.equal(
      Boolean(item[method]),
      Boolean(apiItem[method]),
      `${method.toUpperCase()} ${publicPath}: public and API methods differ`,
    );
    if (!apiItem[method]) continue;
    assert.deepEqual(
      responsesOf(item[method]),
      responsesOf(apiItem[method]),
      `${method.toUpperCase()} ${publicPath}: status codes differ`,
    );
    routes += 1;
  }
}

// Every schema both documents describe has the same fields, and the same
// required ones, after following references and allOf.
function shapeOf(schema, components, seen = new Set()) {
  if (schema.$ref) {
    const name = schema.$ref.split("/").pop();
    if (seen.has(name)) return { properties: new Set(), required: new Set() };
    return shapeOf(
      components.schemas[name],
      components,
      new Set([...seen, name]),
    );
  }
  const properties = new Set(Object.keys(schema.properties ?? {}));
  const required = new Set(schema.required ?? []);
  for (const part of schema.allOf ?? []) {
    const inner = shapeOf(part, components, seen);
    inner.properties.forEach((p) => properties.add(p));
    inner.required.forEach((p) => required.add(p));
  }
  return { properties, required };
}
let schemas = 0;
for (const name of Object.keys(document.components.schemas)) {
  if (!(name in apiDocument.components.schemas)) continue;
  const mine = shapeOf(
    { $ref: `#/components/schemas/${name}` },
    document.components,
  );
  const theirs = shapeOf(
    { $ref: `#/components/schemas/${name}` },
    apiDocument.components,
  );
  assert.deepEqual(
    [...mine.properties].sort(),
    [...theirs.properties].sort(),
    `Schema ${name}: public and API fields differ`,
  );
  assert.deepEqual(
    [...mine.required].sort(),
    [...theirs.required].sort(),
    `Schema ${name}: public and API required fields differ`,
  );
  schemas += 1;
}

// The guide's JSON examples are titled by what they show.
const GUIDE_EXAMPLES = {
  "eval-run.json": "EvalRun",
  "suite-run.json": "EvalSuiteRun",
  "eval-capabilities.json": "OrganizationEvalDiscovery",
};
const guide = readFileSync(
  path.join(docsRoot, "pipecat-cloud/guides/evals.mdx"),
  "utf8",
);
const guideExamples = [
  ...guide.matchAll(/^```json(?:[ \t]([^\r\n]*))?\r?\n([\s\S]*?)^```[ \t]*$/gm),
];
assert.ok(
  guideExamples.length > 0,
  "The evals guide must contain a response JSON example.",
);
const shown = new Set();
for (const match of guideExamples) {
  const line = guide.slice(0, match.index).split("\n").length;
  const title = (match[1] ?? "").trim();
  const name = GUIDE_EXAMPLES[title];
  assert.ok(
    name,
    `Guide JSON at line ${line}: title it one of ${Object.keys(GUIDE_EXAMPLES).join(", ")}`,
  );
  shown.add(title);
  const example = check(
    name,
    JSON.parse(match[2]),
    `Guide JSON at line ${line}`,
  );
  // A full run response always includes params, even when no overrides were
  // requested; OAS currently does not mark this serializer field required.
  if (name === "EvalRun") {
    assert.ok(
      Object.hasOwn(example, "params"),
      `Guide JSON at line ${line}: missing params`,
    );
  }
}
assert.deepEqual(
  [...shown].sort(),
  Object.keys(GUIDE_EXAMPLES).sort(),
  "The evals guide must show each kind of example.",
);

// Eval runs, through the API's own serializer.
const base = "/organizations/{organizationName}/services/{agentName}/eval-runs";
const cancel = document.paths[`${base}/{runId}/cancel`].post;
const validateDetail = validator(
  cancel.responses["200"].content["application/json"].schema,
);
const validatePage = validator(
  document.paths[base].get.responses["200"].content["application/json"].schema,
);
const createdAt = new Date("2026-11-05T12:00:00.000Z");
const startedAt = new Date("2026-11-05T12:00:04.000Z");
const finishedAt = new Date("2026-11-05T12:01:30.000Z");
const FINGERPRINT = `jfp1:${"a".repeat(64)}`;
const OTHER_FINGERPRINT = `jfp1:${"b".repeat(64)}`;
function row(overrides = {}) {
  return {
    id: "0b9f0c3e-6a51-4c7e-9d0a-3f5e2b1c4d6a",
    organizationId: "11111111-1111-4111-8111-111111111111",
    serviceId: "22222222-2222-4222-8222-222222222222",
    region: "us-west",
    kind: "synthetic",
    status: "queued",
    bundle: { "scenario.yaml": "name: scenario" },
    bundleRevisionId: "33333333-3333-4333-8333-333333333333",
    scenarioPath: "scenario.yaml",
    scenarioName: "scenario",
    params: {},
    sessionId: null,
    executorRunId: null,
    attempts: 0,
    sessionsStarted: 0,
    deadlineAt: new Date("2026-11-05T12:30:00.000Z"),
    outcome: null,
    verdict: null,
    startedAt: null,
    finishedAt: null,
    cancelRequestedAt: null,
    createdAt,
    updatedAt: createdAt,
    ...overrides,
  };
}
function audioOutcome(fixture, kind) {
  const outcome = evalOutcome(fixture);
  outcome.error = kind;
  if (fixture.startsWith("script")) {
    outcome.details.failures = [
      {
        turn_index: -1,
        expectation_index: -1,
        event_name: "<audio>",
        reason: "Pipecat's words",
        kind,
      },
    ];
  }
  return outcome;
}
const cases = [
  ...["queued", "starting", "running"].map((status) => [
    status,
    row({ status, startedAt: status === "queued" ? null : startedAt }),
  ]),
  ["error", row({ status: "error", startedAt, finishedAt })],
  [
    "queued cancellation",
    row({ status: "cancelled", cancelRequestedAt: finishedAt, finishedAt }),
  ],
  [
    "started cancellation",
    row({
      status: "cancelled",
      startedAt,
      cancelRequestedAt: finishedAt,
      finishedAt,
    }),
  ],
  ...["synthetic", "session"].map((kind) => [
    `unconfirmed ${kind} cancellation`,
    row({
      kind,
      sessionId:
        kind === "session" ? "5b0f7f0e-3a36-4c1f-9d0a-1e2f3a4b5c6d" : null,
      status: "cancelled",
      startedAt,
      cancelRequestedAt: finishedAt,
      finishedAt,
      outcome: { error: "cancellation_unconfirmed" },
    }),
  ]),
  ...["script-pass", "judged-call-fail"].map((fixture) => {
    const outcome = evalOutcome(fixture);
    return [
      fixture,
      row({
        status: "completed",
        startedAt,
        finishedAt,
        outcome,
        verdict: verdictOfEnd("completed", outcome),
      }),
    ];
  }),
  [
    "suite member",
    row({
      status: "completed",
      startedAt,
      finishedAt,
      outcome: evalOutcome("simulation-pass"),
      verdict: verdictOfEnd("completed", evalOutcome("simulation-pass")),
      suiteRunId: "44444444-4444-4444-8444-444444444444",
      suiteMemberOrdinal: 3,
      executorFingerprint: FINGERPRINT,
      executorBuild: "0123456789abcdef0123456789abcdef01234567",
    }),
  ],
  ...["script-target-unavailable", "judged-call-no-verdict"].map((fixture) => [
    `audio_unsupported (${fixture})`,
    row({
      status: "error",
      startedAt,
      finishedAt,
      outcome: audioOutcome(fixture, "audio_unsupported"),
    }),
  ]),
  // A run stored before the audio check read bot-ready can still carry
  // audio_unverified; it must still read as a valid run, with no other claim.
  [
    "stored audio_unverified run",
    row({
      status: "error",
      startedAt,
      finishedAt,
      outcome: audioOutcome("judged-call-no-verdict", "audio_unverified"),
    }),
  ],
];
for (const [name, source] of cases) {
  const response = evalRunView(source, (message) => {
    throw new Error(message);
  });
  assert.equal(
    validateDetail(response),
    true,
    `${name}: ${ajv.errorsText(validateDetail.errors)}`,
  );
  check("EvalRun", response, name);
  assert.equal(
    validatePage({ total_count: 1, runs: [evalRunSummary(source)] }),
    true,
    `${name} page: ${ajv.errorsText(validatePage.errors)}`,
  );
  assert.doesNotMatch(
    JSON.stringify(response),
    /cancelRequestedAt|sessionsStarted|cancellation_unconfirmed/,
  );
  if (name.startsWith("unconfirmed"))
    assert.match(response.result.reason, /may continue until its deadline/);
  // The guide's account of an audio_unsupported run, scripted or simulated:
  // no verdict, the setting to change named in the reason, and the failure
  // kind first.
  if (name.startsWith("audio_unsupported")) {
    assert.equal(response.verdict, null, `${name}: has a verdict`);
    assert.match(response.result.reason, /audio_in_enabled/);
    assert.match(response.result.reason, /audio_out_enabled/);
    assert.equal(response.result.details.failures[0].kind, "audio_unsupported");
  }
  if (name === "suite member") {
    assert.deepEqual(response.executor, {
      fingerprint: FINGERPRINT,
      build: "0123456789abcdef0123456789abcdef01234567",
    });
    assert.equal(response.suiteMemberOrdinal, 3);
  }
}
assert.equal(
  validateDetail({ ...evalRunView(row(), () => {}), verdict: "unknown" }),
  false,
);
assert.deepEqual(Object.keys(cancel.responses), [
  "200",
  "400",
  "404",
  "409",
  "413",
  "415",
  "503",
]);
assert.equal(cancel.responses["200"].headers, undefined);

// Suite runs, through the API's own serializer, in every state a client can
// read one in.
function suiteRow(overrides = {}) {
  return {
    id: "55555555-5555-4555-8555-555555555555",
    organizationId: "11111111-1111-4111-8111-111111111111",
    serviceId: "22222222-2222-4222-8222-222222222222",
    region: "us-west",
    bundleRevisionId: "33333333-3333-4333-8333-333333333333",
    request: {
      target: { kind: "suite", suitePath: "suite.yaml" },
      filters: null,
      repeat: { requested: null, suite: null, effective: null },
      concurrency: { requested: null, suite: 2, effective: 2 },
      deadlineSeconds: 43200,
    },
    entries: [
      { index: 0, label: "baseline", concurrency: null, body: null },
      { index: 1, label: "vip-caller", concurrency: 1, body: { path: null } },
      { index: 2, label: "", concurrency: null, body: { path: "body.json" } },
    ],
    memberCount: 4,
    repeat: null,
    measurement: false,
    concurrency: 2,
    status: "queued",
    deadlineAt: new Date("2026-11-06T00:00:00.000Z"),
    deploymentId: "66666666-6666-4666-8666-666666666666",
    cancelRequestedAt: null,
    stopCause: null,
    stoppedAt: null,
    stopDetail: null,
    fingerprint: null,
    mixed: false,
    createdAt,
    updatedAt: createdAt,
    startedAt: null,
    finishedAt: null,
    ...overrides,
  };
}
const NONE = { admitted: 0, live: 0, passed: 0, failed: 0, skipped: 0 };
function rate(scenarioName, fingerprint, passed, failed) {
  return {
    entry: 0,
    label: "baseline",
    scenarioPath: "greet.yaml",
    scenarioName,
    fingerprint,
    passed,
    failed,
    skipped: 0,
    withoutVerdict: 0,
    passRate: passed + failed === 0 ? null : passed / (passed + failed),
  };
}
const measured = {
  request: {
    target: {
      kind: "scenarios",
      scenarioPath: "greet.yaml",
      scenarioNames: ["hello"],
    },
    filters: { kinds: ["simulation"] },
    repeat: { requested: 2, suite: null, effective: 2 },
    concurrency: { requested: 1, suite: null, effective: 1 },
    deadlineSeconds: 3600,
  },
  measurement: true,
  repeat: 2,
};
const ended = { startedAt, finishedAt };
const suiteCases = [
  ["queued suite run", suiteRow(), NONE, null],
  [
    "running suite run",
    suiteRow({ status: "running", startedAt }),
    { ...NONE, admitted: 2, live: 1, passed: 1 },
    null,
  ],
  [
    "passed suite run",
    suiteRow({ status: "completed", ...ended, fingerprint: FINGERPRINT }),
    { ...NONE, admitted: 4, passed: 3, skipped: 1 },
    null,
  ],
  [
    "failed suite run, mixed",
    suiteRow({
      status: "completed",
      ...ended,
      fingerprint: FINGERPRINT,
      mixed: true,
    }),
    { ...NONE, admitted: 4, passed: 3, failed: 1 },
    null,
  ],
  [
    "completed suite run without a verdict",
    suiteRow({ status: "completed", ...ended, fingerprint: FINGERPRINT }),
    { ...NONE, admitted: 4, passed: 3 },
    null,
  ],
  [
    "skipped suite run",
    suiteRow({ status: "completed", ...ended, fingerprint: FINGERPRINT }),
    { ...NONE, admitted: 4, skipped: 4 },
    null,
  ],
  [
    "measurement",
    suiteRow({
      ...measured,
      status: "completed",
      ...ended,
      fingerprint: FINGERPRINT,
    }),
    { ...NONE, admitted: 4, passed: 1, failed: 3 },
    [rate("hello", null, 1, 3)],
  ],
  [
    "mixed measurement",
    suiteRow({
      ...measured,
      status: "completed",
      ...ended,
      fingerprint: FINGERPRINT,
      mixed: true,
    }),
    { ...NONE, admitted: 4, passed: 2, failed: 2 },
    [rate("hello", FINGERPRINT, 1, 1), rate("hello", OTHER_FINGERPRINT, 1, 1)],
  ],
  [
    "cancelled suite run",
    suiteRow({
      status: "cancelled",
      ...ended,
      cancelRequestedAt: finishedAt,
      stopCause: "cancelled",
      stoppedAt: finishedAt,
    }),
    { ...NONE, admitted: 1, passed: 1 },
    null,
  ],
  [
    "expired suite run",
    suiteRow({
      status: "expired",
      ...ended,
      stopCause: "expired",
      stoppedAt: finishedAt,
    }),
    { ...NONE, admitted: 2, failed: 1 },
    null,
  ],
  ...[
    [
      "deployment_changed",
      {
        expectedDeploymentId: "66666666-6666-4666-8666-666666666666",
        deploymentId: "77777777-7777-4777-8777-777777777777",
        memberOrdinal: null,
      },
    ],
    [
      "deployment_changed",
      {
        expectedDeploymentId: "66666666-6666-4666-8666-666666666666",
        deploymentId: "77777777-7777-4777-8777-777777777777",
        memberOrdinal: 2,
      },
    ],
    [
      "deployment_unknown",
      {
        expectedDeploymentId: "66666666-6666-4666-8666-666666666666",
        memberOrdinal: 1,
      },
    ],
    ["revision_unavailable", null],
  ].map(([cause, stopDetail]) => [
    `${cause} suite run`,
    suiteRow({
      status: "error",
      ...ended,
      stopCause: cause,
      stopDetail,
      stoppedAt: finishedAt,
    }),
    { ...NONE, admitted: 2, passed: 1 },
    null,
  ]),
];
const suiteRunBodies = [];
for (const [name, source, tally, passRates] of suiteCases) {
  const view = check(
    "EvalSuiteRun",
    evalSuiteRunView(source, "my-agent", { tally, passRates }),
    name,
  );
  suiteRunBodies.push(view);
  const { counts } = view;
  assert.equal(
    counts.pending + counts.live + counts.terminal,
    counts.planned,
    name,
  );
  assert.equal(
    counts.passed + counts.failed + counts.skipped + counts.withoutVerdict,
    counts.terminal,
    name,
  );
  if (source.status === "error") assert.ok(view.error, `${name}: no error`);
  if (source.measurement) assert.equal(view.verdict, null, name);
  // The guide's verdict table.
  if (name === "passed suite run") assert.equal(view.verdict, "passed");
  if (name.startsWith("failed suite run")) assert.equal(view.verdict, "failed");
  if (name === "completed suite run without a verdict") {
    assert.equal(view.counts.withoutVerdict, 1, name);
    assert.equal(view.verdict, null, name);
  }
  if (name === "skipped suite run") assert.equal(view.verdict, "skipped");
  if (name === "mixed measurement") {
    assert.equal(view.mixed, true);
    assert.ok(view.passRates.every((r) => r.fingerprint !== null));
  }
}
// A list shows no pass rates.
check(
  "EvalSuiteRunPage",
  {
    total: suiteRunBodies.length,
    limit: 10,
    offset: 0,
    suiteRuns: suiteCases.map(([, source, tally]) =>
      evalSuiteRunView(source, "my-agent", { tally, passRates: null }),
    ),
  },
  "suite run page",
);
check(
  "EvalSuiteMemberPage",
  {
    total: 2,
    limit: 100,
    offset: 0,
    items: [
      {
        ordinal: 0,
        entry: 0,
        label: "baseline",
        scenarioPath: "greet.yaml",
        scenarioName: "hello",
        kind: "simulation",
        attempt: 1,
        evalRunId: "0b9f0c3e-6a51-4c7e-9d0a-3f5e2b1c4d6a",
      },
      {
        ordinal: 1,
        entry: 0,
        label: "baseline",
        scenarioPath: "greet.yaml",
        scenarioName: "hello",
        kind: "simulation",
        attempt: 2,
        evalRunId: null,
      },
    ],
  },
  "suite member page",
);

// Bundles and revisions, through the API's own serializer: a bundle's
// revision, and the anonymous revision an inline run's files are kept as.
const revisionCreatedAt = new Date("2026-11-05T11:00:00.000Z");
const named = {
  id: "33333333-3333-4333-8333-333333333333",
  organizationId: "11111111-1111-4111-8111-111111111111",
  bundleId: "88888888-8888-4888-8888-888888888888",
  number: 2,
  files: {
    "suite.yaml":
      "kind: suite\nschemaVersion: 1\nsuite:\n  - scenarios: [greet.yaml]\n",
    "greet.yaml": "name: greet\nscenarios:\n  - name: hello\n",
  },
  digest: `sha256+jcs-v1:${"c".repeat(64)}`,
  catalog: {
    suites: [
      {
        path: "suite.yaml",
        entries: [
          { label: "", selections: [{ path: "greet.yaml", name: "hello" }] },
        ],
      },
    ],
    scenarioFiles: {
      "greet.yaml": [{ name: "hello", kind: "simulation", runs: 1 }],
    },
    fragments: [],
    bodies: {},
  },
  coverage: "structural",
  checker: {
    region: "us-west",
    policyVersion: 1,
    harnessVersion: "1.16.0",
    ignored: [{ file: "greet.yaml", scenario: "hello", key: "user.voice" }],
    ignoredTotal: 1,
  },
  requestId: "99999999-9999-4999-8999-999999999999",
  requestFingerprint: "x",
  purgedAt: null,
  createdAt: revisionCreatedAt,
};
const anonymous = {
  ...named,
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  bundleId: null,
  number: null,
  catalog: null,
  coverage: "selection",
  checker: null,
  requestId: null,
};
const bundle = {
  id: named.bundleId,
  name: "support-evals",
  createdAt: revisionCreatedAt,
  updatedAt: revisionCreatedAt,
  deletedAt: null,
};
const latest = evalBundleRevisionSummary(named);
check("EvalBundle", evalBundleView(bundle, latest), "bundle");
check(
  "EvalBundlePage",
  { total_count: 1, bundles: [evalBundleView(bundle, latest)] },
  "bundle page",
);
check(
  "EvalBundleRevisionPage",
  { total_count: 1, revisions: [latest] },
  "revision page",
);
check(
  "EvalBundleCreated",
  {
    bundle: evalBundleView(bundle, latest),
    revision: evalBundleRevisionView(named, null),
  },
  "created bundle",
);
for (const [name, revision, deletedAt] of [
  ["revision", named, null],
  ["deleted bundle's revision", named, finishedAt],
  ["anonymous revision", anonymous, null],
]) {
  check(
    "EvalBundleRevision",
    evalBundleRevisionView(revision, deletedAt),
    name,
  );
  check(
    "EvalBundleRevisionDetail",
    evalBundleRevisionDetail(revision, deletedAt),
    name,
  );
}

// Capabilities, through the API's own discovery, in each state it answers.
const ON = { EVALS: "enabled", EVAL_SUITES: "enabled" };
function executor(readiness) {
  return () => ({
    kind: "resolved",
    client: {
      readiness: async () => {
        if (readiness instanceof Error) throw readiness;
        return readiness;
      },
    },
  });
}
const ready = (capabilities) => ({ kind: "ready", capabilities });
const capabilityCases = [
  ["evals off", undefined, {}, executor(ready([]))],
  ["suspended", { suspended: true }, ON, executor(ready([]))],
  ["no region", undefined, ON, () => ({ kind: "region_not_supported" })],
  ["misconfigured", undefined, ON, () => ({ kind: "endpoint_misconfigured" })],
  ["not ready", undefined, ON, executor({ kind: "not_ready" })],
  ["failing", undefined, ON, executor(new Error("down"))],
  ["text only", undefined, ON, executor(ready([]))],
  [
    "everything",
    undefined,
    ON,
    executor(
      ready([
        EVAL_CAPABILITY_AUDIO,
        EVAL_CAPABILITY_CONVERSATION_REF,
        EVAL_CAPABILITY_BUNDLE_CHECK,
      ]),
    ),
  ],
];
let regions = 0;
for (const [name, properties, env, resolveExecutor] of capabilityCases) {
  check(
    "OrganizationEvalDiscovery",
    await organizationEvalDiscovery(properties, env, {
      resolveExecutor,
      checkRegion: () => `check-region-${(regions += 1)}`,
    }),
    `organization: ${name}`,
  );
  check(
    "AgentEvalCapabilities",
    await agentEvalCapabilities(
      "11111111-1111-4111-8111-111111111111",
      "us-west",
      properties,
      env,
      { resolveExecutor },
    ),
    `agent: ${name}`,
  );
}

console.log(
  `Checked ${routes} public routes and ${schemas} schemas against the API's contract, and validated ${guideExamples.length} guide JSON examples, ${cases.length} eval run responses with their list pages, ${suiteCases.length} suite run responses, bundle and revision responses, and ${capabilityCases.length} capability states (${validated} documents in all); rejected an unknown verdict.`,
);
