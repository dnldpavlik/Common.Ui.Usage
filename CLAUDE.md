# CLAUDE.md

## Project Overview

**Common.Ui.Usage** is a Python CLI utility that scans HTML files across multiple Angular/web application repositories to track usage of shared UI component patterns (primarily `<uui-*>` custom elements). It generates timestamped text reports documenting where each component is used, helping monitor adoption of a shared UI component library across projects.

## Repository Structure

```
Common.Ui.Usage/
├── main.py                       # CLI app — data structures, pure functions, I/O, argparse
├── test_main.py                  # Unit tests (unittest, 81 tests)
├── config.json                   # Patterns to search and repositories to scan
├── pyproject.toml                # Project metadata, CLI entry point, tool config (ruff, mypy)
├── Makefile                      # Dev task runner (make check, make test, make lint, etc.)
├── .github/workflows/ci.yml      # GitHub Actions CI (lint, format, typecheck, test)
├── .pre-commit-config.yaml       # Pre-commit hooks (ruff, mypy)
├── .gitignore                    # Ignores Reports/, caches, build artifacts
└── Reports/                      # Generated output (gitignored, created at runtime)
```

## Tech Stack

- **Language:** Python 3.10+ (standard library only — zero runtime dependencies)
- **Stdlib modules:** `argparse`, `collections.abc`, `dataclasses`, `datetime`, `json`, `logging`, `os`, `pathlib`, `re`, `sys`
- **Packaging:** `pyproject.toml` with `[project.scripts]` entry point
- **Testing:** `unittest` (stdlib). Run with `make test` or `python3 -m unittest test_main -v`
- **Linting:** `ruff` (check + format)
- **Type checking:** `mypy --strict`
- **CI/CD:** GitHub Actions — runs lint, format, typecheck, and tests on Python 3.10–3.13
- **Pre-commit:** `pre-commit` hooks for ruff and mypy
- **Task runner:** `Makefile`

## Quick Start

```bash
# Run all quality checks (lint, format, typecheck, test)
make check

# Run just the tests
make test

# Run the scanner
python3 main.py

# Custom config and output directory
python3 main.py --config path/to/config.json --output-dir path/to/output

# Verbose logging
python3 main.py -v

# Install as CLI tool (optional)
pip install .
common-ui-usage --help
```

### CLI Arguments

| Flag | Short | Default | Description |
|---|---|---|---|
| `--config` | `-c` | `config.json` | Path to configuration file |
| `--output-dir` | `-o` | `Reports` | Directory for output reports |
| `--verbose` | `-v` | off | Enable debug-level logging |

The script returns exit code `0` on success, `1` on config errors.

### Makefile Commands

| Command | What it does |
|---|---|
| `make check` | Run all checks: lint, format, typecheck, test |
| `make test` | Run unit tests (`python3 -m unittest test_main -v`) |
| `make lint` | Run ruff linter (`ruff check .`) |
| `make format` | Check formatting (`ruff format --check .`) |
| `make format-fix` | Auto-fix formatting (`ruff format .`) |
| `make typecheck` | Run mypy strict (`mypy --strict main.py`) |

## Dev Tool Setup

Install dev tools (not required for running the scanner):

```bash
pip install ruff mypy pre-commit
pre-commit install
```

Tool configuration lives in `pyproject.toml`:
- **`[tool.ruff]`** — target Python 3.10, 100-char line length, rule sets: pyflakes, pycodestyle, isort, pep8-naming, pyupgrade, flake8-bugbear, flake8-simplify, ruff-specific
- **`[tool.mypy]`** — strict mode, warn on Any returns

## Configuration (`config.json`)

The configuration has two sections:

- **`patterns`**: Array of string patterns to search for (e.g., `"<uui-grid"`, `"<uui-panel"`). These are typically HTML custom element tag names from the shared UI library.
- **`application_repo`**: Array of objects defining which repositories to scan, each with:
  - `source_path`: Absolute path to the source directory to scan recursively
  - `replace_path`: Path prefix to strip from output for readability
  - `report_name`: Base name for the output report file

Config is validated at load time — missing keys or invalid structure produces a clear error message and exit code 1.

Note: The configured paths currently use Windows-style paths (`C:/Projects/...`). These must be updated to match the local development environment.

## Architecture and Key Patterns

### Design Principles

- **SOLID / SRP**: Each function has a single responsibility — pattern building, line scanning, file scanning, directory walking, formatting, and file writing are all separate functions
- **Functional core, imperative shell**: Pure functions (`scan_line`, `format_report`, `build_patterns`) contain all logic; I/O functions (`scan_file`, `write_report`, `find_html_files`) are thin wrappers
- **Immutable data**: All data structures (`MatchResult`, `FileResult`, `RepoConfig`) are frozen dataclasses
- **Type safety**: Full type annotations throughout, enforced by `mypy --strict`
- **Pipeline composition**: `main()` orchestrates a clear pipeline: config → patterns → scan → format → write

### Data Structures

```python
MatchResult(line_num, excerpt, pattern)   # single match within a file
FileResult(file_path, matches)            # all matches in one file
RepoConfig(source_path, replace_path, report_name)  # one repo to scan
```

All are `@dataclass(frozen=True)` — immutable after creation.

### Function Layers

| Layer | Functions | I/O? |
|---|---|---|
| **Pattern building** | `build_pattern()`, `build_patterns()` | No |
| **Line scanning** | `scan_line()` | No |
| **Formatting** | `format_file_result()`, `format_report()` | No |
| **Config** | `validate_config()`, `parse_repo_configs()` | No |
| **File scanning** | `find_html_files()`, `scan_file()`, `scan_directory()` | Yes |
| **Config loading** | `load_config()` | Yes |
| **Report writing** | `write_report()` | Yes |
| **CLI** | `parse_args()`, `main()`, `cli()` | Yes |

### Pattern Matching
- Patterns starting with `<` get a negative lookahead regex (`(?![!?-])`) appended to avoid matching extended tag names (e.g., `<uui-menu` won't match `<uui-menu-item`)
- All patterns are escaped with `re.escape()` and compiled to `re.Pattern` objects
- Patterns are stored as tuples of `(original_string, compiled_regex)`

### Report Generation
- Reports are written to `{output_dir}/{report_name}-{MM-DD-YYYY}.txt`
- Output directories are created automatically (`mkdir -p` equivalent)
- Results are grouped by file, showing line numbers and matched excerpts
- The `replace_path` config value strips absolute path prefixes for cleaner output

### Code Flow
1. Parse CLI arguments (`argparse`)
2. Load and validate `config.json`
3. Build compiled regex patterns from configured pattern strings
4. For each configured application repository:
   - Skip with warning if source directory doesn't exist
   - Walk the directory tree, yielding `.html` files (generator)
   - Scan each file line-by-line against all patterns
   - Format results into report string
   - Write report to dated output file
5. Return exit code 0

## Known Issues

All previously documented bugs have been fixed:

- ~~**f-string syntax:**~~ Fixed — uses single quotes in `strftime('%m-%d-%Y')`
- ~~**`replace_path` scoping:**~~ Fixed — passed as an explicit function parameter
- ~~**`line_num` increment placement:**~~ Fixed — uses `enumerate(f, start=1)`

## Code Conventions

- **Naming:** snake_case for variables and functions, PascalCase for dataclasses (standard Python)
- **Type hints:** Full annotations on all function signatures, enforced by `mypy --strict`
- **Docstrings:** Google-style format on all public functions
- **Data:** Frozen dataclasses for structured data, no raw dicts/tuples in public API
- **Logging:** `logging` module, not `print()`
- **Paths:** `pathlib.Path`, not string concatenation
- **Formatting:** Enforced by `ruff format` (100-char line length)
- **Commit messages:** Use conventional commit prefixes (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`)
- **Git workflow:** Development on feature branches, `master` as main branch
- **Quality gate:** `make check` must pass before committing (enforced by pre-commit hooks)

## Testing

Run the full test suite:

```bash
make test
# or
python3 -m unittest test_main -v
```

### Test Organization (81 tests across 16 classes)

| Class | Tests | What it covers |
|---|---|---|
| `TestBuildPattern` | 6 | Single pattern: regex compilation, lookahead, escaping |
| `TestBuildPatterns` | 3 | Batch building: count, order, empty list |
| `TestScanLine` | 7 | Pure line scanning: matches, excerpts, line numbers |
| `TestFindHtmlFiles` | 5 | File discovery: recursion, filtering, Path objects |
| `TestScanFile` | 7 | Single file scanning: line numbers, matches, empty files |
| `TestScanDirectory` | 5 | Directory scanning: recursion, filtering, HTML-only |
| `TestFormatReport` | 7 | Pure formatting: headers, line numbers, path stripping |
| `TestValidateConfig` | 8 | Config validation: missing keys, wrong types, repo fields |
| `TestParseRepoConfigs` | 3 | Config parsing: types, values |
| `TestParseArgs` | 5 | CLI argument parsing: defaults, flags, long forms |
| `TestWriteReport` | 3 | File writing: content, parent dirs, overwrite |
| `TestPatternMatching` | 5 | Edge cases: extended tags, self-closing, directives |
| `TestConfigLoading` | 5 | Real config.json: structure, patterns, compilation |
| `TestRealisticPage` | 3 | 18-line HTML page: exact line numbers at data/format/pipeline layers |
| `TestMainIntegration` | 5 | End-to-end through `main()`: success, errors, missing dirs |
| `TestDataStructures` | 4 | Frozen dataclass contracts: immutability, equality |

Key regression guards:
- `test_line_numbers_not_inflated_by_pattern_count` — catches the per-pattern increment bug
- `TestRealisticPage` — verifies exact `(line_num, pattern)` tuples on a real HTML page
- `TestMainIntegration` — verifies exit codes and error handling end-to-end

## Development Guidelines

- Keep all configuration in `config.json` rather than hardcoding values in `main.py`
- The `Reports/` directory is gitignored — do not commit generated reports
- When adding new UI component patterns, add them to the `patterns` array in `config.json`
- When adding new application repositories to scan, add entries to the `application_repo` array in `config.json`
- Keep pure functions pure — no I/O, no side effects, no logging
- Keep I/O functions thin — delegate logic to pure functions
- Use frozen dataclasses for any new data structures
- Add type annotations to all new functions
- Run `make check` before committing changes
- When adding new functionality, add corresponding tests at the appropriate layer
