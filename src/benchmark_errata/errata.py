"""Errata for public agent-benchmark tasks: patches applied by task id.

An erratum is a record in ``errata/registry.json`` plus a Git-format patch against
a Harbor task directory as the benchmark's materializer writes it. Only defects of
the task or dataset itself qualify; a fault of the evaluation environment is fixed
where it lives. Every changed file and every file the fix depends on is pinned by
SHA256, so an erratum either applies to exactly the bytes it was written for or is
refused. This repository is public: patches never touch reference solutions,
changes to graders must state that they carry no expected answers, and patches to
datasets that may not be redistributed are kept out of the repository. See
docs/design.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
MARKER_KEY = "benchmark_erratum"
APPLIED_RECORD = "benchmark-errata.json"
STATUSES = ("candidate", "active", "upstream_fixed", "retired")
APPLIED_STATUSES = ("active", "upstream_fixed")
# class -> (paths the patch must touch at least one of, paths the evidence must cite one of)
DEFECT_CLASSES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "instruction_gap": (("instruction.md", "tests/"), ("tests/",)),
    "grader_bug": (("tests/",), ("tests/",)),
    "image_residue": (("environment/",), ("environment/",)),
    "starter_mismatch": (("environment/", "instruction.md"), ("tests/",)),
}
ENVIRONMENT_CLASSES = frozenset(
    {"network_policy", "gateway", "bridge", "gate", "host", "image_build", "materializer", "budget"}
)
PATCHABLE_FILES = frozenset({"instruction.md", "README.md", "task.toml"})
PATCHABLE_DIRS = ("tests/", "environment/")
PINNABLE_DIRS = (*PATCHABLE_DIRS, "solution/")
REDISTRIBUTION = ("allowed", "unspecified", "none")
LOWER_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_.-]*")
TASK_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
FULL_SHA256 = re.compile(r"[0-9a-f]{64}")
SOURCE_REVISION = re.compile(r"[0-9a-f]{40}|sha256:[0-9a-f]{64}")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DIFF_HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)$")
_DOCKER_IMAGE_LINE = re.compile(r"^\s*docker_image\s*=")
_METADATA_HEADER = re.compile(r"^\s*\[\s*metadata\s*\]\s*(#.*)?$")


class ErrataError(ValueError):
    """A record, a patch or a task does not satisfy the errata contract."""


@dataclass(frozen=True)
class Erratum:
    id: str
    benchmark: str
    task_id: str
    status: str
    source_revision: str
    fixed_in_revision: str | None
    patch_path: Path | None
    patch_sha256: str
    files: dict[str, tuple[str | None, str | None]]
    depends_on: dict[str, str]
    raw: dict[str, Any]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ErrataError(f"{context} must be an object")
    return value


def _string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ErrataError(f"{context}.{key} must be a non-empty string")
    return value


def _matching(data: dict[str, Any], key: str, context: str, pattern: re.Pattern[str]) -> str:
    value = _string(data, key, context)
    if pattern.fullmatch(value) is None:
        raise ErrataError(f"{context}.{key} has an invalid value: {value!r}")
    return value


def _https(value: Any, context: str) -> str:
    if not isinstance(value, str):
        raise ErrataError(f"{context} must be an HTTPS URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ErrataError(f"{context} must be an HTTPS URL without credentials: {value!r}")
    return value


def _url_list(value: Any, context: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ErrataError(f"{context} must be a {'' if allow_empty else 'non-empty '}list")
    return [_https(item, f"{context}[{index}]") for index, item in enumerate(value)]


def _task_path(value: str, context: str, dirs: tuple[str, ...]) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts or value != path.as_posix():
        raise ErrataError(f"{context} is not a safe task-relative path: {value!r}")
    if value.startswith("solution/") and "solution/" not in dirs:
        raise ErrataError(
            f"{context} {value!r}: a public erratum never changes a reference solution"
        )
    if value not in PATCHABLE_FILES and not value.startswith(dirs):
        raise ErrataError(
            f"{context} {value!r} is outside the task files an erratum may name "
            f"({', '.join(sorted(PATCHABLE_FILES))}, {', '.join(dirs)})"
        )
    return value


def _digest_or_null(value: Any, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or FULL_SHA256.fullmatch(value) is None:
        raise ErrataError(f"{context} must be a lowercase SHA256 or null")
    return value


def _touches(paths: Any, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix) for path in paths for prefix in prefixes)


def _validate_class(defect: dict[str, Any], context: str) -> str:
    value = _string(defect, "class", context)
    if value in ENVIRONMENT_CLASSES:
        raise ErrataError(
            f"{context}.class {value!r} is an evaluation-environment fault, not a task defect: "
            "fix the environment where it runs and rerun, instead of patching the task"
        )
    if value not in DEFECT_CLASSES:
        raise ErrataError(
            f"{context}.class {value!r} is unknown; task defects are {', '.join(DEFECT_CLASSES)}"
        )
    return value


def _validate_gates(gates: Any, context: str) -> None:
    gates = _object(gates, context)
    for name, expected in (("oracle", 1), ("nop", 0)):
        run = _object(gates.get(name), f"{context}.{name}")
        rewards = run.get("rewards")
        if (
            not isinstance(rewards, list)
            or len(rewards) < 2
            or not all(
                isinstance(item, int | float) and not isinstance(item, bool) for item in rewards
            )
        ):
            raise ErrataError(f"{context}.{name}.rewards must list at least two numeric rewards")
        if any(item != expected for item in rewards):
            raise ErrataError(f"{context}.{name}.rewards must all be {expected}: {rewards}")
    _string(gates, "runtime", context)
    _matching(gates, "date", context, ISO_DATE)
    witness = _object(gates.get("witness"), f"{context}.witness")
    _string(witness, "summary", f"{context}.witness")


def _validate_license(license_: Any, context: str) -> str:
    license_ = _object(license_, context)
    upstream = license_.get("upstream")
    if not isinstance(upstream, list) or not all(isinstance(i, str) and i for i in upstream):
        raise ErrataError(f"{context}.upstream must list the upstream licenses or terms")
    redistribution = license_.get("redistribution")
    if redistribution not in REDISTRIBUTION:
        raise ErrataError(f"{context}.redistribution must be one of {', '.join(REDISTRIBUTION)}")
    _url_list(license_.get("basis"), f"{context}.basis")
    _matching(license_, "checked_on", context, ISO_DATE)
    if license_.get("published") != "patch":
        raise ErrataError(f"{context}.published must be 'patch': no task content is published")
    _string(license_, "conclusion", context)
    return redistribution


def _parse_erratum(raw: Any, index: int, registry_dir: Path) -> Erratum:
    context = f"errata[{index}]"
    raw = _object(raw, context)
    erratum_id = _matching(raw, "id", context, LOWER_IDENTIFIER)
    context = f"erratum {erratum_id}"
    benchmark = _matching(raw, "benchmark", context, LOWER_IDENTIFIER)
    task_id = _matching(raw, "task_id", context, TASK_IDENTIFIER)
    status = raw.get("status")
    if status not in STATUSES:
        raise ErrataError(f"{context}.status must be one of {', '.join(STATUSES)}")

    source = _object(raw.get("source"), f"{context}.source")
    _https(source.get("url"), f"{context}.source.url")
    source_revision = _matching(source, "revision", f"{context}.source", SOURCE_REVISION)
    _string(source, "materializer", f"{context}.source")

    files_raw = _object(raw.get("files"), f"{context}.files")
    if not files_raw:
        raise ErrataError(f"{context}.files must name every file the patch changes")
    files: dict[str, tuple[str | None, str | None]] = {}
    for path, hashes in files_raw.items():
        _task_path(path, f"{context}.files", PATCHABLE_DIRS)
        hashes = _object(hashes, f"{context}.files.{path}")
        before = _digest_or_null(hashes.get("before"), f"{context}.files.{path}.before")
        after = _digest_or_null(hashes.get("after"), f"{context}.files.{path}.after")
        if before is None and after is None:
            raise ErrataError(f"{context}.files.{path} needs a before or an after hash")
        files[path] = (before, after)
    depends_raw = _object(raw.get("depends_on", {}), f"{context}.depends_on")
    depends_on: dict[str, str] = {}
    for path, digest in depends_raw.items():
        _task_path(path, f"{context}.depends_on", PINNABLE_DIRS)
        if path in files:
            raise ErrataError(f"{context}.depends_on.{path} is already pinned under files")
        value = _digest_or_null(digest, f"{context}.depends_on.{path}")
        if value is None:
            raise ErrataError(f"{context}.depends_on.{path} must be a SHA256")
        depends_on[path] = value

    defect = _object(raw.get("defect"), f"{context}.defect")
    defect_class = _validate_class(defect, f"{context}.defect")
    _string(defect, "summary", f"{context}.defect")
    evidence = defect.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ErrataError(f"{context}.defect.evidence must cite at least one task file")
    pinned_before = {path for path, (before, _) in files.items() if before} | set(depends_on)
    cited: list[str] = []
    for position, item in enumerate(evidence):
        item = _object(item, f"{context}.defect.evidence[{position}]")
        path = _string(item, "path", f"{context}.defect.evidence[{position}]")
        _string(item, "lines", f"{context}.defect.evidence[{position}]")
        _string(item, "fact", f"{context}.defect.evidence[{position}]")
        if path not in pinned_before:
            raise ErrataError(
                f"{context}.defect.evidence[{position}] cites {path!r}, which is not pinned by a "
                "before hash under files or depends_on"
            )
        cited.append(path)
    must_touch, must_cite = DEFECT_CLASSES[defect_class]
    if not _touches(files, must_touch):
        raise ErrataError(
            f"{context}: a {defect_class} erratum must change one of {', '.join(must_touch)}"
        )
    if not _touches(cited, must_cite):
        raise ErrataError(
            f"{context}: a {defect_class} erratum must cite evidence in {', '.join(must_cite)}"
        )
    if _touches(files, ("tests/",)):
        _string(raw, "answer_review", context)

    upstream = _object(raw.get("upstream"), f"{context}.upstream")
    reports = _url_list(
        upstream.get("reports", []), f"{context}.upstream.reports", allow_empty=True
    )
    if not reports:
        _string(upstream, "not_reported", f"{context}.upstream")
    fixed_in_revision: str | None = None
    if upstream.get("fixed_in") is not None:
        fixed_in = _object(upstream["fixed_in"], f"{context}.upstream.fixed_in")
        _https(fixed_in.get("url"), f"{context}.upstream.fixed_in.url")
        fixed_in_revision = _matching(
            fixed_in, "revision", f"{context}.upstream.fixed_in", SOURCE_REVISION
        )
        if fixed_in_revision == source_revision:
            raise ErrataError(f"{context}.upstream.fixed_in.revision equals source.revision")
    if status == "upstream_fixed" and fixed_in_revision is None:
        raise ErrataError(f"{context}: status upstream_fixed needs upstream.fixed_in")
    if status == "retired":
        retired = _object(raw.get("retired"), f"{context}.retired")
        _matching(retired, "date", f"{context}.retired", ISO_DATE)
        _string(retired, "reason", f"{context}.retired")
    elif raw.get("retired") is not None:
        raise ErrataError(f"{context}.retired is set but status is {status}")

    redistribution = _validate_license(raw.get("license"), f"{context}.license")
    patch = _object(raw.get("patch"), f"{context}.patch")
    patch_sha256 = _matching(patch, "sha256", f"{context}.patch", FULL_SHA256)
    _string(patch, "origin", f"{context}.patch")
    storage = patch.get("storage", "repo")
    patch_path: Path | None
    if storage == "repo":
        if redistribution == "none":
            raise ErrataError(
                f"{context}.patch: the upstream terms forbid redistribution, so the patch stays "
                "out of this repository (storage 'external') and only its SHA256 and its "
                "construction are recorded"
            )
        relative = _string(patch, "path", f"{context}.patch")
        expected = f"patches/{benchmark}/{task_id}/{erratum_id}.patch"
        if relative != expected:
            raise ErrataError(f"{context}.patch.path must be {expected!r}, got {relative!r}")
        patch_path = registry_dir / relative
    elif storage == "external":
        if "path" in patch:
            raise ErrataError(f"{context}.patch: an external patch has no repository path")
        _string(patch, "construction", f"{context}.patch")
        patch_path = None
    else:
        raise ErrataError(f"{context}.patch.storage must be 'repo' or 'external'")

    if status in APPLIED_STATUSES:
        _validate_gates(raw.get("gates"), f"{context}.gates")
    return Erratum(
        id=erratum_id,
        benchmark=benchmark,
        task_id=task_id,
        status=status,
        source_revision=source_revision,
        fixed_in_revision=fixed_in_revision,
        patch_path=patch_path,
        patch_sha256=patch_sha256,
        files=files,
        depends_on=depends_on,
        raw=raw,
    )


def load_registry(path: Path | str) -> tuple[Erratum, ...]:
    """Parse and check every record; patches are checked by :func:`verify_registry`."""
    registry_path = Path(path)
    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErrataError(f"cannot load the errata registry: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ErrataError(f"errata registry schema_version must be {SCHEMA_VERSION}")
    entries = raw.get("errata")
    if not isinstance(entries, list):
        raise ErrataError("errata registry must hold an errata list")
    errata = tuple(
        _parse_erratum(entry, index, registry_path.resolve().parent)
        for index, entry in enumerate(entries)
    )
    ids = [erratum.id for erratum in errata]
    if len(ids) != len(set(ids)):
        raise ErrataError("erratum ids must be unique")
    live: dict[tuple[str, str], str] = {}
    for erratum in errata:
        if erratum.status == "retired":
            continue
        key = (erratum.benchmark, erratum.task_id)
        if key in live:
            raise ErrataError(
                f"{erratum.benchmark}/{erratum.task_id} has two errata that are not "
                f"retired: {live[key]} and {erratum.id}"
            )
        live[key] = erratum.id
    return errata


def _patch_sections(patch: bytes, context: str) -> dict[str, list[str]]:
    """Changed paths of a Git diff, each with its added and removed lines."""
    try:
        text = patch.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ErrataError(f"{context} is not UTF-8 text") from exc
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        header = _DIFF_HEADER.match(line)
        if header:
            old, new = header.groups()
            if old != new:
                raise ErrataError(f"{context} renames {old} to {new}; renames are not allowed")
            if old in sections:
                raise ErrataError(f"{context} changes {old} twice")
            current = sections[old] = []
            continue
        if current is None:
            if line.strip():
                raise ErrataError(f"{context} has text before its first diff header")
            continue
        if line.startswith("GIT binary patch") or line.startswith("Binary files "):
            raise ErrataError(f"{context} contains a binary patch; ship a text diff")
        if line.startswith(("+++ ", "--- ")):
            continue
        if line.startswith(("+", "-")):
            current.append(line)
    if not sections:
        raise ErrataError(f"{context} changes no file")
    return sections


def _check_task_toml_lines(lines: list[str], context: str) -> None:
    for line in lines:
        if line.startswith("+") or not _DOCKER_IMAGE_LINE.match(line[1:]):
            raise ErrataError(
                f"{context}: task.toml may only drop [environment].docker_image; "
                f"found {line!r}. Timeouts, resources and the agent table belong to the runner"
            )


def verify_registry(path: Path | str) -> dict[str, Any]:
    """Records plus every patch in the repository: hash, changed paths, no orphans."""
    registry_path = Path(path)
    errata = load_registry(registry_path)
    referenced: set[Path] = set()
    for erratum in errata:
        if erratum.patch_path is None:
            continue
        context = f"erratum {erratum.id} patch"
        try:
            patch = erratum.patch_path.read_bytes()
        except OSError as exc:
            raise ErrataError(f"{context}: cannot read {erratum.patch_path}: {exc}") from exc
        if _sha256(patch) != erratum.patch_sha256:
            raise ErrataError(f"{context}: SHA256 does not match the record")
        sections = _patch_sections(patch, context)
        if set(sections) != set(erratum.files):
            raise ErrataError(
                f"{context} changes {sorted(sections)}, but the record pins {sorted(erratum.files)}"
            )
        if "task.toml" in sections:
            _check_task_toml_lines(sections["task.toml"], context)
        referenced.add(erratum.patch_path.resolve())
    patches_root = registry_path.resolve().parent / "patches"
    if patches_root.is_dir():
        orphans = sorted(
            p.relative_to(patches_root).as_posix()
            for p in patches_root.rglob("*")
            if p.is_file() and p.resolve() not in referenced
        )
        if orphans:
            raise ErrataError(f"patches without an erratum record: {', '.join(orphans)}")
    counts = {status: 0 for status in STATUSES}
    for erratum in errata:
        counts[erratum.status] += 1
    from benchmark_errata.emcv import load_versions  # noqa: PLC0415 (emcv imports this module)

    return {"errata": len(errata), **counts, "emcv_versions": len(load_versions(registry_path))}


def _file_sha256(task_dir: Path, relative: str) -> str | None:
    path = task_dir.joinpath(*PurePosixPath(relative).parts)
    if path.is_symlink():
        raise ErrataError(f"{task_dir.name}/{relative} is a symbolic link")
    if not path.exists():
        return None
    if not path.is_file():
        raise ErrataError(f"{task_dir.name}/{relative} is not a regular file")
    return _sha256(path.read_bytes())


def _check_hashes(task_dir: Path, expected: dict[str, str | None], what: str, eid: str) -> None:
    for relative, digest in sorted(expected.items()):
        actual = _file_sha256(task_dir, relative)
        if actual != digest:
            raise ErrataError(
                f"erratum {eid}: {what} of {relative} is {actual}, expected {digest}; the task "
                "is not the bytes this erratum was written for, so it is refused"
            )


def mark_task_toml(text: str, erratum_id: str) -> str:
    """Add ``benchmark_erratum`` to ``[metadata]``; everything else reads back unchanged."""
    before = tomllib.loads(text)
    metadata = before.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ErrataError("task.toml metadata is not a table")
    if MARKER_KEY in metadata:
        raise ErrataError(f"task.toml already carries {MARKER_KEY} = {metadata[MARKER_KEY]!r}")
    line = f"{MARKER_KEY} = {json.dumps(erratum_id)}\n"
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    for index, current in enumerate(lines):
        if _METADATA_HEADER.match(current.rstrip("\r\n")):
            lines.insert(index + 1, line)
            break
    else:
        lines.extend(["\n", "[metadata]\n", line])
    marked = "".join(lines)
    try:
        after = tomllib.loads(marked)
    except tomllib.TOMLDecodeError as exc:
        raise ErrataError(f"task.toml does not parse after marking: {exc}") from exc
    expected = {**before, "metadata": {**metadata, MARKER_KEY: erratum_id}}
    if after != expected:
        raise ErrataError("task.toml does not read back after marking")
    return marked


def _git_apply(task_dir: Path, patch: Path) -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    # Never let git discover an enclosing repository: inside one, git apply resolves paths
    # against that repository's root instead of the task directory.
    env["GIT_CEILING_DIRECTORIES"] = str(task_dir.parent)
    for check in (True, False):
        command = ["git", "apply", "-p1", "--whitespace=nowarn"]
        if check:
            command.append("--check")
        result = subprocess.run(
            [*command, str(patch)],
            cwd=task_dir,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ErrataError(f"git apply failed in {task_dir.name}: {detail}")


def _revise_copy(erratum: Erratum, task_dir: Path, staged: Path, patch: Path) -> None:
    expected_before = {path: before for path, (before, _) in erratum.files.items()}
    _check_hashes(task_dir, {**expected_before, **erratum.depends_on}, "before", erratum.id)
    toml_before = (task_dir / "task.toml").read_text(encoding="utf-8")
    shutil.copytree(task_dir, staged, symlinks=True)
    _git_apply(staged, patch)
    expected_after = {path: after for path, (_, after) in erratum.files.items()}
    _check_hashes(staged, expected_after, "after", erratum.id)
    toml_path = staged / "task.toml"
    toml_after = toml_path.read_text(encoding="utf-8")
    old, new = tomllib.loads(toml_before), tomllib.loads(toml_after)
    for document in (old, new):
        document.get("environment", {}).pop("docker_image", None)
    if old != new:
        raise ErrataError(
            f"erratum {erratum.id}: task.toml changed beyond dropping [environment].docker_image"
        )
    toml_path.write_text(mark_task_toml(toml_after, erratum.id), encoding="utf-8")


def tree_sha256(root: Path) -> str:
    """SHA256 of the canonical file manifest: path, size, mode (0644/0755), SHA256 per file."""
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ErrataError(f"{root.name}: not a regular file: {path.relative_to(root)}")
        data = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": len(data),
                "mode": 0o755 if mode & stat.S_IXUSR else 0o644,
                "sha256": _sha256(data),
            }
        )
    canonical = json.dumps(files, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    return _sha256(canonical.encode())


def apply_errata(
    registry: Path | str,
    tasks_root: Path | str,
    sources: dict[str, str],
    *,
    patch_root: Path | str | None = None,
    include_candidates: bool = False,
    benchmark_dirs: dict[str, str] | None = None,
    versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply every live erratum whose ``<benchmark>/<task_id>`` exists under ``tasks_root``.

    ``benchmark_dirs`` maps an erratum's benchmark id to the directory name a runner uses
    for it under ``tasks_root`` (default: the id itself).

    ``sources`` names the upstream revision each benchmark was materialized from. All
    tasks are revised in a staging directory first; the root changes only when every
    erratum applied, and ``benchmark-errata.json`` records what was applied or skipped.
    ``include_candidates`` also applies errata still under their release gates; it is
    for the gate runs themselves, never for a scored run.

    ``versions`` pins a benchmark to a clean version (``emcv.json``): exactly the
    errata that version was cut with are applied, a newer erratum for the same
    benchmark is skipped (``skipped_not_in_version``), and an erratum retired after
    the version was cut still applies, so a version always builds the same bytes.
    """
    registry_path = Path(registry)
    root = Path(tasks_root)
    verify_registry(registry_path)
    errata = load_registry(registry_path)
    record_path = root / APPLIED_RECORD
    if record_path.exists():
        raise ErrataError(f"{record_path} exists: errata apply once to a fresh root")
    for benchmark, value in sources.items():
        if SOURCE_REVISION.fullmatch(value) is None:
            raise ErrataError(f"source revision for {benchmark} is invalid: {value!r}")
    pinned: dict[str, Any] = {}
    if versions:
        from benchmark_errata.emcv import find_version  # noqa: PLC0415 (emcv imports this module)

        for benchmark, version in sorted(versions.items()):
            found = find_version(registry_path, benchmark, version)
            if sources.get(benchmark) != found.revision:
                raise ErrataError(
                    f"clean version {found.name} {version} is {benchmark} at {found.revision}; "
                    f"the tasks come from {sources.get(benchmark)}"
                )
            pinned[benchmark] = found
    plan: list[tuple[Erratum, Path, Path]] = []
    entries: list[dict[str, Any]] = []
    wanted = APPLIED_STATUSES + (("candidate",) if include_candidates else ())
    for erratum in errata:
        local = (benchmark_dirs or {}).get(erratum.benchmark, erratum.benchmark)
        task_dir = root / local / erratum.task_id
        version = pinned.get(erratum.benchmark)
        if not (task_dir / "task.toml").is_file():
            continue
        if version is not None and erratum.id not in version.errata:
            if erratum.status in wanted:
                entries.append(
                    {
                        "benchmark": erratum.benchmark,
                        "benchmark_dir": local,
                        "task_id": erratum.task_id,
                        "erratum": erratum.id,
                        "status": erratum.status,
                        "patch_sha256": erratum.patch_sha256,
                        "action": "skipped_not_in_version",
                    }
                )
            continue
        if version is None and erratum.status not in wanted:
            continue
        source = sources.get(erratum.benchmark)
        if source is None:
            raise ErrataError(
                f"erratum {erratum.id} covers {erratum.benchmark}/{erratum.task_id}; pass "
                f"the source revision {erratum.benchmark} was materialized from"
            )
        entry: dict[str, Any] = {
            "benchmark": erratum.benchmark,
            "benchmark_dir": local,
            "task_id": erratum.task_id,
            "erratum": erratum.id,
            "status": erratum.status,
            "patch_sha256": erratum.patch_sha256,
        }
        if source == erratum.source_revision:
            if erratum.patch_path is not None:
                patch = erratum.patch_path
            elif patch_root is not None:
                patch = Path(patch_root) / erratum.benchmark / erratum.task_id
                patch = patch / f"{erratum.id}.patch"
            else:
                raise ErrataError(
                    f"erratum {erratum.id} keeps its patch outside this repository; "
                    "pass --patch-root"
                )
            if _sha256(patch.read_bytes()) != erratum.patch_sha256:
                raise ErrataError(f"erratum {erratum.id}: patch SHA256 does not match")
            plan.append((erratum, task_dir, patch))
            entry["action"] = "applied"
        elif erratum.status == "upstream_fixed" and source == erratum.fixed_in_revision:
            entry["action"] = "skipped_upstream_fixed"
        else:
            raise ErrataError(
                f"erratum {erratum.id} was written for {erratum.benchmark} at "
                f"{erratum.source_revision}, but the tasks come from {source}; re-verify the "
                "erratum against the new source before applying it"
            )
        entries.append(entry)
    with tempfile.TemporaryDirectory(prefix=".benchmark-errata-", dir=root) as temp:
        staging = Path(temp)
        staged_dirs: list[tuple[Path, Path]] = []
        for erratum, task_dir, patch in plan:
            staged = staging / "new" / erratum.benchmark / erratum.task_id
            staged.parent.mkdir(parents=True, exist_ok=True)
            _revise_copy(erratum, task_dir, staged, patch)
            staged_dirs.append((task_dir, staged))
        by_id = {entry["erratum"]: entry for entry in entries}
        for (erratum, _, _), (task_dir, staged) in zip(plan, staged_dirs, strict=True):
            old = staging / "old" / erratum.benchmark / erratum.task_id
            old.parent.mkdir(parents=True, exist_ok=True)
            os.replace(task_dir, old)
            os.replace(staged, task_dir)
            by_id[erratum.id]["output_tree_sha256"] = tree_sha256(task_dir)
    document = {
        "schema_version": SCHEMA_VERSION,
        "registry_sha256": _sha256(registry_path.read_bytes()),
        "sources": dict(sorted(sources.items())),
        "benchmark_dirs": dict(sorted((benchmark_dirs or {}).items())),
        "include_candidates": include_candidates,
        "emcv": {
            benchmark: {"name": found.name, "version": found.version}
            for benchmark, found in sorted(pinned.items())
        },
        "tasks": entries,
    }
    record_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def build_release(
    registry: Path | str,
    output: Path | str,
    *,
    version: str,
    commit: str,
    card: Path | str | None = None,
) -> dict[str, Any]:
    """Copy the registry and its patches into ``output`` with a SHA256 manifest.

    This is the Hugging Face release layout: ``registry.json``, ``emcv.json`` (when the
    repository has clean versions), ``patches/`` and ``MANIFEST.json`` naming the version and
    the Git commit it was built from.
    """
    registry_path = Path(registry)
    verify_registry(registry_path)
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ErrataError("commit must be a full lowercase Git SHA")
    if re.fullmatch(r"v\d+\.\d+\.\d+", version) is None:
        raise ErrataError("version must look like v1.2.3")
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise ErrataError(f"release output is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(registry_path, out / "registry.json")
    versions = registry_path.resolve().parent / "emcv.json"
    if versions.exists():
        shutil.copyfile(versions, out / "emcv.json")
    if card is not None:
        shutil.copyfile(card, out / "README.md")
    for erratum in load_registry(registry_path):
        if erratum.patch_path is None:
            continue
        relative = erratum.patch_path.relative_to(registry_path.resolve().parent)
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(erratum.patch_path, target)
    files = {
        p.relative_to(out).as_posix(): _sha256(p.read_bytes())
        for p in sorted(out.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "source": {"commit": commit, "registry": "errata/registry.json"},
        "registry_sha256": files["registry.json"],
        "files": files,
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
