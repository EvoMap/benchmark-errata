# benchmark-errata

Patches for defects in public agent-benchmark tasks: instructions that omit a requirement the grader checks, grader bugs, reference programs left in the agent's environment, and starter code that does not match the tests. Each erratum carries its evidence, its upstream report, the upstream revision it was written for and the SHA256 of every file it changes or depends on. A runner applies errata by task id after materializing a benchmark, and stops applying one once upstream fixes the task.

Only defects of the task or dataset itself are accepted. A fault of the evaluation environment (network policy, model gateway, host resources, image build tooling, the benchmark adapter, run budget) is fixed where it runs; the validator rejects those classes.

![Errata flow](docs/flow.svg)

## Errata

| Erratum | Task | Defect | Upstream report | Status |
|---|---|---|---|---|
| `tb2-path-tracing-r1` | Terminal-Bench 2.0 `path-tracing` | The compiled reference renderer stays in the image | [harbor-framework/terminal-bench-2#61](https://github.com/harbor-framework/terminal-bench-2/issues/61) | active |
| `harbor-index-dacode-predict-essay-scores-r1` | Harbor Index `dacode-predict-essay-scores` | The QWK pass bar exists only in the grader | [harbor-framework/harbor-index#156](https://github.com/harbor-framework/harbor-index/pull/156) | active |
| `aider-polyglot-go-octal-r1` | Aider polyglot `polyglot_go_octal` | The stub's signature does not match the tests | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `tb2-adaptive-rejection-sampler-r1` | Terminal-Bench 2.0 `adaptive-rejection-sampler` | The tests call a signature the instruction does not give (stated in Terminal-Bench 2.1) | not needed: [fixed upstream](https://github.com/harbor-framework/terminal-bench-2-1/tree/12b7565679ce5006230b820666353673a133db93/tasks/adaptive-rejection-sampler) | upstream_fixed |
| `tb2-raman-fitting-r1` | Terminal-Bench 2.0 `raman-fitting` | The expected peak needs a fit window the instruction does not give | [harbor-framework/terminal-bench-2-1#259](https://github.com/harbor-framework/terminal-bench-2-1/pull/259) | active |
| `harbor-index-scicode-dna-binding-site-scanner-r1` | Harbor Index `scicode-dna-binding-site-scanner` | The expected values depend on three conventions the instruction does not state | [harbor-framework/harbor-index#154](https://github.com/harbor-framework/harbor-index/pull/154) | active |
| `harbor-index-sldbench-discover-vocab-scaling-law-r1` | Harbor Index `sldbench-discover-vocab-scaling-law` | The R² pass bar exists only in the grader; the image caches the test split | [harbor-framework/harbor-index#158](https://github.com/harbor-framework/harbor-index/pull/158), [harbor-framework/harbor-index#157](https://github.com/harbor-framework/harbor-index/pull/157), [harbor-framework/adapters#134](https://github.com/harbor-framework/adapters/pull/134) | active |
| `harbor-index-swebenchverified-fix-annotate-xy-array-copy-r1` | Harbor Index `swebenchverified-fix-annotate-xy-array-copy` | The test also checks a copy the instruction does not report | [harbor-framework/harbor-index#154](https://github.com/harbor-framework/harbor-index/pull/154), [SWE-bench/SWE-bench#727](https://github.com/SWE-bench/SWE-bench/issues/727) | active |
| `harbor-index-swebenchverified-fix-sphinx-literal-nitpick-r1` | Harbor Index `swebenchverified-fix-sphinx-literal-nitpick` | The test pins a node shape the instruction does not ask for | [harbor-framework/harbor-index#154](https://github.com/harbor-framework/harbor-index/pull/154), [SWE-bench/SWE-bench#727](https://github.com/SWE-bench/SWE-bench/issues/727) | active |
| `harbor-index-swebenchverified-fix-span-selector-axes-limits-r1` | Harbor Index `swebenchverified-fix-span-selector-axes-limits` | The pip cache in the image holds a wheel with the fix | [harbor-framework/harbor-index#152](https://github.com/harbor-framework/harbor-index/issues/152) | active |
| `swe-live-xroche__httrack-876-r1` | SWE-bench-Live MultiLang `xroche__httrack-876` | The test probes a file type outside the instruction's list | [microsoft/SWE-bench-Live#116](https://github.com/microsoft/SWE-bench-Live/issues/116) | upstream_fixed |
| `swe-live-xroche__httrack-454-r1` | SWE-bench-Live MultiLang `xroche__httrack-454` | The self-test asserts a MIME pair the instruction does not list | [microsoft/SWE-bench-Live#116](https://github.com/microsoft/SWE-bench-Live/issues/116) | upstream_fixed |
| `swe-live-aomediacodec__libavif-3273-r1` | SWE-bench-Live MultiLang `AOMediaCodec__libavif-3273` | The test reads a pre-encode dump instead of the written file | [microsoft/SWE-bench-Live#116](https://github.com/microsoft/SWE-bench-Live/issues/116) | upstream_fixed |
| `swe-live-varnishcache__varnish-cache-4370-r1` | SWE-bench-Live MultiLang `varnishcache__varnish-cache-4370` | The test changes a second behaviour; the log parser reads summary counts | [microsoft/SWE-bench-Live#116](https://github.com/microsoft/SWE-bench-Live/issues/116) | upstream_fixed |
| `swe-live-colbymchenry__codegraph-454-r1` | SWE-bench-Live MultiLang `colbymchenry__codegraph-454` | The test requires a node kind the instruction does not ask for | [microsoft/SWE-bench-Live#116](https://github.com/microsoft/SWE-bench-Live/issues/116) | upstream_fixed |
| `swe-live-gsd-build__gsd-2-2643-r1` | SWE-bench-Live MultiLang `gsd-build__gsd-2-2643` | The test asserts a reason phrase the instruction never gives | [microsoft/SWE-bench-Live#116](https://github.com/microsoft/SWE-bench-Live/issues/116) | active |
| `swe-live-gsd-build__gsd-2-3258-r1` | SWE-bench-Live MultiLang `gsd-build__gsd-2-3258` | A type-check the instruction does not mention runs before every test | [microsoft/SWE-bench-Live#116](https://github.com/microsoft/SWE-bench-Live/issues/116) | active |
| `swe-live-yvgude__lean-ctx-1164-r1` | SWE-bench-Live MultiLang `yvgude__lean-ctx-1164` | The test calls names only the reference patch defines; stderr goes to a file named 1 | [microsoft/SWE-bench-Live#118](https://github.com/microsoft/SWE-bench-Live/issues/118) | active |
| `aider-polyglot-javascript-two-bucket-r1` | Aider polyglot `polyglot_javascript_two-bucket` | The tests require the constructor to reject an unreachable goal | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `aider-polyglot-java-all-your-base-r1` | Aider polyglot `polyglot_java_all-your-base` | The tests assert exception messages and edge cases the instruction does not state | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `aider-polyglot-cpp-yacht-r1` | Aider polyglot `polyglot_cpp_yacht` | The header stub gives none of the interface the tests call | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `aider-polyglot-cpp-sublist-r1` | Aider polyglot `polyglot_cpp_sublist` | The header stub gives none of the interface the tests call | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `aider-polyglot-rust-acronym-r1` | Aider polyglot `polyglot_rust_acronym` | A Rust-only test contradicts the instruction's rules | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `aider-polyglot-javascript-alphametics-r1` | Aider polyglot `polyglot_javascript_alphametics` | Return value for no solution and the puzzle format are not stated | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `aider-polyglot-go-connect-r1` | Aider polyglot `polyglot_go_connect` | The tests pass boards in another format than the instruction shows | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `aider-polyglot-python-food-chain-r1` | Aider polyglot `polyglot_python_food-chain` | The return format is not stated | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `aider-polyglot-java-wordy-r1` | Aider polyglot `polyglot_java_wordy` | The tests assert an exception message the instruction does not give | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `aider-polyglot-cpp-grade-school-r1` | Aider polyglot `polyglot_cpp_grade-school` | The header stub gives none of the interface the tests call | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `aider-polyglot-java-alphametics-r1` | Aider polyglot `polyglot_java_alphametics` | The puzzle format differs from the instruction's example | [Aider-AI/polyglot-benchmark#26](https://github.com/Aider-AI/polyglot-benchmark/pull/26) | active |
| `tb2-extract-elf-r1` | Terminal-Bench 2.0 `extract-elf` | The address rule and word format exist only in the grader; the example contradicts them | [harbor-framework/terminal-bench-2-1#194](https://github.com/harbor-framework/terminal-bench-2-1/issues/194) | active |
| `tb2-openssl-selfsigned-cert-r1` | Terminal-Bench 2.0 `openssl-selfsigned-cert` | The grader runs the agent's script with its own isolated interpreter | [harbor-framework/terminal-bench-2-1#264](https://github.com/harbor-framework/terminal-bench-2-1/issues/264) | active |
| `aider-polyglot-javascript-simple-linked-list-r1` | Aider polyglot `polyglot_javascript_simple-linked-list` | The tests fix an interface the instruction never gives | [Aider-AI/polyglot-benchmark#26 (comment)](https://github.com/Aider-AI/polyglot-benchmark/pull/26#issuecomment-7236899794) | active |
| `aider-polyglot-javascript-zipper-r1` | Aider polyglot `polyglot_javascript_zipper` | The value for a missing node is not stated | [Aider-AI/polyglot-benchmark#26 (comment)](https://github.com/Aider-AI/polyglot-benchmark/pull/26#issuecomment-7236899794) | active |
| `aider-polyglot-java-food-chain-r1` | Aider polyglot `polyglot_java_food-chain` | The string format of the verses is not stated | [Aider-AI/polyglot-benchmark#26 (comment)](https://github.com/Aider-AI/polyglot-benchmark/pull/26#issuecomment-7236899794) | active |
| `harbor-index-algotune-simplex-projection-speedup-r1` | Harbor Index `algotune-simplex-projection-speedup` | Only solver.py reaches the grader, and the pass bar differs from the instruction's | [harbor-framework/harbor-index#161](https://github.com/harbor-framework/harbor-index/issues/161) | active |
| `harbor-index-algotune-optimize-matrix-sqrt-r1` | Harbor Index `algotune-optimize-matrix-sqrt` | The instruction's list output costs time the grader's own solution does not pay; the bar differs | [harbor-framework/harbor-index#161](https://github.com/harbor-framework/harbor-index/issues/161) | active |
| `swe-live-xroche__httrack-482-r1` | SWE-bench-Live MultiLang `xroche__httrack-482` | The test bounds the grace period the instruction leaves open | [microsoft/SWE-bench-Live#124](https://github.com/microsoft/SWE-bench-Live/issues/124) | active |

The records are in [`errata/registry.json`](errata/registry.json) and the patches under [`errata/patches/`](errata/patches/); a record whose patch would carry hidden test content or a reference patch keeps only the patch's SHA256 and construction (`patch.storage: "external"`). Releases are published as the Hugging Face dataset [`mike-7777777/benchmark-errata`](https://huggingface.co/datasets/mike-7777777/benchmark-errata), one tag per version.

## What is published

Only patches, records and tools. No task files, data, expected answers or reference solutions are published, whatever the upstream license allows:

- a patch never changes a file under `solution/`;
- a patch that changes `tests/` states in `answer_review` that it adds no expected answer or ground truth;
- when the upstream terms forbid redistribution, the patch file stays out of this repository (`patch.storage: "external"`) and the record keeps only its SHA256 and how to construct it;
- every record carries the license conclusion it was published under (`license`).

## Use

```bash
uv sync
uv run benchmark-errata verify

# after materializing tasks as <root>/<benchmark>/<task_id>/
uv run benchmark-errata apply --tasks-root <root> \
  --source terminal-bench-2.0=<revision the tasks came from> \
  --benchmark-dir terminal-bench-2.0=<directory name your runner uses>
```

`apply` checks every pinned file before and after patching and refuses the whole root on any mismatch. It adds `benchmark_erratum = "<id>"` to the `[metadata]` table of each patched `task.toml` and writes `benchmark-errata.json` at the root with what it applied or skipped. `--include-candidates` also applies errata that have not passed their release gates yet; use it for gate runs only. An erratum whose patch would carry hidden test content or a reference patch keeps its patch outside this repository (`patch.storage: "external"`); pass the directory that holds such patches with `--patch-root`.

## Clean versions

A clean version (emcv) is an upstream revision plus a pinned set of released errata, named `<upstream repository name>_emcv` and versioned `emcv-<first 8 hex of the upstream revision>-r<N>`. The versions are listed in [`errata/emcv.json`](errata/emcv.json); `verify` checks them against the registry.

```bash
# apply exactly the errata a version was cut with
uv run benchmark-errata apply --tasks-root <root> --source <benchmark>=<revision> \
  --emcv <benchmark>=emcv-<8 hex>-r<N>

# build one benchmark's clean version from its upstream tasks, with a record of every task's tree SHA256
uv run benchmark-errata emcv build --benchmark <benchmark> --version emcv-<8 hex>-r<N> \
  --tasks-root <upstream root> --output <dir>

# compare our revision with a newer upstream one: which errata upstream adopted, touched or left alone,
# and which other tasks changed upstream
uv run benchmark-errata emcv diff --benchmark <benchmark> --old-root <tasks at our revision> \
  --new-root <tasks at the new revision>
```

Whether a built version may be published whole is its `distribution` (`tasks` or `patches`), set from the upstream licenses; this repository publishes only patches and records either way. See [docs/design.md](docs/design.md), section 7.

## Release gates

An erratum moves from `candidate` to `active` after the patched task scores 1 with the reference solution at least twice, 0 with a no-op agent at least twice, and a witness shows the defect on the upstream bytes and its absence after the patch. The design, the record fields and the lifecycle are in [docs/design.md](docs/design.md).

## License

Apache-2.0 for the tools, records and the text written here. Each patch modifies a task that has its own upstream license or terms; the record's `license` field names them.
