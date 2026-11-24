from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_errata.errata import ErrataError, apply_errata, build_release, verify_registry

DEFAULT_REGISTRY = Path("errata/registry.json")


def _source(value: str) -> tuple[str, str]:
    benchmark, sep, revision = value.partition("=")
    if not sep or not benchmark or not revision:
        raise argparse.ArgumentTypeError("expected <benchmark>=<value>")
    return benchmark, revision


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="benchmark-errata")
    commands = parser.add_subparsers(dest="command", required=True)

    verify = commands.add_parser("verify", help="Check every erratum record and its patch.")
    verify.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)

    apply = commands.add_parser(
        "apply", help="Apply live errata by task id to a materialized task root."
    )
    apply.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    apply.add_argument(
        "--tasks-root", required=True, type=Path, help="<root>/<benchmark>/<task_id>/task.toml"
    )
    apply.add_argument(
        "--source",
        action="append",
        default=[],
        type=_source,
        metavar="BENCHMARK=REVISION",
        help="upstream revision a benchmark was materialized from (repeat per benchmark)",
    )
    apply.add_argument("--patch-root", type=Path, help="where external patches are kept")
    apply.add_argument(
        "--benchmark-dir",
        action="append",
        default=[],
        type=_source,
        metavar="BENCHMARK=DIR",
        help="directory name a runner uses for a benchmark under --tasks-root (repeat)",
    )
    apply.add_argument(
        "--include-candidates",
        action="store_true",
        help="also apply errata still under their release gates (gate runs only)",
    )

    release = commands.add_parser("release", help="Build the Hugging Face release folder.")
    release.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    release.add_argument("--output", required=True, type=Path)
    release.add_argument("--version", required=True)
    release.add_argument("--commit", required=True, help="Git commit the release is built from")
    release.add_argument("--card", type=Path, default=Path("release/README.md"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "verify":
            result: object = verify_registry(args.registry)
        elif args.command == "apply":
            sources = dict(args.source)
            if len(sources) != len(args.source):
                raise ErrataError("--source names a benchmark twice")
            result = apply_errata(
                args.registry,
                args.tasks_root,
                sources,
                patch_root=args.patch_root,
                include_candidates=args.include_candidates,
                benchmark_dirs=dict(args.benchmark_dir),
            )
        else:
            result = build_release(
                args.registry,
                args.output,
                version=args.version,
                commit=args.commit,
                card=args.card,
            )
    except ErrataError as exc:
        _parser().error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
