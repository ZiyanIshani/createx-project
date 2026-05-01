"""
static_analysis — AST-based code analysis layer.

Provides import/call extraction, dependency graph construction, architectural
risk scoring, C semantic analysis, and heuristic test coverage estimation.

Public API:
    from static_analysis import (
        parse_imports,              # extract import strings from a file via tree-sitter
        extract_function_calls,     # extract function call names from a file
        parse_file,                 # wrapper: {imports, calls, parse_error}
        resolve_import,             # resolve raw import string → repo path or "external:X"
        build_dep_graph,            # build NetworkX DiGraph of the repo
        compute_metrics,            # structural metrics from a dep graph
        architectural_risk_score,   # 0–10 risk score + reasons
        analyze_c_file,             # C-specific: functions + dangerous calls
        CSemanticSummary,           # dataclass returned by analyze_c_file
        CFunctionInfo,              # per-function metadata dataclass
        is_test_file,               # True if path matches test file naming conventions
        classify_files,             # split file list into test_files / source_files
        compute_test_coverage,      # heuristic coverage metrics
    )
"""
from .ast_parser import parse_imports, extract_function_calls, parse_file
from .dep_graph import resolve_import, build_dep_graph, compute_metrics, architectural_risk_score
from .c_semantic import analyze_c_file, CSemanticSummary, CFunctionInfo
from .test_coverage import is_test_file, classify_files, compute_test_coverage

__all__ = [
    "parse_imports",
    "extract_function_calls",
    "parse_file",
    "resolve_import",
    "build_dep_graph",
    "compute_metrics",
    "architectural_risk_score",
    "analyze_c_file",
    "CSemanticSummary",
    "CFunctionInfo",
    "is_test_file",
    "classify_files",
    "compute_test_coverage",
]
