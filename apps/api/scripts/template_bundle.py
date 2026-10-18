"""Validate a document-template bundle before it is deployed (M2-04C).

Usage (from apps/api)::

    uv run python -m scripts.template_bundle validate TEMPLATES RULES [--production]

Runs exactly the checks the API runs at startup (``app.documents.bundle``):
the template bundle on its own, then against the rule bundle it will run with
(``RULES``, validated the same way). Prints what a deployment needs: the
bundle id, version, provenance, approval, the SHA-256 pin to configure
(``HEROOS_TEMPLATE_BUNDLE_SHA256``), the content digest, and per template its
code, version, review mode, jurisdictions, and counts of fields, choices and
blocks. It never prints template wording, field labels, conditions or source
fingerprints, so its output can go into a deployment record. Exit code 0:
valid; 1: refused (a fixed code and a structural location).

``--production`` also applies the production-only checks (no synthetic rules
or templates, no provisional wording). Nothing is written and nothing is
contacted.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from app.documents.bundle import (
    TemplateBundle,
    TemplateBundleError,
    check_against_rules,
    load_template_bundle,
)
from app.workflows.progression.bundle import RuleBundleError, load_bundle


def summary(bundle: TemplateBundle) -> list[str]:
    lines = [
        f"bundle:      {bundle.bundle_id}",
        f"version:     {bundle.version}",
        f"provenance:  {bundle.provenance}",
        f"approval:    {bundle.approval}",
        f"workflow:    {bundle.workflow_key}",
        f"rules:       {bundle.rule_bundle_id} ({', '.join(sorted(bundle.rule_bundle_versions))})",
        f"pin:         HEROOS_TEMPLATE_BUNDLE_SHA256={bundle.file_sha256}",
        f"digest:      {bundle.digest}",
    ]
    for template in bundle.templates:
        lines.append(
            f"template:    {template.code} v{template.version} ({template.kind}, "
            f"review={template.review}, {'/'.join(sorted(template.jurisdictions))}): "
            f"{len(template.fields)} fields, {len(template.choices)} choices, "
            f"{len(template.body)} blocks"
        )
    return lines


def _pin(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="template_bundle", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a bundle and print its pin")
    validate.add_argument("templates", type=Path)
    validate.add_argument("rules", type=Path)
    validate.add_argument("--production", action="store_true")
    args = parser.parse_args(argv)

    rules_pin, templates_pin = _pin(args.rules), _pin(args.templates)
    if rules_pin is None:
        print("rule bundle refused: unreadable", file=sys.stderr)
        return 1
    if templates_pin is None:
        print("template bundle refused: unreadable", file=sys.stderr)
        return 1
    try:
        rules = load_bundle(args.rules, rules_pin, production=args.production)
        bundle = load_template_bundle(args.templates, templates_pin, production=args.production)
        check_against_rules(bundle, rules)
    except (RuleBundleError, TemplateBundleError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("\n".join(summary(bundle)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
