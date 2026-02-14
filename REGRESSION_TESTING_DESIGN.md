# Regression Testing Pipeline — Design Document

## Purpose

When the shared UI component library (`<uui-*>`) ships a release, teams need to know:

1. **Which pages** use the changed components
2. **How to navigate** to those pages in a running app
3. **Whether those pages still work** after the update

This document describes how to evolve `Common.Ui.Usage` from a usage scanner into a regression testing pipeline that answers all three questions automatically.

---

## Current State

```
config.json patterns → scan HTML files → text report of matches
```

The tool finds where `<uui-*>` tags appear. The output is a flat text file listing file paths and line numbers. There is no connection to application routes, no test generation, and no way to verify pages still render correctly.

---

## Target State

```
UI library release
  → affected component tags populate config
  → scan apps to find which files use those tags
  → route map resolves file paths to app URLs
  → E2E tests are generated for each affected page
  → tests run against a target environment
  → report shows what passed, what broke
```

---

## Phase 1: Upgrade config.json for release-scoped scanning

### Current format

```json
{
  "patterns": ["<uui-grid", "<uui-panel"],
  "application_repo": [...]
}
```

### Proposed format

```json
{
  "release": {
    "version": "2.4.0",
    "affected_components": ["uui-grid", "uui-button", "uui-panel"],
    "date": "2026-02-14"
  },
  "patterns": ["<uui-grid", "<uui-panel", "<uui-button"],
  "application_repo": [
    {
      "source_path": "C:/Projects/AO.MDM/AppLib/AO.Portal.UI/app/src",
      "replace_path": "C:/Projects/AO.MDM/",
      "report_name": "AO.Portal_Usage_Results",
      "base_url": "https://ao-portal-staging.example.com",
      "route_map": [
        {
          "path_pattern": "app/dashboard/**",
          "route": "/dashboard"
        },
        {
          "path_pattern": "app/devices/device-list/**",
          "route": "/devices"
        },
        {
          "path_pattern": "app/settings/**",
          "route": "/settings"
        }
      ]
    }
  ]
}
```

**What changed:**

- `release` block — metadata from the other tool identifying which components changed
- `base_url` per repo — the URL of the running app to test against
- `route_map` per repo — maps file path globs to application routes

The `release.affected_components` list is what your private tool populates. The `patterns` array can be generated from it (prefixing `<` to each tag name), or kept separate if you also want to track non-release patterns.

---

## Phase 2: Route resolution in main.py

After scanning finds matches in a file, resolve that file path to an application route using the `route_map`.

### Logic

```python
import fnmatch

def resolve_route(file_path, route_map):
    """Match a scanned file path against route_map entries.

    Args:
        file_path: The cleaned file path (after replace_path stripping).
        route_map: List of dicts with 'path_pattern' and 'route' keys.

    Returns:
        The matching route string, or None if no match.
    """
    # Normalize separators
    normalized = file_path.replace('\\', '/')
    for entry in route_map:
        if fnmatch.fnmatch(normalized, entry['path_pattern']):
            return entry['route']
    return None
```

### Updated report output

```
=== AO.Portal — Release 2.4.0 Regression Scan (2026-02-14) ===

** AppLib/AO.Portal.UI/app/src/app/dashboard/dashboard.component.html **
   Route: /dashboard
   Line 8:  <uui-grid ...> (Pattern: <uui-grid)
   Line 22: <uui-panel ...> (Pattern: <uui-panel)

** AppLib/AO.Portal.UI/app/src/app/devices/device-list/device-list.component.html **
   Route: /devices
   Line 3:  <uui-grid ...> (Pattern: <uui-grid)
```

Now the report tells you exactly where to navigate.

---

## Phase 3: Generate E2E tests from scan results

After the scan completes and routes are resolved, generate Playwright test files that verify each affected page still renders correctly.

### Why Playwright over Cypress

- Automatic shadow DOM piercing with CSS selectors (important for `<uui-*>` web components)
- Native parallel test execution without paid tiers
- Cross-browser support (Chromium, Firefox, WebKit)
- Environment URL configuration via `baseURL` + env vars
- Python, TypeScript, and JavaScript bindings

### What gets generated

For each affected route, a test file is created that:

1. Navigates to the page
2. Verifies the page loads without HTTP errors
3. Verifies each affected `<uui-*>` component is present and visible
4. Optionally checks shadow DOM internal structure rendered

### Generated test structure

```
generated-tests/
├── playwright.config.ts
└── tests/
    ├── ao-portal/
    │   ├── dashboard.spec.ts
    │   ├── devices.spec.ts
    │   └── settings.spec.ts
    └── ao-uhe/
        ├── home.spec.ts
        └── reports.spec.ts
```

### Example generated test

For a route `/dashboard` that uses `<uui-grid>` and `<uui-panel>`:

```typescript
// generated-tests/tests/ao-portal/dashboard.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Dashboard — Release 2.4.0 Regression', () => {

  test('page loads without errors', async ({ page }) => {
    const response = await page.goto('/dashboard');
    expect(response).not.toBeNull();
    expect(response!.status()).toBeLessThan(400);
  });

  test('<uui-grid> renders correctly', async ({ page }) => {
    await page.goto('/dashboard');
    const element = page.locator('uui-grid');
    await expect(element.first()).toBeAttached();
    await expect(element.first()).toBeVisible();
  });

  test('<uui-panel> renders correctly', async ({ page }) => {
    await page.goto('/dashboard');
    const element = page.locator('uui-panel');
    await expect(element.first()).toBeAttached();
    await expect(element.first()).toBeVisible();
  });
});
```

### Generated Playwright config

```typescript
// generated-tests/playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: [['html'], ['json', { outputFile: 'results.json' }]],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:4200',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
```

### Running against different environments

```bash
# Against staging
BASE_URL=https://ao-portal-staging.example.com npx playwright test

# Against production (smoke test)
BASE_URL=https://ao-portal.example.com npx playwright test

# Against local dev
npx playwright test
```

---

## Phase 4: Test generation logic in main.py

Add a `generate_tests.py` script (or integrate into `main.py`) that reads the scan results and produces the Playwright test files.

### Proposed function

```python
import os
import json

def generate_e2e_tests(scan_results, output_dir="generated-tests/tests"):
    """Generate Playwright test files from scan results.

    Args:
        scan_results: List of dicts, each with:
            - app_name: str
            - route: str
            - components: list of str (tag names found on this route)
            - release_version: str
        output_dir: Where to write the .spec.ts files.
    """
    for result in scan_results:
        app_dir = os.path.join(output_dir, sanitize(result['app_name']))
        os.makedirs(app_dir, exist_ok=True)

        route_name = sanitize(result['route'].strip('/') or 'home')
        filepath = os.path.join(app_dir, f"{route_name}.spec.ts")

        test_blocks = []
        for component in result['components']:
            test_blocks.append(component_test_block(component, result['route']))

        content = test_file_template(
            route=result['route'],
            release=result['release_version'],
            test_blocks='\n\n'.join(test_blocks)
        )

        with open(filepath, 'w') as f:
            f.write(content)
```

### Data flow

```
config.json
  → main.py scans files, resolves routes
  → builds scan_results list in memory
  → passes to generate_e2e_tests()
  → writes .spec.ts files to generated-tests/
  → developer runs: npx playwright test
```

---

## Phase 5: Structured output for integration

Replace or supplement the text report with a JSON output that other tools can consume.

### Proposed JSON output

```json
{
  "release": "2.4.0",
  "scan_date": "2026-02-14",
  "applications": [
    {
      "name": "AO.Portal",
      "base_url": "https://ao-portal-staging.example.com",
      "affected_pages": [
        {
          "file": "app/dashboard/dashboard.component.html",
          "route": "/dashboard",
          "components_found": [
            {
              "tag": "<uui-grid>",
              "lines": [8, 45]
            },
            {
              "tag": "<uui-panel>",
              "lines": [22]
            }
          ]
        }
      ]
    }
  ]
}
```

This JSON can be consumed by:
- The test generator (Phase 4)
- A CI/CD pipeline that decides which tests to run
- A dashboard that tracks regression coverage
- Your private tool that feeds affected components back

---

## Proposed changes to main.py

These are the modifications needed to support the full pipeline. Listed in order of implementation priority.

### 1. Fix the line_num bug (existing issue)

Move `line_num += 1` outside the inner pattern loop so it increments once per line, not once per pattern.

```python
# Before (buggy):
for pattern, modified_pattern in patterns:
    for match in re.finditer(modified_pattern, line):
        ...
    line_num += 1  # increments per pattern

# After (fixed):
for pattern, modified_pattern in patterns:
    for match in re.finditer(modified_pattern, line):
        ...
line_num += 1  # increments per line
```

### 2. Fix the f-string quoting (existing issue)

```python
# Before (breaks on Python < 3.12):
output_file = f"Reports/{report_name}-{today.strftime("%m-%d-%Y")}.txt"

# After:
output_file = f"Reports/{report_name}-{today.strftime('%m-%d-%Y')}.txt"
```

### 3. Pass replace_path as a parameter (existing issue)

```python
# Before: relies on module-level variable
def search_html_files(patterns, directory, output_file):
    ...
    file_full_path = os.path.join(root, filename).replace(replace_path, '')

# After: explicit parameter
def search_html_files(patterns, directory, output_file, replace_path):
    ...
    file_full_path = os.path.join(root, filename).replace(replace_path, '')
```

### 4. Add route resolution

Add `route_map` support to config, resolve routes during scan, include in output.

### 5. Add JSON output

Write a `.json` file alongside the `.txt` report with structured results.

### 6. Add test generation

Add `generate_e2e_tests()` function or separate `generate_tests.py` script.

---

## Route map maintenance strategies

### Option A: Manual route_map in config.json (recommended starting point)

Simplest approach. Each repo entry gets a hand-maintained `route_map` array. Works well when the number of top-level routes is manageable (< 50).

### Option B: Auto-extract from Angular routing modules

Scan `*-routing.module.ts` or `app.routes.ts` files for route definitions:

```typescript
{ path: 'dashboard', component: DashboardComponent }
```

Resolve `DashboardComponent` → `dashboard.component.ts` → `templateUrl: './dashboard.component.html'` → file path. This eliminates manual route_map maintenance but adds parsing complexity.

### Option C: Route map file per application

Keep route maps in separate files (`routes/ao-portal.json`) so application teams can maintain their own mappings independently of this tool's config.

---

## Summary

| Phase | What it does | Effort |
|-------|-------------|--------|
| 1 | Release-scoped config with affected components | Small — config structure change |
| 2 | Route resolution from file paths to app URLs | Small — fnmatch + config addition |
| 3 | Playwright test generation from scan results | Medium — templates + file writing |
| 4 | Test generation logic integrated into main.py | Medium — data flow wiring |
| 5 | Structured JSON output for tool integration | Small — json.dump alongside text |

Phases 1–2 can be done in a single session. Phase 3–4 is the bulk of the work. Phase 5 is a quick addition that unlocks future integrations.
