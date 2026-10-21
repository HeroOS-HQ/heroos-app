"""Command line for the offline knowledge compiler (see ``scripts.knowledge``).

Prints identities, counts and finding codes only, never source wording. The
bundle and the reports are written with owner-only permissions, and never
inside the repository or the source directory.
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

from app.knowledge.bundle import KnowledgeBundleError, load_knowledge_bundle
from scripts.knowledge.compiler import MappingError, compile_package, report_json
from scripts.knowledge.report import render_markdown
from scripts.knowledge.sources import check_outside, inventory

REPO_ROOT = Path(__file__).resolve().parents[4]


def _write(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
    os.chmod(path, 0o600)


def _inventory(args: argparse.Namespace) -> int:
    for file in inventory(Path(args.source_dir)):
        print(f"{file.sha256}  {file.size:>8}  {file.relative}")
    return 0


def _compile(args: argparse.Namespace) -> int:
    source_dir, out = Path(args.source_dir), Path(args.out)
    for forbidden, what in ((REPO_ROOT, "the repository"), (source_dir, "the source directory")):
        try:
            check_outside(out, forbidden, "compiler output")
        except ValueError:
            print(f"refused: output directory is inside {what}", file=sys.stderr)
            return 2
    try:
        result = compile_package(source_dir, Path(args.mapping))
    except MappingError as error:
        print(f"mapping refused: {error}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = result.report
    _write(out / "validation-report.json", report_json(report) + b"\n")
    _write(out / "validation-report.md", render_markdown(report).encode())
    counts = report["finding_counts"]
    print(f"source_package_digest={report['source_package_digest']}")
    print(f"findings: {', '.join(f'{k}={v}' for k, v in counts.items())}")
    if result.bundle_bytes is None:
        print("bundle NOT written: the package is invalid (see the report)", file=sys.stderr)
        return 1
    name = f"{result.bundle['bundle']}.private-knowledge.json" if result.bundle else "bundle.json"
    _write(out / name, result.bundle_bytes)
    print(f"runtime_bundle_digest={report['runtime_bundle_digest']}")
    print(f"HEROOS_KNOWLEDGE_BUNDLE_SHA256={report['bundle_sha256']}")
    print(f"bundle: {out / name}")
    return 0


def _validate(args: argparse.Namespace) -> int:
    path = Path(args.bundle)
    try:
        pin = hashlib.sha256(path.read_bytes()).hexdigest()
        bundle = load_knowledge_bundle(path, pin, production=args.production)
    except (OSError, KnowledgeBundleError) as error:
        print(f"refused: {getattr(error, 'code', 'unreadable')}", file=sys.stderr)
        return 1
    print(f"HEROOS_KNOWLEDGE_BUNDLE_SHA256={pin}")
    print(f"bundle={bundle.bundle_id} version={bundle.version} provenance={bundle.provenance}")
    print(f"approval={bundle.approval}")
    print(f"source_package_digest={bundle.source_package_digest}")
    print(f"runtime_bundle_digest={bundle.runtime_digest}")
    print(
        f"units={len(bundle.units)} conditions={len(bundle.conditions)} "
        f"(active={len(bundle.executable_conditions())}) guards={len(bundle.guards)} "
        f"documents={len(bundle.documents)} options={len(bundle.options)} "
        f"reference_data={len(bundle.reference_data)} quarantined={len(bundle.quarantine)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.knowledge")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("inventory", help="list the source files and their SHA-256")
    listing.add_argument("source_dir")
    listing.set_defaults(run=_inventory)
    build = commands.add_parser("compile", help="compile a source package into a bundle")
    build.add_argument("source_dir")
    build.add_argument("mapping")
    build.add_argument("--out", required=True)
    build.set_defaults(run=_compile)
    check = commands.add_parser("validate", help="validate a bundle with the API's loader")
    check.add_argument("bundle")
    check.add_argument("--production", action="store_true")
    check.set_defaults(run=_validate)
    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
