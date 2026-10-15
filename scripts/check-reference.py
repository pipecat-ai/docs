#!/usr/bin/env python3
r"""Compare the API reference pages and code samples with the pipecat source.

Maintainer guide (rules, ignore entries, tests, the decay alarm, CI):
scripts/check-reference.md. Tests: python3 -m unittest discover -s scripts/tests

A reference page drifts from the code without anything noticing: a constructor
gains a parameter the page never lists, a default changes, a setting is
renamed, an event is added. The page still renders, and the link checker and
metadata lint pass. This reads both sides and reports where they disagree.

From the source (parsed with `ast`, nothing is imported or installed):
  - each class's `__init__` parameters, with their annotations and defaults,
    following `**kwargs` into base classes
  - the class's `Settings` dataclass fields, and the Pipecat defaults set in
    `__init__` by `default_settings = self.Settings(...)`
  - events registered with `self._register_event_handler("on_...")`
  - deprecations, from pipecat's generated `scripts/deprecations/deprecations.json`

From every page's Python code samples (except the migration guides):
  - calls to pipecat classes: constructor keywords, required arguments, and
    deprecated arguments; methods called on the objects they return; the
    event names given to `event_handler`
  - in the page's first sample, which has complete imports (STYLE.md):
    standard-library modules and pipecat classes it uses without importing
  - API keys handed to pipecat classes under names pipecat never uses

From every page's text (except the migration guides):
  - backticked class names outside code blocks, on pages about the Python
    framework (not the client SDKs or the Pipecat Cloud SDK)
  - `pipecat-ai[...]` install extras, against pipecat's pyproject.toml

From each page under api-reference/server and api-reference/pipecat-flows:
  - `<ParamField>` entries, grouped by the heading they sit under
  - Markdown tables whose first column names fields (`| \`name\` | ... |`)
  - event names (`on_...`) mentioned anywhere on the page

Each group of entries is matched to the class on the page whose parameters or
settings it overlaps most, so the check doesn't depend on heading wording.

Findings, most to least certain:
  stale-param        documented parameter the class doesn't accept
  missing-param      parameter the class declares that the page omits
  stale-setting      documented setting the Settings class doesn't have
  missing-setting    Settings field the page omits
  default-mismatch   documented default differs from the code's
  unmarked-deprecation  deprecated in source, not marked on the page
  missing-event      event the class registers that the page never names
  unfired-event      event the page names that the class registers but nothing fires
  missing-deprecated deprecated parameter or field the page omits
  type-mismatch      documented type differs from the annotation
  sample-unknown-arg     sample passes a keyword the constructor doesn't take
  sample-missing-arg     sample leaves out a required argument
  sample-unknown-attr    sample calls a method the object doesn't have
  sample-unknown-event   sample handles an event the class never registers
  sample-deprecated-arg  sample passes a deprecated argument
  sample-deprecated-call sample uses a deprecated class or method
  sample-undefined-name  first sample uses a module or pipecat class it doesn't import
  sample-unknown-env     sample reads an API key pipecat's env.example and examples never use
  prose-unknown-name     prose names a class pipecat doesn't have
  unknown-extra          install extra pipecat's pyproject.toml doesn't declare
  cli-*                  api-reference/cli pages against pipecat's Typer commands
  stale-ignore           ignore-file entry no finding matches (full runs only)

Usage:
  python3 scripts/check-reference.py [--pipecat PATH] [--json FILE]
                                     [--page GLOB] [--only KIND,...]
                                     [--format text|github|summary]

  --pipecat PATH  pipecat checkout (default: ../pipecat, per CLAUDE.md)
  --pages-from F  report only on the pages listed in F (CI passes a PR's pages)
  --ignore FILE   confirmed false positives (default:
                  scripts/check-reference-ignore.txt)
  --docs-root D   docs tree to check (default: this repo; the tests' fixtures)

Exit code: 1 if any finding is reported, 2 if the decay alarm fires (pipecat's
code no longer looks like what the checker reads), else 0. Standard library
only.
"""

import argparse
import ast
import fnmatch
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = REPO  # the docs tree checked; --docs-root points it elsewhere (the tests' fixtures)
PAGE_DIRS = ("api-reference/server", "api-reference/pipecat-flows")
# Code samples are checked on every page except these: migration guides show
# the old API on purpose.
SAMPLE_SKIP = ("node_modules", "pipecat/migration")


# Parameters every page may leave out: framework plumbing, not configuration.
IGNORED_PARAMS = {"self", "cls"}


# --------------------------------------------------------------------------
# Source side
# --------------------------------------------------------------------------


@dataclass
class Param:
    name: str
    annotation: str | None
    default: str | None  # unparsed source; None when required
    owner: str  # class that declares it
    init: bool = True  # False for a dataclass `field(init=False)`


@dataclass
class Cls:
    name: str
    module: str
    bases: list[str]
    params: list[Param] | None = None  # None: no __init__ of its own
    var_kwargs: bool = False
    settings_ref: str | None = None
    default_settings: dict[str, str] = field(default_factory=dict)
    # Settings `__init__` fills in when the caller left them unset:
    # `if not is_given(self._settings.x): self._settings.x = value`
    fill_settings: dict[str, str] = field(default_factory=dict)
    events: set[str] = field(default_factory=set)
    fired: dict[str, set[str]] = field(default_factory=dict)  # event -> methods that fire it
    fires_dynamic: bool = False  # fires an event whose name isn't a literal
    registers_dynamic: bool = False  # registers an event whose name isn't a literal
    is_dataclass: bool = False
    var_args: bool = False  # `__init__` takes `*args`
    fields: dict[str, Param] = field(default_factory=dict)  # dataclass/BaseModel
    constants: dict[str, str] = field(default_factory=dict)
    members: set[str] = field(default_factory=set)  # methods, properties, self.* attributes
    methods: dict[str, list[str]] = field(default_factory=dict)  # method -> positional parameter names
    class_constants: dict[str, str] = field(default_factory=dict)


def walk(top):
    """`os.walk` in sorted order. Which class a group matches can come down to
    the order classes and pages are read in; a file system's listing order
    must not decide it."""
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames.sort()
        yield dirpath, dirnames, sorted(filenames)


def unparse(node):
    return ast.unparse(node) if node is not None else None


def field_default(node):
    """Default of a dataclass/pydantic field, or None when it has none."""
    if node is None:
        return None
    if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in (
        "field",
        "Field",
    ):
        for kw in node.keywords:
            if kw.arg == "default":
                return unparse(kw.value)
            if kw.arg == "default_factory":
                v = kw.value
                if isinstance(v, ast.Lambda):
                    return unparse(v.body)
                return unparse(v) + "()"
        if node.args:
            return unparse(node.args[0])
        return None
    return unparse(node)


def identifiers_in(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(n.name)
        elif isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.alias):
            out.add((n.asname or n.name).split(".")[-1])
            out.add(n.name.split(".")[-1])
    return out


ENV_NAME_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b|\b[A-Z]{2,}[A-Z0-9]*\b")


def env_names(pipecat):
    """Every upper-case name in pipecat's source, examples, and env.example:
    the environment variables pipecat and its examples read."""
    out = set()
    roots = [os.path.join(pipecat, d) for d in ("src", "examples")]
    files = [os.path.join(pipecat, "env.example")]
    for root in roots:
        for dirpath, dirnames, filenames in walk(root):
            files += [os.path.join(dirpath, fn) for fn in filenames if fn.endswith((".py", ".example", ".md", ".toml", ".env"))]
    for f in files:
        try:
            out.update(ENV_NAME_RE.findall(open(f, encoding="utf-8").read()))
        except (OSError, UnicodeDecodeError):
            pass
    return out


DEPRECATIONS = "scripts/deprecations/deprecations.json"
DEPRECATIONS_SCHEMA = 1
# Registry kinds the checker reads (parameter, class, method) or knowingly
# leaves alone (the rest).
DEPRECATION_KINDS = {"parameter", "class", "method", "property", "module", "function", "attribute"}
# Share of the registry's entries the checker must understand. Below it, the
# registry's format has changed and the deprecation rules are reading little.
DEPRECATIONS_UNDERSTOOD = 0.9


def understood_deprecation(d):
    """Whether a registry entry has the shape the deprecation rules read: a
    string subject and message, and a known kind (`Class.member` for members)."""
    if not (isinstance(d, dict) and isinstance(d.get("subject"), str) and isinstance(d.get("message"), str)):
        return False
    if d.get("kind") in ("parameter", "method", "property"):
        return "." in d["subject"]
    return d.get("kind") in DEPRECATION_KINDS


def load_deprecations(pipecat):
    """({subject: entry} for the entries the checker understands, a problem
    for the decay alarm or None). A registry with few entries is fine (pipecat
    2.0 removes most); one the checker can't read is not."""
    path = os.path.join(pipecat, *DEPRECATIONS.split("/"))
    if not os.path.exists(path):
        return {}, f"{DEPRECATIONS}: not found"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        return {}, f"{DEPRECATIONS}: not valid JSON ({e})"
    entries = data.get("deprecations") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return {}, f"{DEPRECATIONS}: no top-level `deprecations` list"
    out = {d["subject"]: d for d in entries if understood_deprecation(d)}
    understood = sum(understood_deprecation(d) for d in entries)
    if data.get("schema_version") != DEPRECATIONS_SCHEMA:
        return out, f"{DEPRECATIONS}: schema_version {data.get('schema_version')!r}, expected {DEPRECATIONS_SCHEMA}"
    if entries and understood < DEPRECATIONS_UNDERSTOOD * len(entries):
        return out, (
            f"{DEPRECATIONS}: understood {understood} of {len(entries)} entries, "
            f"expected at least {DEPRECATIONS_UNDERSTOOD:.0%}"
        )
    return out, None


def package_of(module):
    """`pipecat.services.assemblyai.stt` -> `pipecat.services.assemblyai`."""
    return ".".join(module.split(".")[:3])


class SourceIndex:
    def __init__(self, pipecat):
        self.root = os.path.join(pipecat, "src", "pipecat")
        self.by_name: dict[str, list[Cls]] = defaultdict(list)
        self.module_constants: dict[str, dict[str, str]] = {}
        self.module_imports: dict[str, dict[str, tuple[str, str]]] = {}
        self.type_aliases: dict[str, str] = {}
        # Names each module mentions (`self._on_x`, `on_x=...`, a string), to
        # tell a private method something calls from one nothing does.
        self.refs: dict[str, Counter] = defaultdict(Counter)
        # Events fired on another object (`transport._call_event_handler(...)`).
        self.external_fired: set[str] = set()
        # Every identifier the source defines or uses (its own names and the
        # libraries' it calls), to tell a name a page invents from a real one.
        self.identifiers: set[str] = set()
        # Classes and functions defined at the top of a pipecat module: what a
        # sample has to import.
        self.top_level: set[str] = set()
        for dirpath, dirnames, filenames in walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in ("tests", "__pycache__")]
            for fn in filenames:
                if fn.endswith(".py"):
                    self._index(os.path.join(dirpath, fn))
        # Names pipecat's examples define are real too: pages describe them.
        for dirpath, dirnames, filenames in walk(os.path.join(pipecat, "examples")):
            for fn in filenames:
                if fn.endswith(".py"):
                    try:
                        tree = ast.parse(open(os.path.join(dirpath, fn), encoding="utf-8").read())
                    except (SyntaxError, UnicodeDecodeError):
                        continue
                    self.identifiers |= identifiers_in(tree)
        self.env_names = env_names(pipecat)
        self.deprecated, self.deprecations_problem = load_deprecations(pipecat)

    def _index(self, path):
        rel = os.path.relpath(path, os.path.dirname(self.root))
        module = rel[:-3].replace(os.sep, ".").removesuffix(".__init__")
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except SyntaxError:
            return
        consts = {}
        for node in tree.body:
            target = value = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                target, value = node.target, node.value
            if not isinstance(target, ast.Name):
                continue
            if isinstance(value, (ast.Constant, ast.UnaryOp)):
                consts[target.id] = unparse(value)
            elif isinstance(value, ast.BinOp):
                try:  # `25 * 1024 * 1024`
                    consts[target.id] = repr(eval(compile(ast.Expression(value), "<const>", "eval"), {"__builtins__": {}}))
                except Exception:
                    if target.id[:1].isupper():
                        self.type_aliases[target.id] = unparse(value)
            elif isinstance(value, ast.Subscript) and target.id[:1].isupper():
                self.type_aliases[target.id] = unparse(value)
        self.module_constants[module] = consts
        self.identifiers |= identifiers_in(tree)
        if ".tests" not in module:
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                    self.top_level.add(node.name)
        refs = self.refs[module]
        for sub in ast.walk(tree):
            if isinstance(sub, ast.Attribute):
                refs[sub.attr] += 1
            elif isinstance(sub, ast.Name):
                refs[sub.id] += 1
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value.isidentifier():
                refs[sub.value] += 1
            elif (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "_call_event_handler"
                and getattr(sub.func.value, "id", None) != "self"
                and sub.args
                and isinstance(sub.args[0], ast.Constant)
            ):
                self.external_fired.add(sub.args[0].value)
        imports = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    pkg = module.split(".") if rel.endswith("__init__.py") else module.split(".")[:-1]
                    pkg = pkg[: len(pkg) - (node.level - 1)]
                    src = ".".join(pkg + ([node.module] if node.module else []))
                else:
                    src = node.module
                for alias in node.names:
                    imports[alias.asname or alias.name] = (src, alias.name)
        self.module_imports[module] = imports
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                self._add_class(node, module, consts)

    def _add_class(self, node, module, consts, prefix=""):
        c = Cls(
            name=prefix + node.name,
            module=module,
            bases=[unparse(b) for b in node.bases],
            constants=consts,  # replaced by constants_for() once all modules are read
            is_dataclass=any("dataclass" in unparse(d) for d in node.decorator_list),
        )
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                c.members.add(item.name)
                c.methods[item.name] = [a.arg for a in item.args.posonlyargs + item.args.args if a.arg not in ("self", "cls")]
                for sub in ast.walk(item):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "_call_event_handler"
                        and getattr(sub.func.value, "id", None) == "self"
                    ):
                        if sub.args and isinstance(sub.args[0], ast.Constant):
                            c.fired.setdefault(sub.args[0].value, set()).add(item.name)
                        else:
                            c.fires_dynamic = True
                for sub in ast.walk(item):
                    if (
                        isinstance(sub, ast.Attribute)
                        and isinstance(sub.ctx, ast.Store)
                        and getattr(sub.value, "id", None) == "self"
                    ):
                        c.members.add(sub.attr.lstrip("_"))
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                c.params, c.var_kwargs = self._init_params(item, c.name)
                c.var_args = item.args.vararg is not None
                for sub in ast.walk(item):
                    if (
                        isinstance(sub, ast.Assign)
                        and len(sub.targets) == 1
                        and getattr(sub.targets[0], "id", None) == "default_settings"
                        and isinstance(sub.value, ast.Call)
                    ):
                        for kw in sub.value.keywords:
                            if kw.arg:
                                c.default_settings[kw.arg] = unparse(kw.value)
                    elif (
                        isinstance(sub, ast.If)
                        and isinstance(sub.test, ast.UnaryOp)
                        and isinstance(sub.test.op, ast.Not)
                        and isinstance(sub.test.operand, ast.Call)
                        and getattr(sub.test.operand.func, "id", None) == "is_given"
                        and sub.test.operand.args
                        and unparse(sub.test.operand.args[0]).startswith("self._settings.")
                    ):
                        name = unparse(sub.test.operand.args[0]).split(".")[-1]
                        for st in sub.body:
                            if (
                                isinstance(st, ast.Assign)
                                and len(st.targets) == 1
                                and unparse(st.targets[0]) == f"self._settings.{name}"
                            ):
                                c.fill_settings[name] = unparse(st.value)
            elif isinstance(item, ast.Assign) and len(item.targets) == 1:
                t = item.targets[0]
                if isinstance(t, ast.Name) and t.id == "Settings" and isinstance(item.value, ast.Name):
                    c.settings_ref = item.value.id
                elif isinstance(t, ast.Name) and isinstance(item.value, ast.Constant):
                    c.class_constants[t.id] = unparse(item.value)
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                name = item.target.id
                if not name.startswith("_") and not (
                    isinstance(item.annotation, ast.Subscript)
                    and unparse(item.annotation.value).endswith("ClassVar")
                ):
                    v = item.value
                    init = not (
                        isinstance(v, ast.Call)
                        and getattr(v.func, "id", getattr(v.func, "attr", "")) == "field"
                        and any(kw.arg == "init" and getattr(kw.value, "value", True) is False for kw in v.keywords)
                    )
                    c.fields[name] = Param(name, unparse(item.annotation), field_default(v), c.name, init)
            elif isinstance(item, ast.ClassDef):
                self._add_class(item, module, consts, prefix=c.name + ".")
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "_register_event_handler"
                and sub.args
            ):
                if isinstance(sub.args[0], ast.Constant):
                    c.events.add(sub.args[0].value)
                else:
                    c.registers_dynamic = True
        self.by_name[c.name].append(c)

    @staticmethod
    def _init_params(fn, owner):
        a = fn.args
        positional = a.posonlyargs + a.args
        defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
        out = []
        for arg, d in zip(positional, defaults):
            out.append(Param(arg.arg, unparse(arg.annotation), unparse(d), owner))
        for arg, d in zip(a.kwonlyargs, a.kw_defaults):
            out.append(Param(arg.arg, unparse(arg.annotation), unparse(d), owner))
        out = [p for p in out if p.name not in IGNORED_PARAMS]
        return out, a.kwarg is not None

    def get(self, name, module_hint=None):
        cands = self.by_name.get(name, [])
        if module_hint:
            for c in cands:
                if c.module == module_hint:
                    return c
        if len(cands) == 1:
            return cands[0]
        # Several classes share the name: prefer one under services/ etc. only
        # when exactly one is a public pipecat class.
        public = [c for c in cands if ".tests" not in c.module]
        return public[0] if len(public) == 1 else None

    def base(self, c, name):
        """Resolve a base class expression: `Foo`, `mod.Foo`, `Foo.Settings`,
        or a parametrized generic like `Foo[Bar]`."""
        name = name.split("[")[0]
        if "." in name:
            head, attr = name.rsplit(".", 1)
            outer = self.get(head, c.module) or self.get(head)
            if outer is None:
                return self.get(attr, c.module) or self.get(attr)
            if attr == "Settings":
                return self.settings_class(outer)
            nested = self.get(f"{outer.name}.{attr}")
            return nested or self.get(attr, c.module) or self.get(attr)
        return self.get(name, c.module) or self.get(name)

    def effective_params(self, c, seen=None):
        """Parameters `c(...)` accepts: its own, plus its bases' through **kwargs."""
        seen = seen or set()
        if c.name in seen:
            return {}
        seen.add(c.name)
        if c.params is None:
            for b in c.bases:
                bc = self.base(c, b)
                if bc:
                    return self.effective_params(bc, seen)
            return {}
        out = {p.name: p for p in c.params}
        if c.var_kwargs:
            for b in c.bases:
                bc = self.base(c, b)
                if bc:
                    for k, v in self.effective_params(bc, seen).items():
                        out.setdefault(k, v)
        return out

    def settings_class(self, c, seen=None):
        seen = seen or set()
        if c.name in seen:
            return None
        seen.add(c.name)
        if c.settings_ref:
            return self.get(c.settings_ref, c.module) or self.get(c.settings_ref)
        for b in c.bases:
            bc = self.base(c, b)
            if bc:
                s = self.settings_class(bc, seen)
                if s:
                    return s
        return None

    def effective_fields(self, c, seen=None):
        seen = seen or set()
        if c is None or c.name in seen:
            return {}
        seen.add(c.name)
        out = {}
        for b in c.bases:
            bc = self.base(c, b)
            if bc:
                out.update(self.effective_fields(bc, seen))
        out.update(c.fields)
        return out

    def effective_default_settings(self, c, seen=None):
        top = seen is None
        seen = seen if seen is not None else set()
        if c.name in seen:
            return {}
        seen.add(c.name)
        out = {}
        for b in c.bases:
            bc = self.base(c, b)
            if bc:
                out.update(self.effective_default_settings(bc, seen))
        out.update(c.default_settings)
        if top:  # apply fills from the whole hierarchy
            for k in self.mro(c):
                for name, v in k.fill_settings.items():
                    if out.get(name) in (None, "NOT_GIVEN"):
                        out[name] = v
        return out

    def effective_events(self, c, seen=None):
        """Events `c` registers itself or inherits from its own module.

        Events from shared bases (FrameProcessor, AIService, the STT/TTS/LLM
        and websocket base classes) are documented once on their own pages,
        so a provider page isn't expected to repeat them.
        """
        seen = seen or set()
        if c.name in seen:
            return set()
        seen.add(c.name)
        out = set(c.events)
        for b in c.bases:
            bc = self.base(c, b)
            if bc and bc.module == c.module:
                out |= self.effective_events(bc, seen)
        return out

    def mro(self, c, seen=None):
        """`c` and every base class that resolves."""
        seen = seen if seen is not None else set()
        if c.name in seen:
            return []
        seen.add(c.name)
        out = [c]
        for b in c.bases:
            bc = self.base(c, b)
            if bc:
                out += self.mro(bc, seen)
        return out

    def registers(self, c, event):
        return any(event in k.events or k.registers_dynamic for k in self.mro(c))

    def constructor(self, c):
        """What `c(...)` accepts: (params by name, positional order, required
        names, closed), or None when it can't be told. `closed` is False when
        unlisted keywords may still be accepted (`**kwargs` into an unknown
        base)."""
        mro = self.mro(c)
        for k in mro:
            if k.params is not None:
                spec = self.effective_params(c)
                closed = not k.var_args and self._closed(k)
                required = {p.name for p in k.params if p.default is None}
                return spec, [p.name for p in k.params], required, closed
            if k.is_dataclass:
                fields = {n: f for n, f in self.effective_fields(c).items() if f.init}
                order = list(fields)
                required = {n for n, f in fields.items() if f.default is None}
                return fields, order, required, True
            if any(b.split("[")[0].endswith("BaseModel") for b in k.bases):
                fields = self.effective_fields(c)
                required = {n for n, f in fields.items() if f.default is None}
                return fields, [], required, True
        return None

    def _closed(self, k, seen=None):
        seen = seen or set()
        if k.name in seen:
            return True
        seen.add(k.name)
        if not k.var_kwargs:
            return True
        bases = [self.base(k, b) for b in k.bases if b not in ("object", "ABC")]
        if not bases or any(b is None for b in bases):
            return False
        for bc in bases:
            first = next((x for x in self.mro(bc) if x.params is not None or x.is_dataclass), None)
            if first is None or (first.params is not None and not self._closed(first, seen)):
                return False
        return True

    def method_params(self, c, name):
        """Positional parameter names of method `name` on `c` or its bases."""
        for k in self.mro(c):
            if name in k.methods:
                return k.methods[name]
        return None

    def has_attr(self, c, name):
        """Whether `obj.name` can resolve on an instance of `c`."""
        mro = self.mro(c)
        if any("__getattr__" in k.members for k in mro):
            return True
        if any(not (self.base(k, b) or b in ("object", "ABC")) for k in mro for b in k.bases):
            return True  # a base outside pipecat may define it
        return self.has_member(c, name) or self.has_member(c, name.lstrip("_"))

    def fires(self, c, event):
        """Whether anything can fire `event` on a `c`: a method of `c` or a
        base calls `_call_event_handler` with it, and that method is public or
        referenced in the module of `c` or one of its bases. A class that overrides
        `add_event_handler` hands its handlers to something else, so it is
        taken to fire everything it registers."""
        if event in self.external_fired:
            return True
        mro = self.mro(c)
        modules = {k.module for k in mro}
        for k in mro:
            if k.fires_dynamic or (k.name != "BaseObject" and "add_event_handler" in k.members):
                return True
            for m in k.fired.get(event, ()):
                if not m.startswith("_") or m.startswith("__"):
                    return True
                if any(self.refs[mod][m] for mod in modules):
                    return True
        return False

    def constants_for(self, module):
        """Constants visible in `module`: its own, plus ones it imports."""
        out = {}
        for name, (src, orig) in self.module_imports.get(module, {}).items():
            v = self.module_constants.get(src, {}).get(orig)
            if v is not None:
                out[name] = v
        out.update(self.module_constants.get(module, {}))
        return out

    def has_member(self, c, name, seen=None):
        seen = seen or set()
        if c.name in seen:
            return False
        seen.add(c.name)
        if name in c.members or name in c.fields:
            return True
        return any(self.has_member(bc, name, seen) for b in c.bases if (bc := self.base(c, b)))

    def deprecation(self, cls, param):
        """Registry entry for `cls.param`, looked up through the class's bases."""
        seen = set()
        stack = [cls]
        while stack:
            c = stack.pop()
            if c.name in seen:
                continue
            seen.add(c.name)
            d = self.deprecated.get(f"{c.name}.{param}")
            if d:
                return d
            stack += [bc for b in c.bases if (bc := self.base(c, b))]
        return None


# --------------------------------------------------------------------------
# Page side
# --------------------------------------------------------------------------

PARAMFIELD_RE = re.compile(r"<ParamField\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>(.*?)</ParamField>", re.S)
ATTR_RE = re.compile(r"(\w+)(?:=(?:\"([^\"]*)\"|'([^']*)'|\{([^}]*)\}))?")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
IMPORT_RE = re.compile(r"^\s*from\s+(pipecat[\w.]*)\s+import\s+\(?([^)\n]*)", re.M)
NAME_CELL_RE = re.compile(r"^`([A-Za-z_][\w.]*)`")
EVENT_RE = re.compile(r"\bon_[a-z0-9_]+\b")
CLASSLIKE_RE = re.compile(r"\b[A-Z][A-Za-z0-9]+\b")


@dataclass
class Entry:
    name: str
    type: str | None
    default: str | None
    deprecated: bool
    line: int


@dataclass
class Group:
    kind: str  # "params" (ParamField) or "table"
    heading: str
    line: int
    entries: list[Entry]
    chain: list[str] = field(default_factory=list)  # enclosing headings, nearest first


@dataclass
class Page:
    community: bool
    path: str
    groups: list[Group]
    classes: dict[str, str | None]  # class name -> module hint from imports
    events: set[str]
    # event -> the classes whose sections name it (`## FooService` above an
    # Event Handlers heading); None for a mention outside any class section
    event_sections: dict[str, set[str | None]] = field(default_factory=dict)


def split_row(line):
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [c.strip() for c in cells[1:-1]]


def parse_page(path):
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    in_code = []
    fence = False
    for ln in lines:
        if FENCE_RE.match(ln):
            in_code.append(True)
            fence = not fence
            continue
        in_code.append(fence)

    headings = []  # (line_no, level, text)
    for i, ln in enumerate(lines):
        if not in_code[i]:
            m = HEADING_RE.match(ln)
            if m:
                headings.append((i + 1, len(m.group(1)), m.group(2).strip("` ")))

    def heading_at(line_no):
        """(line of the nearest heading, its text, enclosing heading texts)."""
        stack = []  # (level, line, text)
        for hl, lvl, t in headings:
            if hl > line_no:
                break
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, hl, t))
        if not stack:
            return 0, "", []
        return stack[-1][1], stack[-1][2], [t for _, _, t in reversed(stack)]

    classes: dict[str, str | None] = {}
    for m in IMPORT_RE.finditer(text):
        for name in m.group(2).split(","):
            name = name.strip().split(" as ")[0].strip()
            if name:
                classes[name] = m.group(1)
    # In order of first mention, not set order: a tie between two classes'
    # targets goes to the first in this dict, so it must not vary by run.
    for tok in dict.fromkeys(CLASSLIKE_RE.findall(text)):
        classes.setdefault(tok, None)

    groups: dict[tuple, Group] = {}
    for m in PARAMFIELD_RE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        attrs = {}
        for a in ATTR_RE.finditer(m.group(1)):
            k = a.group(1)
            v = next((g for g in a.group(2, 3, 4) if g is not None), True)
            attrs[k] = v
        name = attrs.get("path") or attrs.get("query") or attrs.get("body")
        if not isinstance(name, str):
            continue
        body = m.group(2)
        deprecated = "deprecated" in attrs or bool(re.search(r"deprecated", body, re.I))
        hl, ht, chain = heading_at(line_no)
        g = groups.setdefault(("params", hl), Group("params", ht, hl, [], chain))
        g.entries.append(
            Entry(
                name,
                attrs.get("type") if isinstance(attrs.get("type"), str) else None,
                attrs.get("default") if isinstance(attrs.get("default"), str) else None,
                deprecated,
                line_no,
            )
        )

    i = 0
    while i < len(lines):
        if in_code[i] or not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        start = i
        rows = []
        while i < len(lines) and lines[i].lstrip().startswith("|") and not in_code[i]:
            rows.append((i + 1, lines[i]))
            i += 1
        if len(rows) < 3:
            continue
        header = [h.lower() for h in split_row(rows[0][1])]
        if not header:
            continue
        col = {h: k for k, h in enumerate(header)}
        tcol = next((col[h] for h in col if h.startswith("type")), None)
        dcol = next((col[h] for h in col if h.startswith("default")), None)
        if tcol is None and dcol is None:
            continue  # not a field table (e.g. an events or comparison table)
        entries = []
        for line_no, row in rows[2:]:
            cells = split_row(row)
            if not cells:
                continue
            m = NAME_CELL_RE.match(cells[0])
            if not m:
                continue

            def cell(k):
                if k is None or k >= len(cells):
                    return None
                return cells[k].replace("\\|", "|").strip("` ") or None

            desc = " ".join(cells[1:])
            entries.append(
                Entry(m.group(1), cell(tcol), cell(dcol), bool(re.search(r"deprecated", desc, re.I)), line_no)
            )
        if entries:
            hl, ht, chain = heading_at(start + 1)
            groups[("table", start)] = Group("table", ht, hl, entries, chain)

    events = set()
    event_sections = defaultdict(set)
    for i, ln in enumerate(lines):
        found = EVENT_RE.findall(ln)
        if not found:
            continue
        events.update(found)
        _, _, chain = heading_at(i + 1)
        section = next((h.strip("` ") for h in chain if re.fullmatch(r"[A-Z]\w+", h.strip("` "))), None)
        for ev in found:
            event_sections[ev].add(section)
    community = "CommunityMaintained" in text
    return Page(community, os.path.relpath(path, ROOT), list(groups.values()), classes, events, dict(event_sections))


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------

UNSET = "<unset>"
BUILTIN_CASE = {"List": "list", "Dict": "dict", "Tuple": "tuple", "Set": "set", "Type": "type", "Sequence": "list"}
GENERIC_SETTINGS_MODULE = "pipecat.services.settings"


def norm_default(v, consts, code=False):
    """A comparable default, or None when the value isn't a plain literal."""
    if v is None:
        return None
    v = v.strip().strip("`").strip()
    if not v or v.lower().startswith(("required", "—", "-")) and not re.match(r"^-\d", v):
        return None
    v = consts.get(v, v)
    v = re.sub(r"\.value$", "", v)  # `Model.PULSE.value`: compare as the member
    if v == "None":
        return "x:None"
    if v in ("NOT_GIVEN", "NotGiven", "NotGiven()") or v.endswith("_NOT_GIVEN"):
        return UNSET
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return "s:" + v[1:-1]
    try:
        return "n:" + repr(float(v.replace("_", "")))
    except ValueError:
        pass
    if re.fullmatch(r"[A-Za-z_][\w.]*", v):
        if code and "." not in v and not v[:1].isupper():
            return None  # a local variable (`voice=voice`), not a literal
        return "x:" + v
    if re.fullmatch(r"[\[(].*[\])]", v):
        return "x:" + re.sub(r"\s+", "", v.replace("'", '"'))
    return None  # an expression: not compared


def type_bases(t, aliases=None, depth=0, code=False):
    """The set of outer type names in a union, ignoring None and NotGiven.

    In code, a quoted member is a forward reference; on a page, a quoted
    member is a string literal.
    """
    if not t:
        return None
    t = re.sub(r"\s*\((?:optional|required)\)", "", t, flags=re.I)
    t = t.replace("typing.", "").replace("`", "").replace("\\|", "|").strip()
    if code and re.fullmatch(r"([\"']).*\1", t):
        t = t[1:-1]  # the whole annotation is a forward reference
    t = re.sub(r"^(?:Not)?Required\[(.*)\]$", r"\1", t)  # TypedDict keys
    t = re.sub(r"^Optional\[(.*)\]$", r"\1", t.strip())
    m = re.fullmatch(r"Union\[(.*)\]", t.replace(" ", ""))
    if m:
        t = m.group(1).replace(",", "|")
    out = set()
    for part in split_union(t):
        part = part.strip()
        if code and re.fullmatch(r"[\"'][\w.]+[\"']", part):
            part = part[1:-1]  # forward reference
        outer = part.split("[")[0].strip()
        outer = outer.split(".")[-1] if re.fullmatch(r"[\w.]+", outer) else outer
        if outer in ("None", "") or outer.endswith("NotGiven"):
            continue
        if re.fullmatch(r"[\"'].*[\"']", part):
            out.add("str")
            continue
        if aliases and outer in aliases and depth < 3:
            out |= type_bases(aliases[outer], aliases, depth + 1, code=True) or set()
            continue
        if outer.endswith("Settings"):
            outer = "Settings"
        if part == "Literal":
            return None  # a bare `Literal` on a page says too little to compare
        if outer == "Literal":
            inner = part[part.find("[") + 1 : -1]
            outer = "str" if re.match(r"\s*[\"']", inner) else "literal"
        out.add(BUILTIN_CASE.get(outer, TYPE_WORDS.get(outer, outer)))
    return out


def split_union(t):
    depth = 0
    parts, cur = [], ""
    for ch in t:
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


@dataclass
class Target:
    """Something a group of entries documents: a class's parameters, its
    Settings fields, or the fields of a dataclass/model."""

    cls: Cls
    mode: str  # "params" | "settings" | "fields"
    spec: dict  # name -> Param, with Pipecat's default in Param.default
    owner: Cls  # class deprecations are looked up on

    @property
    def key(self):
        return (self.cls.name, self.mode)


def targets_for(c, idx):
    out = []
    params = idx.effective_params(c)
    if params:
        out.append(Target(c, "params", params, c))
    sc = idx.settings_class(c)
    if sc:
        defaults = idx.effective_default_settings(c)
        spec = {}
        for n, f in idx.effective_fields(sc).items():
            spec[n] = Param(n, f.annotation, defaults.get(n, f.default), f.owner)
        out.append(Target(c, "settings", spec, sc))
    fields = idx.effective_fields(c)
    if fields and not params:
        out.append(Target(c, "fields", fields, c))
    return out


class Checker:
    def __init__(self, idx):
        self.idx = idx
        self.consts = {}
        seen = Counter()
        for consts in idx.module_constants.values():
            for k, v in consts.items():
                seen[k] += 1
                self.consts[k] = v
        for k, n in seen.items():
            if n > 1:
                del self.consts[k]  # ambiguous across modules
        # Short names of nested classes (`InputParams`, `Params`) name a
        # different class on every page; only an import can say which.
        self.generic = {n.split(".")[-1] for n in idx.by_name if "." in n}
        self.matches = []  # (page, group, target)
        self.documented = defaultdict(set)  # (page, class) -> names
        self.coverage = Counter()  # (class, mode, page) -> entries
        self.page_events = {}
        self.pages = {}
        self.findings = []

    def add(self, kind, page, line, cls, name, detail):
        self.findings.append(
            {"kind": kind, "page": page, "line": line, "class": cls, "name": name, "detail": detail}
        )

    def page_targets(self, page):
        """Targets for every class the page names, keyed by the names a
        heading might use for them (`Foo`, `Foo.InputParams`, `InputParams`)."""
        by_alias = defaultdict(list)
        all_targets = []
        for name, hint in page.classes.items():
            if hint is None and name in self.generic:
                continue
            c = self.idx.get(name, hint)
            if not c:
                continue
            nested = [n for n in self.idx.by_name if n.startswith(c.name + ".")]
            for cc, aliases in [(c, [c.name])] + [
                (self.idx.by_name[n][0], [n, n.split(".")[-1]]) for n in nested
            ]:
                for t in targets_for(cc, self.idx):
                    all_targets.append(t)
                    for a in aliases:
                        by_alias[a].append(t)
        return by_alias, all_targets

    def match_group(self, g, by_alias, all_targets):
        # A table under a method's heading (`### job_group`) documents that
        # method's parameters, not a class.
        if g.chain and re.fullmatch(r"[a-z_]\w*(\(.*\))?(\s*->.*)?", g.chain[0].strip("` ")):
            return None
        names = {e.name.split(".")[0] for e in g.entries}
        wants_settings = any("setting" in h.lower() for h in g.chain[:1])
        # 1. A class named in the enclosing headings.
        for heading in g.chain:
            toks = re.findall(r"[A-Z][\w]*(?:\.[A-Z]\w*)*", heading)
            for tok in toks:
                cands = by_alias.get(tok, []) + by_alias.get(tok.split(".")[-1], [])
                cands = [t for t in cands if names & set(t.spec)]
                if not cands:
                    continue
                if wants_settings:
                    cands.sort(key=lambda t: t.mode != "settings")
                else:
                    cands.sort(key=lambda t: -len(names & set(t.spec)))
                return cands[0]
        # 2. Otherwise the best overlap, if it is convincing.
        best, best_score = None, 0.0
        for t in all_targets:
            hit = len(names & set(t.spec))
            score = hit / len(names)
            if hit >= min(2, len(names)) and (score, -len(t.spec)) > (best_score, -len(best.spec) if best else 0):
                best, best_score = t, score
        return best if best_score >= 0.6 else None

    def check_page(self, page):
        if page.community:
            return  # integrations maintained outside pipecat
        self.pages[page.path] = page
        by_alias, all_targets = self.page_targets(page)
        self.page_events[page.path] = page.events
        for g in page.groups:
            t = self.match_group(g, by_alias, all_targets)
            if not t:
                continue
            self.matches.append((page, g, t))
            self.coverage[(t.cls.name, t.mode, page.path)] += len(g.entries)
            for e in g.entries:
                self.documented[(page.path, t.cls.name)].add(e.name.split(".")[0])
            for e in g.entries:
                self.check_entry(page, t, e)

    def check_entry(self, page, t, e):
        if e.name.startswith("*") or "(" in e.name:
            return  # `**kwargs`, or a method row in a table
        top = e.name.split(".")[0]
        p = t.spec.get(top)
        if p is None and t.mode != "settings" and self.idx.has_member(t.cls, top):
            return  # an attribute, property, or method documented alongside
        if p is None:
            kind = "stale-setting" if t.mode == "settings" else "stale-param"
            what = "field" if t.mode != "params" else "parameter"
            owner = t.owner.name if t.mode == "settings" else t.cls.name
            self.add(kind, page.path, e.line, t.cls.name, e.name, f"`{owner}` has no {what} `{top}`")
            return
        if "." in e.name:
            return
        dep = self.idx.deprecation(t.owner, p.name)
        if dep and not e.deprecated:
            self.add(
                "unmarked-deprecation", page.path, e.line, t.cls.name, e.name,
                f"deprecated in {dep.get('deprecated_in')}" + (f"; use {dep['replacement']}" if dep.get("replacement") else ""),
            )
        consts = {**self.consts, **self.idx.constants_for(t.owner.module), **t.cls.class_constants, **t.owner.class_constants}
        doc, src = norm_default(e.default, consts), norm_default(p.default, consts, code=True)
        same = doc == src or (
            doc and src and doc[0] in "xs" and src[0] in "xs"
            and doc[2:].lower() in (src[2:].lower(), src[2:].split(".")[-1].lower())
        )
        # `None` on a page for a field Pipecat leaves NOT_GIVEN is fine: both
        # mean "not sent". `NOT_GIVEN` on a page where Pipecat sets a value
        # (including `None`) is not.
        same = same or (doc == "x:None" and src == UNSET)
        if doc and src and not same:
            self.add("default-mismatch", page.path, e.line, t.cls.name, e.name, f"page `{e.default}`, code `{p.default}`")
        dt = type_bases(e.type, self.idx.type_aliases)
        st = type_bases(p.annotation, self.idx.type_aliases, code=True)
        if dt and st and dt != st and "Any" not in dt | st:
            self.add("type-mismatch", page.path, e.line, t.cls.name, e.name, f"page `{e.type}`, code `{p.annotation}`")

    def home_pages(self):
        """Each class's reference page: where the most of it is documented."""
        best = {}
        for (cls, mode, page), n in self.coverage.items():
            if mode == "fields":
                continue
            if cls not in best or n > best[cls][1]:
                best[cls] = (page, n)
        return {cls: page for cls, (page, _) in best.items()}

    def completeness(self):
        homes = self.home_pages()
        done = set()
        # (page, event) -> the page's classes that register it. A page that
        # documents a WebSocket and an HTTP variant names their events once,
        # so an event is unfired only when none of them fires it.
        unfired = defaultdict(list)
        for page, g, t in self.matches:
            if homes.get(t.cls.name) != page.path or (t.key, page.path) in done or t.mode == "fields":
                continue
            # Only a page that presents the class as its subject: named in a
            # heading or imported. Thin subclasses' pages often show a base's
            # parameters without being its reference.
            named = page.classes.get(t.cls.name) is not None or any(
                t.cls.name in h for gg in page.groups for h in gg.chain
            )
            if not named:
                continue
            done.add((t.key, page.path))
            documented = self.documented[(page.path, t.cls.name)]
            line = min(gg.line for pp, gg, tt in self.matches if pp is page and tt.key == t.key)
            if t.mode == "params":
                c = t.cls
                own = c.params if c.params is not None else []
                has_settings = any(tt.mode == "settings" for pp, gg, tt in self.matches if pp is page and tt.cls is c)
                for p in own:
                    if p.name in documented or p.name.startswith("_"):
                        continue
                    if p.name == "settings" and has_settings:
                        continue
                    dep = self.idx.deprecation(c, p.name)
                    kind = "missing-deprecated" if dep else "missing-param"
                    self.add(kind, page.path, line, c.name, p.name, f"`{c.name}.__init__` takes `{p.name}`")
                for ev in sorted(self.idx.effective_events(c) - self.page_events[page.path]):
                    if not self.idx.fires(c, ev):
                        continue  # never fired: leaving it off the page is right
                    self.add("missing-event", page.path, 0, c.name, ev, f"`{c.name}` registers `{ev}`")
                for ev, sections in page.event_sections.items():
                    if not self.idx.registers(c, ev):
                        continue
                    if c.name in sections and not self.idx.fires(c, ev):
                        self.add("unfired-event", page.path, 0, c.name, ev, f"`{c.name}` registers it, but nothing fires it")
                    if None in sections:
                        unfired[(page.path, ev)].append(c)
            elif t.mode == "settings":
                for name, p in t.spec.items():
                    if name in documented:
                        continue
                    # Fields from another package's settings (Grok's from
                    # OpenAI's) are documented there; the page links to them.
                    owner = self.idx.get(p.owner, None)
                    if owner and package_of(owner.module) != package_of(t.cls.module):
                        continue
                    dep = self.idx.deprecation(t.owner, name)
                    kind = "missing-deprecated" if dep else "missing-setting"
                    self.add(kind, page.path, line, t.cls.name, name, f"`{t.owner.name}` has field `{name}`")
        for (path, ev), classes in sorted(unfired.items()):
            if not any(self.idx.fires(c, ev) for c in classes):
                names = ", ".join(f"`{c.name}`" for c in classes)
                self.add("unfired-event", path, 0, classes[0].name, ev, f"registered by {names}, but nothing fires it")


# --------------------------------------------------------------------------
# Code samples
# --------------------------------------------------------------------------


CODE_RE = re.compile(r"^([ \t]*)```(?:python|py)\b[^\n]*\n(.*?)^[ \t]*```", re.S | re.M)
SAMPLE_IMPORT_RE = re.compile(r"^\s*from\s+(pipecat[\w.]*)\s+import\s+(\([^)]*\)|[^\n]*)", re.M)


def samples(text):
    """(first line number, source) of each Python code block."""
    out = []
    for m in CODE_RE.finditer(text):
        indent, body = m.group(1), m.group(2)
        if indent:
            body = "\n".join(ln[len(indent):] if ln.startswith(indent) else ln for ln in body.split("\n"))
        out.append((text.count("\n", 0, m.start(2)) + 1, body))
    return out


def check_samples(checker, page, text):
    """Check each Python sample's calls against the source: keywords a
    constructor doesn't accept, required arguments left out, attributes an
    object doesn't have, events a class never registers."""
    idx = checker.idx
    imported = {}  # local name -> (class name, module)
    for m in SAMPLE_IMPORT_RE.finditer(text):
        for name in m.group(2).strip("()").replace("\n", " ").split(","):
            name = name.strip()
            if not name or name.startswith("#"):
                continue
            orig, _, alias = name.partition(" as ")
            imported[(alias or orig).strip()] = (orig.strip(), m.group(1))

    def resolve(name):
        if name in imported:
            orig, mod = imported[name]
            return idx.get(orig, mod) or idx.get(orig)
        # Samples often leave out imports; a name only one pipecat class has
        # is still that class, unless the sample defines it.
        if name[:1].isupper() and name not in local and name not in checker.generic:
            cands = idx.by_name.get(name, [])
            return cands[0] if len(cands) == 1 else None
        return None

    def class_of(node, bound):
        """The class a call's callee names: `Foo`, `Foo.Settings`, `Foo.InputParams`."""
        if isinstance(node, ast.Name):
            return resolve(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            outer = resolve(node.value.id)
            if outer is None:
                return None
            if node.attr == "Settings":
                return idx.settings_class(outer)
            return idx.get(f"{outer.name}.{node.attr}")
        return None

    own = frozenset(re.findall(r"[A-Z]\w+", " ".join(re.findall(r"^(?:#+ |title: ).*$", text, re.M))))
    local = set()  # names the page's samples define themselves
    trees = []
    for i, (start, src) in enumerate(samples(text)):
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        trees.append((start, tree))
        if i == 0:
            check_first_sample(checker, page, start, tree)
        check_env(checker, page, start, tree, "CommunityMaintained" in text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                local.add(node.name)
    for start, tree in trees:
        bound = {}  # variable -> class of the object assigned to it
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                c = class_of(node.value.func, bound)
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        if c:
                            bound[t.id] = c
                        else:
                            bound.pop(t.id, None)
        for node in ast.walk(tree):
            line = start + getattr(node, "lineno", 1) - 1
            if isinstance(node, ast.Call):
                c = class_of(node.func, bound)
                if c:
                    check_call(checker, page, line, c, node, own)
                elif (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in bound
                ):
                    c = bound[node.func.value.id]
                    attr = node.func.attr
                    if attr == "event_handler" and node.args and isinstance(node.args[0], ast.Constant):
                        ev = node.args[0].value
                        if isinstance(ev, str) and not idx.registers(c, ev):
                            checker.add("sample-unknown-event", page, line, c.name, ev, f"`{c.name}` never registers `{ev}`")
                    elif not attr.startswith("__") and not idx.has_attr(c, attr):
                        checker.add("sample-unknown-attr", page, line, c.name, attr, f"`{c.name}` has no `{attr}`")
                    else:
                        check_method_call(checker, page, line, c, attr, node)


# Standard-library modules a sample may use as `mod.attr`. A sample can't use
# one without importing it, and no reader variable is named like these.
STDLIB_MODULES = {
    "argparse", "asyncio", "base64", "collections", "contextlib", "dataclasses",
    "datetime", "enum", "functools", "hashlib", "hmac", "inspect", "io",
    "itertools", "json", "logging", "math", "os", "pathlib", "random", "re",
    "secrets", "shutil", "signal", "socket", "struct", "subprocess", "sys",
    "tempfile", "threading", "time", "traceback", "typing", "urllib", "uuid",
    "wave", "zoneinfo",
}


def bound_names(tree):
    """Names a sample binds: imports, assignments, definitions, parameters.
    None when it star-imports, so anything may be bound."""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name == "*":
                    return None
                out.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            out.add(n.name)
    return out


def is_signature(tree):
    """A block of signatures (`def f(x: Foo) -> Bar: ...`), not a sample."""
    def stub(body):
        return all(
            isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and (b.value.value is Ellipsis or isinstance(b.value.value, str))
            for b in body
        )
    return bool(tree.body) and all(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and stub(n.body)
        or isinstance(n, ast.ClassDef) and all(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and stub(m.body) or stub([m]) for m in n.body)
        for n in tree.body
    )


def check_first_sample(checker, page, start, tree):
    """The first sample on a page has complete imports (STYLE.md). Flag a name
    it uses without importing or defining, when the name can only be one
    thing: a standard-library module used as `mod.attr`, or a class pipecat
    defines. Other free names (`llm`, `context`) are the reader's to infer."""
    bound = bound_names(tree)
    if bound is None or is_signature(tree):
        return
    seen = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Name) or not isinstance(n.ctx, ast.Load) or n.id in bound or n.id in seen:
            continue
        line = start + n.lineno - 1
        if n.id in STDLIB_MODULES:
            if any(isinstance(p, ast.Attribute) and p.value is n for p in ast.walk(tree)):
                seen.add(n.id)
                checker.add("sample-undefined-name", page, line, n.id, n.id, f"uses `{n.id}` without `import {n.id}`")
        elif n.id in checker.idx.top_level and n.id[:1].isupper() and n.id not in checker.generic:
            seen.add(n.id)
            checker.add("sample-undefined-name", page, line, n.id, n.id, f"uses pipecat's `{n.id}` without importing it")


def env_read(n):
    """X when `n` is `os.getenv("X")`, `os.environ.get("X")`, or `os.environ["X"]`."""
    arg = None
    if isinstance(n, ast.Call) and n.args and unparse(n.func) in ("os.getenv", "getenv", "os.environ.get", "environ.get"):
        arg = n.args[0]
    elif isinstance(n, ast.Subscript) and unparse(n.value) in ("os.environ", "environ"):
        arg = n.slice
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


# Prefixes of made-up variables a sample uses to stand for "your provider".
PLACEHOLDER_ENV = ("MY_", "YOUR_", "OTHER_", "SOME_", "CUSTOM_", "EXAMPLE_", "PROVIDER_", "SERVICE_")


def check_env(checker, page, start, tree, community):
    """An API key a sample hands to a pipecat class under a name pipecat
    never uses: not in env.example, the source, or the examples. A reader's
    `.env`, built from env.example, won't have it (`GROK_API_KEY` where
    pipecat reads `XAI_API_KEY`). Other variables (endpoints, a platform's
    own settings, a community package's key) are the reader's to name."""
    if community:
        return
    idx = checker.idx
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or unparse(call.func).split(".")[0] not in idx.by_name:
            continue
        for v in call.args + [kw.value for kw in call.keywords]:
            name = env_read(v)
            if name and name.endswith("_API_KEY") and not name.startswith(PLACEHOLDER_ENV) and name not in idx.env_names:
                line = start + v.lineno - 1
                checker.add("sample-unknown-env", page, line, unparse(call.func), name, f"pipecat's env.example and examples never use `{name}`")


def deprecated_detail(dep):
    return f"deprecated in {dep.get('deprecated_in')}" + (f"; use {dep['replacement']}" if dep.get("replacement") else "")


def check_method_call(checker, page, line, c, name, call):
    """A call to a method of `c`: the method itself, or an argument passed to
    it, may be deprecated."""
    idx = checker.idx
    dep = idx.deprecation(c, name)
    if dep and dep.get("kind") == "method":
        checker.add("sample-deprecated-call", page, line, c.name, name, deprecated_detail(dep))
        return
    params = idx.method_params(c, name) or []
    passed = [p for p, a in zip(params, call.args) if not isinstance(a, ast.Starred)]
    passed += [kw.arg for kw in call.keywords if kw.arg]
    for p in passed:
        dep = idx.deprecation(c, f"{name}.{p}")
        if dep and dep.get("kind") == "parameter":
            checker.add("sample-deprecated-arg", page, line, c.name, f"{name}({p})", deprecated_detail(dep))


def check_call(checker, page, line, c, call, own=frozenset()):
    idx = checker.idx
    dep = idx.deprecated.get(c.name)
    # A page that documents the deprecated class itself (it names it in its
    # title or a heading) shows it on purpose. A class entry whose message
    # doesn't name the class records something else (an event, say).
    if dep and dep.get("kind") == "class" and c.name not in own and c.name in dep.get("message", ""):
        checker.add("sample-deprecated-call", page, line, c.name, c.name, deprecated_detail(dep))
    ctor = idx.constructor(c)
    if ctor is None:
        return
    spec, order, required, closed = ctor
    if any(isinstance(a, ast.Starred) for a in call.args) or any(kw.arg is None for kw in call.keywords):
        return  # `*args` / `**kwargs`: can't tell what is passed
    if any(isinstance(a, ast.Constant) and a.value is Ellipsis for a in call.args):
        return  # `Frame(...)`: a placeholder, not a call
    given = set(order[: len(call.args)]) | {kw.arg for kw in call.keywords}
    for kw in call.keywords:
        if kw.arg not in spec:
            if closed:
                checker.add("sample-unknown-arg", page, line, c.name, kw.arg, f"`{c.name}(...)` takes no `{kw.arg}`")
            continue
        dep = idx.deprecation(c, kw.arg)
        if dep:
            checker.add(
                "sample-deprecated-arg", page, line, c.name, kw.arg,
                f"deprecated in {dep.get('deprecated_in')}" + (f"; use {dep['replacement']}" if dep.get("replacement") else ""),
            )
    if order or not call.args:
        for name in sorted(required - given):
            checker.add("sample-missing-arg", page, line, c.name, name, f"`{c.name}(...)` requires `{name}`")


# --------------------------------------------------------------------------
# Install extras
# --------------------------------------------------------------------------

EXTRA_RE = re.compile(r"pipecat-ai\[([^\]\n]*)\]")


def norm_extra(name):
    """PEP 685: extras compare lower-cased, with runs of `-_.` as `-`."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def pipecat_extras(pipecat):
    """The extras pipecat's pyproject.toml declares, normalized."""
    import tomllib

    path = os.path.join(pipecat, "pyproject.toml")
    if not os.path.exists(path):
        return set()  # the decay alarm reports it
    with open(path, "rb") as f:
        deps = tomllib.load(f).get("project", {}).get("optional-dependencies", {})
    return {norm_extra(k) for k in deps}


def check_extras(checker, page, text, extras):
    """Flag a `pipecat-ai[...]` install extra pipecat doesn't declare."""
    for m in EXTRA_RE.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        for name in m.group(1).split(","):
            name = name.strip()
            if name and norm_extra(name) not in extras:
                checker.add("unknown-extra", page, line, "pipecat-ai", name, f"pipecat's pyproject.toml declares no `{name}` extra")


# --------------------------------------------------------------------------
# Class names in prose
# --------------------------------------------------------------------------

# Pages that name classes from other packages: the client SDKs (JavaScript,
# Swift, Kotlin) and the Pipecat Cloud SDK.
PROSE_SKIP = ("client/", "api-reference/client/", "api-reference/pipecat-cloud/")
# Endings that mark a name as a pipecat class. Endings that libraries share
# (`Error`, `Config`, `Client`, `Manager`, `Message`) are left out.
CLASS_SUFFIXES = (
    "Service", "Transport", "Frame", "Processor", "Serializer", "Params",
    "Observer", "Strategy", "Filter", "Analyzer", "Aggregator", "Settings",
    "Runner", "Worker", "Adapter", "Mixer", "Detector", "Classifier",
)
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
# A name inside a code span, not part of a placeholder (`*UpdateSettingsFrame`,
# `{Provider}TTSService`, `<Name>Service`).
PROSE_NAME_RE = re.compile(r"(?<![\w*<>{}$-])[A-Z]\w*(?![\w*<>{}])")
# A line or section about an API that is gone: it may name it.
HISTORY_RE = re.compile(r"\b(?:remov|renam|replac|deprecat|formerly|previously|no longer|legacy|migrat|used to)", re.I)

CLIENT_LANG_RE = re.compile(r"\b(?:JavaScript|TypeScript|React|Swift|Kotlin|Android|iOS)\b")


def check_prose(checker, page, text):
    """Flag a backticked class name in the page's prose, tables, or
    ParamFields that pipecat has nowhere in its source or examples."""
    if page.startswith(PROSE_SKIP) or "CommunityMaintained" in text:
        return
    idx = checker.idx
    defined = set()  # names the page's own samples define
    for _, src in samples(text):
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        defined |= bound_names(tree) or set()
    headings = {}  # level -> heading text
    fence = False
    for i, ln in enumerate(text.split("\n"), 1):
        if FENCE_RE.match(ln):
            fence = not fence
            continue
        if fence:
            continue
        m = HEADING_RE.match(ln)
        if m:
            level = len(m.group(1))
            headings = {k: v for k, v in headings.items() if k < level}
            headings[level] = m.group(2)
            continue
        if HISTORY_RE.search(ln) or any(HISTORY_RE.search(h) for h in headings.values()):
            continue
        if CLIENT_LANG_RE.search(ln):
            continue  # "in JavaScript, `URLSearchParams`": a name from the client side
        for span in CODE_SPAN_RE.finditer(ln):
            # "`MiniMaxHttpTTSService`, not `MiniMaxTTSService`" names the
            # wrong spelling on purpose.
            if re.search(r"\b(?:not|instead of|rather than)\s*$", ln[: span.start()]):
                continue
            for name in PROSE_NAME_RE.findall(span.group(1)):
                if (
                    name.endswith(CLASS_SUFFIXES)
                    and name not in CLASS_SUFFIXES
                    and re.search(r"[a-z]", name)
                    and name not in idx.identifiers
                    and name not in defined
                ):
                    checker.add("prose-unknown-name", page, i, name, name, f"pipecat has no `{name}`")


# --------------------------------------------------------------------------
# CLI reference
# --------------------------------------------------------------------------

# CLI pages documented from pipecat's own Typer app (src/pipecat/cli). A page
# whose headings don't name a command documents the command named like it.
CLI_PAGES = ("api-reference/cli/init.mdx", "api-reference/cli/eval.mdx")


@dataclass
class CliOption:
    flags: set[str]  # every spelling: `--name`, `-n`, `--no-recording`
    default: str | None  # unparsed; None when not set
    deprecated: bool


def _typer_call(node, kind):
    return (
        isinstance(node, ast.Call)
        and getattr(node.func, "attr", getattr(node.func, "id", None)) == kind
    )


def cli_commands(pipecat):
    """{"eval run": {long flag: CliOption}} for pipecat's own CLI commands."""
    root = os.path.join(pipecat, "src", "pipecat", "cli")
    funcs, registrations, groups = {}, [], {}
    for dirpath, _, filenames in walk(root):
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            tree = ast.parse(open(os.path.join(dirpath, fn), encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs[node.name] = node
                    for d in node.decorator_list:
                        if _typer_call(d, "command") and isinstance(d.func, ast.Attribute):
                            registrations.append((unparse(d.func.value), d, node.name))
                elif (
                    isinstance(node, ast.Call)
                    and _typer_call(node.func, "command")
                    and isinstance(node.func.func, ast.Attribute)
                    and node.args
                    and isinstance(node.args[0], ast.Name)
                ):  # `app.command("init")(init_command)`
                    registrations.append((unparse(node.func.func.value), node.func, node.args[0].id))
                elif _typer_call(node, "add_typer") and isinstance(node.func, ast.Attribute) and node.args:
                    name = next((getattr(kw.value, "value", None) for kw in node.keywords if kw.arg == "name"), None)
                    if isinstance(name, str):
                        groups[unparse(node.args[0])] = name
    out = {}
    for app, call, fname in registrations:
        if any(kw.arg == "hidden" and getattr(kw.value, "value", False) for kw in call.keywords):
            continue
        name = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else next(
            (getattr(kw.value, "value", None) for kw in call.keywords if kw.arg == "name"), fname.replace("_", "-")
        )
        if not isinstance(name, str):
            continue
        fn = funcs.get(fname)
        if fn is None:
            continue
        path = f"{groups[app]} {name}" if app in groups else name
        out[path] = cli_options(fn)
    return out


def cli_options(fn):
    a = fn.args
    args = a.posonlyargs + a.args + a.kwonlyargs
    defaults = [None] * (len(a.posonlyargs + a.args) - len(a.defaults)) + list(a.defaults) + list(a.kw_defaults)
    opts = {}
    for arg, d in zip(args, defaults):
        call = d if _typer_call(d, "Option") else None
        if call is None and isinstance(arg.annotation, ast.Subscript) and unparse(arg.annotation.value).endswith("Annotated"):
            call = next((e for e in getattr(arg.annotation.slice, "elts", []) if _typer_call(e, "Option")), None)
        if call is None:
            continue  # an Argument, or not a CLI parameter
        kw = {k.arg: k.value for k in call.keywords}
        if getattr(kw.get("hidden"), "value", False):
            continue
        decls = [x.value for x in call.args if isinstance(x, ast.Constant) and isinstance(x.value, str) and x.value.startswith("-")]
        if call is d and call.args and not (isinstance(call.args[0], ast.Constant) and str(call.args[0].value).startswith("-")):
            default = unparse(call.args[0])
        else:
            default = unparse(kw["default"]) if "default" in kw else (unparse(d) if call is not d and d is not None else None)
        flags = {f.strip() for decl in decls for f in decl.split("/")} or {"--" + arg.arg.replace("_", "-")}
        help_ = kw.get("help")
        deprecated = getattr(kw.get("deprecated"), "value", False) or (
            isinstance(help_, ast.Constant) and str(help_.value).lower().startswith("deprecated")
        )
        long = next((f for f in sorted(flags) if f.startswith("--") and not f.startswith("--no-")), sorted(flags)[0])
        opts[long] = CliOption(flags, default, bool(deprecated))
    return opts


def cli_page_sections(path):
    """{command heading or None: [(line, flags, default, deprecated)]} from a CLI page."""
    text = open(os.path.join(ROOT, path), encoding="utf-8").read()
    heads = [(text.count("\n", 0, m.start()) + 1, m.group(1).strip("` ")) for m in re.finditer(r"^#{2,3}\s+(.+)$", text, re.M)]
    out = defaultdict(list)
    for m in PARAMFIELD_RE.finditer(text):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        flags = {f.strip() for f in attrs.get("path", "").split("/")}
        if not any(f.startswith("-") for f in flags):
            continue  # a positional argument
        line = text.count("\n", 0, m.start()) + 1
        section = None
        for hl, h in heads:
            if hl < line:
                section = h
        out[section].append((line, {f for f in flags if f.startswith("-")}, attrs.get("default"), bool(re.search(r"\bdeprecated\b", m.group(1)))))
    return out


def norm_cli_default(v):
    if v is None:
        return None
    v = v.strip().strip("\"'")
    return {"false": "False", "true": "True", "none": "None"}.get(v.lower(), v)


def check_cli(checker, commands):
    for page in CLI_PAGES:
        if not os.path.exists(os.path.join(ROOT, page)):
            continue
        stem = os.path.splitext(os.path.basename(page))[0]
        sections = cli_page_sections(page)
        documented = set()
        for section, entries in sections.items():
            cmd = section if section in commands else (stem if stem in commands else None)
            if cmd is None:
                continue
            documented.add(cmd)
            opts = commands[cmd]
            seen = set()
            for line, flags, default, deprecated in entries:
                o = next((o for o in opts.values() if flags & o.flags), None)
                if o is None:
                    checker.add("cli-stale-option", page, line, cmd, " / ".join(sorted(flags)), f"`pipecat {cmd}` has no such option")
                    continue
                seen.add(id(o))
                for f in sorted(flags - o.flags):
                    checker.add("cli-stale-option", page, line, cmd, f, f"`pipecat {cmd}` has no `{f}`")
                missing_short = {f for f in o.flags if not f.startswith("--")} - flags
                for f in sorted(missing_short):
                    checker.add("cli-missing-option", page, line, cmd, f, f"`pipecat {cmd}` also accepts `{f}`")
                dd, sd = norm_cli_default(default), norm_cli_default(checker.consts.get(o.default, o.default))
                try:
                    same = float(dd) == float(sd)
                except (TypeError, ValueError):
                    same = dd == sd
                if dd and sd and sd not in ("None", "...") and not same:
                    checker.add("cli-default-mismatch", page, line, cmd, sorted(flags)[0], f"page `{default}`, code `{o.default}`")
                if o.deprecated and not deprecated:
                    checker.add("cli-unmarked-deprecation", page, line, cmd, sorted(flags)[0], "deprecated in the CLI's help")
            for long, o in sorted(opts.items()):
                if id(o) not in seen and not o.deprecated:
                    checker.add("cli-missing-option", page, 0, cmd, long, f"`pipecat {cmd}` takes `{long}`")
        group = stem
        for cmd in sorted(commands):
            if cmd.split(" ")[0] == group and cmd not in documented:
                checker.add("cli-missing-command", page, 0, cmd, cmd, f"`pipecat {cmd}` has no section")


# --------------------------------------------------------------------------
# Decay alarm
# --------------------------------------------------------------------------

# Every rule depends on a pipecat convention: `Settings = ...` on a service,
# `default_settings = self.Settings(...)`, `_register_event_handler` and
# `_call_event_handler`, deprecations.json, pyproject extras, the Typer CLI. If
# pipecat changes one, the rules built on it find nothing and the check passes
# without checking. So the checker counts what it read and fails when a count
# drops below its floor: about half the count against pipecat main on
# 2026-10-15 (in the comments). Deprecations have no floor, as pipecat removes
# them in bulk at a major release; load_deprecations() checks the registry's
# format instead. See scripts/check-reference.md, "Decay alarm".
FLOORS = {
    "classes": 870,  # 1748
    "constructors": 235,  # 472
    "classes with a Settings class": 70,  # 138
    "Settings fields": 600,  # 1218
    "default_settings assignments": 65,  # 132
    "registered events": 130,  # 264
    "fired events": 185,  # 375
    "public top-level names": 850,  # 1708
    "API key names": 33,  # 66
    "install extras": 45,  # 90
    "CLI commands": 2,  # 3
    "CLI options": 27,  # 55
}


def pipecat_counts(idx, extras, commands):
    """How much of each convention the checker found in pipecat."""
    classes = [c for cs in idx.by_name.values() for c in cs]
    settings = {}
    for c in classes:
        if c.settings_ref and (s := idx.settings_class(c)):
            settings[(s.module, s.name)] = s
    return {
        "classes": len(classes),
        "constructors": sum(c.params is not None for c in classes),
        "classes with a Settings class": sum(bool(c.settings_ref) for c in classes),
        "Settings fields": sum(len(idx.effective_fields(s)) for s in settings.values()),
        "default_settings assignments": sum(bool(c.default_settings) for c in classes),
        "registered events": sum(len(c.events) for c in classes),
        "fired events": sum(len(c.fired) for c in classes) + len(idx.external_fired),
        "public top-level names": len(idx.top_level),
        "API key names": sum(n.endswith("_API_KEY") for n in idx.env_names),
        "install extras": len(extras),
        "CLI commands": len(commands),
        "CLI options": sum(len(opts) for opts in commands.values()),
    }


def decayed(counts, floors):
    """(what, count, floor) for each count below its floor."""
    return [(k, counts.get(k, 0), n) for k, n in floors.items() if counts.get(k, 0) < n]


KINDS = [
    "stale-param",
    "stale-setting",
    "missing-param",
    "missing-setting",
    "default-mismatch",
    "unmarked-deprecation",
    "missing-event",
    "unfired-event",
    "missing-deprecated",
    "type-mismatch",
    "sample-unknown-arg",
    "sample-missing-arg",
    "sample-unknown-attr",
    "sample-unknown-event",
    "sample-deprecated-arg",
    "sample-deprecated-call",
    "sample-undefined-name",
    "sample-unknown-env",
    "prose-unknown-name",
    "unknown-extra",
    "cli-stale-option",
    "cli-missing-option",
    "cli-missing-command",
    "cli-default-mismatch",
    "cli-unmarked-deprecation",
    "stale-ignore",
]

TYPE_WORDS = {"string": "str", "integer": "int", "boolean": "bool", "number": "float"}


def load_ignore(path):
    """Confirmed false positives: `page kind name  # why`, one per line.
    Returns {(page, kind, name): line number}."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    for n, line in enumerate(lines, 1):
        line = line.split("#", 1)[0].strip()
        if line:
            try:
                page, kind, name = line.split()
            except ValueError:
                sys.exit(f"{path}:{n}: expected `<page> <kind> <name>  # why`")
            out[(page, kind, name)] = n
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pipecat", default=os.path.join(REPO, "..", "pipecat"))
    ap.add_argument("--docs-root", default=REPO, help="docs tree to check (default: this repo)")
    ap.add_argument("--json")
    ap.add_argument("--page", help="glob, relative to the repo root")
    ap.add_argument(
        "--pages-from",
        help="file listing pages (one per line) to report on; the rest are still read, "
        "since a class's home page is decided across the site",
    )
    ap.add_argument("--only", help="comma-separated finding kinds")
    ap.add_argument("--format", choices=["text", "github", "summary"], default="text")
    ap.add_argument("--ignore", default=os.path.join(REPO, "scripts", "check-reference-ignore.txt"))
    ap.add_argument(
        "--no-decay-alarm",
        action="store_true",
        help="check even if pipecat's code doesn't look as expected (an old or partial checkout); not for CI",
    )
    a = ap.parse_args(argv)

    global ROOT
    ROOT = os.path.abspath(a.docs_root)
    if not os.path.isdir(os.path.join(a.pipecat, "src", "pipecat")):
        sys.exit(f"pipecat source not found at {a.pipecat}; pass --pipecat")
    checker = Checker(SourceIndex(a.pipecat))
    extras = pipecat_extras(a.pipecat)
    commands = cli_commands(a.pipecat)

    # Checked before any page: what the source parse found doesn't depend on
    # which pages are reported.
    low = decayed(pipecat_counts(checker.idx, extras, commands), FLOORS)
    lines = [f"{what}: found {n}, expected at least {floor}" for what, n, floor in low]
    if checker.idx.deprecations_problem:
        lines.append(checker.idx.deprecations_problem)
    if lines and not a.no_decay_alarm:
        msg = (
            "pipecat's code no longer looks like what the checker reads, so the checker probably "
            "no longer understands it and its rules would pass without checking. "
            + "; ".join(lines)
            + ". See scripts/check-reference.md, \"Decay alarm\"."
        )
        print(f"::error::{msg}" if a.format == "github" else f"decay-alarm: {msg}")
        return 2

    pages = 0
    for dirpath, _, filenames in (w for d in PAGE_DIRS for w in walk(os.path.join(ROOT, d))):
        for fn in sorted(filenames):
            if fn.endswith(".mdx"):
                pages += 1
                path = os.path.join(dirpath, fn)
                page = parse_page(path)
                checker.check_page(page)
    # Samples on every page, community ones included: they still call
    # pipecat's own classes, and only those are checked.
    for dirpath, dirnames, filenames in walk(ROOT):
        rel = os.path.relpath(dirpath, ROOT)
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and os.path.normpath(os.path.join(rel, d)) not in SAMPLE_SKIP]
        for fn in sorted(filenames):
            if fn.endswith(".mdx"):
                path = os.path.join(dirpath, fn)
                if not any(os.path.relpath(dirpath, ROOT).startswith(d) for d in PAGE_DIRS):
                    pages += 1
                text = open(path, encoding="utf-8").read()
                check_samples(checker, os.path.relpath(path, ROOT), text)
                check_prose(checker, os.path.relpath(path, ROOT), text)
                check_extras(checker, os.path.relpath(path, ROOT), text, extras)
    checker.completeness()
    check_cli(checker, commands)

    # An ignore entry no finding matches is stale: the page or pipecat changed.
    # Matched against every finding, before the report is narrowed, but only
    # reported on a full run, as a PR's scoped run is no place to clean up.
    ignored = load_ignore(a.ignore)
    if not a.pages_from:
        found = {(f["page"], f["kind"], f["name"]) for f in checker.findings}
        rel = os.path.relpath(a.ignore, ROOT)
        rel = a.ignore if rel.startswith("..") else rel
        for (page, kind, name), n in ignored.items():
            if (page, kind, name) not in found:
                checker.add("stale-ignore", rel, n, kind, name, f"no `{kind}` finding for `{name}` on {page}; remove the entry")

    findings = checker.findings
    if a.page:
        findings = [f for f in findings if fnmatch.fnmatch(f["page"], a.page)]
    if a.pages_from:
        with open(a.pages_from) as f:
            wanted = {line.strip() for line in f if line.strip()}
        findings = [f for f in findings if f["page"] in wanted]
    findings = [f for f in findings if (f["page"], f["kind"], f["name"]) not in ignored]
    if a.only:
        keep = set(a.only.split(","))
        findings = [f for f in findings if f["kind"] in keep]
    seen = set()
    findings = [
        f for f in findings
        if (k := (f["kind"], f["page"], f["class"], f["name"], f["line"])) not in seen and not seen.add(k)
    ]
    findings.sort(key=lambda f: (f["page"], KINDS.index(f["kind"]), f["line"]))

    if a.json:
        with open(a.json, "w") as f:
            json.dump(findings, f, indent=1)
    if a.format == "summary":
        by_kind = Counter(f["kind"] for f in findings)
        by_page = Counter(f["page"] for f in findings)
        print(f"{len(findings)} findings on {len(by_page)} of {pages} pages")
        for k in KINDS:
            print(f"  {k:22} {by_kind.get(k, 0)}")
        print("Most findings:")
        for p, n in by_page.most_common(15):
            print(f"  {n:4}  {p}")
    else:
        for f in findings:
            msg = f"{f['kind']}: `{f['name']}` ({f['class']}): {f['detail']}"
            if a.format == "github":
                print(f"::error file={f['page']},line={f['line'] or 1}::{msg}")
            else:
                print(f"{f['page']}:{f['line']}: {msg}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
