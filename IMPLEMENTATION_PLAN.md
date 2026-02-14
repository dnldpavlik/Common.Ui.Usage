# Implementation Plan — Automated Regression Testing and Remediation Pipeline

## Vision

A single tool that a stretched-thin team can point at a UI library release and get back:

1. Which pages across all apps are affected
2. Automated tests that verify those pages still work
3. A clear diagnosis when something breaks
4. A PR with the fix, ready to review

The key enabler is **component behavior definitions** — machine-readable contracts that describe what each component does, how it renders, and what correct usage looks like. Everything else is built on top of those.

---

## Phase 0: Fix existing bugs in main.py

**Goal:** Stable foundation before adding anything.

**Changes:**

1. Fix `line_num` increment — move outside the inner pattern loop (line 32)
2. Fix f-string quoting — use single quotes in `strftime('%m-%d-%Y')` (line 59)
3. Pass `replace_path` as a function parameter instead of relying on module scope (line 37)

**Effort:** ~30 minutes. No config changes needed.

---

## Phase 1: Component Behavior Definitions

**Goal:** Create a structured way to describe what each `<uui-*>` component does so that tests can be generated from it.

### 1.1 The behavior definition schema

Each component in the UI library gets a JSON file that acts as its contract. These files live in the library repo alongside the component source.

**Directory structure in the library repo:**

```
AO.Common.UI.Ng/
└── projects/
    └── ui-library/
        └── src/
            └── lib/
                ├── uui-button/
                │   ├── uui-button.component.ts
                │   ├── uui-button.component.html
                │   └── uui-button.behavior.json      <-- new
                ├── uui-grid/
                │   ├── uui-grid.component.ts
                │   ├── uui-grid.component.html
                │   └── uui-grid.behavior.json         <-- new
                └── uui-panel/
                    └── uui-panel.behavior.json         <-- new
```

### 1.2 Behavior definition format

```json
{
  "$schema": "./behavior-schema.json",
  "component": "uui-button",
  "tag": "<uui-button>",
  "description": "Standard button component with variant support",

  "inputs": [
    {
      "name": "label",
      "type": "string",
      "required": true,
      "description": "Button display text"
    },
    {
      "name": "variant",
      "type": "enum",
      "values": ["primary", "secondary", "danger", "link"],
      "default": "secondary",
      "description": "Visual style variant"
    },
    {
      "name": "disabled",
      "type": "boolean",
      "default": false
    },
    {
      "name": "icon",
      "type": "string",
      "required": false,
      "description": "Icon name to display before label"
    }
  ],

  "outputs": [
    {
      "name": "clicked",
      "type": "EventEmitter<void>",
      "description": "Emitted on button click when not disabled"
    }
  ],

  "rendering": {
    "host_element_visible": true,
    "expected_internal_elements": [
      {
        "selector": "button",
        "count": 1,
        "description": "Renders a native button element internally"
      }
    ],
    "shadow_dom": false,
    "accessibility": {
      "role": "button",
      "aria_attributes": ["aria-disabled", "aria-label"]
    }
  },

  "behaviors": [
    {
      "id": "renders-label",
      "description": "Displays the label text inside the button",
      "test": {
        "type": "text_content",
        "selector": "uui-button",
        "contains": "{{label}}"
      }
    },
    {
      "id": "primary-variant-styling",
      "description": "Primary variant applies the correct CSS class",
      "precondition": { "input": "variant", "value": "primary" },
      "test": {
        "type": "has_class",
        "selector": "uui-button button",
        "class": "btn-primary"
      }
    },
    {
      "id": "disabled-prevents-click",
      "description": "When disabled, button is not clickable",
      "precondition": { "input": "disabled", "value": true },
      "test": {
        "type": "attribute",
        "selector": "uui-button button",
        "attribute": "disabled",
        "exists": true
      }
    },
    {
      "id": "click-emits-event",
      "description": "Clicking the button emits the clicked event",
      "precondition": { "input": "disabled", "value": false },
      "test": {
        "type": "interaction",
        "action": "click",
        "selector": "uui-button button",
        "expect": "event_emitted"
      }
    }
  ],

  "replaces": {
    "anti_patterns": [
      {
        "detect": "<button class=\"btn ",
        "description": "Native Bootstrap button should be <uui-button>",
        "fix_template": "<uui-button label=\"{{text_content}}\" variant=\"{{infer_variant}}\"></uui-button>"
      },
      {
        "detect": "<button mat-raised-button",
        "description": "Material button should be <uui-button>",
        "fix_template": "<uui-button label=\"{{text_content}}\" variant=\"primary\"></uui-button>"
      }
    ]
  },

  "breaking_changes": [
    {
      "version": "2.4.0",
      "change": "Renamed input 'btnLabel' to 'label'",
      "migration": {
        "detect": "<uui-button[^>]*btnLabel=",
        "fix": "Replace 'btnLabel' with 'label'"
      }
    }
  ]
}
```

### 1.3 Why this format

Each section serves a specific phase of the pipeline:

| Section | Used by |
|---------|---------|
| `inputs` / `outputs` | Test generation — knows what data the component needs |
| `rendering` | Test generation — knows what to assert is visible |
| `behaviors` | Test generation — specific assertions to run |
| `replaces.anti_patterns` | Scanner — detects HTML that should use this component |
| `replaces.anti_patterns.fix_template` | Auto-fix — generates the corrected HTML |
| `breaking_changes` | Release scanning — detects usage broken by this version |
| `breaking_changes.migration` | Auto-fix — generates the migration PR |

### 1.4 How to create behavior definitions from existing components

You have 24 components in the library. Writing 24 behavior files from scratch is a lot. Here's how to bootstrap them.

**Step 1: Scaffold from component source**

Write a script (`scaffold_behaviors.py`) that reads each component's `.ts` file and extracts:

- `@Input()` decorators → `inputs` array
- `@Output()` decorators → `outputs` array
- `selector:` in `@Component` → `tag`
- `templateUrl:` → infer `rendering.shadow_dom` from `ViewEncapsulation`

This gets you 60-70% of each definition automatically.

```python
"""
scaffold_behaviors.py

Reads Angular component .ts files and generates starter behavior.json files
by extracting @Input(), @Output(), and @Component metadata.
"""

import os
import re
import json

def extract_component_metadata(ts_content):
    """Extract @Component metadata from a .ts file."""
    metadata = {}

    # Extract selector
    selector_match = re.search(r"selector:\s*['\"]([^'\"]+)['\"]", ts_content)
    if selector_match:
        metadata['tag'] = f"<{selector_match.group(1)}>"
        metadata['component'] = selector_match.group(1)

    # Extract inputs
    inputs = []
    input_matches = re.finditer(
        r"@Input\(\s*(?:\{[^}]*\}\s*)?\)\s*(?:set\s+)?(\w+)\s*[!?]?\s*:\s*([^;=]+)",
        ts_content
    )
    for match in input_matches:
        name = match.group(1)
        type_str = match.group(2).strip().rstrip('{').strip()
        inputs.append({
            "name": name,
            "type": type_str,
            "required": False
        })
    metadata['inputs'] = inputs

    # Extract outputs
    outputs = []
    output_matches = re.finditer(
        r"@Output\(\s*\)\s*(\w+)\s*(?::\s*EventEmitter<([^>]*)>)?",
        ts_content
    )
    for match in output_matches:
        outputs.append({
            "name": match.group(1),
            "type": f"EventEmitter<{match.group(2) or 'any'}>"
        })
    metadata['outputs'] = outputs

    # Check for shadow DOM
    if 'ViewEncapsulation.ShadowDom' in ts_content:
        metadata['shadow_dom'] = True
    else:
        metadata['shadow_dom'] = False

    return metadata


def generate_behavior_file(metadata):
    """Generate a starter behavior.json from extracted metadata."""
    return {
        "component": metadata.get('component', ''),
        "tag": metadata.get('tag', ''),
        "description": "TODO: describe this component",
        "inputs": metadata.get('inputs', []),
        "outputs": metadata.get('outputs', []),
        "rendering": {
            "host_element_visible": True,
            "expected_internal_elements": [],
            "shadow_dom": metadata.get('shadow_dom', False),
            "accessibility": {
                "role": "TODO",
                "aria_attributes": []
            }
        },
        "behaviors": [
            {
                "id": "renders-visible",
                "description": "Component renders and is visible",
                "test": {
                    "type": "visible",
                    "selector": metadata.get('tag', '').strip('<>')
                }
            }
        ],
        "replaces": {
            "anti_patterns": []
        },
        "breaking_changes": []
    }


def scaffold_all(library_src_path, output_dir=None):
    """Walk the library source and generate behavior files.

    Args:
        library_src_path: Path to the ui-library/src/lib directory.
        output_dir: Where to write files. Defaults to next to each .ts file.
    """
    for root, dirs, files in os.walk(library_src_path):
        for filename in files:
            if filename.endswith('.component.ts'):
                filepath = os.path.join(root, filename)
                with open(filepath, 'r') as f:
                    content = f.read()

                metadata = extract_component_metadata(content)
                if not metadata.get('component'):
                    continue

                behavior = generate_behavior_file(metadata)
                behavior_filename = filename.replace('.component.ts', '.behavior.json')

                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
                    out_path = os.path.join(output_dir, behavior_filename)
                else:
                    out_path = os.path.join(root, behavior_filename)

                with open(out_path, 'w') as f:
                    json.dump(behavior, f, indent=2)

                print(f"Scaffolded: {out_path}")


if __name__ == '__main__':
    import sys
    src_path = sys.argv[1] if len(sys.argv) > 1 else 'C:/Projects/AO.Common.UI.Ng/projects/ui-library/src/lib'
    scaffold_all(src_path)
```

**Step 2: Fill in behaviors and anti-patterns manually**

The scaffolder gives you the skeleton. A developer who knows the component fills in:

- `behaviors` — what the component should do (2-5 per component)
- `replaces.anti_patterns` — what native HTML this component replaces
- `rendering.expected_internal_elements` — what the component renders internally

This is the part that requires human knowledge. Budget ~15-20 minutes per component. Start with the most-used ones: `uui-button`, `uui-grid`, `uui-panel`, `uui-menu`.

**Step 3: Validate definitions against actual components**

Write a validation script that loads each `.behavior.json` and checks:

- Every `input` in the definition exists as an `@Input()` in the `.ts` file
- Every `output` in the definition exists as an `@Output()` in the `.ts` file
- No `@Input()` or `@Output()` is missing from the definition

This catches drift when the component changes but the definition wasn't updated.

---

## Phase 2: Route maps and navigation sequences

**Goal:** Map file paths to running application routes, including multi-step navigation for pages behind auth or nested routes.

### 2.1 Route map in config

```json
{
  "application_repo": [
    {
      "source_path": "C:/Projects/AO.MDM/AppLib/AO.Portal.UI/app/src",
      "replace_path": "C:/Projects/AO.MDM/",
      "report_name": "AO.Portal_Usage_Results",
      "base_url": "https://ao-portal-staging.example.com",
      "auth": {
        "type": "login_page",
        "url": "/login",
        "username_selector": "#username",
        "password_selector": "#password",
        "submit_selector": "button[type='submit']",
        "credentials_env": {
          "username": "E2E_USERNAME",
          "password": "E2E_PASSWORD"
        }
      },
      "route_map": [
        {
          "path_pattern": "app/dashboard/**",
          "route": "/dashboard",
          "name": "Dashboard"
        },
        {
          "path_pattern": "app/devices/device-list/**",
          "route": "/devices",
          "name": "Device List"
        },
        {
          "path_pattern": "app/devices/device-detail/**",
          "route": "/devices/:id",
          "name": "Device Detail",
          "navigation_sequence": [
            { "goto": "/devices" },
            { "click": "uui-grid uui-grid-row:first-child" }
          ],
          "test_params": { "id": "test-device-001" }
        }
      ]
    }
  ]
}
```

### 2.2 Why navigation_sequence matters

Not every page is reachable by typing a URL. Some pages require:

- Clicking into a detail view from a list
- Opening a modal from a parent page
- Navigating through a wizard

The `navigation_sequence` field describes the steps to reach the page. The test generator uses this to build `page.goto()` → `page.click()` → assert chains.

Pages that are directly routable don't need a `navigation_sequence` — the `route` field is enough.

### 2.3 Auth handling

Most apps require login. The `auth` block in the config tells the test runner how to authenticate before navigating. Credentials come from environment variables, never stored in config.

---

## Phase 3: Scan + resolve + structured output

**Goal:** Upgrade main.py to produce structured JSON output that connects scan results to routes and behavior definitions.

### 3.1 New output format

The scanner produces two files per application:

1. `Reports/{name}-{date}.txt` — human-readable (existing, improved)
2. `Reports/{name}-{date}.json` — machine-readable (new)

```json
{
  "application": "AO.Portal",
  "base_url": "https://ao-portal-staging.example.com",
  "scan_date": "2026-02-14",
  "release": "2.4.0",
  "affected_pages": [
    {
      "file": "AppLib/AO.Portal.UI/app/src/app/dashboard/dashboard.component.html",
      "route": "/dashboard",
      "page_name": "Dashboard",
      "navigation_sequence": null,
      "components_found": [
        {
          "tag": "uui-grid",
          "lines": [8, 45],
          "behavior_definition": "uui-grid.behavior.json",
          "has_breaking_changes": true,
          "breaking_change": "Column 'sortable' input renamed to 'isSortable'"
        },
        {
          "tag": "uui-panel",
          "lines": [22],
          "behavior_definition": "uui-panel.behavior.json",
          "has_breaking_changes": false
        }
      ]
    }
  ]
}
```

### 3.2 Connecting behavior definitions to scan results

During the scan, for each matched component:

1. Look up its `.behavior.json` file from a `definitions_path` in config
2. Check the `breaking_changes` array for the current release version
3. If breaking changes exist, flag them in the output and include migration info
4. Include the behavior definition path so the test generator can find it

Config addition:

```json
{
  "definitions_path": "C:/Projects/AO.Common.UI.Ng/projects/ui-library/src/lib",
  "definitions_glob": "*/*.behavior.json"
}
```

---

## Phase 4: Test generation from behavior definitions

**Goal:** Generate Playwright tests that validate actual component behavior, not just presence.

### 4.1 What gets generated

For each affected page, a test file is created with:

1. **Page load test** — navigates to route, asserts no HTTP errors
2. **Component presence tests** — each `<uui-*>` component is attached and visible
3. **Behavior tests** — from the `behaviors` array in the definition
4. **Breaking change tests** — specifically validate that migrations were applied

### 4.2 Example generated test

Given the `uui-button.behavior.json` above, for a page `/settings` that uses `<uui-button>`:

```typescript
// generated-tests/tests/ao-portal/settings.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Settings — Release 2.4.0 Regression', () => {

  test.beforeEach(async ({ page }) => {
    // Auth flow from config
    await page.goto('/login');
    await page.fill('#username', process.env.E2E_USERNAME!);
    await page.fill('#password', process.env.E2E_PASSWORD!);
    await page.click('button[type="submit"]');
    await page.waitForURL('**/dashboard');
  });

  test('page loads without errors', async ({ page }) => {
    const response = await page.goto('/settings');
    expect(response!.status()).toBeLessThan(400);
  });

  // === uui-button behavior tests ===

  test('uui-button: renders and is visible', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.locator('uui-button').first()).toBeVisible();
  });

  test('uui-button: renders a native button internally', async ({ page }) => {
    await page.goto('/settings');
    const internalButton = page.locator('uui-button button');
    await expect(internalButton.first()).toBeAttached();
  });

  test('uui-button: displays label text', async ({ page }) => {
    await page.goto('/settings');
    const button = page.locator('uui-button').first();
    const text = await button.textContent();
    expect(text?.trim().length).toBeGreaterThan(0);
  });

  test('uui-button: has accessible role', async ({ page }) => {
    await page.goto('/settings');
    const button = page.locator('uui-button button').first();
    await expect(button).toHaveAttribute('role', 'button');
  });

  // === uui-button breaking change tests (v2.4.0) ===

  test('uui-button: btnLabel migration applied', async ({ page }) => {
    // Verify no usage of deprecated 'btnLabel' input
    // This is a source-level check, not E2E — flagged in scan report
  });
});
```

### 4.3 Test generation engine

A Python module that reads the JSON scan output and behavior definitions, then renders test files from templates.

```
scan_results.json
  + behavior definitions (.behavior.json files)
  + config (auth, route_map, base_url)
  → generate_tests.py
  → generated-tests/
       ├── playwright.config.ts
       ├── package.json
       └── tests/
           └── ao-portal/
               ├── dashboard.spec.ts
               └── settings.spec.ts
```

The `generated-tests/` directory is a self-contained Playwright project. A developer or CI job runs:

```bash
cd generated-tests
npm install
BASE_URL=https://ao-portal-staging.example.com npx playwright test
```

### 4.4 Test types mapped from behavior definitions

| Behavior `test.type` | Playwright assertion |
|---|---|
| `visible` | `toBeVisible()` |
| `text_content` | `toContainText(expected)` |
| `has_class` | `evaluate()` to check `classList.contains()` |
| `attribute` | `toHaveAttribute(name, value)` |
| `count` | `toHaveCount(n)` |
| `interaction` → `click` | `page.click(selector)` + assert outcome |
| `not_present` | `toHaveCount(0)` |

---

## Phase 5: Failure diagnosis and fix suggestions

**Goal:** When tests fail, produce actionable output that tells the developer exactly what broke and how to fix it.

### 5.1 Structured failure report

After Playwright runs, parse the JSON results and cross-reference with behavior definitions:

```json
{
  "application": "AO.Portal",
  "release": "2.4.0",
  "total_tests": 24,
  "passed": 21,
  "failed": 3,
  "failures": [
    {
      "page": "/settings",
      "page_name": "Settings",
      "file": "app/settings/settings.component.html",
      "component": "uui-button",
      "behavior_id": "renders-label",
      "description": "uui-button: displays label text",
      "error": "Expected text content length > 0, got 0",
      "probable_cause": "Breaking change in v2.4.0: input 'btnLabel' renamed to 'label'",
      "fix": {
        "type": "attribute_rename",
        "file": "app/settings/settings.component.html",
        "line": 45,
        "before": "<uui-button btnLabel=\"Save\">",
        "after": "<uui-button label=\"Save\">"
      }
    }
  ]
}
```

### 5.2 How fixes are determined

The pipeline works backward:

1. Test fails for `uui-button` behavior `renders-label` on `/settings`
2. Look up `uui-button.behavior.json` → `breaking_changes` for this release
3. Breaking change says `btnLabel` renamed to `label`
4. Scan the source file at the matched lines for `btnLabel`
5. If found → fix is: rename `btnLabel` to `label`
6. If not found → fix is unknown, flag for manual review

The `breaking_changes.migration.detect` regex does the source-level check. The `fix_template` or `fix` description provides the remediation.

### 5.3 Fix confidence levels

Not every failure has an obvious fix. Categorize:

| Confidence | Meaning | Action |
|---|---|---|
| `auto` | Regex detected the exact issue, fix is mechanical | Can auto-apply |
| `suggested` | Likely cause identified, but human should verify | Include in PR as suggestion |
| `manual` | Test failed but no matching breaking change or anti-pattern | Flag for manual investigation |

---

## Phase 6: Auto-create PRs with fixes

**Goal:** For `auto` and `suggested` confidence fixes, create a branch, apply the changes, and open a PR.

### 6.1 Flow

```
failure report with fixes
  → for each affected app repo:
      → git checkout -b fix/uui-release-2.4.0-regression
      → apply fixes (sed/python string replacement on source files)
      → git commit
      → git push
      → gh pr create
```

### 6.2 PR content

```markdown
## UUI Library v2.4.0 — Automated Regression Fixes

### Summary
3 issues found and fixed from the uui-library v2.4.0 release.

### Changes

| File | Line | Issue | Fix |
|------|------|-------|-----|
| settings.component.html | 45 | `btnLabel` renamed to `label` | Attribute rename |
| dashboard.component.html | 12 | `sortable` renamed to `isSortable` | Attribute rename |
| dashboard.component.html | 88 | Deprecated `<uui-card-panel>` | Replaced with `<uui-card-panel2>` |

### Test Results
- 24 tests run against staging
- 21 passed before fixes
- 24 passed after fixes

### How to verify
1. Check out this branch
2. Run: `BASE_URL=https://staging.example.com npx playwright test`
3. All tests should pass

> Auto-generated by Common.Ui.Usage regression pipeline
```

### 6.3 Safety

- Fixes with confidence `auto` are applied directly
- Fixes with confidence `suggested` are applied but marked with an HTML comment: `<!-- UUI-FIX: verify this change -->`
- Fixes with confidence `manual` are NOT applied — listed in the PR description as "needs manual review"
- The PR is always opened as a draft
- The tool never force-pushes or modifies existing branches

### 6.4 Implementation

Use the `gh` CLI (GitHub CLI) for PR creation. The fix-application logic is Python string replacement guided by the file path, line number, and before/after values from the failure report.

```python
def apply_fix(fix):
    """Apply a single fix to a source file.

    Args:
        fix: Dict with 'file', 'line', 'before', 'after', 'confidence' keys.
    """
    filepath = fix['file']
    with open(filepath, 'r') as f:
        lines = f.readlines()

    line_idx = fix['line'] - 1
    if fix['before'] in lines[line_idx]:
        if fix['confidence'] == 'suggested':
            comment = f"<!-- UUI-FIX: verify this change -->\n"
            lines[line_idx] = lines[line_idx].replace(fix['before'], fix['after'])
            lines.insert(line_idx, comment)
        else:
            lines[line_idx] = lines[line_idx].replace(fix['before'], fix['after'])

        with open(filepath, 'w') as f:
            f.writelines(lines)
```

---

## Complete pipeline flow

```
┌──────────────────────────────────────────────────────────────────┐
│  UI Library Release (e.g., v2.4.0)                               │
│  → Your private tool produces affected component list            │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Phase 1: config.json updated                                    │
│  → affected components, route maps, behavior definition paths    │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Phase 3: main.py scans all app repos                            │
│  → finds which files/pages use affected components               │
│  → cross-references behavior definitions for breaking changes    │
│  → resolves file paths to routes via route_map                   │
│  → outputs scan_results.json                                     │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Phase 4: generate_tests.py                                      │
│  → reads scan_results.json + behavior definitions                │
│  → generates Playwright .spec.ts files per affected page         │
│  → includes auth flows, navigation sequences                     │
│  → outputs generated-tests/ directory                            │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Run tests: npx playwright test                                  │
│  → against staging/QA environment                                │
│  → produces playwright results.json                              │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Phase 5: diagnose_failures.py                                   │
│  → parses Playwright results                                     │
│  → cross-references behavior definitions + breaking changes      │
│  → produces failure_report.json with fixes                       │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Phase 6: create_fix_pr.py                                       │
│  → applies auto/suggested fixes to source files                  │
│  → creates branch, commits, pushes                               │
│  → opens draft PR via gh CLI                                     │
│  → PR includes test results + fix table                          │
└──────────────────────────────────────────────────────────────────┘
```

---

## File structure after all phases

```
Common.Ui.Usage/
├── main.py                      # Scanner + route resolver + JSON output
├── generate_tests.py            # Reads scan results, writes Playwright tests
├── diagnose_failures.py         # Parses test results, produces fix report
├── create_fix_pr.py             # Applies fixes, creates draft PRs
├── scaffold_behaviors.py        # Bootstraps .behavior.json from .ts files
├── validate_behaviors.py        # Checks definitions match component source
├── config.json                  # Patterns, repos, route maps, release info
├── behavior-schema.json         # JSON Schema for .behavior.json validation
├── templates/
│   ├── test_file.ts.j2          # Playwright test file template
│   ├── test_block.ts.j2         # Individual test block template
│   └── playwright_config.ts.j2  # Playwright config template
├── Reports/                     # Generated text + JSON reports (gitignored)
└── generated-tests/             # Generated Playwright project (gitignored)
```

---

## Implementation priority and effort

| Phase | What | Depends on | Effort estimate |
|-------|------|-----------|-----------------|
| 0 | Fix existing bugs | Nothing | Small |
| 1 | Behavior definitions schema + scaffolder | Nothing | Medium — schema design + scaffolding script + manual fill-in for first 5-6 components |
| 2 | Route maps in config | Nothing | Small — config additions, start with one app |
| 3 | Structured JSON scan output | Phase 0, 1, 2 | Medium — refactor main.py |
| 4 | Test generation | Phase 1, 2, 3 | Large — template engine, auth handling, navigation sequences |
| 5 | Failure diagnosis | Phase 1, 4 | Medium — Playwright result parsing, breaking change matching |
| 6 | Auto-PR creation | Phase 5 | Medium — git operations, PR formatting |

### Recommended order of work

1. **Phase 0** — fix bugs, get a clean baseline
2. **Phase 1** — scaffold behavior definitions for 5 core components (`uui-button`, `uui-grid`, `uui-panel`, `uui-menu`, `uui-page-title`). Don't try to do all 24 at once
3. **Phase 2** — add route map for one application (AO.Portal is a good start since it's listed first in config)
4. **Phase 3** — refactor main.py to output JSON alongside text
5. **Phase 4** — build test generator targeting the one app with route maps, validate against a staging environment
6. **Iterate** — add behavior definitions for more components, add route maps for more apps
7. **Phase 5 + 6** — once test generation is proven, add diagnosis and auto-PR

### What to start with right now

Write behavior definitions for these 5 components first — they're the most likely to appear on every page and give you the broadest coverage:

1. `uui-button` — every app has buttons
2. `uui-grid` — data display is core to these apps
3. `uui-panel` — structural component used everywhere
4. `uui-menu` / `uui-menu-item` — navigation is on every page
5. `uui-page-title` — present on every routed page

Once those 5 have behavior definitions, you can run the full pipeline end-to-end on one application and prove the concept before expanding.
