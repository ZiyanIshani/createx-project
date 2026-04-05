"""
c_semantic.py — C-specific semantic-ish analysis built on tree-sitter.

This module stays consistent with the rest of the static analysis layer:
it never executes code and works on a best-effort basis. When the C
parser is not available, it degrades gracefully and returns empty
results instead of raising.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from .ast_parser import _get_ts_parser, _read_file_bytes, _node_text


@dataclass
class CFunctionInfo:
    name: str
    is_static: bool
    returns_pointer: bool


@dataclass
class CSemanticSummary:
    file_path: str
    functions: List[CFunctionInfo]
    dangerous_calls: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "file_path": self.file_path,
            "functions": [asdict(f) for f in self.functions],
            "dangerous_calls": self.dangerous_calls,
        }


_FUNCTIONS_QUERY = """
(
  function_definition
    storage_class_specifier: (storage_class_specifier)? @storage
    declarator: (function_declarator
      declarator: (identifier) @name
      )
)
"""

_POINTER_RETURN_QUERY = """
(
  function_definition
    type: (pointer_declarator) @ptr_ret
)
"""

_CALLS_QUERY = """
(
  call_expression
    function: (identifier) @name
)
"""

_DANGEROUS_FUNCTIONS = {
    "gets",
    "strcpy",
    "strcat",
    "sprintf",
    "vsprintf",
    "scanf",
    "sscanf",
    "fscanf",
    "vfscanf",
}


def analyze_c_file(file_path: str) -> CSemanticSummary:
    """
    Perform lightweight C-specific semantic analysis on `file_path`.

    Returns a CSemanticSummary capturing:
      - declared functions (name, static / pointer-returning)
      - calls to a small set of historically dangerous libc APIs

    Never raises; on any failure it returns an empty-but-well-formed summary.
    """
    parser, lang = _get_ts_parser("C")
    if parser is None or lang is None:
        return CSemanticSummary(file_path=file_path, functions=[], dangerous_calls=[])

    src = _read_file_bytes(file_path)
    if src is None:
        return CSemanticSummary(file_path=file_path, functions=[], dangerous_calls=[])

    try:
        tree = parser.parse(src)
    except Exception:
        return CSemanticSummary(file_path=file_path, functions=[], dangerous_calls=[])

    functions: List[CFunctionInfo] = []
    dangerous_calls: List[str] = []

    try:
        func_query = lang.query(_FUNCTIONS_QUERY)
        ptr_query = lang.query(_POINTER_RETURN_QUERY)
        call_query = lang.query(_CALLS_QUERY)
    except Exception:
        # If any query fails, degrade gracefully.
        return CSemanticSummary(file_path=file_path, functions=[], dangerous_calls=[])

    # Map function-definition nodes → whether they return a pointer
    ptr_return_nodes = {id(node) for node, _ in ptr_query.captures(tree.root_node)}

    for node, captures_name in func_query.captures(tree.root_node):
        # We are interested in identifiers and optional storage specifiers
        if captures_name not in {"name", "storage"}:
            continue

    # func_query.captures gives us a flat list; we want to group by function_definition
    func_defs = {}
    for node, cname in func_query.captures(tree.root_node):
        parent = node
        while parent is not None and parent.type != "function_definition":
            parent = parent.parent
        if parent is None:
            continue
        bucket = func_defs.setdefault(id(parent), {"node": parent, "name": None, "is_static": False})
        if cname == "name" and bucket["name"] is None:
            bucket["name"] = _node_text(node, src)
        elif cname == "storage":
            text = _node_text(node, src)
            if "static" in text:
                bucket["is_static"] = True

    for info in func_defs.values():
        name = info["name"]
        if not name:
            continue
        node = info["node"]
        returns_pointer = id(node) in ptr_return_nodes
        functions.append(
            CFunctionInfo(
                name=name,
                is_static=info["is_static"],
                returns_pointer=returns_pointer,
            )
        )

    # Collect dangerous calls by simple name match
    for node, cname in call_query.captures(tree.root_node):
        if cname != "name":
            continue
        name = _node_text(node, src)
        if name in _DANGEROUS_FUNCTIONS:
            dangerous_calls.append(name)

    return CSemanticSummary(file_path=file_path, functions=functions, dangerous_calls=sorted(set(dangerous_calls)))

