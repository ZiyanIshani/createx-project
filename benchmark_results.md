# Due Diligence Benchmark Results

**Date:** 2026-03-17
**Tool:** AI-Powered Due Diligence Pipeline (Steps 1 & 2)
**Machine:** macOS Darwin 24.1.0

---

## Summary Table

| Repo                                            | Language   | LOC Parsed | Runtime (real)    | Arch Risk Score | Internal Files | External Deps | Circular Dep Groups |
| ----------------------------------------------- | ---------- | ---------- | ----------------- | --------------- | -------------- | ------------- | ------------------- |
| [requests](https://github.com/psf/requests)     | Python     | 11,164     | 59.6s             | 3/10            | 132            | 53            | 0                   |
| [express](https://github.com/expressjs/express) | JavaScript | 21,346     | 25.7s             | 5/10            | 212            | 50            | 2                   |
| [fastapi](https://github.com/tiangolo/fastapi)  | Python     | 107,291    | 2053.4s (~34 min) | 6/10            | 2,915          | 78            | 1                   |

> **LOC** = lines in primary source files (.py / .js / .ts). Runtime measured with `/usr/bin/time -p`.

---

## requests (Python)

**Runtime:** 59.6s real / 50.8s user / 1.1s sys
**LOC:** 11,164 Python lines

### Language Breakdown (top 5)

| Language | Files |
| -------- | ----- |
| Unknown  | 70    |
| Markdown | 12    |
| YAML     | 10    |
| HTML     | 3     |
| CSS      | 1     |

### Top Contributors

| Name                | Commits | Recency     |
| ------------------- | ------- | ----------- |
| Kenneth Reitz       | 2,141   | inactive    |
| Kenneth Reitz (alt) | 1,006   | inactive    |
| Cory Benfield       | 610     | inactive    |
| Ian Cordasco        | 293     | semi-active |
| Nate Prewitt        | 195     | active      |

### Dependency Graph Metrics

| Metric                     | Value    |
| -------------------------- | -------- |
| Internal files             | 132      |
| External dependencies      | 53       |
| Edges                      | 166      |
| Avg in-degree              | —        |
| Max in-degree              | —        |
| Orphaned files             | 98 (74%) |
| Circular dependency groups | 0        |

### Architectural Risk

- **Score: 3/10**
- 98 orphaned files (74% of codebase) — likely dead code or broken imports.

---

## express (Node.js)

**Runtime:** 25.7s real / 22.7s user / 0.9s sys
**LOC:** 21,346 JS/TS lines

### Language Breakdown (top 5)

| Language   | Files |
| ---------- | ----- |
| JavaScript | 141   |
| Unknown    | 48    |
| YAML       | 6     |
| Markdown   | 4     |
| CSS        | 4     |

### Top Contributors

| Name                       | Commits | Recency     |
| -------------------------- | ------- | ----------- |
| visionmedia                | 3,881   | inactive    |
| Douglas Christopher Wilson | 1,232   | inactive    |
| Jonathan Ong               | 84      | inactive    |
| Roman Shtylman             | 70      | inactive    |
| Wes                        | 45      | semi-active |

### Dependency Graph Metrics

| Metric                     | Value    |
| -------------------------- | -------- |
| Internal files             | 212      |
| External dependencies      | 50       |
| Edges                      | 296      |
| Avg in-degree              | —        |
| Max in-degree              | —        |
| Orphaned files             | 75 (35%) |
| Circular dependency groups | 2        |

### Architectural Risk

- **Score: 5/10**
- 2 circular dependency groups detected.
- 75 orphaned files (35% of codebase).

---

## fastapi (Python)

**Runtime:** 2053.4s real / 2012.4s user / 25.7s sys (~34 minutes)
**LOC:** 107,291 Python lines

### Language Breakdown (top 5)

| Language | Files |
| -------- | ----- |
| Markdown | 1,488 |
| Python   | 1,118 |
| Unknown  | 242   |
| YAML     | 51    |
| Shell    | 6     |

### Top Contributors

| Name                | Commits | Recency     |
| ------------------- | ------- | ----------- |
| github-actions      | 2,237   | semi-active |
| Sebastián Ramírez   | 2,019   | active      |
| github-actions[bot] | 456     | active      |
| dependabot[bot]     | 153     | active      |
| Nils Lindemann      | 131     | inactive    |

### Dependency Graph Metrics

| Metric                     | Value       |
| -------------------------- | ----------- |
| Internal files             | 2,915       |
| External dependencies      | 78          |
| Edges                      | 3,171       |
| Avg in-degree              | 0.51        |
| Max in-degree              | 573         |
| Orphaned files             | 1,977 (68%) |
| Circular dependency groups | 1           |

### Fragile Files (highest in-degree)

| File                                 | In-Degree |
| ------------------------------------ | --------- |
| docs/en/docs/reference/fastapi.md    | 573       |
| docs/en/docs/reference/testclient.md | 449       |
| docs/en/docs/reference/responses.md  | 73        |

### Top External Dependencies

| Package         | Import Count |
| --------------- | ------------ |
| inline_snapshot | 297          |
| pytest          | 269          |
| pydantic        | 231          |
| typing          | 203          |
| importlib       | 157          |

### Architectural Risk

- **Score: 6/10**
- 1 circular dependency group detected.
- Max in-degree (573) is 20% of internal file count.
- 1,977 orphaned files (68% of codebase) — likely dead code or broken imports.

---

## Performance Notes

- **express** was the fastest despite having more LOC than requests — likely due to simpler git history and fewer files to blame-walk.
- **requests** (~59s) stays within the 60s pipeline target for repos ≤50k LOC.
- **fastapi** (~34 min) significantly exceeds the 60s target. The large doc tree (1,488 Markdown files) and massive git history drive up bus-factor blame-walking time. This indicates the pipeline needs optimization for large monorepo-style repos.
- The high orphaned-file ratios across all repos are partly expected: the dep graph currently only tracks files that appear in import statements; test fixtures, docs, and config files show up as disconnected nodes.
