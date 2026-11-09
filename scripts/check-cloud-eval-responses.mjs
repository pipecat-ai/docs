#!/usr/bin/env node

// Compare these public schemas with actual API serialization. Use an API
// checkout containing the eval-run contract, with its dependencies installed:
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

const base = "/organizations/{organizationName}/services/{agentName}/eval-runs";
const cancel = document.paths[`${base}/{runId}/cancel`].post;
const ajv = new Ajv({ strict: false, allErrors: true, validateFormats: false });
function validator(schema, components = document.components) {
  return ajv.compile({
    components: jsonSchemaBounds(components),
    ...schema,
  });
}
const validateDetail = validator(
  cancel.responses["200"].content["application/json"].schema,
);
const validatePage = validator(
  document.paths[base].get.responses["200"].content["application/json"].schema,
);
// Check the literal guide examples against both public docs and the current
// API contract. The latter also pins dashboard identity fields that the
// narrower public reference does not yet describe.
const apiDocument = parseYaml(
  readFileSync(path.resolve(apiRoot, "src/docs/oas.yaml"), "utf8"),
);
const validateApiDetail = validator(
  { $ref: "#/components/schemas/EvalRun" },
  apiDocument.components,
);
const guide = readFileSync(
  path.join(docsRoot, "pipecat-cloud/guides/evals.mdx"),
  "utf8",
);
const guideExamples = [
  ...guide.matchAll(/^```json(?:[ \t][^\r\n]*)?\r?\n([\s\S]*?)^```[ \t]*$/gm),
];
assert.ok(
  guideExamples.length > 0,
  "The evals guide must contain a response JSON example.",
);
for (const match of guideExamples) {
  const line = guide.slice(0, match.index).split("\n").length;
  const example = JSON.parse(match[1]);
  for (const [name, validate] of [
    ["public", validateDetail],
    ["API", validateApiDetail],
  ]) {
    assert.equal(
      validate(example),
      true,
      `Guide JSON at line ${line} (${name}): ${ajv.errorsText(validate.errors)}`,
    );
  }
  // A full run response always includes params, even when no overrides were
  // requested; OAS currently does not mark this serializer field required.
  assert.ok(
    Object.hasOwn(example, "params"),
    `Guide JSON at line ${line}: missing params`,
  );
}
const createdAt = new Date("2026-11-05T12:00:00.000Z");
const startedAt = new Date("2026-11-05T12:00:04.000Z");
const finishedAt = new Date("2026-11-05T12:01:30.000Z");
function row(overrides = {}) {
  return {
    id: "0b9f0c3e-6a51-4c7e-9d0a-3f5e2b1c4d6a",
    organizationId: "11111111-1111-4111-8111-111111111111",
    serviceId: "22222222-2222-4222-8222-222222222222",
    region: "us-west",
    kind: "synthetic",
    status: "queued",
    bundle: { "scenario.yaml": "name: scenario" },
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
console.log(
  `Validated ${guideExamples.length} actual guide JSON examples, ${cases.length} serialized detail responses and ${cases.length} nonempty list pages; rejected an unknown verdict.`,
);
