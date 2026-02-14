import os
import re
import json
import tempfile
import shutil
import unittest
from unittest.mock import patch
from datetime import date

from main import search_html_files


def build_patterns(pattern_strings):
    """Build regex pattern tuples from raw pattern strings, matching main.py logic."""
    negative_lookahead = r'(?![!?-])'
    return [
        (p, re.escape(p) + negative_lookahead) if p.startswith('<') else (p, re.escape(p))
        for p in pattern_strings
    ]


class TestBuildPatterns(unittest.TestCase):
    """Tests for the pattern-building logic."""

    def test_html_tag_gets_negative_lookahead(self):
        patterns = build_patterns(['<uui-button'])
        _, regex = patterns[0]
        self.assertIn('(?![!?-])', regex)

    def test_non_tag_pattern_no_lookahead(self):
        patterns = build_patterns(['someDirective'])
        _, regex = patterns[0]
        self.assertNotIn('(?![!?-])', regex)

    def test_pattern_escapes_special_chars(self):
        patterns = build_patterns(['<uui-grid'])
        _, regex = patterns[0]
        # The hyphen should be escaped by re.escape()
        self.assertIn(r'\-', regex)

    def test_tag_pattern_matches_opening_tag(self):
        patterns = build_patterns(['<uui-button'])
        _, regex = patterns[0]
        self.assertIsNotNone(re.search(regex, '<uui-button label="Save">'))

    def test_tag_pattern_does_not_match_closing_tag_lookahead(self):
        """The negative lookahead (?![!?-]) should prevent matching patterns
        immediately followed by !, ?, or -."""
        patterns = build_patterns(['<uui-button'])
        _, regex = patterns[0]
        # A pattern like <uui-button- (with trailing hyphen) should not match
        match = re.search(regex, '<uui-button-extended>')
        self.assertIsNone(match)

    def test_multiple_patterns_built(self):
        patterns = build_patterns(['<uui-grid', '<uui-panel', 'someDirective'])
        self.assertEqual(len(patterns), 3)


class TestSearchHtmlFiles(unittest.TestCase):
    """Tests for the search_html_files function."""

    def setUp(self):
        """Create a temporary directory structure with HTML files."""
        self.test_dir = tempfile.mkdtemp()
        self.output_file = os.path.join(self.test_dir, 'output.txt')

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.test_dir)

    def _create_html(self, relative_path, content):
        """Helper to create an HTML file in the test directory."""
        full_path = os.path.join(self.test_dir, relative_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
        return full_path

    def _read_output(self):
        """Read the output file contents."""
        with open(self.output_file, 'r') as f:
            return f.read()

    def test_finds_single_pattern_match(self):
        self._create_html('app/page.html', '<div>\n  <uui-button label="Save"></uui-button>\n</div>')
        patterns = build_patterns(['<uui-button'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertIn('<uui-button', output)
        self.assertIn('Line 2', output)

    def test_finds_multiple_patterns_in_same_file(self):
        html = '<uui-grid>\n  <uui-panel>content</uui-panel>\n</uui-grid>'
        self._create_html('app/page.html', html)
        patterns = build_patterns(['<uui-grid', '<uui-panel'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertIn('Pattern: <uui-grid', output)
        self.assertIn('Pattern: <uui-panel', output)

    def test_correct_line_numbers(self):
        html = 'line one\nline two\n<uui-button label="go">\nline four\n<uui-panel>\n'
        self._create_html('app/page.html', html)
        patterns = build_patterns(['<uui-button', '<uui-panel'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertIn('Line 3', output)
        self.assertIn('Line 5', output)

    def test_line_numbers_not_inflated_by_pattern_count(self):
        """Regression test: line_num must increment once per line, not once per pattern."""
        html = 'line one\n<uui-button>\nline three\n'
        self._create_html('app/page.html', html)
        # Use 5 patterns to verify line_num doesn't multiply
        patterns = build_patterns(['<uui-button', '<uui-grid', '<uui-panel', '<uui-menu', '<uui-tag'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertIn('Line 2', output)
        # If the bug were present with 5 patterns, line 2 would be reported as line 6
        self.assertNotIn('Line 6', output)

    def test_no_match_produces_empty_output(self):
        self._create_html('app/page.html', '<div>no components here</div>')
        patterns = build_patterns(['<uui-button'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertEqual(output.strip(), '')

    def test_only_scans_html_files(self):
        self._create_html('app/page.html', '<uui-button>')
        # Create a .ts file with the same content — should be ignored
        ts_path = os.path.join(self.test_dir, 'app', 'page.component.ts')
        with open(ts_path, 'w') as f:
            f.write("template: '<uui-button>'")
        patterns = build_patterns(['<uui-button'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        # Should only have the .html match, not the .ts
        self.assertIn('page.html', output)
        self.assertNotIn('page.component.ts', output)

    def test_recursive_directory_scanning(self):
        self._create_html('app/dashboard/dashboard.component.html', '<uui-grid>')
        self._create_html('app/settings/settings.component.html', '<uui-panel>')
        patterns = build_patterns(['<uui-grid', '<uui-panel'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertIn('dashboard', output)
        self.assertIn('settings', output)

    def test_replace_path_strips_prefix(self):
        self._create_html('app/page.html', '<uui-button>')
        replace = self.test_dir + '/'
        patterns = build_patterns(['<uui-button'])
        search_html_files(patterns, self.test_dir, self.output_file, replace)
        output = self._read_output()
        # The full temp path should be stripped
        self.assertNotIn(self.test_dir, output)
        self.assertIn('app/page.html', output)

    def test_multiple_matches_on_same_line(self):
        html = '<uui-button label="a"> <uui-button label="b">\n'
        self._create_html('app/page.html', html)
        patterns = build_patterns(['<uui-button'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        # Should find two matches, both on line 1
        lines_with_match = [l for l in output.split('\n') if 'Line 1' in l]
        self.assertEqual(len(lines_with_match), 2)

    def test_output_file_header_format(self):
        self._create_html('app/page.html', '<uui-button>')
        patterns = build_patterns(['<uui-button'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        # File header should be wrapped in ** markers
        self.assertRegex(output, r'\*\* .+page\.html \*\*')

    def test_empty_html_file(self):
        self._create_html('app/empty.html', '')
        patterns = build_patterns(['<uui-button'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertEqual(output.strip(), '')

    def test_result_includes_pattern_label(self):
        self._create_html('app/page.html', '<uui-grid columns="3">')
        patterns = build_patterns(['<uui-grid'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertIn('(Pattern: <uui-grid)', output)

    def test_realistic_page_exact_line_numbers(self):
        """Full-page HTML with components on known lines. Verifies every reported
        line number matches the actual position in the source file."""
        html = (
            '<html>\n'                                          # line 1
            '<head><title>Dashboard</title></head>\n'           # line 2
            '<body>\n'                                          # line 3
            '  <div class="container">\n'                       # line 4
            '    <uui-grid columns="3">\n'                      # line 5  -- uui-grid
            '      <uui-panel header="Sales">\n'                # line 6  -- uui-panel
            '        <p>Content here</p>\n'                     # line 7
            '      </uui-panel>\n'                              # line 8
            '      <uui-panel header="Revenue">\n'              # line 9  -- uui-panel
            '        <uui-button label="Refresh"></uui-button>\n'  # line 10 -- uui-button
            '      </uui-panel>\n'                              # line 11
            '    </uui-grid>\n'                                 # line 12
            '    <div class="footer">\n'                        # line 13
            '      <uui-button label="Save" />\n'              # line 14 -- uui-button
            '    </div>\n'                                      # line 15
            '  </div>\n'                                        # line 16
            '</body>\n'                                         # line 17
            '</html>\n'                                         # line 18
        )
        self._create_html('app/dashboard.component.html', html)
        patterns = build_patterns(['<uui-grid', '<uui-panel', '<uui-button'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()

        # Parse every "Line N: ... (Pattern: ...)" entry from the output
        result_lines = [l.strip() for l in output.split('\n') if l.strip().startswith('Line ')]

        # Build a list of (line_number, pattern) from output
        import re as _re
        parsed = []
        for entry in result_lines:
            m = _re.match(r'Line (\d+): .+ \(Pattern: (.+)\)', entry)
            self.assertIsNotNone(m, f"Could not parse result line: {entry}")
            parsed.append((int(m.group(1)), m.group(2)))

        # Expected matches based on the HTML above
        expected = [
            (5,  '<uui-grid'),
            (6,  '<uui-panel'),
            (9,  '<uui-panel'),
            (10, '<uui-button'),
            (14, '<uui-button'),
        ]

        self.assertEqual(sorted(parsed), sorted(expected),
                         f"Mismatch.\nExpected: {sorted(expected)}\nGot:      {sorted(parsed)}")


class TestPatternMatching(unittest.TestCase):
    """Tests for specific pattern matching edge cases."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.output_file = os.path.join(self.test_dir, 'output.txt')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _create_html(self, content):
        path = os.path.join(self.test_dir, 'test.html')
        with open(path, 'w') as f:
            f.write(content)

    def _read_output(self):
        with open(self.output_file, 'r') as f:
            return f.read()

    def test_does_not_match_extended_tag_name(self):
        """<uui-menu should not match <uui-menu-item due to negative lookahead on hyphen."""
        self._create_html('<uui-menu-item>stuff</uui-menu-item>')
        patterns = build_patterns(['<uui-menu'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertEqual(output.strip(), '')

    def test_matches_tag_with_space_after(self):
        self._create_html('<uui-menu class="nav">')
        patterns = build_patterns(['<uui-menu'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertIn('<uui-menu', output)

    def test_matches_tag_with_closing_bracket(self):
        self._create_html('<uui-menu>')
        patterns = build_patterns(['<uui-menu'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertIn('<uui-menu', output)

    def test_matches_self_closing_tag(self):
        self._create_html('<uui-button label="go" />')
        patterns = build_patterns(['<uui-button'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertIn('<uui-button', output)

    def test_non_tag_pattern_matches_anywhere(self):
        self._create_html('<div uuiDirective="true"></div>')
        patterns = build_patterns(['uuiDirective'])
        search_html_files(patterns, self.test_dir, self.output_file, self.test_dir + '/')
        output = self._read_output()
        self.assertIn('uuiDirective', output)


class TestConfigLoading(unittest.TestCase):
    """Tests for config.json structure and loading."""

    def test_config_is_valid_json(self):
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        self.assertIsInstance(config, dict)

    def test_config_has_required_keys(self):
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        self.assertIn('patterns', config)
        self.assertIn('application_repo', config)

    def test_patterns_is_nonempty_list(self):
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        self.assertIsInstance(config['patterns'], list)
        self.assertGreater(len(config['patterns']), 0)

    def test_application_repo_entries_have_required_fields(self):
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        for repo in config['application_repo']:
            self.assertIn('source_path', repo)
            self.assertIn('replace_path', repo)
            self.assertIn('report_name', repo)

    def test_all_patterns_can_build_regex(self):
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        patterns = build_patterns(config['patterns'])
        for original, regex in patterns:
            # Should not raise
            compiled = re.compile(regex)
            self.assertIsNotNone(compiled)


if __name__ == '__main__':
    unittest.main()
