"""Template parser and renderer for refine-plan prompt assembly.

Provenance:
- Adapted from trycycle `orchestrator/prompt_builder/template_ast.py`
- Baseline import reference: trycycle base commit `8ea3981`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, TypeAlias

TOKEN_RE = re.compile(r"{{#if (?P<if>[A-Z][A-Z0-9_]*)}}|{{(?P<else>else)}}|{{(?P<endif>/if)}}")
PLACEHOLDER_RE = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")


@dataclass(frozen=True)
class TextNode:
    text: str


@dataclass(frozen=True)
class IfNode:
    name: str
    truthy: list["Node"]
    falsy: list["Node"]


Node: TypeAlias = TextNode | IfNode
MissingHandler: TypeAlias = Callable[[str], str]


class TemplateError(RuntimeError):
    """Prompt template parsing or rendering failure."""


def tokenize(template: str) -> list[tuple[str, str]]:
    """Tokenize template text into text and conditional markers."""
    tokens: list[tuple[str, str]] = []
    cursor = 0
    for match in TOKEN_RE.finditer(template):
        if match.start() > cursor:
            tokens.append(("text", template[cursor : match.start()]))
        if match.group("if"):
            tokens.append(("if", match.group("if")))
        elif match.group("else"):
            tokens.append(("else", ""))
        else:
            tokens.append(("endif", ""))
        cursor = match.end()
    if cursor < len(template):
        tokens.append(("text", template[cursor:]))
    return tokens


def parse_template_text(template_text: str) -> list[Node]:
    """Parse template text into AST nodes."""
    nodes, index = _parse_nodes(tokenize(template_text), index=0, stop=None)
    if index != len(tokenize(template_text)):
        raise TemplateError("template parsing stopped before token stream end")
    return nodes


def render_nodes(
    nodes: list[Node],
    bindings: dict[str, str],
    on_missing: MissingHandler | None = None,
) -> str:
    """Render AST nodes with placeholder bindings."""
    rendered: list[str] = []
    for node in nodes:
        if isinstance(node, TextNode):
            rendered.append(_render_text(node.text, bindings, on_missing=on_missing))
            continue
        branch = node.truthy if bindings.get(node.name, "") else node.falsy
        rendered.append(render_nodes(branch, bindings, on_missing=on_missing))
    return "".join(rendered)


def _parse_nodes(
    tokens: list[tuple[str, str]],
    *,
    index: int,
    stop: set[str] | None,
) -> tuple[list[Node], int]:
    nodes: list[Node] = []
    stop_set = stop or set()

    while index < len(tokens):
        kind, value = tokens[index]
        if kind in stop_set:
            return nodes, index

        if kind == "text":
            nodes.append(TextNode(value))
            index += 1
            continue

        if kind == "if":
            truthy, index = _parse_nodes(tokens, index=index + 1, stop={"else", "endif"})
            falsy: list[Node] = []
            if index >= len(tokens):
                raise TemplateError(f"unclosed conditional block for {value}")
            end_kind, _ = tokens[index]
            if end_kind == "else":
                falsy, index = _parse_nodes(tokens, index=index + 1, stop={"endif"})
                if index >= len(tokens) or tokens[index][0] != "endif":
                    raise TemplateError(f"conditional block for {value} is missing {{/if}}")
            elif end_kind != "endif":
                raise TemplateError(f"unexpected token {end_kind!r} for {value}")
            nodes.append(IfNode(name=value, truthy=truthy, falsy=falsy))
            index += 1
            continue

        raise TemplateError(f"unexpected template token: {kind}")

    if stop_set:
        expected = " or ".join(sorted(stop_set))
        raise TemplateError(f"expected {expected} before end of template")
    return nodes, index


def _render_text(
    text: str,
    bindings: dict[str, str],
    *,
    on_missing: MissingHandler | None,
) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in bindings:
            return bindings[name]
        if on_missing is not None:
            return on_missing(name)
        raise TemplateError(f"missing placeholder value for {name}")

    return PLACEHOLDER_RE.sub(replace, text)
