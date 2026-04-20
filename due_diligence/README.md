# AI-Powered Technical Due Diligence

Automated technical due diligence for M&A transactions targeting the middle market (deals under $100M). Analyzes software repositories and produces risk reports covering contributor continuity, architectural fragility, code provenance, and technical debt — fully offline, optionally powered by a local LLM.

## What It Does

The pipeline runs in up to three stages against any local git repository:

**Step 1 — Repository Ingestion**
- Contributor statistics: commit counts, activity timelines, recency scoring
- Bus factor analysis: identifies files touched by only one contributor
- Language detection across all tracked files

**Step 2 — Static Analysis**
- Tree-sitter AST parsing extracts imports and function calls per file
- Dependency graph construction using NetworkX
- Risk metrics: circular dependencies, fragile hubs, orphaned files, external package exposure
- Architectural risk score (0–10)

**Step 3 — LLM Agentic Analysis** *(optional, requires Ollama)*
- **Authorship risk**: who wrote the critical files and are they still around?
- **Provenance risk**: does any code look copy-pasted from online sources?
- **Code quality**: does the code meet your coding standards?

The LLM stage uses a hand-rolled ReAct agent loop (Reason → Act → Observe) against a locally-running Ollama instance. No cloud APIs, no LLM framework dependencies.

## Installation

```bash
pip install -r requirements.txt
```

**Dependencies:**
- `pygit2>=1.14.0` — git history and blame without subprocess calls
- `networkx>=3.0` — dependency graph construction and analysis
- `tree-sitter>=0.21.0,<0.22.0` — AST parsing
- `tree-sitter-languages>=1.10.0` — pre-built language grammars
- `requests>=2.31.0` — HTTP calls to Ollama (LLM stage only)

## Ollama Setup (for LLM analysis)

```bash
# Install ollama (macOS)
brew install ollama

# Pull the default model
ollama pull mistral

# Start the server (runs on port 11434)
ollama serve

# Verify it's running
curl http://localhost:11434/api/tags
```

## Usage

```bash
python main.py <repo_path> [--ref HEAD] [--output json|pretty] [--llm] [--standards PATH] [--model NAME] [--ollama-url URL]
```

**Arguments:**
- `repo_path` — path to the git repository to analyze
- `--ref` — git ref to analyze (default: `HEAD`)
- `--output` — `json` (default) or `pretty` for a human-readable report
- `--llm` — enable LLM agentic analysis (off by default; requires Ollama running)
- `--standards` — path to a coding standards file (markdown or plain text)
- `--model` — Ollama model name (default: `mistral`)
- `--ollama-url` — Ollama base URL (default: `http://localhost:11434`)

**Examples:**

```bash
# JSON output (pipe-friendly), no LLM
python main.py /path/to/repo

# Human-readable report, no LLM
python main.py /path/to/repo --output pretty

# Full analysis with LLM (default model: mistral)
python main.py /path/to/repo --llm --output pretty

# With a custom coding standards file
python main.py /path/to/repo --llm --standards standards/my_standards.md --output pretty

# With a different model
python main.py /path/to/repo --llm --model codestral --output pretty

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
    "reasons": ["1 circular dependency group detected"]
  },
  "llm_analysis": {
    "model": "mistral",
    "authorship": [
      {
        "file": "src/core/auth.py",
        "contributor_count": 1,
        "risk_level": "critical",
        "risk_summary": "Sole contributor is inactive. Critical knowledge loss risk.",
        "contributors": [
          { "email": "bob@example.com", "recency_score": 0.0, "recency_label": "inactive" }
        ]
      }
    ],
    "provenance": [
      {
        "file": "src/utils.py",
        "provenance_risk": "medium",
        "evidence": ["URL found in comment", "Generic placeholder names found"],
        "suspicious_sections": [{ "start_line": 12, "end_line": 25, "reason": "style shift" }]
      }
    ],
    "quality": [
      {
        "file": "src/utils.py",
        "language": "Python",
        "overall_grade": "C",
        "violation_count": 4,
        "violations": [
          { "line": 18, "severity": "error", "rule": "bare_except", "description": "Bare except clause" }
        ],
        "summary": "Several violations found. Missing docstrings and bare excepts."
      }
    ]
  }
}
```

### Recency scores

| Score | Meaning |
|-------|---------|
| `1.0` | Last commit within 6 months — active |
| `0.5` | Last commit 6–18 months ago — semi-active |
| `0.0` | Last commit older than 18 months — inactive |

### Authorship risk levels

| Level | Meaning |
|-------|---------|
| `low` | Multiple active contributors |
| `medium` | Few contributors or mixed activity |
| `high` | All contributors semi-active or inactive |
| `critical` | Sole contributor is inactive (knowledge loss risk) |

### Quality grades

| Grade | Error count (errors + 0.5 × warnings) |
|-------|---------------------------------------|
| A | 0 |
| B | 1–2 |
| C | 3–5 |
| D | 6–10 |
| F | 11+ |

## Coding Standards

Place custom standards files in the `standards/` directory (markdown or plain text). Pass the path with `--standards`:

```bash
python main.py /path/to/repo --llm --standards standards/my_standards.md --output pretty
```

If no standards file is provided, the agent applies built-in defaults: max 50-line functions, docstring requirements, no bare `except` clauses, no magic numbers, consistent naming conventions.

## Project Structure

```
due_diligence/
├── main.py                          # CLI entrypoint
├── requirements.txt
├── standards/                       # user coding standards files go here
├── repo_ingestion/
│   ├── git_stats.py                 # contributor stats, timeline, bus factor
│   └── file_tree.py                 # file discovery, language detection
├── static_analysis/
│   ├── ast_parser.py                # tree-sitter parsing → imports + calls
│   └── dep_graph.py                 # NetworkX graph construction + metrics
├── llm/
│   ├── client.py                    # OllamaClient — raw HTTP wrapper (no openai SDK)
│   ├── prompts.py                   # all prompt templates as string constants
│   └── agents/
│       ├── __init__.py              # AgentLoopMixin — shared ReAct loop
│       ├── authorship.py            # AuthorshipAgent
│       ├── provenance.py            # ProvenanceAgent
│       └── quality.py              # QualityAgent
└── tests/
    ├── test_git_stats.py
    ├── test_file_tree.py
    ├── test_ast_parser.py
    ├── test_dep_graph.py
    ├── test_authorship.py
    ├── test_provenance.py
    └── test_quality.py
```

## Supported Languages

Python, JavaScript, TypeScript, Java, Go, Rust, C, C++, C#, Ruby, PHP, Swift, Kotlin, Scala, Shell, HTML, CSS, JSON, YAML, Markdown.

AST-level import parsing is supported for: Python, JavaScript/TypeScript, Java, Go, Rust.

## Running Tests

```bash
pytest tests/
```

Tests use real minimal git repositories created via `pygit2` — no mocking of git internals. LLM agent tests mock the Ollama client and run entirely offline.

## Design Constraints

- **No network calls** — fully offline by default; Ollama runs locally
- **No code execution** — never compiles, runs, or installs the target repo's code
- **No code storage** — file content read for LLM analysis is never written to disk
- **Graceful degradation** — handles empty repos, binary files, and parse errors without crashing; unavailable Ollama produces a partial result with a warning rather than a crash
- **Performance** — Steps 1 + 2 complete in under 60 seconds for repos up to 50k LOC
- **LLM is opt-in** — `--llm` flag required; without it the pipeline runs exactly as before
