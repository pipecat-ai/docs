#!/usr/bin/env python3
r"""Compare the server API reference pages with the pipecat source.

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

From each page under api-reference/server:
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
  type-mismatch      documented type differs from the annotation

Usage:
  python3 scripts/check-reference.py [--pipecat PATH] [--json FILE]
                                     [--page GLOB] [--only KIND,...]
                                     [--format text|github|summary]

  --pipecat PATH  pipecat checkout (default: ../pipecat, per CLAUDE.md)

Exit code: 1 if any finding is reported, else 0. Standard library only.
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES_DIR = "api-reference/server"


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


@dataclass
class Cls:
    name: str
    module: str
    bases: list[str]
    params: list[Param] | None = None  # None: no __init__ of its own
    var_kwargs: bool = False
    settings_ref: str | None = None
    default_settings: dict[str, str] = field(default_factory=dict)
    events: set[str] = field(default_factory=set)
    fields: dict[str, Param] = field(default_factory=dict)  # dataclass/BaseModel
    constants: dict[str, str] = field(default_factory=dict)
    members: set[str] = field(default_factory=set)  # methods, properties, self.* attributes


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
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in ("tests", "__pycache__")]
            for fn in filenames:
                if fn.endswith(".py"):
                    self._index(os.path.join(dirpath, fn))
        self.deprecated: dict[str, dict] = {}
        dep = os.path.join(pipecat, "scripts", "deprecations", "deprecations.json")
        if os.path.exists(dep):
            for d in json.load(open(dep))["deprecations"]:
                self.deprecated[d["subject"]] = d

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
            elif isinstance(value, (ast.Subscript, ast.BinOp)) and target.id[:1].isupper():
                self.type_aliases[target.id] = unparse(value)
        self.module_constants[module] = consts
        imports = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                for alias in node.names:
                    imports[alias.asname or alias.name] = (node.module, alias.name)
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
        )
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                c.members.add(item.name)
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
            elif isinstance(item, ast.Assign) and len(item.targets) == 1:
                t = item.targets[0]
                if isinstance(t, ast.Name) and t.id == "Settings" and isinstance(item.value, ast.Name):
                    c.settings_ref = item.value.id
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                name = item.target.id
                if not name.startswith("_") and not (
                    isinstance(item.annotation, ast.Subscript)
                    and unparse(item.annotation.value).endswith("ClassVar")
                ):
                    c.fields[name] = Param(name, unparse(item.annotation), field_default(item.value), c.name)
            elif isinstance(item, ast.ClassDef):
                self._add_class(item, module, consts, prefix=c.name + ".")
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "_register_event_handler"
                and sub.args
                and isinstance(sub.args[0], ast.Constant)
            ):
                c.events.add(sub.args[0].value)
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
        """Resolve a base class expression: `Foo`, `mod.Foo`, or `Foo.Settings`."""
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
        seen = seen or set()
        if c.name in seen:
            return {}
        seen.add(c.name)
        out = {}
        for b in c.bases:
            bc = self.base(c, b)
            if bc:
                out.update(self.effective_default_settings(bc, seen))
        out.update(c.default_settings)
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
    for tok in set(CLASSLIKE_RE.findall(text)):
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
    for i, ln in enumerate(lines):
        events.update(EVENT_RE.findall(ln))
    community = "CommunityMaintained" in text
    return Page(community, os.path.relpath(path, ROOT), list(groups.values()), classes, events)


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
    if v in ("None", "NOT_GIVEN", "NotGiven", "NotGiven()") or v.endswith("_NOT_GIVEN"):
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
    t = t.replace("typing.", "").replace("`", "").replace("\\|", "|")
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
        consts = {**self.consts, **self.idx.constants_for(t.owner.module)}
        doc, src = norm_default(e.default, consts), norm_default(p.default, consts, code=True)
        if dep and t.mode == "params":
            doc = None  # a deprecated parameter's own default defers to settings
        same = doc == src or (
            doc and src and doc[0] in "xs" and src[0] in "xs"
            and doc[2:].lower() in (src[2:].lower(), src[2:].split(".")[-1].lower())
        )
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
                    self.add("missing-event", page.path, 0, c.name, ev, f"`{c.name}` registers `{ev}`")
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


KINDS = [
    "stale-param",
    "stale-setting",
    "missing-param",
    "missing-setting",
    "default-mismatch",
    "unmarked-deprecation",
    "missing-event",
    "missing-deprecated",
    "type-mismatch",
]

TYPE_WORDS = {"string": "str", "integer": "int", "boolean": "bool", "number": "float"}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pipecat", default=os.path.join(ROOT, "..", "pipecat"))
    ap.add_argument("--json")
    ap.add_argument("--page", help="glob, relative to the repo root")
    ap.add_argument("--only", help="comma-separated finding kinds")
    ap.add_argument("--format", choices=["text", "github", "summary"], default="text")
    a = ap.parse_args()

    if not os.path.isdir(os.path.join(a.pipecat, "src", "pipecat")):
        sys.exit(f"pipecat source not found at {a.pipecat}; pass --pipecat")
    checker = Checker(SourceIndex(a.pipecat))

    pages = 0
    for dirpath, _, filenames in os.walk(os.path.join(ROOT, PAGES_DIR)):
        for fn in sorted(filenames):
            if fn.endswith(".mdx"):
                pages += 1
                checker.check_page(parse_page(os.path.join(dirpath, fn)))
    checker.completeness()

    findings = checker.findings
    if a.page:
        findings = [f for f in findings if fnmatch.fnmatch(f["page"], a.page)]
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
        json.dump(findings, open(a.json, "w"), indent=1)
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
