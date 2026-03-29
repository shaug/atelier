#!/usr/bin/env python3
"""Render refine-plan prompt templates with validation.

Provenance:
- Adapted from trycycle `orchestrator/prompt_builder/build.py`
- Baseline import reference: trycycle base commit `8ea3981`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from template_ast import (  # pyright: ignore[reportMissingImports]
    TemplateError,
    parse_template_text,
    render_nodes,
)
from validate_rendered import (  # pyright: ignore[reportMissingImports]
    ValidationError,
    validate_rendered_prompt,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--set-file", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--require-nonempty-tag", action="append", default=[])
    parser.add_argument("--ignore-tag-for-placeholders", action="append", default=[])
    return parser.parse_args()


def _parse_binding(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise TemplateError(f"binding must be NAME=VALUE, got: {raw!r}")
    name, value = raw.split("=", 1)
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
        raise TemplateError(f"invalid placeholder name: {name!r}")
    return name, value


def _load_bindings(args: argparse.Namespace) -> dict[str, str]:
    bindings: dict[str, str] = {}

    def bind(name: str, value: str) -> None:
        if name in bindings:
            raise TemplateError(f"duplicate binding for {name}")
        bindings[name] = value

    for raw in args.set:
        name, value = _parse_binding(raw)
        bind(name, value)

    for raw in args.set_file:
        name, path = _parse_binding(raw)
        try:
            value = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise TemplateError(f"could not read binding file for {name}: {path}") from exc
        bind(name, value)

    return bindings


def _write_output(text: str, output_path: Path | None) -> None:
    if output_path is None:
        sys.stdout.write(text)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def main() -> int:
    args = _parse_args()
    template_text = args.template.read_text(encoding="utf-8")
    nodes = parse_template_text(template_text)
    rendered = render_nodes(nodes, _load_bindings(args))
    try:
        validate_rendered_prompt(
            rendered,
            required_nonempty_tags=args.require_nonempty_tag,
            ignore_tags_for_placeholders=args.ignore_tag_for_placeholders,
        )
    except ValidationError as exc:
        raise TemplateError(str(exc)) from exc

    _write_output(rendered, args.output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TemplateError as exc:
        print(f"prompt builder error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
