---
license: apache-2.0
pretty_name: benchmark-errata
tags:
  - benchmark
  - evaluation
  - agents
---

# benchmark-errata

Patches for defects in public agent-benchmark tasks: instructions that omit a requirement the grader checks, grader bugs, reference programs left in the agent's environment, and starter code that does not match the tests. Each release holds:

- `registry.json`: one record per erratum, with the task id, the upstream revision it was written for, the defect and its evidence (file, lines, fact), the upstream report, the license conclusion, the release gate results and the SHA256 of every file the patch changes or depends on;
- `patches/<benchmark>/<task_id>/<erratum>.patch`: Git diffs against the upstream task directory;
- `MANIFEST.json`: the SHA256 of every file in the release and the source commit it was built from.

No task files, data, expected answers or reference solutions are included. Each patch modifies a task that has its own upstream license or terms, named in the record's `license` field; the records and tools are Apache-2.0.

Source, tools and design: https://github.com/Mike-7777777/benchmark-errata (fork of https://github.com/EvoMap/benchmark-errata). Apply errata with `benchmark-errata apply`, which checks every pinned file before and after patching and refuses a task that is not the bytes an erratum was written for.
