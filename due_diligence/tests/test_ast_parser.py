"""Tests for static_analysis/ast_parser.py using tmp file snippets."""

from __future__ import annotations

import pytest

from static_analysis.ast_parser import extract_function_calls, parse_file, parse_imports


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path, filename: str, content: str):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# parse_imports — Python
# ---------------------------------------------------------------------------

class TestParseImportsPython:
    def test_simple_import(self, tmp_path):
        path = _write(tmp_path, "a.py", "import os\nimport sys\n")
        result = parse_imports(path, "Python")
        assert "os" in result
        assert "sys" in result

    def test_from_import(self, tmp_path):
        path = _write(tmp_path, "b.py", "from collections import defaultdict\n")
        result = parse_imports(path, "Python")
        assert "collections" in result

    def test_relative_import(self, tmp_path):
        path = _write(tmp_path, "c.py", "from . import utils\nfrom ..helpers import foo\n")
        result = parse_imports(path, "Python")
        assert len(result) >= 1  # at least one relative import captured

    def test_no_imports(self, tmp_path):
        path = _write(tmp_path, "d.py", "x = 1 + 2\n")
        result = parse_imports(path, "Python")
        assert result == []

    def test_unsupported_language_returns_empty(self, tmp_path):
        path = _write(tmp_path, "e.rb", 'require "json"\n')
        result = parse_imports(path, "Ruby")
        assert result == []


# ---------------------------------------------------------------------------
# parse_imports — JavaScript (require)
# ---------------------------------------------------------------------------

class TestParseImportsJS:
    def test_require_call(self, tmp_path):
        path = _write(tmp_path, "app.js", "const fs = require('fs');\nconst _ = require('lodash');\n")
        result = parse_imports(path, "JavaScript")
        assert "fs" in result
        assert "lodash" in result

    def test_esm_import(self, tmp_path):
        path = _write(tmp_path, "mod.js", "import React from 'react';\nimport { useState } from 'react';\n")
        result = parse_imports(path, "JavaScript")
        assert "react" in result


# ---------------------------------------------------------------------------
# extract_function_calls
# ---------------------------------------------------------------------------

class TestExtractFunctionCalls:
    def test_simple_calls(self, tmp_path):
        path = _write(tmp_path, "f.py", "print('hello')\nlen([1, 2, 3])\n")
        result = extract_function_calls(path, "Python")
        assert "print" in result
        assert "len" in result

    def test_method_calls(self, tmp_path):
        path = _write(tmp_path, "g.py", "x = requests.get('http://example.com')\n")
        result = extract_function_calls(path, "Python")
        assert any("requests" in c for c in result)

    def test_unsupported_language(self, tmp_path):
        path = _write(tmp_path, "h.rb", "puts 'hello'\n")
        result = extract_function_calls(path, "Ruby")
        assert result == []


# ---------------------------------------------------------------------------
# parse_file — wrapper + error handling
# ---------------------------------------------------------------------------

class TestParseFile:
    def test_normal_python(self, tmp_path):
        path = _write(tmp_path, "i.py", "import os\nprint('hi')\n")
        result = parse_file(path, "Python")
        assert "imports" in result
        assert "calls" in result
        assert result["parse_error"] is False
        assert "os" in result["imports"]

    def test_binary_file_no_crash(self, tmp_path):
        p = tmp_path / "binary.py"
        p.write_bytes(bytes(range(256)))
        result = parse_file(str(p), "Python")
        # Must not raise; parse_error may be True or False
        assert "imports" in result
        assert "calls" in result
        assert isinstance(result["parse_error"], bool)

    def test_missing_file_no_crash(self, tmp_path):
        result = parse_file(str(tmp_path / "nonexistent.py"), "Python")
        assert result["parse_error"] is False  # missing file → empty lists, no exception
        assert result["imports"] == []
        assert result["calls"] == []

    def test_unsupported_language_no_crash(self, tmp_path):
        path = _write(tmp_path, "j.rb", "require 'json'\n")
        result = parse_file(path, "Ruby")
        assert result["parse_error"] is False
        assert result["imports"] == []

    def test_garbled_source_no_crash(self, tmp_path):
        path = _write(tmp_path, "k.py", "def ((((\n\nbroken\n")
        result = parse_file(path, "Python")
        # tree-sitter is error-tolerant; must not raise regardless
        assert "imports" in result
        assert isinstance(result["parse_error"], bool)
