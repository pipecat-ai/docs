# Reference Checker: Maintainer Guide

`scripts/check-reference.py` compares the docs with pipecat's source and
reports where they disagree. It reads pipecat with `ast` (nothing is imported or
installed) and uses only the Python standard library. This guide is for whoever
changes the checker, its ignore list, or its tests. The reasons behind each rule
are here, not only in commit messages.

## Running It

```bash
# Every page, against a pipecat checkout (default: ../pipecat)
python3 scripts/check-reference.py --pipecat ../pipecat

# Only report on some pages (CI passes a PR's changed pages)
python3 scripts/check-reference.py --pipecat ../pipecat --pages-from pages.txt

# The checker's own tests (seconds; no pipecat checkout needed)
python3 -m unittest discover -s scripts/tests
```

Other options: `--page GLOB`, `--only KIND,...`, `--json FILE`,
`--format text|github|summary`, `--ignore FILE`, and `--docs-root DIR` (the
docs tree to check; the tests point it at their fixtures).

Exit codes: `0` no findings, `1` findings, `2` the decay alarm fired (see
below).

## What It Checks

From pipecat it reads:

- each class's `__init__` parameters, annotations and defaults, following
  `**kwargs` into base classes
- the class's `Settings = SomeSettings` dataclass and its fields, and the
  defaults set by `default_settings = self.Settings(...)` or filled in by
  `if not is_given(self._settings.x): self._settings.x = ...`
- events registered with `self._register_event_handler("on_...")` and fired
  with `_call_event_handler`
- `scripts/deprecations/deprecations.json`, pipecat's generated registry
- `[project.optional-dependencies]` in `pyproject.toml`
- `env.example`, `src/` and `examples/` for environment variable names, and
  every identifier in `src/` and `examples/`
- the Typer app under `src/pipecat/cli` (commands, options, defaults, hidden
  and deprecated flags)

On the docs side:

- reference pages under `api-reference/server` and `api-reference/pipecat-flows`:
  `<ParamField>` entries and Markdown field tables, grouped by heading and
  matched to the class whose parameters or settings they overlap most
- Python code samples on every page except `pipecat/migration`
- backticked class names in prose, and `pipecat-ai[...]` install extras, on
  every page except `pipecat/migration`
- `api-reference/cli/init.mdx` and `api-reference/cli/eval.mdx`

## What It Doesn't Check

- Whether descriptions are true. It compares names, types, defaults,
  deprecation marks and events, not what the text says they do.
- JavaScript, TypeScript, Swift or Kotlin samples, and the client SDK and
  Pipecat Cloud pages (other repos' APIs).
- Community-maintained integrations (pages with `CommunityMaintained`), beyond
  calls their samples make to pipecat's own classes.
- Classes it can't resolve: a name several pipecat modules define, with no
  import on the page to say which.
- Deprecations of modules, functions, properties and attributes (the registry
  has them; no rule reads them yet).
- Links, imports and frontmatter: `mint broken-links`, `check-imports.mjs` and
  `docs-meta-lint.mjs` cover those.

## Finding Kinds

A class's "home page" is the page that documents the most of it. The
completeness kinds (`missing-*`, events) are only reported there, and only when
the page names the class in a heading or imports it.

| Kind                       | Reported when                                                                                            | Main exclusions                                                                                                                                                                                                     |
| -------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `stale-param`              | An entry names a parameter the matched class's constructor doesn't take.                                 | Attributes, properties and methods of the class; parameters bases take through `**kwargs`; `**kwargs` rows; tables under a method's heading; community pages.                                                       |
| `stale-setting`            | A row matched to a Settings class names a field it doesn't have.                                         | Groups that match no class: a heading must name it, or at least two entries and 60% of them must overlap.                                                                                                           |
| `missing-param`            | The class's own `__init__` takes a parameter its home page omits.                                        | Names starting with `_`; names in any of the class's groups, Settings rows included; `settings` when the page has a Settings table; parameters of base classes; deprecated ones (reported as `missing-deprecated`). |
| `missing-setting`          | The Settings class has a field its home page omits.                                                      | Fields declared in another package's Settings, such as the shared `TTSSettings` or OpenAI's for Grok.                                                                                                               |
| `default-mismatch`         | A documented default differs from the code's.                                                            | Expressions on either side; `None` on the page where the code has `NOT_GIVEN`; constants are resolved first; strings compare case-insensitively.                                                                    |
| `unmarked-deprecation`     | The registry deprecates a parameter or field the page lists without `deprecated`.                        | Entries with the `deprecated` attribute, or "deprecated" in their text or table row.                                                                                                                                |
| `missing-event`            | The class registers an event that something fires, and its home page never names it.                     | Events registered by bases in other modules (documented once on the base's page); events nothing fires.                                                                                                             |
| `unfired-event`            | The page names an event the class registers but nothing fires.                                           | A public method fires it, or a private one the module calls, or another object does; outside a class's own section, any of the page's classes firing it is enough.                                                  |
| `missing-deprecated`       | Like `missing-param` and `missing-setting`, for a deprecated parameter or field.                         | The same as those.                                                                                                                                                                                                  |
| `type-mismatch`            | The outer type names differ.                                                                             | `None` and `NotGiven` in unions; `Optional`, `Union` and aliases unwrapped; `string`, `integer`, `boolean`, `number`; `Any`; a bare `Literal`.                                                                      |
| `sample-unknown-arg`       | A sample passes a keyword a pipecat constructor doesn't take.                                            | Classes whose `**kwargs` reach a base outside pipecat; calls with `*args` or `**kwargs`.                                                                                                                            |
| `sample-missing-arg`       | A sample leaves out a required constructor argument.                                                     | Calls with `*args` or `**kwargs`; `Frame(...)` placeholders.                                                                                                                                                        |
| `sample-unknown-attr`      | A sample calls a method the object's class doesn't have.                                                 | Dunder names; classes with `__getattr__` or a base outside pipecat.                                                                                                                                                 |
| `sample-unknown-event`     | A sample handles an event the class and its bases never register.                                        | Classes that register events under computed names.                                                                                                                                                                  |
| `sample-deprecated-arg`    | A sample passes a deprecated constructor or method argument.                                             |                                                                                                                                                                                                                     |
| `sample-deprecated-call`   | A sample constructs a deprecated class or calls a deprecated method.                                     | Pages that name the class in their title or a heading; `class` entries whose message doesn't name the class (`AudioBufferProcessor`'s deprecated events).                                                           |
| `sample-undefined-name`    | A page's first sample uses a standard-library module (`os.getenv`) or a pipecat class it doesn't import. | Other free names (`llm`, `task`); later samples; star imports; signature-only blocks; nested-class names like `InputParams`.                                                                                        |
| `sample-unknown-env`       | A sample passes `os.getenv("X_API_KEY")` to a pipecat class, and pipecat never uses `X_API_KEY`.         | Names not ending in `_API_KEY`; placeholders (`MY_`, `YOUR_`, ...); values read into a variable first; community pages.                                                                                             |
| `prose-unknown-name`       | Prose names a backticked class (with an ending like `Service` or `Frame`) pipecat doesn't have.          | Client and Pipecat Cloud SDK pages; community pages; lines or sections about removed, renamed or deprecated APIs; names the page's samples define; "not `X`"; placeholders like `{Provider}TTSService`.             |
| `unknown-extra`            | An install extra isn't in pipecat's `pyproject.toml`.                                                    | Extras are compared normalized (`Local_Smart.Turn` is `local-smart-turn`).                                                                                                                                          |
| `cli-stale-option`         | A CLI page documents a flag the command doesn't accept.                                                  | Positional arguments.                                                                                                                                                                                               |
| `cli-missing-option`       | A command option, or one of its short forms, isn't on the page.                                          | Hidden and deprecated options.                                                                                                                                                                                      |
| `cli-missing-command`      | A command in the page's group has no section.                                                            | Hidden commands.                                                                                                                                                                                                    |
| `cli-default-mismatch`     | A CLI default differs from the code's.                                                                   | Code defaults of `None` or `...`; numbers compare as numbers; `true` and `True` are equal.                                                                                                                          |
| `cli-unmarked-deprecation` | An option is deprecated (`deprecated=True`, or help starting "Deprecated") and the page doesn't mark it. |                                                                                                                                                                                                                     |
| `stale-ignore`             | An ignore entry matched no finding.                                                                      | Not reported with `--pages-from`.                                                                                                                                                                                   |

## Ignore Entries

`scripts/check-reference-ignore.txt` lists confirmed false positives, one per
line:

```text
api-reference/server/services/stt/funasr.mdx default-mismatch model  # default resolved in __init__, not in default_settings
```

The fields are the page, the finding kind and the name the finding reports,
then `#` and the reason. Add an entry only after checking the source and the
page and finding the page correct, and say in the reason why the checker is
wrong.

Don't add an entry when:

- the page is wrong: fix the page
- the same false positive would appear on many pages: fix the rule (see below)
- the finding comes from pipecat being wrong: fix pipecat, and add the entry
  only until that fix is released

A full run reports an entry that no longer matches anything as `stale-ignore`,
pointing at its line. That happens when a page or pipecat changed so the false
positive is gone, or the entry was mistyped. Remove it. Under `--pages-from`
stale entries aren't reported, since a scoped run is no place to clean up the
list.

## Adding or Changing a Rule

The tests in `scripts/tests/` run the checker on a fake pipecat
(`fixtures/pipecat`) and a few fake pages (`fixtures/docs`). The pages are
stored as `*.mdx.in` so the site build, the link and metadata checks, the import
check and the checker's own run don't pick them up; the tests copy them to
`*.mdx` in a temporary directory.

1. **Write the fixture cases first.** Add the smallest code to
   `fixtures/pipecat` and page text to `fixtures/docs` that should be flagged,
   plus a near miss that shouldn't. Model both on a real pipecat module and a
   real page, so the fixture tests what the checker sees in production.
2. **Add them to the tests.** Add flagged findings to `EXPECTED` in
   `test_check_reference.py`, and a test per case with `flagged()` or
   `not_flagged()`. A new kind needs a row in `KINDS`; `test_every_kind_has_a_fixture`
   fails until it has a case.
3. **Change the checker** until the tests pass.
4. **Run it against pipecat main.** It should report nothing new beyond what
   you meant to find. Fix the pages, or add ignore entries for confirmed false
   positives, and remove entries the change made stale.
5. **Update this guide**: the table above, and the module docstring's list.

`TestExactFindings` pins the full set of findings, so a change that makes any
rule flag something new, or stop flagging something, fails a test.

## Decay Alarm

Each rule depends on a pipecat convention. If pipecat changes one (renames
`_register_event_handler`, stops assigning `Settings = ...`, moves
`deprecations.json`, moves the CLI), the rules built on it stop finding
anything, and the check passes without checking.

So after reading pipecat, the checker counts what it found and compares each
count with a floor in `FLOORS`. If any count is below its floor, it prints a
`decay-alarm` message naming the counts and exits with `2`, without reporting
findings. The floors are about half of the counts against pipecat main on
2026-10-15:

| Count                         | 2026-10-15 | Floor |
| ----------------------------- | ---------- | ----- |
| classes                       | 1748       | 870   |
| constructors                  | 472        | 235   |
| classes with a Settings class | 138        | 70    |
| Settings fields               | 1218       | 600   |
| default_settings assignments  | 132        | 65    |
| registered events             | 264        | 130   |
| fired events                  | 375        | 185   |
| deprecated parameters         | 318        | 155   |
| deprecated classes            | 103        | 50    |
| deprecated methods            | 30         | 15    |
| public top-level names        | 1708       | 850   |
| API key names                 | 66         | 33    |
| install extras                | 90         | 45    |
| CLI commands                  | 3          | 2     |
| CLI options                   | 55         | 27    |

The counts come from the pipecat source alone, so `--pages-from` can't set the
alarm off.

When it fires:

1. Find what changed in pipecat. The message names the low counts; look at
   pipecat's recent history for the convention behind each.
2. If the convention changed, teach the checker the new one. Change the fake
   pipecat in `scripts/tests/fixtures/pipecat` to the new convention first, so
   the tests show the rule working again, then change the parser.
3. If pipecat really has less of something (pipecat 2.0 will remove most
   deprecations, for example), lower that floor and update the table above with
   the new count and date. Don't lower a floor without knowing why the count
   fell.

## CI

`.github/workflows/check-reference.yml` runs on pull requests that change a
page, the checker, its ignore file, its tests or the workflow, and on demand.

- A PR is checked only on the pages it changes, so drift pipecat introduced
  elsewhere doesn't block unrelated work.
- A PR that changes the checker, its ignore file or the workflow checks every
  page, and so reports stale ignore entries.
- A PR that changes the checker, its ignore file, its tests or the workflow
  runs the tests first. A failing test fails the job.
- A manual run tests the checker and checks every page.

Pipecat's update-docs workflow also runs the checker, with `--pages-from` set to
the pages its update changes, and gives the findings to the agent writing the
update. A decay alarm shows up there too.
