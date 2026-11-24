# Contributing

An erratum is welcome when the defect belongs to the task or dataset itself and would persist in a correctly configured environment. Read [docs/design.md](docs/design.md) first; it defines the four accepted classes and what the validator checks.

## Adding an erratum

1. Materialize the upstream task at a fixed revision, unmodified.
2. Write the fix and produce a Git diff relative to the task directory (`git diff --no-index` between the upstream copy and the fixed copy, paths starting with `a/` and `b/`).
3. Add the patch under `errata/patches/<benchmark>/<task_id>/<erratum id>.patch` and a record in `errata/registry.json` with status `candidate`: source, license conclusion, defect evidence (file, lines, fact), upstream report, and the before and after SHA256 of every changed file plus the files the fix depends on.
4. Report the defect upstream and link the report. If you cannot, say why in `upstream.not_reported`.
5. Run the release gates: `benchmark-errata apply --include-candidates`, then the reference solution twice (reward 1 each time) and a no-op agent twice (reward 0 each time), plus the witness for the defect class. Record the results under `gates` and set the status to `active`.

Never include task files, data, expected answers or reference solutions. A patch must not change `solution/`; a patch that changes `tests/` explains in `answer_review` why it adds no expected answer.

## Checks

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
uv run benchmark-errata verify
```

When upstream fixes a task, set `upstream.fixed_in` and the status to `upstream_fixed`. Once runners have moved to the fixed revision, set it to `retired` with the date and reason; records and patches stay so earlier runs can be reproduced.
