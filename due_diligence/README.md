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

**Step 3 — Subscription Service Detection** *(always runs, no LLM needed)*
- Heuristic scan of every tracked file for references to external SaaS APIs, cloud platforms, payment processors, and data services
- Three signal types: import/package names, URL patterns, and string/comment usage patterns
- Produces a deduplicated summary of services found, grouped by category (Cloud, Payments, Monitoring, etc.) with reference counts per file

**Step 4 — LLM Agentic Analysis** *(optional, requires Groq API key)*
- **Authorship risk**: who wrote the critical files and are they still around?
- **Provenance risk**: does any code look copy-pasted from online sources?
- **Code quality**: does the code meet your coding standards?

The LLM stage uses a hand-rolled ReAct agent loop (Reason → Act → Observe) against the Groq API.

## Installation

```bash
pip install -r requirements.txt
```

**Dependencies:**
- `pygit2>=1.14.0` — git history and blame without subprocess calls
- `networkx>=3.0` — dependency graph construction and analysis
- `tree-sitter>=0.21.0,<0.22.0` — AST parsing
- `tree-sitter-languages>=1.10.0` — pre-built language grammars
- `requests>=2.31.0` — HTTP calls to Groq API (LLM stage only)

## LLM Backend

This tool uses the Groq API for LLM analysis. Groq offers a free tier with
generous limits (30 RPM, 14,400 RPD).

Set your API key:
    export GROQ_API_KEY="your-key-here"

Get a free key at: https://console.groq.com/keys

Recommended models (pass via --model flag):
- llama-3.1-70b-versatile  (default, best quality)
- llama-3.1-8b-instant     (faster, lower quality)
- mixtral-8x7b-32768       (good for long files, 32k context)

## Usage

```bash
python main.py <repo_path> [--ref HEAD] [--output json|pretty] [--llm] [--standards PATH] [--model NAME]
```

**Arguments:**
- `repo_path` — path to the git repository to analyze
- `--ref` — git ref to analyze (default: `HEAD`)
- `--output` — `json` (default) or `pretty` for a human-readable report
- `--llm` — enable LLM agentic analysis (off by default; requires Groq API key)
- `--standards` — path to a coding standards file (markdown or plain text)
- `--model` — Groq model name (default: `llama-3.1-8b-instant`)
- `--top-n` — number of critical files to run LLM analysis on (default: `3`)

**Examples:**

```bash
# JSON output (pipe-friendly), no LLM
python main.py /path/to/repo

# Human-readable report, no LLM
python main.py /path/to/repo --output pretty

# Full analysis with LLM (default model: llama-3.1-8b-instant)
python main.py /path/to/repo --llm --output pretty

# With a custom coding standards file
python main.py /path/to/repo --llm --standards standards/my_standards.md --output pretty

# With a different model
python main.py /path/to/repo --llm --model mixtral-8x7b-32768 --output pretty

# Analyze top 5 files instead of the default 3
python main.py /path/to/repo --llm --top-n 5 --output pretty

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
  "commit_velocity": {
    "months": ["2023-01", "2023-02"],
    "commits_per_month": [12, 8],
    "lines_added_per_month": [400, 220],
    "lines_removed_per_month": [80, 60],
    "total_commits": 223,
    "first_commit_date": "2022-03-01",
    "last_commit_date": "2024-03-15"
  },
  "test_coverage": {
    "test_file_count": 9,
    "source_file_count": 18,
    "test_to_source_ratio": 0.5,
    "coverage_percent": 72.2,
    "coverage_estimated": false,
    "tested_files": ["src/utils.py"],
    "untested_files": ["src/legacy.py"]
  },
  "debt_scores": {
    "total": 47,
    "bus_score": 60,
    "test_score": 28,
    "churn_score": 45,
    "hub_score": 30,
    "doc_score": 80,
    "remediation_estimate": "2-4 months",
    "top_contributor_name": "Alice",
    "top_contributor_share": 64.5,
    "bf_file_count": 5,
    "coverage_pct": 72.2,
    "hot_file_count": 3,
    "hot_file_ratio_pct": 15.8,
    "median_commits": 4.0,
    "doc_density_pct": 8.2,
    "max_in_degree": 8,
    "total_files": 19
  },
  "subscription_services": {
    "service_count": 3,
    "services": [
      {
        "service": "stripe",
        "category": "Payments",
        "tier": "pay-as-you-go",
        "reference_count": 2,
        "files": ["src/billing.py", "src/checkout.py"],
        "first_seen": {
          "file": "src/billing.py",
          "line": 1,
          "signal_type": "import",
          "matched_text": "import stripe"
        }
      }
    ],
    "by_category": {
      "Cloud": ["aws"],
      "Payments": ["stripe"],
      "Monitoring": ["datadog"]
    }
  },
  "contributor_file_graph": "/abs/path/to/repo/images/contributor_file_graph.png",
  "llm_analysis": {
    "model": "llama-3.1-8b-instant",
    "debt_narrative": "Technical debt is moderate, driven primarily by...",
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

## Technical Debt Scoring

A composite debt score (0–100) is computed on every run and included in `debt_scores`. Higher = more debt.

| Component | Weight | Signal |
|-----------|--------|--------|
| Knowledge concentration | 30% | Bus factor + top-contributor commit share |
| Test coverage gaps | 25% | `100 − coverage_percent` |
| Code churn | 25% | Fraction of source files touched >2× the median commit count |
| Hub fragility | 15% | Max in-degree relative to codebase size |
| Documentation density | 5% | Comment/docstring line ratio vs 15% target |

`remediation_estimate` is a deterministic time range (e.g. `"2-4 months"`) computed from the score and the codebase size, assuming 2 engineers dedicate 20% of sprint capacity to debt reduction.

When `--llm` is enabled, `llm_analysis.debt_narrative` adds a plain-English paragraph explaining the primary drivers.

## Coding Standards

Place custom standards files in the `standards/` directory (markdown or plain text). Pass the path with `--standards`:

```bash
python main.py /path/to/repo --llm --standards standards/my_standards.md --output pretty
```

If no standards file is provided, the agent applies built-in defaults: max 50-line functions, docstring requirements, no bare `except` clauses, no magic numbers, consistent naming conventions.

## Project Structure

```
due_diligence/
├── main.py                          # CLI entrypoint — orchestrates all pipeline stages
├── server.py                        # Flask web dashboard server
├── llm_summaries.py                 # Experimental: local LLM summary generation (Ollama)
├── requirements.txt
├── standards/                       # User coding standards files go here
│   └── code_standards.md            # Example standards document
├── repo_ingestion/
│   ├── __init__.py                  # Package re-exports
│   ├── git_stats.py                 # Contributor stats, timeline, bus factor (pygit2)
│   └── file_tree.py                 # File discovery, language detection
├── static_analysis/
│   ├── __init__.py                  # Package re-exports
│   ├── ast_parser.py                # Tree-sitter parsing → imports + calls
│   ├── dep_graph.py                 # NetworkX graph construction + risk metrics
│   ├── graph_viz.py                 # Matplotlib contributor ↔ file graph PNG
│   ├── test_coverage.py             # Heuristic test coverage estimation
│   └── c_semantic.py                # C-specific: function list + dangerous call detection
├── llm/
│   ├── __init__.py
│   ├── client.py                    # GroqClient — raw HTTP wrapper, retry on 429
│   ├── prompts.py                   # All prompt templates as string constants
│   └── agents/
│       ├── __init__.py              # AgentLoopMixin — shared ReAct loop
│       ├── authorship.py            # AuthorshipAgent — contributor risk assessment
│       ├── provenance.py            # ProvenanceAgent — copy-paste detection
│       ├── quality.py               # QualityAgent — standards-based code grading
│       └── subscriptions.py         # SubscriptionDetector — heuristic SaaS scanner
├── templates/
│   ├── index.html                   # Landing page (Tailwind CSS dark theme)
│   └── dashboard.html               # Report dashboard (Tailwind + Chart.js + Cytoscape)
└── tests/
    ├── test_git_stats.py            # Contributor stats tests (real pygit2 repos)
    ├── test_file_tree.py            # File discovery and language detection tests
    ├── test_ast_parser.py           # Import/call extraction tests
    ├── test_dep_graph.py            # Dependency graph and metrics tests
    ├── test_authorship.py           # AuthorshipAgent tests (mocked Groq client)
    ├── test_provenance.py           # ProvenanceAgent tests
    ├── test_quality.py              # QualityAgent and grading tests
    ├── test_agent_loop.py           # AgentLoopMixin JSON extraction unit tests
    └── test_subscriptions.py        # SubscriptionDetector unit tests
```

## Supported Languages

Python, JavaScript, TypeScript, Java, Go, Rust, C, C++, C#, Ruby, PHP, Swift, Kotlin, Scala, Shell, HTML, CSS, JSON, YAML, Markdown.

AST-level import parsing is supported for: Python, JavaScript/TypeScript, Java, Go, Rust.

## Running Tests

```bash
pytest tests/
```

Tests use real minimal git repositories created via `pygit2` — no mocking of git internals. LLM agent tests mock the Groq client and run entirely offline.

## Design Constraints

- **Minimal network calls** — only the Groq API when `--llm` is used; everything else is fully offline
- **No code execution** — never compiles, runs, or installs the target repo's code
- **No code storage** — file content read for LLM analysis is never written to disk
- **Graceful degradation** — handles empty repos, binary files, and parse errors without crashing; unavailable Groq API produces a partial result with a warning rather than a crash
- **Performance** — all offline stages (Steps 1–4) complete in under 60 seconds for repos up to 50k LOC
- **LLM is opt-in** — `--llm` flag required; without it the full offline pipeline still runs and produces complete results
- **Subscription scan always runs** — heuristic only, no API key needed; results appear in all output modes
- **Debt scoring always runs** — deterministic computation, no LLM needed; narrative paragraph requires `--llm`
