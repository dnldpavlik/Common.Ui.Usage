"""Tests for Common.Ui.Usage scanner."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from common_ui_usage import (
    NEGATIVE_LOOKAHEAD,
    BehaviorDefinition,
    BreakingChange,
    CompiledPattern,
    ComponentMatch,
    FileResult,
    MatchResult,
    ReleaseInfo,
    RepoConfig,
    ResolvedPage,
    RouteMapping,
    ScanReport,
    build_behavior_index,
    build_pattern,
    build_patterns,
    build_resolved_pages,
    build_scan_report,
    check_breaking_changes,
    enrich_component_match,
    extract_component_name,
    find_behavior_for_tag,
    find_html_files,
    format_file_result,
    format_report,
    group_matches_by_tag,
    load_behavior_file,
    load_behaviors,
    load_config,
    main,
    parse_args,
    parse_definitions_config,
    parse_release_info,
    parse_repo_configs,
    resolve_route,
    scan_directory,
    scan_file,
    scan_line,
    scan_report_to_dict,
    validate_config,
    write_json_report,
    write_report,
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
        config_path = self.test_dir / "config.json"
        config_path.write_text(json.dumps(config))
        return config_path


# ===========================================================================
# TestBuildPattern — single pattern construction
# ===========================================================================


class TestBuildPattern(unittest.TestCase):
    """Tests for build_pattern (single pattern)."""

    def test_tag_pattern_returns_compiled_pattern(self):
        cp = build_pattern("<uui-button")
        self.assertIsInstance(cp, CompiledPattern)
        self.assertEqual(cp.original, "<uui-button")
        self.assertIsInstance(cp.regex, re.Pattern)

    def test_tag_pattern_includes_negative_lookahead(self):
        cp = build_pattern("<uui-button")
        self.assertIn(NEGATIVE_LOOKAHEAD, cp.regex.pattern)

    def test_non_tag_pattern_no_lookahead(self):
        cp = build_pattern("someDirective")
        self.assertNotIn(NEGATIVE_LOOKAHEAD, cp.regex.pattern)

    def test_special_chars_escaped(self):
        cp = build_pattern("<uui-grid")
        self.assertIn(r"\-", cp.regex.pattern)

    def test_tag_matches_opening_tag(self):
        cp = build_pattern("<uui-button")
        self.assertIsNotNone(cp.regex.search('<uui-button label="Save">'))

    def test_tag_does_not_match_extended_name(self):
        """Negative lookahead prevents <uui-button matching <uui-button-extended."""
        cp = build_pattern("<uui-button")
        self.assertIsNone(cp.regex.search("<uui-button-extended>"))


# ===========================================================================
# TestBuildPatterns — batch pattern construction
# ===========================================================================


class TestBuildPatterns(unittest.TestCase):
    """Tests for build_patterns (batch)."""

    def test_builds_correct_count(self):
        patterns = build_patterns(["<uui-grid", "<uui-panel", "someDirective"])
        self.assertEqual(len(patterns), 3)

    def test_preserves_order(self):
        raw = ["<uui-grid", "directive", "<uui-panel"]
        patterns = build_patterns(raw)
        originals = [p.original for p in patterns]
        self.assertEqual(originals, raw)

    def test_empty_list(self):
        self.assertEqual(build_patterns([]), [])


# ===========================================================================
# TestScanLine — pure line scanning, no I/O
# ===========================================================================


class TestScanLine(unittest.TestCase):
    """Tests for scan_line — pure function, no file I/O."""

    def setUp(self):
        self.patterns = build_patterns(["<uui-button", "<uui-grid"])

    def test_no_match_returns_empty(self):
        results = scan_line("<div>hello</div>", 1, self.patterns)
        self.assertEqual(results, [])

    def test_single_match(self):
        results = scan_line('  <uui-button label="go">', 5, self.patterns)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].line_num, 5)
        self.assertEqual(results[0].pattern, "<uui-button")

    def test_multiple_patterns_on_same_line(self):
        results = scan_line("<uui-grid><uui-button>", 1, self.patterns)
        patterns_found = {r.pattern for r in results}
        self.assertEqual(patterns_found, {"<uui-grid", "<uui-button"})

    def test_same_pattern_twice_on_line(self):
        results = scan_line("<uui-button> <uui-button>", 1, self.patterns)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.pattern == "<uui-button" for r in results))

    def test_returns_match_result_instances(self):
        results = scan_line("<uui-button>", 1, self.patterns)
        self.assertIsInstance(results[0], MatchResult)

    def test_excerpt_is_stripped(self):
        results = scan_line("  <uui-button  ", 1, self.patterns)
        self.assertEqual(results[0].excerpt, "<uui-button")

    def test_line_num_passed_through(self):
        for num in [1, 50, 999]:
            results = scan_line("<uui-button>", num, self.patterns)
            self.assertEqual(results[0].line_num, num)


# ===========================================================================
# TestFindHtmlFiles — file discovery
# ===========================================================================


class TestFindHtmlFiles(TempDirMixin, unittest.TestCase):
    """Tests for find_html_files generator."""

    def test_finds_html_files(self):
        self._create_html("app/page.html", "<div>")
        files = list(find_html_files(self.test_dir))
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0].name.endswith(".html"))

    def test_ignores_non_html(self):
        self._create_html("app/page.html", "<div>")
        (self.test_dir / "app" / "script.ts").write_text("code")
        files = list(find_html_files(self.test_dir))
        self.assertEqual(len(files), 1)

    def test_recursive(self):
        self._create_html("a/b/c/deep.html", "<div>")
        files = list(find_html_files(self.test_dir))
        self.assertEqual(len(files), 1)
        self.assertIn("deep.html", str(files[0]))

    def test_empty_directory(self):
        files = list(find_html_files(self.test_dir))
        self.assertEqual(files, [])

    def test_returns_path_objects(self):
        self._create_html("page.html", "<div>")
        files = list(find_html_files(self.test_dir))
        self.assertIsInstance(files[0], Path)


# ===========================================================================
# TestScanFile — single file scanning
# ===========================================================================


class TestScanFile(TempDirMixin, unittest.TestCase):
    """Tests for scan_file."""

    def test_returns_file_result(self):
        path = self._create_html("page.html", "<uui-button>")
        result = scan_file(path, build_patterns(["<uui-button"]))
        self.assertIsInstance(result, FileResult)

    def test_correct_line_numbers(self):
        path = self._create_html("page.html", "line one\nline two\n<uui-button>\n")
        result = scan_file(path, build_patterns(["<uui-button"]))
        self.assertEqual(result.matches[0].line_num, 3)

    def test_multiple_matches(self):
        path = self._create_html("page.html", "<uui-grid>\n<uui-panel>\n")
        result = scan_file(path, build_patterns(["<uui-grid", "<uui-panel"]))
        self.assertEqual(len(result.matches), 2)

    def test_no_matches_returns_empty_tuple(self):
        path = self._create_html("page.html", "<div>nothing</div>")
        result = scan_file(path, build_patterns(["<uui-button"]))
        self.assertEqual(result.matches, ())

    def test_preserves_file_path(self):
        path = self._create_html("app/page.html", "<uui-button>")
        result = scan_file(path, build_patterns(["<uui-button"]))
        self.assertEqual(result.file_path, str(path))

    def test_empty_file(self):
        path = self._create_html("empty.html", "")
        result = scan_file(path, build_patterns(["<uui-button"]))
        self.assertEqual(result.matches, ())

    def test_line_numbers_not_inflated_by_pattern_count(self):
        """Regression: line_num must increment once per line, not per pattern."""
        path = self._create_html("page.html", "line one\n<uui-button>\nline three\n")
        patterns = build_patterns(
            [
                "<uui-button",
                "<uui-grid",
                "<uui-panel",
                "<uui-menu",
                "<uui-tag",
            ]
        )
        result = scan_file(path, patterns)
        self.assertEqual(result.matches[0].line_num, 2)


# ===========================================================================
# TestScanDirectory — directory-level scanning
# ===========================================================================


class TestScanDirectory(TempDirMixin, unittest.TestCase):
    """Tests for scan_directory."""

    def test_finds_matches_across_files(self):
        self._create_html("app/a.html", "<uui-grid>")
        self._create_html("app/b.html", "<uui-panel>")
        results = scan_directory(self.test_dir, build_patterns(["<uui-grid", "<uui-panel"]))
        self.assertEqual(len(results), 2)

    def test_excludes_files_without_matches(self):
        self._create_html("app/match.html", "<uui-grid>")
        self._create_html("app/nope.html", "<div>plain</div>")
        results = scan_directory(self.test_dir, build_patterns(["<uui-grid"]))
        self.assertEqual(len(results), 1)

    def test_recursive_scanning(self):
        self._create_html("a/b/deep.html", "<uui-button>")
        results = scan_directory(self.test_dir, build_patterns(["<uui-button"]))
        self.assertEqual(len(results), 1)

    def test_only_scans_html(self):
        self._create_html("page.html", "<uui-button>")
        (self.test_dir / "script.ts").write_text("'<uui-button>'")
        results = scan_directory(self.test_dir, build_patterns(["<uui-button"]))
        self.assertEqual(len(results), 1)
        self.assertIn("page.html", results[0].file_path)

    def test_empty_directory(self):
        results = scan_directory(self.test_dir, build_patterns(["<uui-button"]))
        self.assertEqual(results, [])


# ===========================================================================
# TestFormatReport — pure formatting
# ===========================================================================


class TestFormatReport(unittest.TestCase):
    """Tests for format_file_result and format_report — pure, no I/O."""

    def test_format_file_result_strips_replace_path(self):
        result = FileResult(
            file_path="/projects/app/src/page.html",
            matches=(MatchResult(1, "<uui-button", "<uui-button"),),
        )
        output = format_file_result(result, "/projects/app/")
        self.assertIn("src/page.html", output)
        self.assertNotIn("/projects/app/", output)

    def test_format_file_result_header_format(self):
        result = FileResult(
            file_path="/app/page.html",
            matches=(MatchResult(1, "<uui-button", "<uui-button"),),
        )
        output = format_file_result(result, "/app/")
        self.assertRegex(output, r"\*\* page\.html \*\*")

    def test_format_file_result_includes_line_numbers(self):
        result = FileResult(
            file_path="page.html",
            matches=(
                MatchResult(3, "<uui-grid", "<uui-grid"),
                MatchResult(7, "<uui-panel", "<uui-panel"),
            ),
        )
        output = format_file_result(result, "")
        self.assertIn("Line 3:", output)
        self.assertIn("Line 7:", output)

    def test_format_file_result_includes_pattern_label(self):
        result = FileResult(
            file_path="page.html",
            matches=(MatchResult(1, "<uui-grid", "<uui-grid"),),
        )
        output = format_file_result(result, "")
        self.assertIn("(Pattern: <uui-grid)", output)

    def test_format_report_empty_results(self):
        self.assertEqual(format_report([], ""), "")

    def test_format_report_single_file(self):
        results = [FileResult("page.html", (MatchResult(1, "<uui-button", "<uui-button"),))]
        output = format_report(results, "")
        self.assertIn("page.html", output)
        self.assertIn("Line 1", output)

    def test_format_report_multiple_files(self):
        results = [
            FileResult("a.html", (MatchResult(1, "<uui-grid", "<uui-grid"),)),
            FileResult("b.html", (MatchResult(2, "<uui-panel", "<uui-panel"),)),
        ]
        output = format_report(results, "")
        self.assertIn("a.html", output)
        self.assertIn("b.html", output)


# ===========================================================================
# TestValidateConfig — config validation
# ===========================================================================


class TestValidateConfig(unittest.TestCase):
    """Tests for validate_config."""

    def test_valid_config_passes(self):
        config = {
            "patterns": ["<uui-button"],
            "application_repo": [
                {"source_path": "/tmp", "replace_path": "/", "report_name": "test"},
            ],
        }
        validate_config(config)  # should not raise

    def test_missing_patterns_key(self):
        with self.assertRaises(ValueError) as ctx:
            validate_config({"application_repo": []})
        self.assertIn("patterns", str(ctx.exception))

    def test_missing_application_repo_key(self):
        with self.assertRaises(ValueError) as ctx:
            validate_config({"patterns": ["<uui-button"]})
        self.assertIn("application_repo", str(ctx.exception))

    def test_empty_patterns_list(self):
        with self.assertRaises(ValueError):
            validate_config({"patterns": [], "application_repo": []})

    def test_patterns_not_a_list(self):
        with self.assertRaises(ValueError):
            validate_config({"patterns": "not-a-list", "application_repo": []})

    def test_repo_missing_source_path(self):
        config = {
            "patterns": ["<uui-button"],
            "application_repo": [{"replace_path": "/", "report_name": "test"}],
        }
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn("source_path", str(ctx.exception))

    def test_repo_missing_replace_path(self):
        config = {
            "patterns": ["<uui-button"],
            "application_repo": [{"source_path": "/tmp", "report_name": "test"}],
        }
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn("replace_path", str(ctx.exception))

    def test_repo_missing_report_name(self):
        config = {
            "patterns": ["<uui-button"],
            "application_repo": [{"source_path": "/tmp", "replace_path": "/"}],
        }
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn("report_name", str(ctx.exception))


# ===========================================================================
# TestParseRepoConfigs — config parsing
# ===========================================================================


class TestParseRepoConfigs(unittest.TestCase):
    """Tests for parse_repo_configs."""

    def test_parses_to_repo_config(self):
        raw = [{"source_path": "/tmp/src", "replace_path": "/tmp/", "report_name": "test"}]
        configs = parse_repo_configs(raw)
        self.assertEqual(len(configs), 1)
        self.assertIsInstance(configs[0], RepoConfig)

    def test_source_path_is_path(self):
        raw = [{"source_path": "/tmp/src", "replace_path": "/tmp/", "report_name": "test"}]
        configs = parse_repo_configs(raw)
        self.assertIsInstance(configs[0].source_path, Path)

    def test_preserves_values(self):
        raw = [{"source_path": "/a/b", "replace_path": "/a/", "report_name": "report"}]
        cfg = parse_repo_configs(raw)[0]
        self.assertEqual(cfg.source_path, Path("/a/b"))
        self.assertEqual(cfg.replace_path, "/a/")
        self.assertEqual(cfg.report_name, "report")


# ===========================================================================
# TestParseArgs — CLI argument parsing
# ===========================================================================


class TestParseArgs(unittest.TestCase):
    """Tests for parse_args."""

    def test_defaults(self):
        args = parse_args([])
        self.assertEqual(args.config, Path("config.json"))
        self.assertEqual(args.output_dir, Path("Reports"))
        self.assertFalse(args.verbose)

    def test_custom_config(self):
        args = parse_args(["-c", "/tmp/my.json"])
        self.assertEqual(args.config, Path("/tmp/my.json"))

    def test_custom_output_dir(self):
        args = parse_args(["-o", "/tmp/output"])
        self.assertEqual(args.output_dir, Path("/tmp/output"))

    def test_verbose_flag(self):
        args = parse_args(["-v"])
        self.assertTrue(args.verbose)

    def test_long_form_args(self):
        args = parse_args(["--config", "c.json", "--output-dir", "out", "--verbose"])
        self.assertEqual(args.config, Path("c.json"))
        self.assertEqual(args.output_dir, Path("out"))
        self.assertTrue(args.verbose)


# ===========================================================================
# TestWriteReport — report file writing
# ===========================================================================


class TestWriteReport(TempDirMixin, unittest.TestCase):
    """Tests for write_report."""

    def test_writes_content(self):
        output = self.test_dir / "report.txt"
        write_report("hello world", output)
        self.assertEqual(output.read_text(), "hello world")

    def test_creates_parent_directories(self):
        output = self.test_dir / "deep" / "nested" / "report.txt"
        write_report("content", output)
        self.assertTrue(output.exists())

    def test_overwrites_existing(self):
        output = self.test_dir / "report.txt"
        write_report("first", output)
        write_report("second", output)
        self.assertEqual(output.read_text(), "second")


# ===========================================================================
# TestPatternMatching — edge cases
# ===========================================================================


class TestPatternMatching(TempDirMixin, unittest.TestCase):
    """Tests for specific pattern matching edge cases."""

    def test_does_not_match_extended_tag_name(self):
        """<uui-menu should not match <uui-menu-item due to negative lookahead."""
        path = self._create_html("test.html", "<uui-menu-item>stuff</uui-menu-item>")
        result = scan_file(path, build_patterns(["<uui-menu"]))
        self.assertEqual(result.matches, ())

    def test_matches_tag_with_space_after(self):
        path = self._create_html("test.html", '<uui-menu class="nav">')
        result = scan_file(path, build_patterns(["<uui-menu"]))
        self.assertEqual(len(result.matches), 1)

    def test_matches_tag_with_closing_bracket(self):
        path = self._create_html("test.html", "<uui-menu>")
        result = scan_file(path, build_patterns(["<uui-menu"]))
        self.assertEqual(len(result.matches), 1)

    def test_matches_self_closing_tag(self):
        path = self._create_html("test.html", '<uui-button label="go" />')
        result = scan_file(path, build_patterns(["<uui-button"]))
        self.assertEqual(len(result.matches), 1)

    def test_non_tag_pattern_matches_anywhere(self):
        path = self._create_html("test.html", '<div uuiDirective="true"></div>')
        result = scan_file(path, build_patterns(["uuiDirective"]))
        self.assertEqual(len(result.matches), 1)


# ===========================================================================
# TestConfigLoading — loads actual config.json
# ===========================================================================


class TestConfigLoading(unittest.TestCase):
    """Tests for loading the real config.json."""

    def test_config_is_valid_json(self):
        config = load_config(Path("config.json"))
        self.assertIsInstance(config, dict)

    def test_config_has_required_keys(self):
        config = load_config(Path("config.json"))
        self.assertIn("patterns", config)
        self.assertIn("application_repo", config)

    def test_patterns_is_nonempty_list(self):
        config = load_config(Path("config.json"))
        self.assertIsInstance(config["patterns"], list)
        self.assertGreater(len(config["patterns"]), 0)

    def test_all_patterns_compile(self):
        config = load_config(Path("config.json"))
        patterns = build_patterns(config["patterns"])
        for cp in patterns:
            self.assertIsInstance(cp, CompiledPattern)
            self.assertIsInstance(cp.regex, re.Pattern)

    def test_repo_entries_have_required_fields(self):
        config = load_config(Path("config.json"))
        for repo in config["application_repo"]:
            self.assertIn("source_path", repo)
            self.assertIn("replace_path", repo)
            self.assertIn("report_name", repo)


# ===========================================================================
# TestRealisticPage — full integration with exact line numbers
# ===========================================================================


class TestRealisticPage(TempDirMixin, unittest.TestCase):
    """Full-page HTML integration test verifying exact line numbers."""

    DASHBOARD_HTML = (
        "<html>\n"  # line 1
        "<head><title>Dashboard</title></head>\n"  # line 2
        "<body>\n"  # line 3
        '  <div class="container">\n'  # line 4
        '    <uui-grid columns="3">\n'  # line 5
        '      <uui-panel header="Sales">\n'  # line 6
        "        <p>Content here</p>\n"  # line 7
        "      </uui-panel>\n"  # line 8
        '      <uui-panel header="Revenue">\n'  # line 9
        '        <uui-button label="Refresh"></uui-button>\n'  # line 10
        "      </uui-panel>\n"  # line 11
        "    </uui-grid>\n"  # line 12
        '    <div class="footer">\n'  # line 13
        '      <uui-button label="Save" />\n'  # line 14
        "    </div>\n"  # line 15
        "  </div>\n"  # line 16
        "</body>\n"  # line 17
        "</html>\n"  # line 18
    )

    EXPECTED = [
        (5, "<uui-grid"),
        (6, "<uui-panel"),
        (9, "<uui-panel"),
        (10, "<uui-button"),
        (14, "<uui-button"),
    ]

    def test_scan_file_exact_line_numbers(self):
        """Verify scan_file returns correct line numbers for every match."""
        path = self._create_html("dashboard.component.html", self.DASHBOARD_HTML)
        result = scan_file(path, build_patterns(["<uui-grid", "<uui-panel", "<uui-button"]))
        actual = sorted((m.line_num, m.pattern) for m in result.matches)
        self.assertEqual(actual, sorted(self.EXPECTED))

    def test_formatted_report_line_numbers(self):
        """Verify formatted output preserves correct line numbers."""
        path = self._create_html("dashboard.component.html", self.DASHBOARD_HTML)
        result = scan_file(path, build_patterns(["<uui-grid", "<uui-panel", "<uui-button"]))
        report = format_report([result], str(self.test_dir) + "/")

        for line_num, pattern in self.EXPECTED:
            self.assertIn(
                f"Line {line_num}:", report, f"Expected Line {line_num} for pattern {pattern}"
            )

    def test_end_to_end_through_scan_directory(self):
        """Verify the full pipeline from directory scan to report."""
        self._create_html("app/dashboard.component.html", self.DASHBOARD_HTML)
        patterns = build_patterns(["<uui-grid", "<uui-panel", "<uui-button"])
        results = scan_directory(self.test_dir, patterns)
        self.assertEqual(len(results), 1)
        actual = sorted((m.line_num, m.pattern) for m in results[0].matches)
        self.assertEqual(actual, sorted(self.EXPECTED))


# ===========================================================================
# TestMainIntegration — end-to-end through main()
# ===========================================================================


class TestMainIntegration(TempDirMixin, unittest.TestCase):
    """End-to-end tests through the main() entry point."""

    def test_missing_config_returns_1(self):
        exit_code = main(["-c", str(self.test_dir / "nonexistent.json")])
        self.assertEqual(exit_code, 1)

    def test_invalid_json_returns_1(self):
        bad_config = self.test_dir / "bad.json"
        bad_config.write_text("{not valid json}")
        exit_code = main(["-c", str(bad_config)])
        self.assertEqual(exit_code, 1)

    def test_invalid_config_structure_returns_1(self):
        bad_config = self._create_config({"wrong_key": True})
        exit_code = main(["-c", str(bad_config)])
        self.assertEqual(exit_code, 1)

    def test_successful_scan_returns_0(self):
        self._create_html("src/page.html", "<uui-button>")
        config = {
            "patterns": ["<uui-button"],
            "application_repo": [
                {
                    "source_path": str(self.test_dir / "src"),
                    "replace_path": str(self.test_dir) + "/",
                    "report_name": "test_report",
                }
            ],
        }
        config_path = self._create_config(config)
        output_dir = self.test_dir / "output"

        exit_code = main(["-c", str(config_path), "-o", str(output_dir)])
        self.assertEqual(exit_code, 0)

        # Verify report was written
        reports = list(output_dir.glob("test_report-*.txt"))
        self.assertEqual(len(reports), 1)
        content = reports[0].read_text()
        self.assertIn("<uui-button", content)

    def test_missing_source_dir_skipped_gracefully(self):
        config = {
            "patterns": ["<uui-button"],
            "application_repo": [
                {
                    "source_path": str(self.test_dir / "does_not_exist"),
                    "replace_path": "/",
                    "report_name": "test",
                }
            ],
        }
        config_path = self._create_config(config)
        exit_code = main(["-c", str(config_path), "-o", str(self.test_dir / "out")])
        self.assertEqual(exit_code, 0)


# ===========================================================================
# TestDataStructures — frozen dataclass contracts
# ===========================================================================


class TestDataStructures(unittest.TestCase):
    """Tests for immutable data structures."""

    def test_match_result_is_frozen(self):
        m = MatchResult(line_num=1, excerpt="<uui-button", pattern="<uui-button")
        with self.assertRaises(AttributeError):
            m.line_num = 2

    def test_file_result_is_frozen(self):
        r = FileResult(file_path="test.html", matches=())
        with self.assertRaises(AttributeError):
            r.file_path = "other.html"

    def test_repo_config_is_frozen(self):
        rc = RepoConfig(source_path=Path("/tmp"), replace_path="/", report_name="test")
        with self.assertRaises(AttributeError):
            rc.report_name = "changed"

    def test_match_result_equality(self):
        a = MatchResult(1, "<uui-button", "<uui-button")
        b = MatchResult(1, "<uui-button", "<uui-button")
        self.assertEqual(a, b)


# ===========================================================================
# TestRouteMapping — route resolution
# ===========================================================================


class TestRouteResolution(unittest.TestCase):
    """Tests for resolve_route — pure function, no I/O."""

    def test_matches_glob_pattern(self):
        route_map = (RouteMapping("app/dashboard/**", "/dashboard", "Dashboard"),)
        route, name = resolve_route(
            "/projects/src/app/dashboard/page.html", "/projects/src/", route_map
        )
        self.assertEqual(route, "/dashboard")
        self.assertEqual(name, "Dashboard")

    def test_no_match_returns_none(self):
        route_map = (RouteMapping("app/dashboard/**", "/dashboard", "Dashboard"),)
        route, name = resolve_route(
            "/projects/src/app/settings/page.html", "/projects/src/", route_map
        )
        self.assertIsNone(route)
        self.assertIsNone(name)

    def test_empty_route_map(self):
        route, name = resolve_route("/projects/src/app/page.html", "/projects/src/", ())
        self.assertIsNone(route)
        self.assertIsNone(name)

    def test_first_match_wins(self):
        route_map = (
            RouteMapping("app/dashboard/**", "/dashboard", "Dashboard"),
            RouteMapping("app/**", "/app", "App"),
        )
        route, name = resolve_route(
            "/projects/src/app/dashboard/page.html", "/projects/src/", route_map
        )
        self.assertEqual(route, "/dashboard")
        self.assertEqual(name, "Dashboard")

    def test_exact_file_pattern(self):
        route_map = (RouteMapping("app/home.component.html", "/home", "Home"),)
        route, name = resolve_route("/src/app/home.component.html", "/src/", route_map)
        self.assertEqual(route, "/home")
        self.assertEqual(name, "Home")


# ===========================================================================
# TestGroupMatchesByTag — match grouping
# ===========================================================================


class TestGroupMatchesByTag(unittest.TestCase):
    """Tests for group_matches_by_tag — pure function."""

    def test_groups_by_pattern(self):
        matches = (
            MatchResult(5, "<uui-grid", "<uui-grid"),
            MatchResult(10, "<uui-grid", "<uui-grid"),
            MatchResult(7, "<uui-panel", "<uui-panel"),
        )
        components = group_matches_by_tag(matches)
        tags = {c.tag for c in components}
        self.assertEqual(tags, {"<uui-grid", "<uui-panel"})

    def test_collects_line_numbers(self):
        matches = (
            MatchResult(5, "<uui-grid", "<uui-grid"),
            MatchResult(12, "<uui-grid", "<uui-grid"),
        )
        components = group_matches_by_tag(matches)
        self.assertEqual(components[0].lines, (5, 12))

    def test_empty_matches(self):
        self.assertEqual(group_matches_by_tag(()), ())

    def test_single_match(self):
        matches = (MatchResult(1, "<uui-button", "<uui-button"),)
        components = group_matches_by_tag(matches)
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].tag, "<uui-button")
        self.assertEqual(components[0].lines, (1,))


# ===========================================================================
# TestBuildResolvedPages — structured page building
# ===========================================================================


class TestBuildResolvedPages(unittest.TestCase):
    """Tests for build_resolved_pages — pure function."""

    def test_groups_matches_by_tag(self):
        results = [
            FileResult(
                "/src/app/page.html",
                (
                    MatchResult(5, "<uui-grid", "<uui-grid"),
                    MatchResult(10, "<uui-grid", "<uui-grid"),
                    MatchResult(7, "<uui-panel", "<uui-panel"),
                ),
            )
        ]
        pages = build_resolved_pages(results, "/src/", ())
        self.assertEqual(len(pages), 1)
        page = pages[0]
        tags = {c.tag for c in page.components}
        self.assertEqual(tags, {"<uui-grid", "<uui-panel"})

    def test_groups_lines_correctly(self):
        results = [
            FileResult(
                "/src/page.html",
                (
                    MatchResult(5, "<uui-grid", "<uui-grid"),
                    MatchResult(12, "<uui-grid", "<uui-grid"),
                ),
            )
        ]
        pages = build_resolved_pages(results, "/src/", ())
        grid = next(c for c in pages[0].components if c.tag == "<uui-grid")
        self.assertEqual(grid.lines, (5, 12))

    def test_strips_replace_path(self):
        results = [FileResult("/projects/src/app/page.html", (MatchResult(1, "x", "x"),))]
        pages = build_resolved_pages(results, "/projects/src/", ())
        self.assertEqual(pages[0].file_path, "app/page.html")

    def test_resolves_route(self):
        route_map = (RouteMapping("app/dashboard/**", "/dashboard", "Dashboard"),)
        results = [
            FileResult(
                "/src/app/dashboard/page.html",
                (MatchResult(1, "<uui-grid", "<uui-grid"),),
            )
        ]
        pages = build_resolved_pages(results, "/src/", route_map)
        self.assertEqual(pages[0].route, "/dashboard")
        self.assertEqual(pages[0].page_name, "Dashboard")

    def test_no_route_match(self):
        results = [FileResult("/src/app/page.html", (MatchResult(1, "x", "x"),))]
        pages = build_resolved_pages(results, "/src/", ())
        self.assertIsNone(pages[0].route)
        self.assertIsNone(pages[0].page_name)


# ===========================================================================
# TestBuildScanReport — full report building
# ===========================================================================


class TestBuildScanReport(unittest.TestCase):
    """Tests for build_scan_report — pure function."""

    def test_builds_report_structure(self):
        repo = RepoConfig(
            source_path=Path("/src"),
            replace_path="/src/",
            report_name="TestApp",
            base_url="https://test.example.com",
        )
        results = [FileResult("/src/page.html", (MatchResult(1, "<uui-grid", "<uui-grid"),))]
        report = build_scan_report(repo=repo, scan_date="02-15-2026", release=None, results=results)
        self.assertEqual(report.application, "TestApp")
        self.assertEqual(report.base_url, "https://test.example.com")
        self.assertEqual(report.scan_date, "02-15-2026")
        self.assertIsNone(report.release)
        self.assertEqual(len(report.pages), 1)

    def test_includes_release_info(self):
        repo = RepoConfig(source_path=Path("/tmp"), replace_path="", report_name="App")
        release = ReleaseInfo("2.4.0", ("uui-grid",), "2026-02-14")
        report = build_scan_report(repo=repo, scan_date="02-15-2026", release=release, results=[])
        self.assertIsNotNone(report.release)
        self.assertEqual(report.release.version, "2.4.0")

    def test_empty_results_produces_empty_pages(self):
        repo = RepoConfig(source_path=Path("/tmp"), replace_path="", report_name="App")
        report = build_scan_report(repo=repo, scan_date="02-15-2026", release=None, results=[])
        self.assertEqual(report.pages, ())


# ===========================================================================
# TestScanReportToDict — JSON serialization
# ===========================================================================


class TestScanReportToDict(unittest.TestCase):
    """Tests for scan_report_to_dict."""

    def test_produces_dict(self):
        report = ScanReport(
            application="App",
            base_url=None,
            scan_date="02-15-2026",
            release=None,
            pages=(),
        )
        d = scan_report_to_dict(report)
        self.assertIsInstance(d, dict)
        self.assertEqual(d["application"], "App")
        self.assertIsNone(d["base_url"])
        self.assertEqual(d["pages"], [])

    def test_serializes_nested_structures(self):
        report = ScanReport(
            application="App",
            base_url="https://example.com",
            scan_date="02-15-2026",
            release=ReleaseInfo("1.0.0", ("uui-grid",), "2026-01-01"),
            pages=(
                ResolvedPage(
                    file_path="app/page.html",
                    route="/home",
                    page_name="Home",
                    components=(ComponentMatch(tag="<uui-grid", lines=(5, 10)),),
                ),
            ),
        )
        d = scan_report_to_dict(report)
        self.assertEqual(d["release"]["version"], "1.0.0")
        self.assertEqual(len(d["pages"]), 1)
        self.assertEqual(d["pages"][0]["route"], "/home")
        self.assertEqual(d["pages"][0]["components"][0]["tag"], "<uui-grid")
        self.assertEqual(d["pages"][0]["components"][0]["lines"], [5, 10])

    def test_round_trips_through_json(self):
        report = ScanReport(
            application="App",
            base_url=None,
            scan_date="02-15-2026",
            release=None,
            pages=(
                ResolvedPage(
                    file_path="page.html",
                    route=None,
                    page_name=None,
                    components=(ComponentMatch(tag="<uui-button", lines=(1,)),),
                ),
            ),
        )
        d = scan_report_to_dict(report)
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["application"], "App")
        self.assertEqual(parsed["pages"][0]["components"][0]["tag"], "<uui-button")


# ===========================================================================
# TestExtendedConfigValidation — new optional config fields
# ===========================================================================


class TestExtendedConfigValidation(unittest.TestCase):
    """Tests for extended config validation with optional fields."""

    def _base_config(self):
        return {
            "patterns": ["<uui-button"],
            "application_repo": [
                {"source_path": "/tmp", "replace_path": "/", "report_name": "test"},
            ],
        }

    def test_config_with_release_passes(self):
        config = self._base_config()
        config["release"] = {
            "version": "2.4.0",
            "affected_components": ["uui-grid"],
            "date": "2026-02-14",
        }
        validate_config(config)  # should not raise

    def test_release_missing_version_fails(self):
        config = self._base_config()
        config["release"] = {"affected_components": [], "date": "2026-02-14"}
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn("version", str(ctx.exception))

    def test_release_not_a_dict_fails(self):
        config = self._base_config()
        config["release"] = "not-a-dict"
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn("release", str(ctx.exception))

    def test_config_with_base_url_passes(self):
        config = self._base_config()
        config["application_repo"][0]["base_url"] = "https://example.com"
        validate_config(config)  # should not raise

    def test_base_url_not_a_string_fails(self):
        config = self._base_config()
        config["application_repo"][0]["base_url"] = 123
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn("base_url", str(ctx.exception))

    def test_config_with_route_map_passes(self):
        config = self._base_config()
        config["application_repo"][0]["route_map"] = [
            {"path_pattern": "app/**", "route": "/home", "name": "Home"},
        ]
        validate_config(config)  # should not raise

    def test_route_map_not_a_list_fails(self):
        config = self._base_config()
        config["application_repo"][0]["route_map"] = "not-a-list"
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn("route_map", str(ctx.exception))

    def test_route_map_entry_missing_key_fails(self):
        config = self._base_config()
        config["application_repo"][0]["route_map"] = [
            {"path_pattern": "app/**", "route": "/home"},  # missing 'name'
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn("name", str(ctx.exception))


# ===========================================================================
# TestParseReleaseInfo — release info parsing
# ===========================================================================


class TestParseReleaseInfo(unittest.TestCase):
    """Tests for parse_release_info."""

    def test_returns_none_when_absent(self):
        self.assertIsNone(parse_release_info({"patterns": []}))

    def test_parses_release_info(self):
        config = {
            "release": {
                "version": "2.4.0",
                "affected_components": ["uui-grid", "uui-panel"],
                "date": "2026-02-14",
            }
        }
        release = parse_release_info(config)
        self.assertIsNotNone(release)
        self.assertEqual(release.version, "2.4.0")
        self.assertEqual(release.affected_components, ("uui-grid", "uui-panel"))
        self.assertEqual(release.release_date, "2026-02-14")

    def test_returns_release_info_type(self):
        config = {"release": {"version": "1.0.0", "affected_components": [], "date": "2026-01-01"}}
        release = parse_release_info(config)
        self.assertIsInstance(release, ReleaseInfo)


# ===========================================================================
# TestExtendedParseRepoConfigs — route_map and base_url parsing
# ===========================================================================


class TestExtendedParseRepoConfigs(unittest.TestCase):
    """Tests for parse_repo_configs with extended fields."""

    def test_parses_base_url(self):
        raw = [
            {
                "source_path": "/tmp",
                "replace_path": "/",
                "report_name": "test",
                "base_url": "https://example.com",
            }
        ]
        configs = parse_repo_configs(raw)
        self.assertEqual(configs[0].base_url, "https://example.com")

    def test_base_url_defaults_to_none(self):
        raw = [{"source_path": "/tmp", "replace_path": "/", "report_name": "test"}]
        configs = parse_repo_configs(raw)
        self.assertIsNone(configs[0].base_url)

    def test_parses_route_map(self):
        raw = [
            {
                "source_path": "/tmp",
                "replace_path": "/",
                "report_name": "test",
                "route_map": [
                    {"path_pattern": "app/**", "route": "/home", "name": "Home"},
                ],
            }
        ]
        configs = parse_repo_configs(raw)
        self.assertEqual(len(configs[0].route_map), 1)
        self.assertIsInstance(configs[0].route_map[0], RouteMapping)
        self.assertEqual(configs[0].route_map[0].path_pattern, "app/**")

    def test_route_map_defaults_to_empty(self):
        raw = [{"source_path": "/tmp", "replace_path": "/", "report_name": "test"}]
        configs = parse_repo_configs(raw)
        self.assertEqual(configs[0].route_map, ())


# ===========================================================================
# TestWriteJsonReport — JSON report writing
# ===========================================================================


class TestWriteJsonReport(TempDirMixin, unittest.TestCase):
    """Tests for write_json_report."""

    def test_writes_valid_json(self):
        report = ScanReport(
            application="App",
            base_url=None,
            scan_date="02-15-2026",
            release=None,
            pages=(),
        )
        output = self.test_dir / "report.json"
        write_json_report(report, output)
        data = json.loads(output.read_text())
        self.assertEqual(data["application"], "App")

    def test_creates_parent_directories(self):
        report = ScanReport("App", None, "02-15-2026", None, ())
        output = self.test_dir / "deep" / "nested" / "report.json"
        write_json_report(report, output)
        self.assertTrue(output.exists())

    def test_includes_nested_data(self):
        report = ScanReport(
            application="App",
            base_url="https://example.com",
            scan_date="02-15-2026",
            release=ReleaseInfo("1.0.0", ("uui-grid",), "2026-01-01"),
            pages=(
                ResolvedPage(
                    file_path="page.html",
                    route="/home",
                    page_name="Home",
                    components=(ComponentMatch("<uui-grid", (5, 10)),),
                ),
            ),
        )
        output = self.test_dir / "report.json"
        write_json_report(report, output)
        data = json.loads(output.read_text())
        self.assertEqual(data["release"]["version"], "1.0.0")
        self.assertEqual(data["pages"][0]["route"], "/home")
        self.assertEqual(data["pages"][0]["components"][0]["lines"], [5, 10])


# ===========================================================================
# TestMainIntegrationJsonOutput — JSON output from main()
# ===========================================================================


class TestMainIntegrationJsonOutput(TempDirMixin, unittest.TestCase):
    """Tests for JSON output generated by main()."""

    def test_produces_json_alongside_txt(self):
        self._create_html("src/page.html", "<uui-button>")
        config = {
            "patterns": ["<uui-button"],
            "application_repo": [
                {
                    "source_path": str(self.test_dir / "src"),
                    "replace_path": str(self.test_dir) + "/",
                    "report_name": "test_report",
                }
            ],
        }
        config_path = self._create_config(config)
        output_dir = self.test_dir / "output"

        exit_code = main(["-c", str(config_path), "-o", str(output_dir)])
        self.assertEqual(exit_code, 0)

        txt_reports = list(output_dir.glob("test_report-*.txt"))
        json_reports = list(output_dir.glob("test_report-*.json"))
        self.assertEqual(len(txt_reports), 1)
        self.assertEqual(len(json_reports), 1)

    def test_json_report_has_correct_structure(self):
        self._create_html("src/page.html", '<uui-grid columns="3">')
        config = {
            "patterns": ["<uui-grid"],
            "application_repo": [
                {
                    "source_path": str(self.test_dir / "src"),
                    "replace_path": str(self.test_dir) + "/",
                    "report_name": "json_test",
                }
            ],
        }
        config_path = self._create_config(config)
        output_dir = self.test_dir / "output"

        main(["-c", str(config_path), "-o", str(output_dir)])

        json_file = next(iter(output_dir.glob("json_test-*.json")))
        data = json.loads(json_file.read_text())
        self.assertEqual(data["application"], "json_test")
        self.assertEqual(len(data["pages"]), 1)
        self.assertEqual(data["pages"][0]["components"][0]["tag"], "<uui-grid")

    def test_json_report_with_route_map(self):
        self._create_html("src/app/dashboard/page.html", "<uui-panel>")
        config = {
            "patterns": ["<uui-panel"],
            "application_repo": [
                {
                    "source_path": str(self.test_dir / "src"),
                    "replace_path": str(self.test_dir) + "/",
                    "report_name": "route_test",
                    "base_url": "https://staging.example.com",
                    "route_map": [
                        {
                            "path_pattern": "src/app/dashboard/**",
                            "route": "/dashboard",
                            "name": "Dashboard",
                        }
                    ],
                }
            ],
        }
        config_path = self._create_config(config)
        output_dir = self.test_dir / "output"

        main(["-c", str(config_path), "-o", str(output_dir)])

        json_file = next(iter(output_dir.glob("route_test-*.json")))
        data = json.loads(json_file.read_text())
        self.assertEqual(data["base_url"], "https://staging.example.com")
        page = data["pages"][0]
        self.assertEqual(page["route"], "/dashboard")
        self.assertEqual(page["page_name"], "Dashboard")

    def test_json_report_with_release_info(self):
        self._create_html("src/page.html", "<uui-button>")
        config = {
            "patterns": ["<uui-button"],
            "release": {
                "version": "2.4.0",
                "affected_components": ["uui-button"],
                "date": "2026-02-14",
            },
            "application_repo": [
                {
                    "source_path": str(self.test_dir / "src"),
                    "replace_path": str(self.test_dir) + "/",
                    "report_name": "release_test",
                }
            ],
        }
        config_path = self._create_config(config)
        output_dir = self.test_dir / "output"

        main(["-c", str(config_path), "-o", str(output_dir)])

        json_file = next(iter(output_dir.glob("release_test-*.json")))
        data = json.loads(json_file.read_text())
        self.assertEqual(data["release"]["version"], "2.4.0")
        self.assertEqual(data["release"]["affected_components"], ["uui-button"])


# ===========================================================================
# TestNewDataStructures — new frozen dataclass contracts
# ===========================================================================


class TestNewDataStructures(unittest.TestCase):
    """Tests for new immutable data structures."""

    def test_compiled_pattern_is_frozen(self):
        cp = build_pattern("<uui-button")
        with self.assertRaises(AttributeError):
            cp.original = "other"

    def test_route_mapping_is_frozen(self):
        rm = RouteMapping(path_pattern="app/**", route="/home", name="Home")
        with self.assertRaises(AttributeError):
            rm.route = "/other"

    def test_component_match_is_frozen(self):
        cm = ComponentMatch(tag="<uui-grid", lines=(5, 10))
        with self.assertRaises(AttributeError):
            cm.tag = "other"

    def test_resolved_page_is_frozen(self):
        rp = ResolvedPage(file_path="page.html", route="/", page_name="Page", components=())
        with self.assertRaises(AttributeError):
            rp.route = "/other"

    def test_release_info_is_frozen(self):
        ri = ReleaseInfo(version="1.0.0", affected_components=(), release_date="2026-01-01")
        with self.assertRaises(AttributeError):
            ri.version = "2.0.0"

    def test_scan_report_is_frozen(self):
        sr = ScanReport(application="App", base_url=None, scan_date="", release=None, pages=())
        with self.assertRaises(AttributeError):
            sr.application = "Other"

    def test_route_mapping_equality(self):
        a = RouteMapping("app/**", "/home", "Home")
        b = RouteMapping("app/**", "/home", "Home")
        self.assertEqual(a, b)

    def test_component_match_equality(self):
        a = ComponentMatch("<uui-grid", (5,))
        b = ComponentMatch("<uui-grid", (5,))
        self.assertEqual(a, b)


# ===========================================================================
# TestBreakingChangeDataclass — frozen dataclass contracts
# ===========================================================================


class TestBreakingChangeDataclass(unittest.TestCase):
    """Tests for BreakingChange frozen dataclass."""

    def test_is_frozen(self):
        bc = BreakingChange(version="2.0.0", description="Removed input X")
        with self.assertRaises(AttributeError):
            bc.version = "3.0.0"

    def test_equality(self):
        a = BreakingChange("2.0.0", "Removed input X")
        b = BreakingChange("2.0.0", "Removed input X")
        self.assertEqual(a, b)


# ===========================================================================
# TestBehaviorDefinitionDataclass — frozen dataclass contracts
# ===========================================================================


class TestBehaviorDefinitionDataclass(unittest.TestCase):
    """Tests for BehaviorDefinition frozen dataclass."""

    def test_is_frozen(self):
        bd = BehaviorDefinition(
            component="uui-button",
            version="1.0.0",
            tag="<uui-button>",
            filename="uui-button.behavior.json",
            breaking_changes=(),
        )
        with self.assertRaises(AttributeError):
            bd.component = "other"

    def test_equality(self):
        a = BehaviorDefinition("uui-button", "1.0.0", "<uui-button>", "f.json", ())
        b = BehaviorDefinition("uui-button", "1.0.0", "<uui-button>", "f.json", ())
        self.assertEqual(a, b)

    def test_fields(self):
        bd = BehaviorDefinition(
            component="uui-grid",
            version="2.0.0",
            tag="<uui-grid>",
            filename="uui-grid.behavior.json",
            breaking_changes=(BreakingChange("2.0.0", "Changed API"),),
        )
        self.assertEqual(bd.component, "uui-grid")
        self.assertEqual(bd.version, "2.0.0")
        self.assertEqual(bd.tag, "<uui-grid>")
        self.assertEqual(bd.filename, "uui-grid.behavior.json")
        self.assertEqual(len(bd.breaking_changes), 1)


# ===========================================================================
# TestExtractComponentName — tag stripping
# ===========================================================================


class TestExtractComponentName(unittest.TestCase):
    """Tests for extract_component_name."""

    def test_strips_leading_angle_bracket(self):
        self.assertEqual(extract_component_name("<uui-button"), "uui-button")

    def test_strips_leading_bracket_with_closing(self):
        self.assertEqual(extract_component_name("<uui-grid"), "uui-grid")

    def test_non_tag_passthrough(self):
        self.assertEqual(extract_component_name("someDirective"), "someDirective")

    def test_empty_string(self):
        self.assertEqual(extract_component_name(""), "")


# ===========================================================================
# TestLoadBehaviorFile — single file loading
# ===========================================================================


class TestLoadBehaviorFile(TempDirMixin, unittest.TestCase):
    """Tests for load_behavior_file."""

    def _create_behavior(self, filename: str, data: dict) -> Path:
        path = self.test_dir / filename
        path.write_text(json.dumps(data))
        return path

    def test_loads_valid_file(self):
        path = self._create_behavior(
            "uui-button.behavior.json",
            {
                "component": "uui-button",
                "version": "1.0.0",
                "tag": "<uui-button>",
                "breaking_changes": [],
            },
        )
        bd = load_behavior_file(path)
        self.assertEqual(bd.component, "uui-button")
        self.assertEqual(bd.version, "1.0.0")
        self.assertEqual(bd.tag, "<uui-button>")

    def test_captures_filename(self):
        path = self._create_behavior(
            "uui-grid.behavior.json",
            {
                "component": "uui-grid",
                "version": "2.0.0",
                "tag": "<uui-grid>",
                "breaking_changes": [],
            },
        )
        bd = load_behavior_file(path)
        self.assertEqual(bd.filename, "uui-grid.behavior.json")

    def test_parses_breaking_changes(self):
        path = self._create_behavior(
            "uui-panel.behavior.json",
            {
                "component": "uui-panel",
                "version": "2.0.0",
                "tag": "<uui-panel>",
                "breaking_changes": [
                    {"version": "2.0.0", "description": "Removed header input"},
                    {"version": "3.0.0", "description": "Changed API"},
                ],
            },
        )
        bd = load_behavior_file(path)
        self.assertEqual(len(bd.breaking_changes), 2)
        self.assertEqual(bd.breaking_changes[0].version, "2.0.0")
        self.assertEqual(bd.breaking_changes[0].description, "Removed header input")


# ===========================================================================
# TestLoadBehaviors — directory loading
# ===========================================================================


class TestLoadBehaviors(TempDirMixin, unittest.TestCase):
    """Tests for load_behaviors."""

    def _create_behavior(self, filename: str, data: dict) -> Path:
        path = self.test_dir / filename
        path.write_text(json.dumps(data))
        return path

    def test_loads_from_directory(self):
        self._create_behavior(
            "uui-button.behavior.json",
            {"component": "uui-button", "version": "1.0.0", "tag": "<uui-button>"},
        )
        self._create_behavior(
            "uui-grid.behavior.json",
            {"component": "uui-grid", "version": "1.0.0", "tag": "<uui-grid>"},
        )
        behaviors = load_behaviors(self.test_dir, "*.behavior.json")
        self.assertEqual(len(behaviors), 2)

    def test_glob_filtering(self):
        self._create_behavior(
            "uui-button.behavior.json",
            {"component": "uui-button", "version": "1.0.0", "tag": "<uui-button>"},
        )
        (self.test_dir / "other.json").write_text("{}")
        behaviors = load_behaviors(self.test_dir, "*.behavior.json")
        self.assertEqual(len(behaviors), 1)

    def test_empty_directory(self):
        behaviors = load_behaviors(self.test_dir, "*.behavior.json")
        self.assertEqual(behaviors, ())

    def test_missing_directory(self):
        behaviors = load_behaviors(self.test_dir / "nonexistent", "*.behavior.json")
        self.assertEqual(behaviors, ())


# ===========================================================================
# TestBuildBehaviorIndex — index building
# ===========================================================================


class TestBuildBehaviorIndex(unittest.TestCase):
    """Tests for build_behavior_index."""

    def test_indexes_by_component(self):
        behaviors = (
            BehaviorDefinition("uui-button", "1.0.0", "<uui-button>", "f1.json", ()),
            BehaviorDefinition("uui-grid", "1.0.0", "<uui-grid>", "f2.json", ()),
        )
        index = build_behavior_index(behaviors)
        self.assertIn("uui-button", index)
        self.assertIn("uui-grid", index)
        self.assertEqual(index["uui-button"].filename, "f1.json")

    def test_empty_input(self):
        index = build_behavior_index(())
        self.assertEqual(index, {})

    def test_last_wins_on_duplicate(self):
        behaviors = (
            BehaviorDefinition("uui-button", "1.0.0", "<uui-button>", "old.json", ()),
            BehaviorDefinition("uui-button", "2.0.0", "<uui-button>", "new.json", ()),
        )
        index = build_behavior_index(behaviors)
        self.assertEqual(index["uui-button"].filename, "new.json")


# ===========================================================================
# TestFindBehaviorForTag — tag lookup
# ===========================================================================


class TestFindBehaviorForTag(unittest.TestCase):
    """Tests for find_behavior_for_tag."""

    def setUp(self):
        self.bd = BehaviorDefinition("uui-button", "1.0.0", "<uui-button>", "f.json", ())
        self.index = {"uui-button": self.bd}

    def test_match(self):
        result = find_behavior_for_tag("<uui-button", self.index)
        self.assertEqual(result, self.bd)

    def test_no_match(self):
        result = find_behavior_for_tag("<uui-grid", self.index)
        self.assertIsNone(result)

    def test_non_tag_pattern(self):
        index = {"someDirective": self.bd}
        result = find_behavior_for_tag("someDirective", index)
        self.assertEqual(result, self.bd)

    def test_empty_index(self):
        result = find_behavior_for_tag("<uui-button", {})
        self.assertIsNone(result)


# ===========================================================================
# TestCheckBreakingChanges — breaking change detection
# ===========================================================================


class TestCheckBreakingChanges(unittest.TestCase):
    """Tests for check_breaking_changes."""

    def test_no_breaking_changes(self):
        bd = BehaviorDefinition("uui-button", "1.0.0", "<uui-button>", "f.json", ())
        has, desc = check_breaking_changes(bd, "2.0.0")
        self.assertFalse(has)
        self.assertIsNone(desc)

    def test_version_match(self):
        bd = BehaviorDefinition(
            "uui-button",
            "1.0.0",
            "<uui-button>",
            "f.json",
            (BreakingChange("2.0.0", "Removed input X"),),
        )
        has, desc = check_breaking_changes(bd, "2.0.0")
        self.assertTrue(has)
        self.assertEqual(desc, "Removed input X")

    def test_version_mismatch(self):
        bd = BehaviorDefinition(
            "uui-button",
            "1.0.0",
            "<uui-button>",
            "f.json",
            (BreakingChange("3.0.0", "Changed API"),),
        )
        has, desc = check_breaking_changes(bd, "2.0.0")
        self.assertFalse(has)
        self.assertIsNone(desc)

    def test_none_version(self):
        bd = BehaviorDefinition(
            "uui-button",
            "1.0.0",
            "<uui-button>",
            "f.json",
            (BreakingChange("2.0.0", "Removed input X"),),
        )
        has, desc = check_breaking_changes(bd, None)
        self.assertFalse(has)
        self.assertIsNone(desc)


# ===========================================================================
# TestEnrichComponentMatch — component enrichment
# ===========================================================================


class TestEnrichComponentMatch(unittest.TestCase):
    """Tests for enrich_component_match."""

    def test_with_behavior_no_breaking(self):
        bd = BehaviorDefinition("uui-button", "1.0.0", "<uui-button>", "f.json", ())
        index = {"uui-button": bd}
        cm = ComponentMatch(tag="<uui-button", lines=(5, 10))
        enriched = enrich_component_match(cm, index, None)
        self.assertEqual(enriched.behavior_definition, "f.json")
        self.assertFalse(enriched.has_breaking_changes)
        self.assertIsNone(enriched.breaking_change)

    def test_with_breaking_change(self):
        bd = BehaviorDefinition(
            "uui-button",
            "1.0.0",
            "<uui-button>",
            "f.json",
            (BreakingChange("2.0.0", "Removed input X"),),
        )
        index = {"uui-button": bd}
        cm = ComponentMatch(tag="<uui-button", lines=(5,))
        enriched = enrich_component_match(cm, index, "2.0.0")
        self.assertTrue(enriched.has_breaking_changes)
        self.assertEqual(enriched.breaking_change, "Removed input X")

    def test_without_behavior(self):
        cm = ComponentMatch(tag="<uui-unknown", lines=(1,))
        enriched = enrich_component_match(cm, {}, None)
        self.assertIsNone(enriched.behavior_definition)
        self.assertFalse(enriched.has_breaking_changes)

    def test_preserves_lines(self):
        bd = BehaviorDefinition("uui-grid", "1.0.0", "<uui-grid>", "g.json", ())
        index = {"uui-grid": bd}
        cm = ComponentMatch(tag="<uui-grid", lines=(3, 7, 15))
        enriched = enrich_component_match(cm, index, None)
        self.assertEqual(enriched.lines, (3, 7, 15))
        self.assertEqual(enriched.tag, "<uui-grid")


# ===========================================================================
# TestDefinitionsConfigValidation — definitions config validation
# ===========================================================================


class TestDefinitionsConfigValidation(unittest.TestCase):
    """Tests for definitions config validation in validate_config."""

    def _base_config(self):
        return {
            "patterns": ["<uui-button"],
            "application_repo": [
                {"source_path": "/tmp", "replace_path": "/", "report_name": "test"},
            ],
        }

    def test_valid_definitions_config(self):
        config = self._base_config()
        config["definitions_path"] = "behaviors"
        config["definitions_glob"] = "*.behavior.json"
        validate_config(config)  # should not raise

    def test_definitions_path_not_string_fails(self):
        config = self._base_config()
        config["definitions_path"] = 123
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn("definitions_path", str(ctx.exception))

    def test_definitions_glob_not_string_fails(self):
        config = self._base_config()
        config["definitions_glob"] = 456
        with self.assertRaises(ValueError) as ctx:
            validate_config(config)
        self.assertIn("definitions_glob", str(ctx.exception))

    def test_absent_definitions_fields_ok(self):
        config = self._base_config()
        validate_config(config)  # should not raise


# ===========================================================================
# TestParseDefinitionsConfig — definitions config parsing
# ===========================================================================


class TestParseDefinitionsConfig(unittest.TestCase):
    """Tests for parse_definitions_config."""

    def test_present(self):
        config = {"definitions_path": "behaviors", "definitions_glob": "*.test.json"}
        path, glob = parse_definitions_config(config)
        self.assertEqual(path, Path("behaviors"))
        self.assertEqual(glob, "*.test.json")

    def test_absent(self):
        path, glob = parse_definitions_config({})
        self.assertIsNone(path)
        self.assertEqual(glob, "*.behavior.json")

    def test_defaults_glob_when_only_path(self):
        config = {"definitions_path": "defs"}
        path, glob = parse_definitions_config(config)
        self.assertEqual(path, Path("defs"))
        self.assertEqual(glob, "*.behavior.json")


# ===========================================================================
# TestBehaviorIntegration — end-to-end with behaviors
# ===========================================================================


class TestBehaviorIntegration(TempDirMixin, unittest.TestCase):
    """End-to-end tests for behavior integration in JSON output."""

    def _create_behavior(self, filename: str, data: dict) -> Path:
        behaviors_dir = self.test_dir / "behaviors"
        behaviors_dir.mkdir(exist_ok=True)
        path = behaviors_dir / filename
        path.write_text(json.dumps(data))
        return path

    def test_json_output_includes_behavior_definition(self):
        self._create_html("src/page.html", "<uui-general-button>")
        self._create_behavior(
            "uui-general-button.behavior.json",
            {
                "component": "uui-general-button",
                "version": "21.5.1",
                "tag": "<uui-general-button>",
                "breaking_changes": [],
            },
        )
        config = {
            "patterns": ["<uui-general-button"],
            "definitions_path": "behaviors",
            "definitions_glob": "*.behavior.json",
            "application_repo": [
                {
                    "source_path": str(self.test_dir / "src"),
                    "replace_path": str(self.test_dir) + "/",
                    "report_name": "behavior_test",
                }
            ],
        }
        config_path = self._create_config(config)
        output_dir = self.test_dir / "output"

        exit_code = main(["-c", str(config_path), "-o", str(output_dir)])
        self.assertEqual(exit_code, 0)

        json_file = next(iter(output_dir.glob("behavior_test-*.json")))
        data = json.loads(json_file.read_text())
        component = data["pages"][0]["components"][0]
        self.assertEqual(component["behavior_definition"], "uui-general-button.behavior.json")
        self.assertFalse(component["has_breaking_changes"])
        self.assertIsNone(component["breaking_change"])

    def test_json_output_with_breaking_changes(self):
        self._create_html("src/page.html", "<uui-panel>")
        self._create_behavior(
            "uui-panel.behavior.json",
            {
                "component": "uui-panel",
                "version": "2.0.0",
                "tag": "<uui-panel>",
                "breaking_changes": [
                    {"version": "2.4.0", "description": "Removed header input"},
                ],
            },
        )
        config = {
            "patterns": ["<uui-panel"],
            "definitions_path": "behaviors",
            "definitions_glob": "*.behavior.json",
            "release": {
                "version": "2.4.0",
                "affected_components": ["uui-panel"],
                "date": "2026-02-14",
            },
            "application_repo": [
                {
                    "source_path": str(self.test_dir / "src"),
                    "replace_path": str(self.test_dir) + "/",
                    "report_name": "breaking_test",
                }
            ],
        }
        config_path = self._create_config(config)
        output_dir = self.test_dir / "output"

        exit_code = main(["-c", str(config_path), "-o", str(output_dir)])
        self.assertEqual(exit_code, 0)

        json_file = next(iter(output_dir.glob("breaking_test-*.json")))
        data = json.loads(json_file.read_text())
        component = data["pages"][0]["components"][0]
        self.assertTrue(component["has_breaking_changes"])
        self.assertEqual(component["breaking_change"], "Removed header input")

    def test_json_output_without_definitions_config(self):
        self._create_html("src/page.html", "<uui-button>")
        config = {
            "patterns": ["<uui-button"],
            "application_repo": [
                {
                    "source_path": str(self.test_dir / "src"),
                    "replace_path": str(self.test_dir) + "/",
                    "report_name": "no_behavior_test",
                }
            ],
        }
        config_path = self._create_config(config)
        output_dir = self.test_dir / "output"

        exit_code = main(["-c", str(config_path), "-o", str(output_dir)])
        self.assertEqual(exit_code, 0)

        json_file = next(iter(output_dir.glob("no_behavior_test-*.json")))
        data = json.loads(json_file.read_text())
        component = data["pages"][0]["components"][0]
        self.assertIsNone(component["behavior_definition"])
        self.assertFalse(component["has_breaking_changes"])


if __name__ == "__main__":
    unittest.main()
