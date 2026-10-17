"""Validate a workflow-progression rule bundle before it is deployed (M2-03).

Usage (from apps/api)::

    uv run python -m scripts.rule_bundle validate PATH [--production]

Runs exactly the checks the API runs at startup (``app.workflows.progression
.bundle``) and prints what a deployment needs: the bundle id, version,
provenance, the SHA-256 pin to configure (``HEROOS_RULE_BUNDLE_SHA256``), the
content digest stored with every progress event, and coverage counts per
jurisdiction and pathway. It never prints bundle wording, rule conditions or
source references, so its output can go into a deployment record. Exit code 0:
valid; 1: refused (a fixed code and a structural location).

``--production`` also applies the production-only check (no synthetic rules).
Nothing is written and nothing is contacted.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from app.workflows.progression.bundle import RuleBundle, RuleBundleError, load_bundle


def summary(bundle: RuleBundle) -> list[str]:
    lines = [
        f"bundle:      {bundle.bundle_id}",
        f"version:     {bundle.version}",
        f"provenance:  {bundle.provenance}",
        f"workflow:    {bundle.workflow_key} (definition versions "
        f"{', '.join(str(v) for v in sorted(bundle.definition_versions))})",
        f"serves:      {', '.join(sorted(bundle.serves_versions)) or '-'}",
        f"pin:         HEROOS_RULE_BUNDLE_SHA256={bundle.file_sha256}",
        f"digest:      {bundle.digest}",
    ]
    for code, program in sorted(bundle.jurisdictions.items()):
        for pathway in program.pathways:
            rules = len(pathway.select_rules) + sum(
                len(s.start_rules) + len(s.complete_rules) for s in pathway.stages
            )
            checklist = sum(len(s.checklist) for s in pathway.stages)
            lines.append(
                f"coverage:    {code} / {pathway.pathway}: {len(pathway.stages)} stages, "
                f"{checklist} checklist items, {rules} rules"
            )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rule_bundle", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a bundle and print its pin")
    validate.add_argument("path", type=Path)
    validate.add_argument("--production", action="store_true")
    args = parser.parse_args(argv)

    path: Path = args.path
    try:
        pin = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        print("rule bundle refused: unreadable", file=sys.stderr)
        return 1
    try:
        bundle = load_bundle(path, pin, production=args.production)
    except RuleBundleError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("\n".join(summary(bundle)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
