# AI-Powered Technical Due Diligence

Automated technical due diligence for M&A transactions targeting the middle market (deals under $100M). Analyzes software repositories and produces risk reports covering contributor continuity, architectural fragility, and technical debt — fully offline, no LLM required.

## What It Does

The pipeline runs two stages against any local git repository:

**Step 1 — Repository Ingestion**
- Contributor statistics: commit counts, activity timelines, recency scoring
- Bus factor analysis: identifies files touched by only one contributor
- Language detection across all tracked files

**Step 2 — Static Analysis**
- Tree-sitter AST parsing extracts imports and function calls per file
- Dependency graph construction using NetworkX
- Risk metrics: circular dependencies, fragile hubs, orphaned files, external package exposure
- Architectural risk score (0–10)

## Installation

```bash
pip install -r requirements.txt
```

**Dependencies:**
- `pygit2>=1.14.0` — git history and blame without subprocess calls
- `networkx>=3.0` — dependency graph construction and analysis
- `tree-sitter>=0.21.0,<0.22.0` — AST parsing
- `tree-sitter-languages>=1.10.0` — pre-built language grammars

## Usage

```bash
python main.py <repo_path> [--ref HEAD] [--output json|pretty]
```

**Arguments:**
- `repo_path` — path to the git repository to analyze
- `--ref` — git ref to analyze (default: `HEAD`)
- `--output` — `json` (default) or `pretty` for a human-readable report

**Examples:**

```bash
# JSON output (pipe-friendly)
python main.py /path/to/repo

# Human-readable report
python main.py /path/to/repo --output pretty

# Analyze a specific branch or tag
python main.py /path/to/repo --ref main --output pretty
```

## Output

### JSON format

```json
{
  "repo_path": "/abs/path/to/repo",
  "languages": {
    "summary": { "Python": 12, "JavaScript": 4 },
    "per_file": { "src/app.py": "Python" }
  },
  "contributors": [
    {
      "commit_count": 142,
      "name": "Alice",
      "email": "alice@example.com",
      "last_commit_ts": 1710000000,
      "recency_score": 1.0
    }
  ],
  "bus_factor_risk": [
    { "file": "src/core/auth.py", "sole_contributor": "bob@example.com" }
  ],
  "dep_graph_metrics": {
    "node_count": 28,
    "edge_count": 41,
    "external_dep_count": 9,
    "internal_file_count": 19,
    "fragile_files": [{ "file": "src/utils.py", "in_degree": 8 }],
    "circular_dependency_groups": [["a.py", "b.py"]],
    "orphaned_files": ["scripts/one_off.py"],
    "avg_in_degree": 1.46,
    "max_in_degree": 8,
    "top_external_deps": [{ "package": "requests", "import_count": 5 }]
  },
  "architectural_risk": {
    "score": 4,
    "reasons": ["1 circular dependency group detected", "High hub concentration: max in-degree 8 in a 19-file repo"]
  }
}
```

### Recency scores

| Score | Meaning |
|-------|---------|
| `1.0` | Last commit within 6 months — active |
| `0.5` | Last commit 6–18 months ago — semi-active |
| `0.0` | Last commit older than 18 months — inactive |

## Project Structure

```
due_diligence/
├── main.py                          # CLI entrypoint
├── requirements.txt
├── repo_ingestion/
│   ├── git_stats.py                 # contributor stats, timeline, bus factor
│   └── file_tree.py                 # file discovery, language detection
├── static_analysis/
│   ├── ast_parser.py                # tree-sitter parsing → imports + calls
│   └── dep_graph.py                 # NetworkX graph construction + metrics
└── tests/
    ├── test_git_stats.py
    ├── test_file_tree.py
    ├── test_ast_parser.py
    └── test_dep_graph.py
```

## Supported Languages

Python, JavaScript, TypeScript, Java, Go, Rust, C, C++, C#, Ruby, PHP, Swift, Kotlin, Scala, Shell, HTML, CSS, JSON, YAML, Markdown.

AST-level import parsing is supported for: Python, JavaScript/TypeScript, Java, Go, Rust.

## Running Tests

```bash
pytest tests/
```

Tests use real minimal git repositories created via `pygit2` — no mocking of git internals.

## Design Constraints

- **No network calls** — fully offline; no API calls of any kind
- **No code execution** — never compiles, runs, or installs the target repo's code
- **No code storage** — does not write source files to disk
- **Graceful degradation** — handles empty repos, binary files, and parse errors without crashing
- **Performance** — completes in under 60 seconds for repos up to 50k LOC
