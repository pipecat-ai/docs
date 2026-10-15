"""Fixture tests for scripts/check-reference.py.

Run from the repo root:

    python3 -m unittest discover -s scripts/tests

The checker runs against two small trees under fixtures/:

- fixtures/pipecat: a fake pipecat checkout (src/pipecat, examples,
  env.example, pyproject.toml, scripts/deprecations/deprecations.json) shaped
  like the real one.
- fixtures/docs: pages shaped like this site's. They are stored as `*.mdx.in`
  and copied to `*.mdx` in a temporary directory, so that Mintlify, the link
  check, the metadata lint, check-imports.mjs and the checker's own run on this
  repo never see them.

Every finding kind has a case that must be flagged and near misses that must
not be. TestExactFindings pins the whole set, so a rule that starts flagging
something new fails too. See scripts/check-reference.md for how to add a case.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
import warnings
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PIPECAT = os.path.join(HERE, "fixtures", "pipecat")
DOCS = os.path.join(HERE, "fixtures", "docs")

_spec = importlib.util.spec_from_file_location("check_reference", os.path.join(REPO, "scripts", "check-reference.py"))
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)

TTS = "api-reference/server/services/tts/acme.mdx"
STT = "api-reference/server/services/stt/acme.mdx"
COMMUNITY = "api-reference/server/services/community/community-tts.mdx"
EVAL = "api-reference/cli/eval.mdx"
INIT = "api-reference/cli/init.mdx"
GUIDE = "pipecat/guides/acme-guide.mdx"
OLD = "pipecat/guides/old-acme.mdx"
SIGNATURES = "pipecat/guides/signatures.mdx"
STAR = "pipecat/guides/star-import.mdx"
MIGRATION = "pipecat/migration/acme-migration.mdx"
CLIENT = "client/js/acme-client.mdx"

# Everything the fixtures must produce, and nothing else.
EXPECTED = {
    (TTS, "stale-param", "bogus_option"),
    (TTS, "stale-setting", "pitch"),
    (TTS, "missing-param", "timeout_secs"),
    (TTS, "missing-setting", "emotion"),
    (TTS, "default-mismatch", "encoding"),
    (TTS, "default-mismatch", "speed"),
    (TTS, "unmarked-deprecation", "voice_id"),
    (TTS, "missing-event", "on_acme_ready"),
    (TTS, "unfired-event", "on_acme_never"),
    (TTS, "unfired-event", "on_acme_http_only"),
    (TTS, "missing-deprecated", "model_name"),
    (TTS, "type-mismatch", "container"),
    (GUIDE, "sample-unknown-arg", "bogus_flag"),
    (GUIDE, "sample-missing-arg", "api_key"),
    (GUIDE, "sample-missing-arg", "text"),
    (GUIDE, "sample-unknown-attr", "bogus_method"),
    (GUIDE, "sample-unknown-event", "on_acme_bogus"),
    (GUIDE, "sample-deprecated-arg", "voice_id"),
    (GUIDE, "sample-deprecated-arg", "set_voice(legacy)"),
    (GUIDE, "sample-deprecated-call", "old_flush"),
    (GUIDE, "sample-deprecated-call", "OldAcmeTTSService"),
    (GUIDE, "sample-undefined-name", "os"),
    (GUIDE, "sample-undefined-name", "TextFrame"),
    (GUIDE, "sample-unknown-env", "ACME_TTS_API_KEY"),
    (GUIDE, "prose-unknown-name", "AcmeTurboTTSService"),
    (GUIDE, "unknown-extra", "bogus-extra"),
    (EVAL, "cli-stale-option", "--bogus-flag"),
    (EVAL, "cli-missing-option", "-v"),
    (EVAL, "cli-missing-option", "--fail-fast"),
    (EVAL, "cli-missing-command", "eval report"),
    (EVAL, "cli-default-mismatch", "--timeout"),
    (EVAL, "cli-unmarked-deprecation", "--legacy-mode"),
}


def build_docs(dest):
    """Copy the fixture pages to `dest`, renaming `x.mdx.in` to `x.mdx`."""
    for dirpath, _, filenames in os.walk(DOCS):
        for fn in filenames:
            if fn.endswith(".mdx.in"):
                rel = os.path.relpath(os.path.join(dirpath, fn), DOCS)
                os.makedirs(os.path.join(dest, os.path.dirname(rel)), exist_ok=True)
                shutil.copy(os.path.join(DOCS, rel), os.path.join(dest, rel.removesuffix(".in")))


def run_checker(docs, *args, pipecat=PIPECAT, floors=None, ignore=""):
    """Run the checker in-process. `ignore` is the ignore file's text. The
    decay alarm is off unless `floors` is given: the fixtures are far smaller
    than pipecat. Returns (exit code, stdout, findings or None)."""
    with tempfile.TemporaryDirectory() as tmp:
        ignore_path = os.path.join(tmp, "ignore.txt")
        with open(ignore_path, "w") as f:
            f.write(ignore)
        out_path = os.path.join(tmp, "out.json")
        argv = ["--pipecat", pipecat, "--docs-root", docs, "--ignore", ignore_path, "--json", out_path, *args]
        out = io.StringIO()
        with mock.patch.object(cr, "FLOORS", floors or {}), contextlib.redirect_stdout(out):
            code = cr.main(argv)
        findings = None
        if os.path.exists(out_path):
            with open(out_path) as f:
                findings = json.load(f)
    return code, out.getvalue(), findings


def keys(findings):
    return {(f["page"], f["kind"], f["name"]) for f in findings}


def setUpModule():
    global DOCS_TMP, FINDINGS, KEYS, EXIT
    # The checker reads files with `open(path).read()`; fine in a one-shot
    # script, noise when unittest turns ResourceWarning on.
    warnings.simplefilter("ignore", ResourceWarning)
    DOCS_TMP = tempfile.mkdtemp()
    build_docs(DOCS_TMP)
    EXIT, _, FINDINGS = run_checker(DOCS_TMP)
    KEYS = keys(FINDINGS)


def tearDownModule():
    shutil.rmtree(DOCS_TMP)


class Case(unittest.TestCase):
    def flagged(self, page, kind, name):
        self.assertIn((page, kind, name), KEYS, f"expected {kind} for `{name}` on {page}")

    def not_flagged(self, page, kind, name):
        self.assertNotIn((page, kind, name), KEYS, f"unexpected {kind} for `{name}` on {page}")

    def page_clean(self, page):
        self.assertEqual({k for k in KEYS if k[0] == page}, set(), f"{page} should have no findings")


class TestExactFindings(Case):
    def test_exactly_the_expected_findings(self):
        self.assertEqual(KEYS - EXPECTED, set(), "findings the fixtures shouldn't produce")
        self.assertEqual(EXPECTED - KEYS, set(), "findings the fixtures should produce")
        self.assertEqual(EXIT, 1)

    def test_every_kind_has_a_fixture(self):
        kinds = {k for _, k, _ in EXPECTED} | {"stale-ignore"}  # stale-ignore: TestIgnoreFile
        self.assertEqual(kinds, set(cr.KINDS))

    def test_lines_point_at_the_entry(self):
        lines = {(f["kind"], f["name"]): f["line"] for f in FINDINGS if f["page"] == TTS}
        with open(os.path.join(DOCS_TMP, TTS)) as f:
            text = f.read().split("\n")
        self.assertIn('path="bogus_option"', text[lines[("stale-param", "bogus_option")] - 1])
        self.assertIn("`pitch`", text[lines[("stale-setting", "pitch")] - 1])


class TestParams(Case):
    def test_stale_param(self):
        self.flagged(TTS, "stale-param", "bogus_option")

    def test_stale_param_skips_base_kwargs_properties_and_kwargs(self):
        self.not_flagged(TTS, "stale-param", "push_stop_frames")  # TTSService via **kwargs
        self.not_flagged(TTS, "stale-param", "voice_count")  # a property
        self.not_flagged(TTS, "stale-param", "**kwargs")

    def test_stale_param_skips_method_tables(self):
        self.not_flagged(TTS, "stale-param", "voice")  # table under `### set_voice`

    def test_missing_param(self):
        self.flagged(TTS, "missing-param", "timeout_secs")

    def test_missing_param_skips_private_settings_and_deprecated(self):
        self.not_flagged(TTS, "missing-param", "_test_delay")
        self.not_flagged(TTS, "missing-param", "settings")  # the page has a Settings table
        self.not_flagged(TTS, "missing-param", "model_name")  # missing-deprecated instead

    def test_missing_deprecated(self):
        self.flagged(TTS, "missing-deprecated", "model_name")

    def test_missing_deprecated_skips_documented(self):
        self.not_flagged(TTS, "missing-deprecated", "voice_id")
        self.not_flagged(TTS, "missing-deprecated", "params")

    def test_default_mismatch(self):
        self.flagged(TTS, "default-mismatch", "encoding")

    def test_default_mismatch_resolves_constants(self):
        self.not_flagged(TTS, "default-mismatch", "sample_rate")  # DEFAULT_SAMPLE_RATE

    def test_type_mismatch(self):
        self.flagged(TTS, "type-mismatch", "container")

    def test_type_mismatch_normalizes(self):
        self.not_flagged(TTS, "type-mismatch", "region")  # "string" vs Optional[str]
        self.not_flagged(TTS, "type-mismatch", "language")  # `Language \| str` in a table

    def test_unmarked_deprecation(self):
        self.flagged(TTS, "unmarked-deprecation", "voice_id")

    def test_unmarked_deprecation_skips_marked(self):
        self.not_flagged(TTS, "unmarked-deprecation", "params")

    def test_community_page_skipped(self):
        self.page_clean(COMMUNITY)


class TestSettings(Case):
    def test_stale_setting(self):
        self.flagged(TTS, "stale-setting", "pitch")

    def test_stale_setting_skips_inherited(self):
        self.not_flagged(TTS, "stale-setting", "model")  # ServiceSettings
        self.not_flagged(TTS, "stale-setting", "language")  # TTSSettings

    def test_missing_setting(self):
        self.flagged(TTS, "missing-setting", "emotion")

    def test_missing_setting_skips_fields_from_another_package(self):
        self.not_flagged(TTS, "missing-setting", "extra")  # pipecat.services.settings

    def test_settings_default_mismatch(self):
        self.flagged(TTS, "default-mismatch", "speed")  # default_settings sets 1.0

    def test_settings_default_none_for_not_given(self):
        self.not_flagged(TTS, "default-mismatch", "style")
        self.not_flagged(TTS, "default-mismatch", "model")  # from default_settings

    def test_settings_default_filled_in_init(self):
        self.page_clean(STT)  # `language` filled by `if not is_given(...)`


class TestEvents(Case):
    def test_missing_event(self):
        self.flagged(TTS, "missing-event", "on_acme_ready")

    def test_missing_event_skips_unfired_and_base_events(self):
        self.not_flagged(TTS, "missing-event", "on_acme_unused")  # never fired
        self.not_flagged(TTS, "missing-event", "on_connected")  # TTSService's, another module

    def test_unfired_event(self):
        self.flagged(TTS, "unfired-event", "on_acme_never")  # page-wide Event Handlers table
        self.flagged(TTS, "unfired-event", "on_acme_http_only")  # under the class's heading

    def test_unfired_event_skips_fired(self):
        self.not_flagged(TTS, "unfired-event", "on_acme_connected")  # private method, called
        self.not_flagged(TTS, "unfired-event", "on_acme_shared")  # one of the page's classes fires it


class TestSamples(Case):
    def test_sample_unknown_arg(self):
        self.flagged(GUIDE, "sample-unknown-arg", "bogus_flag")

    def test_sample_unknown_arg_skips_base_kwargs_and_open_classes(self):
        for name in ("push_stop_frames", "name", "region"):
            self.not_flagged(GUIDE, "sample-unknown-arg", name)
        self.not_flagged(GUIDE, "sample-unknown-arg", "sdk_timeout")  # base outside pipecat

    def test_sample_missing_arg(self):
        self.flagged(GUIDE, "sample-missing-arg", "api_key")
        self.flagged(GUIDE, "sample-missing-arg", "text")  # dataclass field

    def test_sample_missing_arg_skips_positional_splat_and_ellipsis(self):
        missing = [f for f in FINDINGS if f["page"] == GUIDE and f["kind"] == "sample-missing-arg"]
        self.assertEqual(len(missing), 2, missing)  # not `TextFrame("Hello")`, `TextFrame(...)`, `(**options)`

    def test_sample_unknown_attr(self):
        self.flagged(GUIDE, "sample-unknown-attr", "bogus_method")

    def test_sample_unknown_attr_skips_base_methods_and_open_classes(self):
        for name in ("say", "queue_frame", "set_voice", "sdk_method"):
            self.not_flagged(GUIDE, "sample-unknown-attr", name)

    def test_sample_unknown_event(self):
        self.flagged(GUIDE, "sample-unknown-event", "on_acme_bogus")

    def test_sample_unknown_event_skips_base_events(self):
        self.not_flagged(GUIDE, "sample-unknown-event", "on_connected")

    def test_sample_deprecated_arg(self):
        self.flagged(GUIDE, "sample-deprecated-arg", "voice_id")
        self.flagged(GUIDE, "sample-deprecated-arg", "set_voice(legacy)")

    def test_sample_deprecated_arg_skips_current_args(self):
        args = {f["name"] for f in FINDINGS if f["page"] == GUIDE and f["kind"] == "sample-deprecated-arg"}
        self.assertEqual(args, {"voice_id", "set_voice(legacy)"})

    def test_sample_deprecated_call(self):
        self.flagged(GUIDE, "sample-deprecated-call", "OldAcmeTTSService")
        self.flagged(GUIDE, "sample-deprecated-call", "old_flush")

    def test_sample_deprecated_call_skips_class_own_page(self):
        self.page_clean(OLD)

    def test_sample_deprecated_call_skips_class_entry_for_events(self):
        # AudioBufferProcessor's `class` registry entries record deprecated
        # events; their messages don't name the class.
        self.not_flagged(GUIDE, "sample-deprecated-call", "AudioBufferProcessor")

    def test_sample_undefined_name(self):
        self.flagged(GUIDE, "sample-undefined-name", "os")
        self.flagged(GUIDE, "sample-undefined-name", "TextFrame")

    def test_sample_undefined_name_skips_free_variables_and_imported(self):
        self.not_flagged(GUIDE, "sample-undefined-name", "task")
        self.not_flagged(GUIDE, "sample-undefined-name", "AcmeTTSService")

    def test_sample_undefined_name_only_first_sample(self):
        # The second sample uses `FrameProcessor`, `AcmeSdkWrapper` and
        # `AudioBufferProcessor` without importing them.
        names = {f["name"] for f in FINDINGS if f["kind"] == "sample-undefined-name"}
        self.assertEqual(names, {"os", "TextFrame"})

    def test_sample_undefined_name_skips_signatures_and_star_imports(self):
        self.page_clean(SIGNATURES)
        self.page_clean(STAR)

    def test_sample_unknown_env(self):
        self.flagged(GUIDE, "sample-unknown-env", "ACME_TTS_API_KEY")

    def test_sample_unknown_env_scope(self):
        envs = {f["name"] for f in FINDINGS if f["kind"] == "sample-unknown-env"}
        # Not: ACME_API_KEY (env.example), ACME_ALT_API_KEY (an example),
        # MY_API_KEY (placeholder), WHATEVER_API_KEY (not passed to a pipecat
        # class directly), ACME_REGION (not an API key), ACME_COMMUNITY_API_KEY
        # (community page).
        self.assertEqual(envs, {"ACME_TTS_API_KEY"})

    def test_migration_guides_skipped(self):
        self.page_clean(MIGRATION)


class TestProse(Case):
    def test_prose_unknown_name(self):
        self.flagged(GUIDE, "prose-unknown-name", "AcmeTurboTTSService")

    def test_prose_unknown_name_exclusions(self):
        for name in (
            "AcmeLegacyTTSService",  # a line about a removed API
            "AcmeOldStyleTTSService",  # a Migration section
            "AcmeTtsService",  # "not `X`"
            "MyCustomProcessor",  # the page's sample defines it
            "ExampleHoldFrame",  # a pipecat example defines it
            "AcmeBrowserTransport",  # a JavaScript line
            "AcmeFencedTTSService",  # inside a code block
            "AcmeClient",  # no class-like ending
        ):
            self.not_flagged(GUIDE, "prose-unknown-name", name)
        names = {f["name"] for f in FINDINGS if f["kind"] == "prose-unknown-name"}
        self.assertEqual(names, {"AcmeTurboTTSService"})  # also not on client or community pages

    def test_client_pages_skipped(self):
        self.page_clean(CLIENT)


class TestExtras(Case):
    def test_unknown_extra(self):
        self.flagged(GUIDE, "unknown-extra", "bogus-extra")

    def test_extras_normalized(self):
        self.not_flagged(GUIDE, "unknown-extra", "acme")
        self.not_flagged(GUIDE, "unknown-extra", "Local_Smart.Turn")


class TestCli(Case):
    def test_cli_stale_option(self):
        self.flagged(EVAL, "cli-stale-option", "--bogus-flag")

    def test_cli_stale_option_skips_positionals(self):
        self.not_flagged(EVAL, "cli-stale-option", "SCENARIOS...")

    def test_cli_missing_option(self):
        self.flagged(EVAL, "cli-missing-option", "-v")  # short form left out
        self.flagged(EVAL, "cli-missing-option", "--fail-fast")  # option left out

    def test_cli_missing_option_skips_deprecated_and_hidden(self):
        self.not_flagged(EVAL, "cli-missing-option", "--older-flag")
        self.not_flagged(EVAL, "cli-missing-option", "--secret")

    def test_cli_missing_command(self):
        self.flagged(EVAL, "cli-missing-command", "eval report")

    def test_cli_missing_command_skips_hidden_and_other_groups(self):
        self.not_flagged(EVAL, "cli-missing-command", "eval debug-dump")
        self.not_flagged(EVAL, "cli-missing-command", "init")
        self.not_flagged(INIT, "cli-missing-command", "create")

    def test_cli_default_mismatch(self):
        self.flagged(EVAL, "cli-default-mismatch", "--timeout")

    def test_cli_default_mismatch_normalizes(self):
        self.not_flagged(EVAL, "cli-default-mismatch", "--retries")  # 3.0 == 3, Annotated
        self.not_flagged(EVAL, "cli-default-mismatch", "--bot-url")

    def test_cli_unmarked_deprecation(self):
        self.flagged(EVAL, "cli-unmarked-deprecation", "--legacy-mode")

    def test_cli_unmarked_deprecation_skips_marked(self):
        self.not_flagged(EVAL, "cli-unmarked-deprecation", "--old-flag")

    def test_page_without_command_headings_uses_its_name(self):
        self.page_clean(INIT)  # `--context-hub` default "true", `-n`, `--dry-run`


class TestIgnoreFile(unittest.TestCase):
    IGNORE = (
        "# A comment line.\n"
        f"{TTS} stale-param bogus_option  # matches a finding\n"
        "\n"
        f"{TTS} stale-param long_gone  # matches nothing\n"
    )

    def test_suppresses_matching_findings(self):
        _, _, findings = run_checker(DOCS_TMP, ignore=self.IGNORE)
        self.assertNotIn((TTS, "stale-param", "bogus_option"), keys(findings))
        self.assertIn((TTS, "stale-setting", "pitch"), keys(findings))

    def test_reports_stale_entries(self):
        code, _, findings = run_checker(DOCS_TMP, ignore=self.IGNORE)
        stale = [f for f in findings if f["kind"] == "stale-ignore"]
        self.assertEqual([(f["name"], f["class"], f["line"]) for f in stale], [("long_gone", "stale-param", 4)])
        self.assertTrue(stale[0]["page"].endswith("ignore.txt"))
        self.assertEqual(code, 1)

    def test_no_stale_entries_when_all_match(self):
        _, _, findings = run_checker(DOCS_TMP, ignore=f"{TTS} stale-param bogus_option  # why\n")
        self.assertEqual([f for f in findings if f["kind"] == "stale-ignore"], [])

    def test_stale_entries_not_reported_under_pages_from(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as pages:
            pages.write(f"{TTS}\n")
            pages.flush()
            _, _, findings = run_checker(DOCS_TMP, "--pages-from", pages.name, ignore=self.IGNORE)
        self.assertEqual([f for f in findings if f["kind"] == "stale-ignore"], [])
        self.assertNotIn((TTS, "stale-param", "bogus_option"), keys(findings))

    def test_malformed_entry(self):
        with self.assertRaises(SystemExit) as cm:
            run_checker(DOCS_TMP, ignore=f"{TTS} stale-param  # no name\n")
        self.assertIn(":1:", str(cm.exception.code))


class TestPagesFrom(unittest.TestCase):
    def test_reports_only_listed_pages(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as pages:
            pages.write(f"{GUIDE}\n{STT}\n")
            pages.flush()
            code, _, findings = run_checker(DOCS_TMP, "--pages-from", pages.name)
        self.assertEqual(keys(findings), {k for k in EXPECTED if k[0] == GUIDE})
        self.assertEqual(code, 1)

    def test_clean_pages_pass(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as pages:
            pages.write(f"{STT}\n{OLD}\n")
            pages.flush()
            code, out, findings = run_checker(DOCS_TMP, "--pages-from", pages.name)
        self.assertEqual((code, out, findings), (0, "", []))


class TestDecayAlarm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        idx = cr.SourceIndex(PIPECAT)
        cls.counts = cr.pipecat_counts(idx, cr.pipecat_extras(PIPECAT), cr.cli_commands(PIPECAT))

    def test_every_count_has_a_floor(self):
        self.assertEqual(set(cr.FLOORS), set(self.counts))

    def test_fixtures_exercise_every_count(self):
        self.assertEqual([k for k, n in self.counts.items() if n == 0], [])

    def test_quiet_at_the_floors(self):
        code, out, _ = run_checker(DOCS_TMP, floors=self.counts)
        self.assertEqual(code, 1)  # the fixtures' findings, no alarm
        self.assertNotIn("decay-alarm", out)

    def test_fires_below_a_floor(self):
        floors = {**self.counts, "registered events": self.counts["registered events"] + 1}
        code, out, findings = run_checker(DOCS_TMP, floors=floors)
        self.assertEqual(code, 2)
        self.assertIsNone(findings)  # no report: its rules can't be trusted
        self.assertIn("decay-alarm", out)
        self.assertIn("registered events", out)
        self.assertIn("scripts/check-reference.md", out)

    def test_github_format(self):
        floors = {**self.counts, "install extras": 1000}
        code, out, _ = run_checker(DOCS_TMP, "--format", "github", floors=floors)
        self.assertEqual(code, 2)
        self.assertTrue(out.startswith("::error::"), out)

    def test_not_affected_by_pages_from(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as pages:
            code, out, _ = run_checker(DOCS_TMP, "--pages-from", pages.name, floors=self.counts)
        self.assertEqual((code, out), (0, ""))
        floors = {**self.counts, "CLI options": 1000}
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as pages:
            code, _, _ = run_checker(DOCS_TMP, "--pages-from", pages.name, floors=floors)
        self.assertEqual(code, 2)

    def decay(self, mutate):
        """Run against a copy of the fake pipecat changed by `mutate(root)`,
        with floors at the unchanged fixture's counts."""
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "pipecat")
            shutil.copytree(PIPECAT, root)
            mutate(root)
            return run_checker(DOCS_TMP, pipecat=root, floors=self.counts)

    @staticmethod
    def rewrite(root, rel, old, new):
        path = os.path.join(root, rel)
        with open(path) as f:
            text = f.read()
        assert old in text, (rel, old)
        with open(path, "w") as f:
            f.write(text.replace(old, new))

    REGISTRY = os.path.join("scripts", "deprecations", "deprecations.json")

    def test_deprecation_registry_gone(self):
        code, out, _ = self.decay(lambda r: os.remove(os.path.join(r, self.REGISTRY)))
        self.assertEqual(code, 2)
        self.assertIn("deprecations.json: not found", out)

    def test_deprecation_registry_key_renamed(self):
        code, out, _ = self.decay(lambda r: self.rewrite(r, self.REGISTRY, '"subject":', '"target":'))
        self.assertEqual(code, 2)
        self.assertIn("deprecations.json: understood 0 of", out)

    def test_deprecation_registry_schema_bumped(self):
        code, out, _ = self.decay(lambda r: self.rewrite(r, self.REGISTRY, '"schema_version": 1', '"schema_version": 2'))
        self.assertEqual(code, 2)
        self.assertIn("schema_version 2, expected 1", out)

    def test_deprecations_removed_in_bulk(self):
        """A major release removes most deprecations: an emptier registry is
        not decay."""

        def empty(root):
            path = os.path.join(root, self.REGISTRY)
            with open(path) as f:
                data = json.load(f)
            data["deprecations"] = []
            with open(path, "w") as f:
                json.dump(data, f)

        code, out, _ = self.decay(empty)
        self.assertNotEqual(code, 2)
        self.assertNotIn("decay-alarm", out)

    def test_no_decay_alarm_flag(self):
        floors = {**self.counts, "install extras": 1000}
        code, out, findings = run_checker(DOCS_TMP, "--no-decay-alarm", floors=floors)
        self.assertEqual(code, 1)  # the fixtures' findings, reported anyway
        self.assertNotIn("decay-alarm", out)
        self.assertTrue(findings)

    def test_settings_convention_changed(self):
        rel = os.path.join("src", "pipecat", "services", "acme", "tts.py")
        code, out, _ = self.decay(lambda r: self.rewrite(r, rel, "    Settings = AcmeTTSSettings\n", "    settings_class = AcmeTTSSettings\n"))
        self.assertEqual(code, 2)
        self.assertIn("classes with a Settings class", out)

    def test_event_registration_renamed(self):
        rel = os.path.join("src", "pipecat", "services", "acme", "tts.py")
        code, out, _ = self.decay(lambda r: self.rewrite(r, rel, "_register_event_handler", "_register_event"))
        self.assertEqual(code, 2)
        self.assertIn("registered events", out)

    def test_cli_moved(self):
        code, out, _ = self.decay(lambda r: shutil.rmtree(os.path.join(r, "src", "pipecat", "cli")))
        self.assertEqual(code, 2)
        self.assertIn("CLI commands: found 0", out)

    def test_extras_moved(self):
        code, out, _ = self.decay(
            lambda r: self.rewrite(r, "pyproject.toml", "[project.optional-dependencies]", "[dependency-groups]")
        )
        self.assertEqual(code, 2)
        self.assertIn("install extras: found 0", out)


if __name__ == "__main__":
    unittest.main()
