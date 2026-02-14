# CLAUDE.md

## Project Overview

**Common.Ui.Usage** is a Python utility that scans HTML files across multiple Angular/web application repositories to track usage of shared UI component patterns (primarily `<uui-*>` custom elements). It generates timestamped text reports documenting where each component is used, helping monitor adoption of a shared UI component library across projects.

## Repository Structure

```
Common.Ui.Usage/
├── main.py          # Primary script - all scanning and report logic
├── config.json      # Patterns to search and repositories to scan
├── .gitignore       # Ignores /Reports output directory
└── Reports/         # Generated output (gitignored, created at runtime)
```

This is a single-script project with no subdirectories in source control.

## Tech Stack

- **Language:** Python 3 (standard library only)
- **Dependencies:** None external. Uses only `os`, `re`, `json`, `datetime`
- **Package manager:** None (no requirements.txt, setup.py, or pyproject.toml)
- **Build system:** None
- **Testing:** None configured
- **Linting:** None configured
- **CI/CD:** None configured

## How to Run

```bash
python3 main.py
```

The script reads `config.json` from the current working directory and outputs reports to the `Reports/` directory (created automatically if it doesn't exist).

## Configuration (`config.json`)

The configuration has two sections:

- **`patterns`**: Array of string patterns to search for (e.g., `"<uui-grid"`, `"<uui-panel"`). These are typically HTML custom element tag names from the shared UI library.
- **`application_repo`**: Array of objects defining which repositories to scan, each with:
  - `source_path`: Absolute path to the source directory to scan recursively
  - `replace_path`: Path prefix to strip from output for readability
  - `report_name`: Base name for the output report file

Note: The configured paths currently use Windows-style paths (`C:/Projects/...`). These must be updated to match the local development environment.

## Architecture and Key Patterns

### Pattern Matching
- Patterns starting with `<` get a negative lookahead regex (`(?![!?-])`) appended to avoid matching inside closing tags or similar markup
- All patterns are escaped with `re.escape()` before compilation
- Patterns are stored as tuples of `(original_pattern, compiled_regex_pattern)`

### Report Generation
- Reports are written to `Reports/{report_name}-{MM-DD-YYYY}.txt`
- Results are grouped by file, showing line numbers and matched excerpts
- The `replace_path` config value strips absolute path prefixes for cleaner output

### Code Flow
1. Load `config.json`
2. Build regex patterns from configured pattern strings
3. For each configured application repository:
   - Walk the directory tree recursively
   - Read each `.html` file line-by-line
   - Match all patterns against each line
   - Write matches to a dated report file

## Known Issues

- **Line 59 f-string syntax:** The nested double quotes in `today.strftime("%m-%d-%Y")` inside the f-string may cause a `SyntaxError` on Python versions before 3.12 (which added support for nested quotes in f-strings). For broader compatibility, use single quotes: `today.strftime('%m-%d-%Y')`.
- **`replace_path` scoping:** The `replace_path` variable used inside `search_html_files()` (line 37) relies on a module-level variable set in the `__main__` block rather than being passed as a function parameter.
- **`line_num` increment placement:** The `line_num += 1` on line 32 is inside the inner pattern loop, causing it to increment once per pattern rather than once per line.

## Code Conventions

- **Naming:** snake_case for variables and functions (standard Python)
- **Docstrings:** Google-style format on the main function
- **Commit messages:** Use conventional commit prefixes (`chore:`, `config:`) for maintenance changes
- **Git workflow:** Development on feature branches, `master` as main branch

## Development Guidelines

- Keep all configuration in `config.json` rather than hardcoding values in `main.py`
- The `Reports/` directory is gitignored - do not commit generated reports
- When adding new UI component patterns, add them to the `patterns` array in `config.json`
- When adding new application repositories to scan, add entries to the `application_repo` array in `config.json`
