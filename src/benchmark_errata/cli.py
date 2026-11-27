from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark_errata.emcv import build_emcv, upstream_diff
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
    apply.add_argument(
        "--emcv",
        action="append",
        default=[],
        type=_source,
        metavar="BENCHMARK=VERSION",
        help="pin a benchmark to a clean version from emcv.json (repeat per benchmark)",
    )

    emcv = commands.add_parser("emcv", help="Clean versions: an upstream revision plus errata.")
    emcv_commands = emcv.add_subparsers(dest="emcv_command", required=True)
    build = emcv_commands.add_parser("build", help="Materialize a clean version from upstream.")
    build.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    build.add_argument("--tasks-root", required=True, type=Path, help="upstream tasks root")
    build.add_argument("--benchmark", required=True)
    build.add_argument("--version", required=True, help="emcv-<8 hex>-r<N>")
    build.add_argument("--benchmark-dir", help="directory name under --tasks-root")
    build.add_argument("--patch-root", type=Path, help="where external patches are kept")
    build.add_argument("--output", required=True, type=Path)
    diff = emcv_commands.add_parser(
        "diff", help="Compare our revision of a benchmark with a newer upstream one."
    )
    diff.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    diff.add_argument("--benchmark", required=True)
    diff.add_argument("--old-root", required=True, type=Path, help="tasks at our revision")
    diff.add_argument("--new-root", required=True, type=Path, help="tasks at the new revision")
    diff.add_argument("--benchmark-dir", help="directory name under both roots")
    diff.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="GLOB",
        help="task-relative paths that differ on every materialization (repeat)",
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
            versions = dict(args.emcv)
            if len(versions) != len(args.emcv):
                raise ErrataError("--emcv names a benchmark twice")
            if versions and args.include_candidates:
                raise ErrataError("a clean version never includes candidates")
            result = apply_errata(
                args.registry,
                args.tasks_root,
                sources,
                patch_root=args.patch_root,
                include_candidates=args.include_candidates,
                benchmark_dirs=dict(args.benchmark_dir),
                versions=versions,
            )
        elif args.command == "emcv" and args.emcv_command == "build":
            result = build_emcv(
                args.registry,
                args.tasks_root,
                args.output,
                benchmark=args.benchmark,
                version=args.version,
                benchmark_dir=args.benchmark_dir,
                patch_root=args.patch_root,
            )
        elif args.command == "emcv":
            result = upstream_diff(
                args.registry,
                args.benchmark,
                args.old_root,
                args.new_root,
                benchmark_dir=args.benchmark_dir,
                ignore=tuple(args.ignore),
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
