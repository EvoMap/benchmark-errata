"""Clean versions (emcv): an upstream revision plus a pinned set of errata.

A clean version is named ``<upstream repository name>_emcv`` and versioned
``emcv-<first 8 hex of the upstream revision>-r<N>``. Its record in
``errata/emcv.json`` names the upstream revision and, for every erratum it includes,
the patch SHA256 the version was cut with, so the same version always builds the
same bytes. ``build_emcv`` materializes a version from a root of upstream tasks;
``upstream_diff`` compares two materializations of a benchmark (our revision and a
newer upstream one) and says, per erratum, whether upstream adopted the fix, touched
the files it relies on, or left them alone, and which other tasks changed upstream.
See docs/design.md, section 7.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark_errata.errata import (
    ISO_DATE,
    SCHEMA_VERSION,
    SOURCE_REVISION,
    ErrataError,
    Erratum,
    apply_errata,
    load_registry,
    tree_sha256,
)

VERSIONS_FILE = "emcv.json"
EMCV_RECORD = "EMCV.json"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*_emcv")
VERSION = re.compile(r"emcv-([0-9a-f]{8})-r([1-9][0-9]*)")
DISTRIBUTIONS = ("tasks", "patches")
VERSION_STATUSES = ("active", "upstream_fixed", "retired")


@dataclass(frozen=True)
class Version:
    name: str
    version: str
    benchmark: str
    revision: str
    errata: dict[str, str]
    distribution: str
    raw: dict[str, Any]

    @property
    def release(self) -> int:
        match = VERSION.fullmatch(self.version)
        assert match is not None
        return int(match.group(2))


def short_revision(revision: str) -> str:
    return revision.removeprefix("sha256:")[:8]


def versions_path(registry: Path | str) -> Path:
    return Path(registry).resolve().parent / VERSIONS_FILE


def _parse_version(raw: Any, index: int, errata: dict[str, Erratum]) -> Version:
    context = f"versions[{index}]"
    if not isinstance(raw, dict):
        raise ErrataError(f"{context} must be an object")
    name, version, benchmark = raw.get("name"), raw.get("version"), raw.get("benchmark")
    if not isinstance(name, str) or NAME.fullmatch(name) is None:
        raise ErrataError(f"{context}.name must look like <upstream repository name>_emcv")
    if not isinstance(version, str) or VERSION.fullmatch(version) is None:
        raise ErrataError(f"{context}.version must look like emcv-<8 hex>-r<N>: {version!r}")
    context = f"emcv {name} {version}"
    if not isinstance(benchmark, str) or not benchmark:
        raise ErrataError(f"{context}.benchmark must name the errata benchmark id")
    upstream = raw.get("upstream")
    if not isinstance(upstream, dict) or not isinstance(upstream.get("url"), str):
        raise ErrataError(f"{context}.upstream must give url and revision")
    revision = upstream.get("revision")
    if not isinstance(revision, str) or SOURCE_REVISION.fullmatch(revision) is None:
        raise ErrataError(f"{context}.upstream.revision must be a Git SHA or sha256 digest")
    if VERSION.fullmatch(version).group(1) != short_revision(revision):  # type: ignore[union-attr]
        raise ErrataError(f"{context}: the version must carry the upstream revision {revision}")
    released = raw.get("released")
    if not isinstance(released, str) or ISO_DATE.fullmatch(released) is None:
        raise ErrataError(f"{context}.released must be an ISO date")
    distribution = raw.get("distribution")
    if distribution not in DISTRIBUTIONS:
        raise ErrataError(f"{context}.distribution must be one of {', '.join(DISTRIBUTIONS)}")
    if not isinstance(raw.get("basis"), str) or not raw["basis"].strip():
        raise ErrataError(f"{context}.basis must say why the version may be distributed so")
    pinned = raw.get("errata")
    if not isinstance(pinned, dict):
        raise ErrataError(f"{context}.errata must map erratum ids to patch SHA256")
    for erratum_id, digest in pinned.items():
        erratum = errata.get(erratum_id)
        if erratum is None:
            raise ErrataError(f"{context} names {erratum_id}, which the registry does not hold")
        if erratum.benchmark != benchmark or erratum.source_revision != revision:
            raise ErrataError(
                f"{context}: {erratum_id} was written for {erratum.benchmark} at "
                f"{erratum.source_revision}, not {benchmark} at {revision}"
            )
        if erratum.status not in VERSION_STATUSES:
            raise ErrataError(f"{context}: {erratum_id} is {erratum.status}, not released")
        if digest != erratum.patch_sha256:
            raise ErrataError(
                f"{context}: {erratum_id} was cut with patch {digest}, the registry now has "
                f"{erratum.patch_sha256}; a changed patch is a new erratum and a new version"
            )
        if distribution == "tasks" and erratum.raw["license"]["redistribution"] != "allowed":
            raise ErrataError(
                f"{context}: whole tasks may be distributed only when every erratum's upstream "
                f"allows redistribution; {erratum_id} is "
                f"{erratum.raw['license']['redistribution']}"
            )
    return Version(name, version, benchmark, revision, dict(pinned), distribution, raw)


def load_versions(registry: Path | str) -> tuple[Version, ...]:
    """Parse ``emcv.json`` next to the registry and check it against the registry."""
    path = versions_path(registry)
    if not path.exists():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErrataError(f"cannot load {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ErrataError(f"{path.name} schema_version must be {SCHEMA_VERSION}")
    entries = raw.get("versions")
    if not isinstance(entries, list):
        raise ErrataError(f"{path.name} must hold a versions list")
    errata = {erratum.id: erratum for erratum in load_registry(registry)}
    versions = tuple(_parse_version(entry, i, errata) for i, entry in enumerate(entries))
    seen: dict[str, Version] = {}
    latest: dict[tuple[str, str], Version] = {}
    for version in versions:
        if version.version in seen and seen[version.version].name == version.name:
            raise ErrataError(f"emcv {version.name} {version.version} is listed twice")
        seen[version.version] = version
        key = (version.name, version.revision)
        previous = latest.get(key)
        if previous is not None and version.benchmark != previous.benchmark:
            raise ErrataError(f"emcv {version.name} names two benchmarks")
        if previous is None or version.release > previous.release:
            if previous is not None and version.release != previous.release + 1:
                raise ErrataError(f"emcv {version.name} {version.version} skips a release number")
            if previous is None and version.release != 1:
                raise ErrataError(f"emcv {version.name} {version.version} must start at r1")
            latest[key] = version
        else:
            raise ErrataError(f"emcv {version.name}: list releases in order")
    # The newest release of each (name, revision) holds every released erratum the registry
    # has for that benchmark and revision: adding or changing an erratum means cutting a version.
    for version in latest.values():
        live = {
            erratum.id
            for erratum in errata.values()
            if erratum.benchmark == version.benchmark
            and erratum.source_revision == version.revision
            and erratum.status in ("active", "upstream_fixed")
        }
        missing = sorted(live - set(version.errata))
        if missing:
            raise ErrataError(
                f"emcv {version.name} {version.version} is the newest release for "
                f"{version.revision} but lacks released errata {', '.join(missing)}; cut "
                f"r{version.release + 1}"
            )
    return versions


def find_version(registry: Path | str, benchmark: str, version: str) -> Version:
    for candidate in load_versions(registry):
        if candidate.benchmark == benchmark and candidate.version == version:
            return candidate
    raise ErrataError(f"no clean version {version} for {benchmark} in {VERSIONS_FILE}")


def build_emcv(
    registry: Path | str,
    tasks_root: Path | str,
    output: Path | str,
    *,
    benchmark: str,
    version: str,
    benchmark_dir: str | None = None,
    patch_root: Path | str | None = None,
) -> dict[str, Any]:
    """Copy one benchmark's upstream tasks to ``output`` and apply a clean version.

    ``output/<benchmark dir>/`` receives the tasks and ``output/EMCV.json`` the
    version record, the apply record and the tree SHA256 of every task, so two
    builds of a version can be compared file for file.
    """
    pinned = find_version(registry, benchmark, version)
    local = benchmark_dir or benchmark
    source = Path(tasks_root) / local
    out = Path(output)
    if not source.is_dir():
        raise ErrataError(f"no {local}/ under {tasks_root}")
    if out.exists() and any(out.iterdir()):
        raise ErrataError(f"emcv output is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, out / local, symlinks=True)
    document = apply_errata(
        registry,
        out,
        {benchmark: pinned.revision},
        patch_root=patch_root,
        benchmark_dirs={benchmark: local},
        versions={benchmark: version},
    )
    applied = {e["erratum"] for e in document["tasks"] if e["action"] == "applied"}
    present = {e["erratum"] for e in document["tasks"]}
    absent = sorted(set(pinned.errata) - present)
    tasks = {
        toml.parent.name: tree_sha256(toml.parent)
        for toml in sorted((out / local).glob("*/task.toml"))
    }
    record = {
        "schema_version": SCHEMA_VERSION,
        "name": pinned.name,
        "version": pinned.version,
        "benchmark": benchmark,
        "benchmark_dir": local,
        "upstream": pinned.raw["upstream"],
        "distribution": pinned.distribution,
        "registry_sha256": document["registry_sha256"],
        "errata": pinned.errata,
        "applied": sorted(applied),
        "errata_without_task": absent,
        "tasks": tasks,
    }
    (out / EMCV_RECORD).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def _ignored(relative: str, ignore: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(relative, pattern) for pattern in ignore)


def _file_hashes(task: Path, ignore: tuple[str, ...]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(task.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(task).as_posix()
        if _ignored(relative, ignore):
            continue
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _tasks(root: Path) -> dict[str, Path]:
    return {toml.parent.name: toml.parent for toml in sorted(root.glob("*/task.toml"))}


def upstream_diff(
    registry: Path | str,
    benchmark: str,
    old_root: Path | str,
    new_root: Path | str,
    *,
    benchmark_dir: str | None = None,
    ignore: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Compare one benchmark materialized at our revision and at a newer upstream one.

    Per erratum of the benchmark (any status but retired), on the new bytes:
    ``adopted``: every file the erratum changes now has its after hash, so upstream
    shipped our fix; ``touched``: a file it changes or depends on differs from the
    bytes it was written for, so it must be re-verified (upstream may have fixed the
    defect another way, or changed the tests); ``unchanged``: every pinned file is
    the same, so the defect is still there and the erratum can be re-pinned to the
    new revision as it is. Tasks without an erratum whose files changed are listed as
    ``unreviewed``: upstream changed them and nobody here has looked yet. Paths matching
    ``ignore`` count for none of this; a pinned file among them is listed as ignored.
    """
    local = benchmark_dir or benchmark
    old_tasks, new_tasks = _tasks(Path(old_root) / local), _tasks(Path(new_root) / local)
    errata = [e for e in load_registry(registry) if e.benchmark == benchmark]
    by_task: dict[str, list[Erratum]] = {}
    for erratum in errata:
        if erratum.status != "retired":
            by_task.setdefault(erratum.task_id, []).append(erratum)
    report: dict[str, Any] = {
        "benchmark": benchmark,
        "benchmark_dir": local,
        "ignore": list(ignore),
        "added": sorted(set(new_tasks) - set(old_tasks)),
        "removed": sorted(set(old_tasks) - set(new_tasks)),
        "errata": [],
        "unreviewed": [],
    }
    for task_id in sorted(set(old_tasks) & set(new_tasks)):
        old = _file_hashes(old_tasks[task_id], ignore)
        new = _file_hashes(new_tasks[task_id], ignore)
        changed = sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))
        task_errata = by_task.get(task_id, [])
        if not task_errata:
            if changed:
                report["unreviewed"].append({"task_id": task_id, "changed": changed})
            continue
        for erratum in task_errata:
            pinned = {path: before for path, (before, _) in erratum.files.items()}
            pinned.update(erratum.depends_on)
            ignored = sorted(p for p in pinned if _ignored(p, ignore))
            drifted = sorted(
                path
                for path, digest in pinned.items()
                if path not in ignored and new.get(path) != digest
            )
            adopted = all(
                new.get(path) == after
                for path, (_, after) in erratum.files.items()
                if path not in ignored
            )
            verdict = "adopted" if adopted else ("touched" if drifted else "unchanged")
            report["errata"].append(
                {
                    "erratum": erratum.id,
                    "task_id": task_id,
                    "status": erratum.status,
                    "verdict": verdict,
                    "pinned_files_changed": drifted,
                    "pinned_files_ignored": ignored,
                    "other_files_changed": sorted(set(changed) - set(pinned)),
                }
            )
    for task_id in sorted(set(by_task) - set(old_tasks) - set(new_tasks)):
        for erratum in by_task[task_id]:
            report["errata"].append(
                {
                    "erratum": erratum.id,
                    "task_id": task_id,
                    "status": erratum.status,
                    "verdict": "task_absent",
                }
            )
    counts: dict[str, int] = {}
    for entry in report["errata"]:
        counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1
    report["summary"] = {
        "errata": counts,
        "unreviewed_tasks": len(report["unreviewed"]),
        "added_tasks": len(report["added"]),
        "removed_tasks": len(report["removed"]),
    }
    return report
