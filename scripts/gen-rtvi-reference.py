#!/usr/bin/env python3
"""Generate the RTVI protocol reference pages from pipecat's RTVI specification.

pipecat keeps a machine-readable AsyncAPI document for each RTVI protocol
version, at ``src/pipecat/processors/frameworks/rtvi/spec/<version>/rtvi.asyncapi.json``.
This script turns each one into ``api-reference/standards/rtvi/<version>.mdx``:
every message, grouped as the document groups them, with who sends it, what it
means, its fields and an example, then the rules the server follows across
messages. ``api-reference/standards/rtvi-standard.mdx`` links to each version.

The pages are generated, never edited by hand. Run, from the docs root::

    python3 scripts/gen-rtvi-reference.py --pipecat ../pipecat

``--check`` writes nothing and fails when a page is missing or out of date, as
CI runs it. Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = DOCS_ROOT / "api-reference" / "standards" / "rtvi"
SPEC_DIR = Path("src/pipecat/processors/frameworks/rtvi/spec")
SPEC_URL = "https://github.com/pipecat-ai/pipecat/blob/main/" + SPEC_DIR.as_posix()
STANDARD_PAGE = "/api-reference/standards/rtvi-standard"

# How deep nested objects are expanded; deeper ones are named, not expanded.
MAX_DEPTH = 4

_CODE_SPAN = re.compile(r"(`[^`]*`)")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def mdx_text(text: str) -> str:
    """Markdown text as MDX: outside code spans, MDX reads ``<`` and ``{`` as markup."""
    parts = _CODE_SPAN.split(text)
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("<", "&lt;").replace("{", "&#123;").replace("}", "&#125;")
    return "".join(parts)


def mdx_attr(text: str) -> str:
    """A JSX attribute's value: a string, or an expression when it holds a quote."""
    return f'"{text}"' if '"' not in text else "{" + json.dumps(text) + "}"


class Reference:
    """One protocol version's document, rendered as a page."""

    def __init__(self, document: dict, version: str):
        self.document = document
        self.version = version
        self.schemas = document["components"].get("schemas", {})
        self.messages = document["components"]["messages"]
        operations = document["operations"]
        self.client_keys = self._keys(operations["receiveClientMessages"])

    @staticmethod
    def _keys(operation: dict) -> set[str]:
        return {ref["$ref"].rsplit("/", 1)[1] for ref in operation["messages"]}

    # -- Schemas ------------------------------------------------------------

    def resolve(self, schema: dict) -> tuple[dict, str | None]:
        """A schema with its ``$ref`` followed, and the name it was referred to by."""
        ref = schema.get("$ref", "")
        if ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[1]
            return self.schemas[name], name
        return schema, None

    def variants(self, schema: dict) -> tuple[list[dict], bool]:
        """A schema's alternatives without ``null``, and whether ``null`` is one of them."""
        options = schema.get("anyOf") or schema.get("oneOf")
        if not options:
            return [schema], schema.get("type") == "null"
        others = [option for option in options if option.get("type") != "null"]
        return others, len(others) < len(options)

    def type_name(self, schema: dict) -> str:
        """A schema's type, as the reference shows it."""
        options, nullable = self.variants(schema)
        names = []
        for option in options:
            resolved, ref_name = self.resolve(option)
            if "enum" in resolved or "const" in resolved:
                names.append(resolved.get("type", "string"))
            elif resolved.get("type") == "array":
                items = resolved.get("items", {})
                names.append(f"{self.type_name(items) if items else 'any'}[]")
            elif ref_name and (resolved.get("type") == "object" or "properties" in resolved):
                names.append(ref_name)
            elif "type" in resolved:
                names.append(resolved["type"])
            elif ref_name:
                names.append(ref_name)
            else:
                names.append("any")
        name = " | ".join(dict.fromkeys(names)) or "any"
        return f"{name} | null" if nullable and name != "any" else name

    def allowed(self, schema: dict) -> str:
        """The values a schema allows, when it lists them."""
        options, _ = self.variants(schema)
        values = []
        for option in options:
            resolved, _ = self.resolve(option)
            values += resolved.get("enum", [])
            if "const" in resolved:
                values.append(resolved["const"])
        if not values:
            return ""
        listed = ", ".join(f"`{json.dumps(value)}`" for value in values)
        return f"Always {listed}." if len(values) == 1 else f"One of {listed}."

    def object_variants(self, schema: dict) -> list[tuple[dict, str | None]]:
        """The objects a schema can be, through ``$ref``, ``anyOf`` and arrays."""
        options, _ = self.variants(schema)
        objects = []
        for option in options:
            resolved, ref_name = self.resolve(option)
            if resolved.get("type") == "array" and resolved.get("items"):
                objects += self.object_variants(resolved["items"])
            elif resolved.get("properties"):
                objects.append((resolved, ref_name))
        return objects

    @staticmethod
    def variant_title(variant: dict, ref_name: str | None, variants: list) -> str:
        """A title for one of several objects: the field that tells them apart, or its name.

        That field is in every object and has a fixed value in some; an object
        without a fixed value for it takes any other value.
        """
        for name in variant.get("properties", {}):
            fields = [other.get("properties", {}).get(name) for other, _ in variants]
            if all(fields) and any("const" in field for field in fields):
                field = variant["properties"][name]
                if "const" not in field:
                    return f"{name}: any other"
                const = field["const"]
                return f"{name}: {const if isinstance(const, str) else json.dumps(const)}"
        return ref_name or "object"

    def param_fields(
        self, schema: dict, path: str, indent: str, depth: int, seen: tuple[str, ...]
    ) -> list[str]:
        """A ``ParamField`` for each property of an object schema."""
        lines = []
        required = set(schema.get("required", []))
        for name, field in schema.get("properties", {}).items():
            lines += self.param_field(
                field, f"{path}{name}", name in required, indent, depth, seen
            )
        return lines

    def param_field(
        self,
        field: dict,
        path: str,
        required: bool,
        indent: str,
        depth: int,
        seen: tuple[str, ...],
    ) -> list[str]:
        attrs = [f"path={mdx_attr(path)}", f"type={mdx_attr(self.type_name(field))}"]
        if required:
            attrs.append("required")
        if "default" in field and field["default"] is not None:
            default = field["default"]
            text = default if isinstance(default, str) else json.dumps(default)
            attrs.append(f"default={mdx_attr(text)}")
        description = field.get("description", "")
        allowed = self.allowed(field)
        # A description that already gives the allowed values needn't repeat them.
        if allowed and all(f"`{value}`" in description for value in re.findall(r"`([^`]*)`", allowed)):
            allowed = ""
        body = [part for part in (description, allowed) if part]
        lines = [f"{indent}<ParamField {' '.join(attrs)}>"]
        if body:
            lines.append(f"{indent}  {mdx_text(' '.join(body))}")
        variants = self.object_variants(field)
        if len(variants) > 1:
            # One of several objects: each in its own expandable, by what tells them apart.
            for variant, ref_name in variants:
                title = self.variant_title(variant, ref_name, variants)
                lines.append("")
                lines.append(f"{indent}  <Expandable title={mdx_attr(title)}>")
                if variant.get("description"):
                    lines.append(f"{indent}    {mdx_text(variant['description'])}")
                    lines.append("")
                lines += self.param_fields(
                    variant,
                    "",
                    indent + "    ",
                    depth + 1,
                    seen + ((ref_name,) if ref_name else ()),
                )
                lines.append(f"{indent}  </Expandable>")
        elif variants:
            nested, ref_name = variants[0]
            if ref_name and ref_name in seen:
                lines.append(f"{indent}  Same fields as `{ref_name}`, above.")
            elif depth >= MAX_DEPTH:
                lines.append(f"{indent}  A `{ref_name or 'object'}`.")
            else:
                title = ref_name or "properties"
                lines.append("")
                lines.append(f"{indent}  <Expandable title={mdx_attr(title)}>")
                lines += self.param_fields(
                    nested,
                    "",
                    indent + "    ",
                    depth + 1,
                    seen + ((ref_name,) if ref_name else ()),
                )
                lines.append(f"{indent}  </Expandable>")
        lines.append(f"{indent}</ParamField>")
        return lines

    # -- Page ---------------------------------------------------------------

    def message_section(self, key: str) -> list[str]:
        message = self.messages[key]
        type = message["name"]
        sender = "client" if key in self.client_keys else "server"
        lines = [f"#### {type}", ""]
        lines += [mdx_text(message["summary"]), ""]
        if message.get("description"):
            lines += [mdx_text(message["description"]), ""]
        payload = message["payload"]
        properties = payload["properties"]
        required = set(payload.get("required", []))
        if "id" in properties:
            if sender == "client":
                about_id = "The message's id. An answer to it carries the same id."
            else:
                about_id = "The id of the client message this answers."
            lines += [f'<ParamField path="id" type="string" required>', f"  {about_id}", "</ParamField>"]
        if "data" in properties:
            data = properties["data"]
            variants = self.object_variants(data)
            if len(variants) == 1:
                lines += self.param_fields(variants[0][0], "data.", "", 1, ())
            else:
                lines += self.param_field(data, "data", "data" in required, "", 1, ())
        if "id" in properties or "data" in properties:
            lines.append("")
        example = message.get("examples", [{}])[0].get("payload")
        if example is not None:
            lines += ["```json Example", json.dumps(example, indent=2, ensure_ascii=False), "```", ""]
        return lines

    def render(self) -> str:
        info = self.document["info"]
        groups = info.get("tags", [])
        lines = [
            "---",
            f'title: "RTVI {self.version}"',
            f'sidebarTitle: "{self.version}"',
            f'description: "Every message of RTVI protocol {self.version} by group: what a '
            'client sends, what it receives, each message\'s fields, and the server\'s rules."',
            "---",
            "",
            "{/* Generated by scripts/gen-rtvi-reference.py from pipecat's RTVI "
            "specification. Don't edit by hand: rerun the script. */}",
            "",
            f"Every message of RTVI protocol {self.version}, generated from the protocol's "
            f"[machine-readable AsyncAPI document]({SPEC_URL}/{self.version}/rtvi.asyncapi.json). "
            f"See [RTVI]({STANDARD_PAGE}) for how the protocol works.",
            "",
        ]
        by_group: dict[str, list[str]] = {group["name"]: [] for group in groups}
        ungrouped = []
        for key, message in self.messages.items():
            tags = [tag["name"] for tag in message.get("tags", [])]
            if tags and tags[0] in by_group:
                by_group[tags[0]].append(key)
            else:
                ungrouped.append(key)
        sections = [(group["name"], group.get("description", "")) for group in groups]
        if ungrouped:
            by_group["Other Messages"] = ungrouped
            sections.append(("Other Messages", ""))
        for name, description in sections:
            if not by_group[name]:
                continue
            lines += [f"## {name}", ""]
            if description:
                lines += [mdx_text(description), ""]
            # As a client sees them: what it sends, then what it receives.
            sends = [key for key in by_group[name] if key in self.client_keys]
            receives = [key for key in by_group[name] if key not in self.client_keys]
            for heading, keys in (("Client sends", sends), ("Client receives", receives)):
                if keys:
                    lines += [f"### {heading}", ""]
                    for key in keys:
                        lines += self.message_section(key)
        behaviors = self.document.get("x-rtvi-behaviors", [])
        if behaviors:
            lines += [
                "## Server Behaviors",
                "",
                "The rules a server follows across messages, beyond the shape of each one.",
                "",
            ]
            for behavior in behaviors:
                involved = ", ".join(f"`{type}`" for type in behavior["messages"])
                suffix = f" ({involved})" if involved else ""
                lines.append(f"- **{behavior['id']}**: {mdx_text(behavior['description'])}{suffix}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def documents(pipecat: Path) -> dict[str, Path]:
    """Each protocol version's document in a pipecat checkout."""
    spec_dir = pipecat / SPEC_DIR
    found = {path.parent.name: path for path in spec_dir.glob("*/rtvi.asyncapi.json")}
    return dict(sorted(found.items(), key=lambda item: _version_key(item[0])))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pipecat", default="../pipecat", help="a pipecat checkout")
    parser.add_argument("--check", action="store_true", help="fail when a page is out of date")
    args = parser.parse_args()

    found = documents(Path(args.pipecat))
    if not found:
        print(f"no RTVI specification in {Path(args.pipecat) / SPEC_DIR}", file=sys.stderr)
        return 2
    stale = []
    for version, path in found.items():
        page = PAGES_DIR / f"{version}.mdx"
        text = Reference(json.loads(path.read_text(encoding="utf-8")), version).render()
        current = page.read_text(encoding="utf-8") if page.exists() else None
        if current == text:
            continue
        if args.check:
            stale.append(page.relative_to(DOCS_ROOT))
        else:
            PAGES_DIR.mkdir(parents=True, exist_ok=True)
            page.write_text(text, encoding="utf-8")
            print(f"wrote {page.relative_to(DOCS_ROOT)}")
    if stale:
        for page in stale:
            print(f"{page} is out of date; run python3 scripts/gen-rtvi-reference.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
