from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import pytest

from benchmark_errata.cli import main
from benchmark_errata.errata import (
    MARKER_KEY,
    ErrataError,
    apply_errata,
    build_release,
    load_registry,
    mark_task_toml,
    tree_sha256,
    verify_registry,
)

SOURCE = "a" * 40
FIXED = "b" * 40
TASK_TOML = """version = "1.0"

[metadata]
author_name = "Example"

[agent]
timeout_sec = 600.0

[environment]
docker_image = "example/task:1"
cpus = 1
"""
DOCKERFILE = "FROM ubuntu:24.04\nCOPY ref.c /app\nRUN gcc -o /app/ref /app/ref.c\n"
TEST_SH = "#!/bin/bash\ngrep -q 'answer = 42' /app/out.txt\n"
INSTRUCTION = "Write the answer to /app/out.txt.\n"
SOLVE_SH = "#!/bin/bash\necho 'answer = 42' > /app/out.txt\n"
DOCKER_FIX = "FROM example/task:1\nRUN rm -f /app/ref\n"
TOML_FIX = TASK_TOML.replace('docker_image = "example/task:1"\n', "")


def _sha(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def _git(cwd: Path, *args: str) -> str:
    # A pre-commit hook runs inside `git commit`, whose GIT_INDEX_FILE and GIT_DIR would
    # otherwise point these fixture repositories at the repository being committed.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _write_task(task: Path) -> None:
    for sub in ("environment", "tests", "solution"):
        (task / sub).mkdir(parents=True)
    (task / "task.toml").write_text(TASK_TOML)
    (task / "instruction.md").write_text(INSTRUCTION)
    (task / "environment" / "Dockerfile").write_text(DOCKERFILE)
    (task / "tests" / "test.sh").write_text(TEST_SH)
    (task / "tests" / "test.sh").chmod(0o755)
    (task / "solution" / "solve.sh").write_text(SOLVE_SH)


def _make_patch(tmp_path: Path, edits: dict[str, str | None]) -> str:
    """A Git diff of the fixture task with ``edits`` applied (None deletes a file)."""
    repo = Path(tempfile.mkdtemp(prefix="patch-source-", dir=tmp_path))
    _write_task(repo)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    for relative, text in edits.items():
        if text is None:
            (repo / relative).unlink()
        else:
            (repo / relative).write_text(text)
    _git(repo, "add", "-A")
    return _git(repo, "diff", "--cached")


def _record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": "bench-task-r1",
        "benchmark": "bench",
        "task_id": "task",
        "status": "active",
        "source": {
            "url": "https://example.com/bench",
            "revision": SOURCE,
            "materializer": "example materializer",
        },
        "license": {
            "upstream": ["Apache-2.0"],
            "redistribution": "allowed",
            "basis": ["https://example.com/bench/LICENSE"],
            "checked_on": "2026-11-25",
            "published": "patch",
            "conclusion": "Apache-2.0 allows redistribution; only the patch is published.",
        },
        "defect": {
            "class": "image_residue",
            "summary": "The image keeps the compiled reference program.",
            "evidence": [
                {"path": "environment/Dockerfile", "lines": "3", "fact": "builds /app/ref"}
            ],
        },
        "upstream": {"reports": ["https://example.com/bench/issues/1"]},
        "patch": {
            "path": "patches/bench/task/bench-task-r1.patch",
            "sha256": "0" * 64,
            "origin": "written for the fixture",
        },
        "files": {
            "environment/Dockerfile": {"before": _sha(DOCKERFILE), "after": _sha(DOCKER_FIX)},
            "task.toml": {"before": _sha(TASK_TOML), "after": _sha(TOML_FIX)},
        },
        "depends_on": {"tests/test.sh": _sha(TEST_SH)},
        "gates": {
            "oracle": {"rewards": [1.0, 1.0]},
            "nop": {"rewards": [0.0, 0.0]},
            "runtime": "Harbor-compatible runner",
            "date": "2026-11-25",
            "witness": {"summary": "upstream image has the program; the revised image does not"},
        },
    }
    record.update(overrides)
    return record


def _registry(
    tmp_path: Path,
    records: list[dict[str, Any]] | None = None,
    patches: dict[str, str] | None = None,
) -> Path:
    root = tmp_path / "errata"
    root.mkdir(exist_ok=True)
    if records is None:
        records = [_record()]
    if patches is None:
        patches = {
            "bench-task-r1": _make_patch(
                tmp_path, {"environment/Dockerfile": DOCKER_FIX, "task.toml": TOML_FIX}
            )
        }
    for record in records:
        text = patches.get(record["id"])
        if text is None or record["patch"].get("storage") == "external":
            continue
        path = root / record["patch"]["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        record["patch"]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    registry = root / "registry.json"
    registry.write_text(json.dumps({"schema_version": 1, "errata": records}, indent=2))
    return registry


def _tasks_root(tmp_path: Path) -> Path:
    root = tmp_path / "tasks"
    _write_task(root / "bench" / "task")
    _write_task(root / "other" / "untouched")
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_apply_revises_the_task_marks_it_and_records_what_was_applied(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    root = _tasks_root(tmp_path)
    untouched = _snapshot(root / "other")

    document = apply_errata(registry, root, {"bench": SOURCE})

    task = root / "bench" / "task"
    assert (task / "environment" / "Dockerfile").read_text() == DOCKER_FIX
    config = tomllib.loads((task / "task.toml").read_text())
    assert config["metadata"] == {"author_name": "Example", MARKER_KEY: "bench-task-r1"}
    assert "docker_image" not in config["environment"]
    assert config["agent"] == {"timeout_sec": 600.0}
    assert _snapshot(root / "other") == untouched
    assert [entry["action"] for entry in document["tasks"]] == ["applied"]
    assert document["tasks"][0]["output_tree_sha256"] == tree_sha256(task)
    assert json.loads((root / "benchmark-errata.json").read_text()) == document
    assert not [p for p in root.iterdir() if p.name.startswith(".benchmark-errata-")]


@pytest.mark.parametrize("drifted", ["environment/Dockerfile", "tests/test.sh"])
def test_a_task_that_drifted_from_the_pinned_bytes_is_refused_untouched(
    tmp_path: Path, drifted: str
) -> None:
    registry = _registry(tmp_path)
    root = _tasks_root(tmp_path)
    (root / "bench" / "task" / drifted).write_text("changed upstream\n")
    before = _snapshot(root)

    with pytest.raises(ErrataError, match=f"before of {drifted}"):
        apply_errata(registry, root, {"bench": SOURCE})
    assert _snapshot(root) == before


def test_a_new_upstream_source_is_refused_and_a_fixed_one_is_skipped(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(ErrataError, match="re-verify the erratum"):
        apply_errata(registry, _tasks_root(tmp_path), {"bench": FIXED})
    with pytest.raises(ErrataError, match="pass the source revision"):
        apply_errata(registry, tmp_path / "tasks", {})

    fixed = _record(
        status="upstream_fixed",
        upstream={
            "reports": ["https://example.com/bench/pull/2"],
            "fixed_in": {"url": "https://example.com/bench/pull/2", "revision": FIXED},
        },
    )
    registry = _registry(tmp_path, [fixed])
    root = tmp_path / "tasks"
    before = _snapshot(root / "bench")
    document = apply_errata(registry, root, {"bench": FIXED})
    assert [entry["action"] for entry in document["tasks"]] == ["skipped_upstream_fixed"]
    assert _snapshot(root / "bench") == before


def test_a_retired_erratum_is_never_applied(tmp_path: Path) -> None:
    retired = _record(status="retired", retired={"date": "2026-11-25", "reason": "upstream fix"})
    registry = _registry(tmp_path, [retired])
    root = _tasks_root(tmp_path)
    before = _snapshot(root / "bench")
    assert apply_errata(registry, root, {"bench": SOURCE})["tasks"] == []
    assert _snapshot(root / "bench") == before


def test_a_candidate_applies_only_to_gate_runs_and_needs_no_gate_results(tmp_path: Path) -> None:
    record = _record(status="candidate")
    del record["gates"]
    registry = _registry(tmp_path, [record])
    root = _tasks_root(tmp_path)
    before = _snapshot(root / "bench")
    assert apply_errata(registry, root, {"bench": SOURCE})["tasks"] == []
    assert _snapshot(root / "bench") == before
    (root / "benchmark-errata.json").unlink()
    document = apply_errata(registry, root, {"bench": SOURCE}, include_candidates=True)
    assert [(e["status"], e["action"]) for e in document["tasks"]] == [("candidate", "applied")]
    assert document["include_candidates"] is True


def test_apply_inside_an_enclosing_git_repository_patches_the_task_directory(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    root = _tasks_root(tmp_path)
    _git(root, "init", "-q")
    apply_errata(registry, root, {"bench": SOURCE})
    assert (root / "bench" / "task" / "environment" / "Dockerfile").read_text() == DOCKER_FIX
    assert not (root / "environment").exists()


@pytest.mark.parametrize("environment_class", ["network_policy", "gateway", "host", "budget"])
def test_environment_faults_are_rejected_as_not_task_defects(
    tmp_path: Path, environment_class: str
) -> None:
    record = _record()
    record["defect"]["class"] = environment_class
    with pytest.raises(ErrataError, match="fix the environment where it runs"):
        load_registry(_registry(tmp_path, [record]))


def test_the_patch_must_touch_what_its_defect_class_requires(tmp_path: Path) -> None:
    record = _record()
    record["files"] = {"instruction.md": {"before": _sha(INSTRUCTION), "after": _sha("x\n")}}
    record["depends_on"]["environment/Dockerfile"] = _sha(DOCKERFILE)
    with pytest.raises(ErrataError, match="image_residue erratum must change"):
        load_registry(_registry(tmp_path, [record]))


def test_evidence_must_cite_a_hash_pinned_file(tmp_path: Path) -> None:
    record = _record()
    record["defect"]["evidence"].append({"path": "instruction.md", "lines": "1", "fact": "x"})
    with pytest.raises(ErrataError, match="not pinned by a before hash"):
        load_registry(_registry(tmp_path, [record]))


def test_a_public_erratum_never_changes_a_reference_solution(tmp_path: Path) -> None:
    record = _record()
    record["files"]["solution/solve.sh"] = {"before": _sha(SOLVE_SH), "after": _sha("x\n")}
    with pytest.raises(ErrataError, match="never changes a reference solution"):
        load_registry(_registry(tmp_path, [record]))
    pinned = _record()
    pinned["depends_on"]["solution/solve.sh"] = _sha(SOLVE_SH)
    assert load_registry(_registry(tmp_path, [pinned]))


def test_a_grader_change_must_state_that_it_carries_no_expected_answers(tmp_path: Path) -> None:
    record = _record()
    record["defect"]["class"] = "grader_bug"
    record["defect"]["evidence"] = [{"path": "tests/test.sh", "lines": "2", "fact": "wrong"}]
    record["files"] = {"tests/test.sh": {"before": _sha(TEST_SH), "after": _sha("x\n")}}
    record["depends_on"] = {}
    with pytest.raises(ErrataError, match="answer_review"):
        load_registry(_registry(tmp_path, [copy.deepcopy(record)]))
    record["answer_review"] = "Changes a comparison operator; no expected value is added."
    assert load_registry(_registry(tmp_path, [record]))[0].id == "bench-task-r1"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("oracle", {"rewards": [1.0]}, "at least two"),
        ("oracle", {"rewards": [1.0, 0.0]}, "must all be 1"),
        ("nop", {"rewards": [0.0, 1.0]}, "must all be 0"),
    ],
)
def test_live_errata_need_passing_release_gates(
    tmp_path: Path, field: str, value: dict[str, Any], message: str
) -> None:
    record = _record()
    record["gates"][field] = value
    with pytest.raises(ErrataError, match=message):
        load_registry(_registry(tmp_path, [record]))


def test_every_erratum_records_its_license_conclusion(tmp_path: Path) -> None:
    record = _record()
    del record["license"]["conclusion"]
    with pytest.raises(ErrataError, match="license.conclusion"):
        load_registry(_registry(tmp_path, [copy.deepcopy(record)]))
    record = _record()
    record["license"]["published"] = "patch_and_task"
    with pytest.raises(ErrataError, match="no task content is published"):
        load_registry(_registry(tmp_path, [record]))


def test_a_dataset_that_forbids_redistribution_keeps_its_patch_out(tmp_path: Path) -> None:
    record = _record()
    record["license"]["redistribution"] = "none"
    with pytest.raises(ErrataError, match="forbid redistribution"):
        load_registry(_registry(tmp_path, [copy.deepcopy(record)]))
    record["patch"] = {
        "storage": "external",
        "sha256": "1" * 64,
        "origin": "kept by the maintainer",
        "construction": "Delete line 3 of environment/Dockerfile and add `RUN rm -f /app/ref`.",
    }
    assert load_registry(_registry(tmp_path, [record]))[0].patch_path is None


def test_task_toml_patches_may_only_drop_the_prebuilt_image(tmp_path: Path) -> None:
    widened = TASK_TOML.replace("timeout_sec = 600.0", "timeout_sec = 3600.0")
    record = _record()
    record["files"]["task.toml"]["after"] = _sha(widened)
    patch = _make_patch(tmp_path, {"environment/Dockerfile": DOCKER_FIX, "task.toml": widened})
    with pytest.raises(ErrataError, match="may only drop"):
        verify_registry(_registry(tmp_path, [record], {"bench-task-r1": patch}))


def test_the_record_must_name_exactly_the_files_the_patch_changes(tmp_path: Path) -> None:
    record = _record()
    del record["files"]["task.toml"]
    patch = _make_patch(tmp_path, {"environment/Dockerfile": DOCKER_FIX, "task.toml": TOML_FIX})
    with pytest.raises(ErrataError, match="but the record pins"):
        verify_registry(_registry(tmp_path, [record], {"bench-task-r1": patch}))


def test_patch_hashes_and_orphans_are_checked(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    (tmp_path / "errata" / "patches" / "bench" / "stray.patch").write_text("x")
    with pytest.raises(ErrataError, match="patches without an erratum record"):
        verify_registry(registry)
    (tmp_path / "errata" / "patches" / "bench" / "stray.patch").unlink()
    patch = tmp_path / "errata" / "patches" / "bench" / "task" / "bench-task-r1.patch"
    patch.write_text(patch.read_text() + "\n")
    with pytest.raises(ErrataError, match="SHA256 does not match"):
        verify_registry(registry)


def test_one_task_has_at_most_one_live_erratum(tmp_path: Path) -> None:
    second = _record(id="bench-task-r2")
    second["patch"]["path"] = "patches/bench/task/bench-task-r2.patch"
    with pytest.raises(ErrataError, match="two errata that are not retired"):
        load_registry(_registry(tmp_path, [_record(), second]))


def test_an_unreported_defect_says_why(tmp_path: Path) -> None:
    record = _record(upstream={"reports": []})
    with pytest.raises(ErrataError, match="not_reported"):
        load_registry(_registry(tmp_path, [copy.deepcopy(record)]))
    record["upstream"]["not_reported"] = "upstream repository is archived"
    assert load_registry(_registry(tmp_path, [record]))


def test_marking_keeps_every_other_task_toml_value() -> None:
    marked = mark_task_toml(TASK_TOML, "x-r1")
    assert tomllib.loads(marked)["metadata"] == {"author_name": "Example", MARKER_KEY: "x-r1"}
    bare = mark_task_toml('version = "1.0"\n', "x-r1")
    assert tomllib.loads(bare) == {"version": "1.0", "metadata": {MARKER_KEY: "x-r1"}}
    with pytest.raises(ErrataError, match="already carries"):
        mark_task_toml(marked, "x-r2")


def test_release_copies_registry_patches_and_a_manifest(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    card = tmp_path / "card.md"
    card.write_text("# card\n")
    out = tmp_path / "release"
    manifest = build_release(registry, out, version="v0.1.0", commit="c" * 40, card=card)
    assert sorted(manifest["files"]) == [
        "README.md",
        "patches/bench/task/bench-task-r1.patch",
        "registry.json",
    ]
    assert manifest["registry_sha256"] == hashlib.sha256(registry.read_bytes()).hexdigest()
    assert json.loads((out / "MANIFEST.json").read_text()) == manifest
    with pytest.raises(ErrataError, match="not empty"):
        build_release(registry, out, version="v0.1.0", commit="c" * 40)


def test_cli_verifies_and_applies(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    registry = _registry(tmp_path)
    root = _tasks_root(tmp_path)
    assert main(["verify", "--registry", str(registry)]) == 0
    assert json.loads(capsys.readouterr().out)["active"] == 1
    argv = ["apply", "--registry", str(registry), "--tasks-root", str(root)]
    assert main([*argv, "--source", f"bench={SOURCE}"]) == 0
    assert json.loads(capsys.readouterr().out)["tasks"][0]["action"] == "applied"
    with pytest.raises(SystemExit):
        main([*argv, "--source", f"bench={SOURCE}"])
    assert "errata apply once" in capsys.readouterr().err


def test_the_repository_registry_verifies() -> None:
    assert verify_registry(Path(__file__).parents[1] / "errata" / "registry.json")


def test_a_runner_can_keep_its_own_directory_name_for_a_benchmark(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    root = tmp_path / "tasks"
    _write_task(root / "local-bench" / "task")
    document = apply_errata(
        registry, root, {"bench": SOURCE}, benchmark_dirs={"bench": "local-bench"}
    )
    assert [(e["benchmark_dir"], e["action"]) for e in document["tasks"]] == [
        ("local-bench", "applied")
    ]
    assert (root / "local-bench" / "task" / "environment" / "Dockerfile").read_text() == DOCKER_FIX
