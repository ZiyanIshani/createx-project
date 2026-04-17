"""
ast_parser.py — tree-sitter based import/call extraction.

Uses tree-sitter-languages for pre-built parsers; gracefully degrades on
unsupported languages or parse errors.
"""

from __future__ import annotations

import re
from typing import Dict, List

# tree-sitter-languages bundles parsers; import may fail if not installed.
try:
    from tree_sitter_languages import get_language, get_parser as _get_parser  # type: ignore

    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Language name → tree-sitter language identifier
# ---------------------------------------------------------------------------

_LANG_MAP: Dict[str, str] = {
    "Python": "python",
    "JavaScript": "javascript",
    "TypeScript": "typescript",
    "Java": "java",
    "Go": "go",
    "Rust": "rust",
    "C": "c",
}


def _get_ts_parser(language: str):
    """Return a tree-sitter Parser for the given language name, or None."""
    if not _TS_AVAILABLE:
        return None, None
    ts_name = _LANG_MAP.get(language)
    if ts_name is None:
        return None, None
    try:
        lang = get_language(ts_name)
        parser = _get_parser(ts_name)
        return parser, lang
    except Exception:
        return None, None


def _read_file_bytes(file_path: str) -> bytes | None:
    try:
        with open(file_path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Query strings per language
# ---------------------------------------------------------------------------

_IMPORT_QUERIES: Dict[str, str] = {
    "python": """
        (import_statement
            name: (dotted_name) @module)
        (import_statement
            name: (aliased_import
                name: (dotted_name) @module))
        (import_from_statement
            module_name: (dotted_name) @module)
        (import_from_statement
            module_name: (relative_import) @module)
    """,
    "javascript": """
        (import_statement
            source: (string) @source)
        (call_expression
            function: (identifier) @callee
            arguments: (arguments (string) @source)
            (#eq? @callee "require"))
    """,
    "typescript": """
        (import_statement
            source: (string) @source)
        (call_expression
            function: (identifier) @callee
            arguments: (arguments (string) @source)
            (#eq? @callee "require"))
    """,
    "java": """
        (import_declaration
            (scoped_identifier) @module)
    """,
    "go": """
        (import_spec
            path: (interpreted_string_literal) @path)
    """,
    "rust": """
        (use_declaration
            argument: (_) @path)
    """,
    "c": """
        (preproc_include
            path: (_) @path)
    """,
}

_CALL_QUERIES: Dict[str, str] = {
    "python": """
        (call
            function: [
                (identifier) @name
                (attribute
                    object: (_) @obj
                    attribute: (identifier) @attr)
            ])
    """,
    "javascript": """
        (call_expression
            function: [
                (identifier) @name
                (member_expression
                    object: (_) @obj
                    property: (property_identifier) @attr)
            ])
    """,
    "typescript": """
        (call_expression
            function: [
                (identifier) @name
                (member_expression
                    object: (_) @obj
                    property: (property_identifier) @attr)
            ])
    """,
    "java": """
        (method_invocation
            name: (identifier) @name)
    """,
    "go": """
        (call_expression
            function: [
                (identifier) @name
                (selector_expression
                    operand: (_) @obj
                    field: (field_identifier) @attr)
            ])
    """,
    "rust": """
        (call_expression
            function: [
                (identifier) @name
                (field_expression
                    value: (_) @obj
                    field: (field_identifier) @attr)
            ])
    """,
    "c": """
        (call_expression
            function: (identifier) @name)
    """,
}


def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes from a tree-sitter string node text."""
    return s.strip("\"'`")


def _node_text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_imports(file_path: str, language: str) -> List[str]:
    """
    Parse `file_path` and return a list of raw import/module strings.
    Returns [] on any error or unsupported language.
    """
    parser, lang = _get_ts_parser(language)
    if parser is None:
        return []

    src = _read_file_bytes(file_path)
    if src is None:
        return []

    try:
        tree = parser.parse(src)
    except Exception:
        return []

    ts_name = _LANG_MAP.get(language, "")
    query_str = _IMPORT_QUERIES.get(ts_name)
    if not query_str:
        return []

    imports: List[str] = []

    try:
        query = lang.query(query_str)
        captures = query.captures(tree.root_node)

        # For JS/TS require() calls we get both @callee and @source captures per call;
        # we only want @source when @callee == "require".
        # Build a map: node → capture_name to handle this.
        capture_map: Dict[int, List[str]] = {}
        for node, capture_name in captures:
            capture_map.setdefault(id(node), []).append((node, capture_name))

        # Simpler: iterate captures linearly
        i = 0
        capture_list = list(captures)
        while i < len(capture_list):
            node, cname = capture_list[i]
            text = _node_text(node, src)

            if cname in ("module", "path"):
                # Python dotted_name / relative_import, Java scoped_identifier, Rust/Go/C path
                if ts_name == "c":
                    # For C includes we may see <stdio.h> or "foo.h"
                    clean = text.strip("\"'`<>").replace(" ", "")
                else:
                    clean = _strip_quotes(text).replace(" ", "")
                if clean:
                    imports.append(clean)

            elif cname == "source":
                # JS/TS import declaration source string
                clean = _strip_quotes(text)
                if clean:
                    imports.append(clean)

            elif cname == "callee":
                # JS/TS require() — next capture should be @source
                if text == "require" and i + 1 < len(capture_list):
                    next_node, next_cname = capture_list[i + 1]
                    if next_cname == "source":
                        clean = _strip_quotes(_node_text(next_node, src))
                        if clean:
                            imports.append(clean)
                        i += 1  # skip the source capture we just consumed

            i += 1

    except Exception:
        pass

    return imports


def extract_function_calls(file_path: str, language: str) -> List[str]:
    """
    Best-effort extraction of function call names from `file_path`.
    Returns [] on any error or unsupported language.
    """
    parser, lang = _get_ts_parser(language)
    if parser is None:
        return []

    src = _read_file_bytes(file_path)
    if src is None:
        return []

    try:
        tree = parser.parse(src)
    except Exception:
        return []

    ts_name = _LANG_MAP.get(language, "")
    query_str = _CALL_QUERIES.get(ts_name)
    if not query_str:
        return []

    calls: List[str] = []

    try:
        query = lang.query(query_str)
        captures = query.captures(tree.root_node)

        capture_list = list(captures)
        i = 0
        while i < len(capture_list):
            node, cname = capture_list[i]
            text = _node_text(node, src)

            if cname == "name":
                calls.append(text)
            elif cname == "obj":
                # peek ahead for @attr
                if i + 1 < len(capture_list):
                    next_node, next_cname = capture_list[i + 1]
                    if next_cname == "attr":
                        attr_text = _node_text(next_node, src)
                        calls.append(f"{text}.{attr_text}")
                        i += 1

            i += 1

    except Exception:
        pass

    return calls


def parse_file(file_path: str, language: str) -> Dict[str, object]:
    """
    Wrapper around parse_imports + extract_function_calls.
    Returns {"imports": [...], "calls": [...], "parse_error": bool}.
    Never raises.
    """
    try:
        imports = parse_imports(file_path, language)
        calls = extract_function_calls(file_path, language)
        return {"imports": imports, "calls": calls, "parse_error": False}
    except Exception:
        return {"imports": [], "calls": [], "parse_error": True}
