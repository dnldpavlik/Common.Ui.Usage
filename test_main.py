"""Tests for Common.Ui.Usage scanner."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from main import (
    MatchResult,
    FileResult,
    RepoConfig,
    build_pattern,
    build_patterns,
    scan_line,
    scan_file,
    scan_directory,
    find_html_files,
    format_file_result,
    format_report,
    write_report,
    load_config,
    validate_config,
    parse_repo_configs,
    parse_args,
    main,
    NEGATIVE_LOOKAHEAD,
)


# ===========================================================================
# Helpers
# ===========================================================================

class TempDirMixin:
    """Mixin providing a temp directory with HTML file helpers."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _create_html(self, relative_path: str, content: str) -> Path:
        full_path = self.test_dir / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        return full_path

    def _create_config(self, config: dict) -> Path:
        config_path = self.test_dir / 'config.json'
        config_path.write_text(json.dumps(config))
        return config_path


# ===========================================================================
# TestBuildPattern — single pattern construction
# ===========================================================================

class TestBuildPattern(unittest.TestCase):
    """Tests for build_pattern (single pattern)."""

    def test_tag_pattern_returns_compiled_regex(self):
        original, compiled = build_pattern('<uui-button')
        self.assertEqual(original, '<uui-button')
        self.assertIsInstance(compiled, re.Pattern)

    def test_tag_pattern_includes_negative_lookahead(self):
        _, compiled = build_pattern('<uui-button')
        self.assertIn(NEGATIVE_LOOKAHEAD, compiled.pattern)

    def test_non_tag_pattern_no_lookahead(self):
        _, compiled = build_pattern('someDirective')
        self.assertNotIn(NEGATIVE_LOOKAHEAD, compiled.pattern)

    def test_special_chars_escaped(self):
        _, compiled = build_pattern('<uui-grid')
        self.assertIn(r'\-', compiled.pattern)

    def test_tag_matches_opening_tag(self):
        _, compiled = build_pattern('<uui-button')
        self.assertIsNotNone(compiled.search('<uui-button label="Save">'))

    def test_tag_does_not_match_extended_name(self):
        """Negative lookahead prevents <uui-button matching <uui-button-extended."""
        _, compiled = build_pattern('<uui-button')
        self.assertIsNone(compiled.search('<uui-button-extended>'))


# ===========================================================================
# TestBuildPatterns — batch pattern construction
# ===========================================================================

class TestBuildPatterns(unittest.TestCase):
    """Tests for build_patterns (batch)."""

    def test_builds_correct_count(self):
        patterns = build_patterns(['<uui-grid', '<uui-panel', 'someDirective'])
        self.assertEqual(len(patterns), 3)

    def test_preserves_order(self):
        raw = ['<uui-grid', 'directive', '<uui-panel']
        patterns = build_patterns(raw)
        originals = [p[0] for p in patterns]
        self.assertEqual(originals, raw)

    def test_empty_list(self):
        self.assertEqual(build_patterns([]), [])


# ===========================================================================
# TestScanLine — pure line scanning, no I/O
# ===========================================================================

class TestScanLine(unittest.TestCase):
    """Tests for scan_line — pure function, no file I/O."""

    def setUp(self):
        self.patterns = build_patterns(['<uui-button', '<uui-grid'])

    def test_no_match_returns_empty(self):
        results = scan_line('<div>hello</div>', 1, self.patterns)
        self.assertEqual(results, [])

    def test_single_match(self):
        results = scan_line('  <uui-button label="go">', 5, self.patterns)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].line_num, 5)
        self.assertEqual(results[0].pattern, '<uui-button')

    def test_multiple_patterns_on_same_line(self):
        results = scan_line('<uui-grid><uui-button>', 1, self.patterns)
        patterns_found = {r.pattern for r in results}
        self.assertEqual(patterns_found, {'<uui-grid', '<uui-button'})

    def test_same_pattern_twice_on_line(self):
        results = scan_line('<uui-button> <uui-button>', 1, self.patterns)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.pattern == '<uui-button' for r in results))

    def test_returns_match_result_instances(self):
        results = scan_line('<uui-button>', 1, self.patterns)
        self.assertIsInstance(results[0], MatchResult)

    def test_excerpt_is_stripped(self):
        results = scan_line('  <uui-button  ', 1, self.patterns)
        self.assertEqual(results[0].excerpt, '<uui-button')

    def test_line_num_passed_through(self):
        for num in [1, 50, 999]:
            results = scan_line('<uui-button>', num, self.patterns)
            self.assertEqual(results[0].line_num, num)


# ===========================================================================
# TestFindHtmlFiles — file discovery
# ===========================================================================

class TestFindHtmlFiles(TempDirMixin, unittest.TestCase):
    """Tests for find_html_files generator."""

    def test_finds_html_files(self):
        self._create_html('app/page.html', '<div>')
        files = list(find_html_files(self.test_dir))
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith('.html'))

    def test_ignores_non_html(self):
        self._create_html('app/page.html', '<div>')
        (self.test_dir / 'app' / 'script.ts').write_text('code')
        files = list(find_html_files(self.test_dir))
        self.assertEqual(len(files), 1)

    def test_recursive(self):
        self._create_html('a/b/c/deep.html', '<div>')
        files = list(find_html_files(self.test_dir))
        self.assertEqual(len(files), 1)
        self.assertIn('deep.html', str(files[0]))

    def test_empty_directory(self):
        files = list(find_html_files(self.test_dir))
        self.assertEqual(files, [])

    def test_returns_path_objects(self):
        self._create_html('page.html', '<div>')
        files = list(find_html_files(self.test_dir))
        self.assertIsInstance(files[0], Path)


# ===========================================================================
# TestScanFile — single file scanning
# ===========================================================================

class TestScanFile(TempDirMixin, unittest.TestCase):
    """Tests for scan_file."""

    def test_returns_file_result(self):
        path = self._create_html('page.html', '<uui-button>')
        result = scan_file(path, build_patterns(['<uui-button']))
        self.assertIsInstance(result, FileResult)

    def test_correct_line_numbers(self):
        path = self._create_html('page.html', 'line one\nline two\n<uui-button>\n')
        result = scan_file(path, build_patterns(['<uui-button']))
        self.assertEqual(result.matches[0].line_num, 3)

    def test_multiple_matches(self):
        path = self._create_html('page.html', '<uui-grid>\n<uui-panel>\n')
        result = scan_file(path, build_patterns(['<uui-grid', '<uui-panel']))
        self.assertEqual(len(result.matches), 2)

    def test_no_matches_returns_empty_tuple(self):
        path = self._create_html('page.html', '<div>nothing</div>')
        result = scan_file(path, build_patterns(['<uui-button']))
        self.assertEqual(result.matches, ())

    def test_preserves_file_path(self):
        path = self._create_html('app/page.html', '<uui-button>')
        result = scan_file(path, build_patterns(['<uui-button']))
        self.assertEqual(result.file_path, str(path))

    def test_empty_file(self):
        path = self._create_html('empty.html', '')
        result = scan_file(path, build_patterns(['<uui-button']))
        self.assertEqual(result.matches, ())

    def test_line_numbers_not_inflated_by_pattern_count(self):
        """Regression: line_num must increment once per line, not per pattern."""
        path = self._create_html('page.html', 'line one\n<uui-button>\nline three\n')
        patterns = build_patterns(['<uui-button', '<uui-grid', '<uui-panel', '<uui-menu', '<uui-tag'])
        result = scan_file(path, patterns)
        self.assertEqual(result.matches[0].line_num, 2)


# ===========================================================================
# TestScanDirectory — directory-level scanning
# ===========================================================================

class TestScanDirectory(TempDirMixin, unittest.TestCase):
    """Tests for scan_directory."""

    def test_finds_matches_across_files(self):
        self._create_html('app/a.html', '<uui-grid>')
        self._create_html('app/b.html', '<uui-panel>')
        results = scan_directory(self.test_dir, build_patterns(['<uui-grid', '<uui-panel']))
        self.assertEqual(len(results), 2)

    def test_excludes_files_without_matches(self):
        self._create_html('app/match.html', '<uui-grid>')
        self._create_html('app/nope.html', '<div>plain</div>')
        results = scan_directory(self.test_dir, build_patterns(['<uui-grid']))
        self.assertEqual(len(results), 1)

    def test_recursive_scanning(self):
        self._create_html('a/b/deep.html', '<uui-button>')
        results = scan_directory(self.test_dir, build_patterns(['<uui-button']))
        self.assertEqual(len(results), 1)

    def test_only_scans_html(self):
        self._create_html('page.html', '<uui-button>')
        (self.test_dir / 'script.ts').write_text("'<uui-button>'")
        results = scan_directory(self.test_dir, build_patterns(['<uui-button']))
        self.assertEqual(len(results), 1)
        self.assertIn('page.html', results[0].file_path)

    def test_empty_directory(self):
        results = scan_directory(self.test_dir, build_patterns(['<uui-button']))
        self.assertEqual(results, [])


# ===========================================================================
# TestFormatReport — pure formatting
# ===========================================================================

class TestFormatReport(unittest.TestCase):
    """Tests for format_file_result and format_report — pure, no I/O."""

    def test_format_file_result_strips_replace_path(self):
        result = FileResult(
            file_path='/projects/app/src/page.html',
            matches=(MatchResult(1, '<uui-button', '<uui-button'),),
        )
        output = format_file_result(result, '/projects/app/')
        self.assertIn('src/page.html', output)
        self.assertNotIn('/projects/app/', output)

    def test_format_file_result_header_format(self):
        result = FileResult(
            file_path='/app/page.html',
            matches=(MatchResult(1, '<uui-button', '<uui-button'),),
        )
        output = format_file_result(result, '/app/')
        self.assertRegex(output, r'\*\* page\.html \*\*')

    def test_format_file_result_includes_line_numbers(self):
        result = FileResult(
            file_path='page.html',
            matches=(
                MatchResult(3, '<uui-grid', '<uui-grid'),
                MatchResult(7, '<uui-panel', '<uui-panel'),
            ),
        )
        output = format_file_result(result, '')
        self.assertIn('Line 3:', output)
        self.assertIn('Line 7:', output)

    def test_format_file_result_includes_pattern_label(self):
        result = FileResult(
            file_path='page.html',
            matches=(MatchResult(1, '<uui-grid', '<uui-grid'),),
        )
        output = format_file_result(result, '')
        self.assertIn('(Pattern: <uui-grid)', output)

    def test_format_report_empty_results(self):
        self.assertEqual(format_report([], ''), '')

    def test_format_report_single_file(self):
        results = [FileResult('page.html', (MatchResult(1, '<uui-button', '<uui-button'),))]
        output = format_report(results, '')
        self.assertIn('page.html', output)
        self.assertIn('Line 1', output)

    def test_format_report_multiple_files(self):
        results = [
            FileResult('a.html', (MatchResult(1, '<uui-grid', '<uui-grid'),)),
            FileResult('b.html', (MatchResult(2, '<uui-panel', '<uui-panel'),)),
        ]
        output = format_report(results, '')
        self.assertIn('a.html', output)
        self.assertIn('b.html', output)


# ===========================================================================
# TestValidateConfig — config validation
# ===========================================================================

class TestValidateConfig(unittest.TestCase):
    """Tests for validate_config."""

    def test_valid_config_passes(self):
        config = {
            'patterns': ['<uui-button'],
            'application_repo': [
                {'source_path': '/tmp', 'replace_path': '/', 'report_name': 'test'},
            ],
        }
        validate_config(config)  # should not raise

    def test_missing_patterns_key(self):
        with self.assertRaises(ValueError) as ctx:
            validate_config({'application_repo': []})
        self.assertIn('patterns', str(ctx.exception))

    def test_missing_application_repo_key(self):
        with self.assertRaises(ValueError) as ctx:
            validate_config({'patterns': ['<uui-button']})
        self.assertIn('application_repo', str(ctx.exception))

    def test_empty_patterns_list(self):
        with self.assertRaises(ValueError):
            validate_config({'patterns': [], 'application_repo': []})

    def test_patterns_not_a_list(self):
        with self.assertRaises(ValueError):
            validate_config({'patterns': 'not-a-list', 'application_repo': []})

    def test_repo_missing_source_path(self):
        config = {
            'patterns': ['<uui-button'],
            'application_repo': [{'replace_path': '/', 'report_name': 'test'}],
        }
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn('source_path', str(ctx.exception))

    def test_repo_missing_replace_path(self):
        config = {
            'patterns': ['<uui-button'],
            'application_repo': [{'source_path': '/tmp', 'report_name': 'test'}],
        }
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn('replace_path', str(ctx.exception))

    def test_repo_missing_report_name(self):
        config = {
            'patterns': ['<uui-button'],
            'application_repo': [{'source_path': '/tmp', 'replace_path': '/'}],
        }
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn('report_name', str(ctx.exception))


# ===========================================================================
# TestParseRepoConfigs — config parsing
# ===========================================================================

class TestParseRepoConfigs(unittest.TestCase):
    """Tests for parse_repo_configs."""

    def test_parses_to_repo_config(self):
        raw = [{'source_path': '/tmp/src', 'replace_path': '/tmp/', 'report_name': 'test'}]
        configs = parse_repo_configs(raw)
        self.assertEqual(len(configs), 1)
        self.assertIsInstance(configs[0], RepoConfig)

    def test_source_path_is_path(self):
        raw = [{'source_path': '/tmp/src', 'replace_path': '/tmp/', 'report_name': 'test'}]
        configs = parse_repo_configs(raw)
        self.assertIsInstance(configs[0].source_path, Path)

    def test_preserves_values(self):
        raw = [{'source_path': '/a/b', 'replace_path': '/a/', 'report_name': 'report'}]
        cfg = parse_repo_configs(raw)[0]
        self.assertEqual(cfg.source_path, Path('/a/b'))
        self.assertEqual(cfg.replace_path, '/a/')
        self.assertEqual(cfg.report_name, 'report')


# ===========================================================================
# TestParseArgs — CLI argument parsing
# ===========================================================================

class TestParseArgs(unittest.TestCase):
    """Tests for parse_args."""

    def test_defaults(self):
        args = parse_args([])
        self.assertEqual(args.config, Path('config.json'))
        self.assertEqual(args.output_dir, Path('Reports'))
        self.assertFalse(args.verbose)

    def test_custom_config(self):
        args = parse_args(['-c', '/tmp/my.json'])
        self.assertEqual(args.config, Path('/tmp/my.json'))

    def test_custom_output_dir(self):
        args = parse_args(['-o', '/tmp/output'])
        self.assertEqual(args.output_dir, Path('/tmp/output'))

    def test_verbose_flag(self):
        args = parse_args(['-v'])
        self.assertTrue(args.verbose)

    def test_long_form_args(self):
        args = parse_args(['--config', 'c.json', '--output-dir', 'out', '--verbose'])
        self.assertEqual(args.config, Path('c.json'))
        self.assertEqual(args.output_dir, Path('out'))
        self.assertTrue(args.verbose)


# ===========================================================================
# TestWriteReport — report file writing
# ===========================================================================

class TestWriteReport(TempDirMixin, unittest.TestCase):
    """Tests for write_report."""

    def test_writes_content(self):
        output = self.test_dir / 'report.txt'
        write_report('hello world', output)
        self.assertEqual(output.read_text(), 'hello world')

    def test_creates_parent_directories(self):
        output = self.test_dir / 'deep' / 'nested' / 'report.txt'
        write_report('content', output)
        self.assertTrue(output.exists())

    def test_overwrites_existing(self):
        output = self.test_dir / 'report.txt'
        write_report('first', output)
        write_report('second', output)
        self.assertEqual(output.read_text(), 'second')


# ===========================================================================
# TestPatternMatching — edge cases
# ===========================================================================

class TestPatternMatching(TempDirMixin, unittest.TestCase):
    """Tests for specific pattern matching edge cases."""

    def test_does_not_match_extended_tag_name(self):
        """<uui-menu should not match <uui-menu-item due to negative lookahead."""
        path = self._create_html('test.html', '<uui-menu-item>stuff</uui-menu-item>')
        result = scan_file(path, build_patterns(['<uui-menu']))
        self.assertEqual(result.matches, ())

    def test_matches_tag_with_space_after(self):
        path = self._create_html('test.html', '<uui-menu class="nav">')
        result = scan_file(path, build_patterns(['<uui-menu']))
        self.assertEqual(len(result.matches), 1)

    def test_matches_tag_with_closing_bracket(self):
        path = self._create_html('test.html', '<uui-menu>')
        result = scan_file(path, build_patterns(['<uui-menu']))
        self.assertEqual(len(result.matches), 1)

    def test_matches_self_closing_tag(self):
        path = self._create_html('test.html', '<uui-button label="go" />')
        result = scan_file(path, build_patterns(['<uui-button']))
        self.assertEqual(len(result.matches), 1)

    def test_non_tag_pattern_matches_anywhere(self):
        path = self._create_html('test.html', '<div uuiDirective="true"></div>')
        result = scan_file(path, build_patterns(['uuiDirective']))
        self.assertEqual(len(result.matches), 1)


# ===========================================================================
# TestConfigLoading — loads actual config.json
# ===========================================================================

class TestConfigLoading(unittest.TestCase):
    """Tests for loading the real config.json."""

    def test_config_is_valid_json(self):
        config = load_config(Path('config.json'))
        self.assertIsInstance(config, dict)

    def test_config_has_required_keys(self):
        config = load_config(Path('config.json'))
        self.assertIn('patterns', config)
        self.assertIn('application_repo', config)

    def test_patterns_is_nonempty_list(self):
        config = load_config(Path('config.json'))
        self.assertIsInstance(config['patterns'], list)
        self.assertGreater(len(config['patterns']), 0)

    def test_all_patterns_compile(self):
        config = load_config(Path('config.json'))
        patterns = build_patterns(config['patterns'])
        for original, compiled in patterns:
            self.assertIsInstance(compiled, re.Pattern)

    def test_repo_entries_have_required_fields(self):
        config = load_config(Path('config.json'))
        for repo in config['application_repo']:
            self.assertIn('source_path', repo)
            self.assertIn('replace_path', repo)
            self.assertIn('report_name', repo)


# ===========================================================================
# TestRealisticPage — full integration with exact line numbers
# ===========================================================================

class TestRealisticPage(TempDirMixin, unittest.TestCase):
    """Full-page HTML integration test verifying exact line numbers."""

    DASHBOARD_HTML = (
        '<html>\n'                                              # line 1
        '<head><title>Dashboard</title></head>\n'               # line 2
        '<body>\n'                                              # line 3
        '  <div class="container">\n'                           # line 4
        '    <uui-grid columns="3">\n'                          # line 5
        '      <uui-panel header="Sales">\n'                    # line 6
        '        <p>Content here</p>\n'                         # line 7
        '      </uui-panel>\n'                                  # line 8
        '      <uui-panel header="Revenue">\n'                  # line 9
        '        <uui-button label="Refresh"></uui-button>\n'   # line 10
        '      </uui-panel>\n'                                  # line 11
        '    </uui-grid>\n'                                     # line 12
        '    <div class="footer">\n'                            # line 13
        '      <uui-button label="Save" />\n'                   # line 14
        '    </div>\n'                                          # line 15
        '  </div>\n'                                            # line 16
        '</body>\n'                                             # line 17
        '</html>\n'                                             # line 18
    )

    EXPECTED = [
        (5,  '<uui-grid'),
        (6,  '<uui-panel'),
        (9,  '<uui-panel'),
        (10, '<uui-button'),
        (14, '<uui-button'),
    ]

    def test_scan_file_exact_line_numbers(self):
        """Verify scan_file returns correct line numbers for every match."""
        path = self._create_html('dashboard.component.html', self.DASHBOARD_HTML)
        result = scan_file(path, build_patterns(['<uui-grid', '<uui-panel', '<uui-button']))
        actual = sorted((m.line_num, m.pattern) for m in result.matches)
        self.assertEqual(actual, sorted(self.EXPECTED))

    def test_formatted_report_line_numbers(self):
        """Verify formatted output preserves correct line numbers."""
        path = self._create_html('dashboard.component.html', self.DASHBOARD_HTML)
        result = scan_file(path, build_patterns(['<uui-grid', '<uui-panel', '<uui-button']))
        report = format_report([result], str(self.test_dir) + '/')

        for line_num, pattern in self.EXPECTED:
            self.assertIn(f'Line {line_num}:', report,
                          f'Expected Line {line_num} for pattern {pattern}')

    def test_end_to_end_through_scan_directory(self):
        """Verify the full pipeline from directory scan to report."""
        self._create_html('app/dashboard.component.html', self.DASHBOARD_HTML)
        results = scan_directory(self.test_dir, build_patterns(['<uui-grid', '<uui-panel', '<uui-button']))
        self.assertEqual(len(results), 1)
        actual = sorted((m.line_num, m.pattern) for m in results[0].matches)
        self.assertEqual(actual, sorted(self.EXPECTED))


# ===========================================================================
# TestMainIntegration — end-to-end through main()
# ===========================================================================

class TestMainIntegration(TempDirMixin, unittest.TestCase):
    """End-to-end tests through the main() entry point."""

    def test_missing_config_returns_1(self):
        exit_code = main(['-c', str(self.test_dir / 'nonexistent.json')])
        self.assertEqual(exit_code, 1)

    def test_invalid_json_returns_1(self):
        bad_config = self.test_dir / 'bad.json'
        bad_config.write_text('{not valid json}')
        exit_code = main(['-c', str(bad_config)])
        self.assertEqual(exit_code, 1)

    def test_invalid_config_structure_returns_1(self):
        bad_config = self._create_config({'wrong_key': True})
        exit_code = main(['-c', str(bad_config)])
        self.assertEqual(exit_code, 1)

    def test_successful_scan_returns_0(self):
        self._create_html('src/page.html', '<uui-button>')
        config = {
            'patterns': ['<uui-button'],
            'application_repo': [{
                'source_path': str(self.test_dir / 'src'),
                'replace_path': str(self.test_dir) + '/',
                'report_name': 'test_report',
            }],
        }
        config_path = self._create_config(config)
        output_dir = self.test_dir / 'output'

        exit_code = main(['-c', str(config_path), '-o', str(output_dir)])
        self.assertEqual(exit_code, 0)

        # Verify report was written
        reports = list(output_dir.glob('test_report-*.txt'))
        self.assertEqual(len(reports), 1)
        content = reports[0].read_text()
        self.assertIn('<uui-button', content)

    def test_missing_source_dir_skipped_gracefully(self):
        config = {
            'patterns': ['<uui-button'],
            'application_repo': [{
                'source_path': str(self.test_dir / 'does_not_exist'),
                'replace_path': '/',
                'report_name': 'test',
            }],
        }
        config_path = self._create_config(config)
        exit_code = main(['-c', str(config_path), '-o', str(self.test_dir / 'out')])
        self.assertEqual(exit_code, 0)


# ===========================================================================
# TestDataStructures — frozen dataclass contracts
# ===========================================================================

class TestDataStructures(unittest.TestCase):
    """Tests for immutable data structures."""

    def test_match_result_is_frozen(self):
        m = MatchResult(line_num=1, excerpt='<uui-button', pattern='<uui-button')
        with self.assertRaises(AttributeError):
            m.line_num = 2

    def test_file_result_is_frozen(self):
        r = FileResult(file_path='test.html', matches=())
        with self.assertRaises(AttributeError):
            r.file_path = 'other.html'

    def test_repo_config_is_frozen(self):
        rc = RepoConfig(source_path=Path('/tmp'), replace_path='/', report_name='test')
        with self.assertRaises(AttributeError):
            rc.report_name = 'changed'

    def test_match_result_equality(self):
        a = MatchResult(1, '<uui-button', '<uui-button')
        b = MatchResult(1, '<uui-button', '<uui-button')
        self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
