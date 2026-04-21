# Coding Standards — Technical Due Diligence Reference

This document defines the coding standards used to evaluate software repositories
during technical due diligence. The quality agent must evaluate submitted code
against each rule below and cite specific line numbers for violations.

---

## 1. Function and Method Length

- **RULE Q001**: No function or method body may exceed 50 lines of code (excluding
  blank lines and comments).
- **RULE Q002**: Functions exceeding 30 lines should be flagged as a warning and
  reviewed for decomposition opportunities.
- Rationale: Long functions indicate low cohesion and are harder to test, review,
  and maintain post-acquisition.

## 2. Naming Conventions

- **RULE Q003**: Variables and function names must use `snake_case` in Python,
  `camelCase` in JavaScript/TypeScript, and follow the language's idiomatic
  convention in all other languages.
- **RULE Q004**: No single-letter variable names outside of loop counters (`i`, `j`, `k`)
  or well-established mathematical conventions (`x`, `y` in geometry code).
- **RULE Q005**: No generic placeholder names: `foo`, `bar`, `baz`, `temp`, `tmp`,
  `data2`, `result2`, `thing`, `stuff`, `obj2`. These indicate rushed or throwaway code.
- **RULE Q006**: Class names must use `PascalCase` in all languages.
- **RULE Q007**: Constants must be `UPPER_SNAKE_CASE`.

## 3. Documentation and Comments

- **RULE Q008**: Every public function, method, and class must have a docstring or
  equivalent documentation comment. Missing docstrings on public interfaces are errors.
- **RULE Q009**: Every module/file must have a top-level docstring explaining its
  purpose, inputs, and outputs at a high level.
- **RULE Q010**: Inline comments must explain *why*, not *what*. Comments that simply
  restate the code (e.g. `# increment i` above `i += 1`) are a warning.
- **RULE Q011**: TODO and FIXME comments must include an owner and date:
  `# TODO(ziyan, 2024-03): refactor this`. Bare `# TODO` or `# FIXME` are warnings.

## 4. Error Handling

- **RULE Q012**: No bare `except:` or `except Exception:` clauses without a
  logged message or re-raise. Silent exception swallowing is an error.
- **RULE Q013**: Caught exceptions must either be logged, re-raised, or converted
  to a domain-specific exception. Empty `except` blocks are errors.
- **RULE Q014**: Functions that can fail must either raise exceptions or return
  typed result objects. Returning `None` to signal failure without documentation
  is a warning.
- **RULE Q015**: External I/O operations (file reads, network calls, DB queries)
  must be wrapped in error handling. Unguarded I/O is an error.

## 5. Magic Numbers and Hardcoded Values

- **RULE Q016**: No magic numbers in logic. Numeric literals other than `0` and `1`
  must be assigned to a named constant before use.
  - Bad:  `if retries > 3:`
  - Good: `MAX_RETRIES = 3` ... `if retries > MAX_RETRIES:`
- **RULE Q017**: No hardcoded credentials, API keys, tokens, passwords, or secrets
  anywhere in source code. This is a critical error and a deal-blocker.
- **RULE Q018**: No hardcoded absolute file paths (e.g. `/Users/ziyan/data/file.csv`).
  Paths must be constructed relative to a config value or environment variable.

## 6. Code Duplication

- **RULE Q019**: Identical or near-identical code blocks appearing more than twice
  must be extracted into a shared function. Copy-paste duplication is a warning.
- **RULE Q020**: Import statements must not be duplicated within the same file.

## 7. Complexity

- **RULE Q021**: Cyclomatic complexity per function should not exceed 10 branches
  (if/elif/else/for/while/try/except each count as one branch). Flag as warning
  above 7, error above 10.
- **RULE Q022**: Nesting depth must not exceed 4 levels. Deeply nested code
  (4+ levels of indentation) is a warning; 5+ levels is an error.
- **RULE Q023**: No functions with more than 5 parameters. Use a config object or
  dataclass instead. Flag as warning at 5, error at 7+.

## 8. Imports and Dependencies

- **RULE Q024**: No wildcard imports (`from module import *`). These pollute the
  namespace and make dependency analysis unreliable.
- **RULE Q025**: Imports must be grouped and ordered: standard library first,
  third-party second, local imports third, with a blank line between each group.
- **RULE Q026**: Unused imports must be removed. Unused imports are warnings.

## 9. Testing Indicators

- **RULE Q027**: Every module should have a corresponding test file. Missing test
  coverage for a module is a warning.
- **RULE Q028**: Test functions must have descriptive names that explain what is
  being tested: `test_parse_imports_returns_empty_on_binary_file` not `test_1`.
- **RULE Q029**: No `print()` statements in non-test, non-CLI source files.
  Use a logger instead. Print statements in library code are warnings.

## 10. Security

- **RULE Q030**: No use of `eval()`, `exec()`, or `pickle.loads()` on untrusted
  input. These are critical errors.
- **RULE Q031**: No use of `subprocess` with `shell=True` on user-controlled input.
  Shell injection risk is a critical error.
- **RULE Q032**: No MD5 or SHA1 for cryptographic purposes (hashing passwords,
  signing tokens). Use SHA256 or better. This is an error.
- **RULE Q033**: SQL queries must use parameterized statements. String-formatted
  SQL queries are critical errors (SQL injection risk).

---

## Severity Definitions

| Severity | Meaning |
|----------|---------|
| `critical` | Deal-blocker. Must be resolved before close. Examples: hardcoded secrets, SQL injection, eval on untrusted input. |
| `error` | Significant technical debt. Increases integration cost and maintenance burden. |
| `warning` | Minor debt or style issue. Should be tracked but does not block the deal. |
| `info` | Observation only. No remediation required. |

---

## Grading Scale

The overall file grade is computed from weighted violation counts:
- Critical violations count as 5 errors
- Errors count as 1
- Warnings count as 0.5
- Info count as 0

| Grade | Weighted Score |
|-------|---------------|
| A | 0 |
| B | 1–2 |
| C | 3–5 |
| D | 6–10 |
| F | 11+ |
