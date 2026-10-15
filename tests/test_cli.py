import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egi_bench import cli


class CliTests(unittest.TestCase):
    def test_help_parser_contains_core_commands(self):
        parser = cli.build_parser()
        output = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(output):
            parser.parse_args(["--help"])
        help_text = output.getvalue()
        self.assertIn("doctor", help_text)
        self.assertIn("setup", help_text)
        self.assertIn("report", help_text)

    def test_run_translates_args_to_runner(self):
        with mock.patch.object(cli, "_load_run_all_module") as load_run_all:
            run_all = mock.Mock()
            load_run_all.return_value = run_all
            exit_code = cli.main(
                [
                    "run",
                    "--model",
                    "gpt-4o-mini",
                    "--mode",
                    "quick",
                    "--benchmarks",
                    "herb",
                    "personabench",
                    "--parallel",
                    "--max-workers",
                    "2",
                ]
            )
        self.assertEqual(exit_code, 0)
        run_all.main.assert_called_once_with(
            [
                "--model",
                "gpt-4o-mini",
                "--mode",
                "quick",
                "--benchmarks",
                "herb",
                "personabench",
                "--parallel",
                "--max-workers",
                "2",
            ]
        )

    def test_run_no_longer_accepts_skip_run(self):
        parser = cli.build_parser()
        stderr = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(stderr):
            parser.parse_args(["run", "--model", "gpt-4o-mini", "--skip-run"])
        self.assertIn("--skip-run", stderr.getvalue())

    def test_report_rescore_translates_to_runner(self):
        with mock.patch.object(cli, "_load_run_all_module") as load_run_all:
            run_all = mock.Mock()
            load_run_all.return_value = run_all
            exit_code = cli.main(
                [
                    "report",
                    "--rescore",
                    "--model",
                    "gpt-4o-mini",
                    "--mode",
                    "quick",
                    "--benchmarks",
                    "herb",
                    "personabench",
                ]
            )
        self.assertEqual(exit_code, 0)
        run_all.main.assert_called_once_with(
            [
                "--model",
                "gpt-4o-mini",
                "--mode",
                "quick",
                "--skip-run",
                "--benchmarks",
                "herb",
                "personabench",
            ]
        )

    def test_report_rescore_requires_model_and_mode(self):
        with mock.patch.object(cli, "_load_run_all_module") as load_run_all:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main(["report", "--rescore", "--mode", "quick"])
        self.assertEqual(exit_code, 2)
        self.assertIn("--rescore requires", stderr.getvalue())
        load_run_all.assert_not_called()

    def test_report_rescore_rejects_path(self):
        with mock.patch.object(cli, "_load_run_all_module") as load_run_all:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main(
                    [
                        "report",
                        "--rescore",
                        "--model",
                        "gpt-4o-mini",
                        "--mode",
                        "quick",
                        "--path",
                        "results_aggregated/foo.json",
                    ]
                )
        self.assertEqual(exit_code, 2)
        self.assertIn("--rescore cannot be combined with --path", stderr.getvalue())
        load_run_all.assert_not_called()

    def test_report_rejects_rescore_only_flags_without_rescore(self):
        with mock.patch.object(cli, "_load_run_all_module") as load_run_all:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main(["report", "--model", "gpt-4o-mini"])
        self.assertEqual(exit_code, 2)
        self.assertIn("only apply with --rescore", stderr.getvalue())
        load_run_all.assert_not_called()

    def test_report_prints_latest_json(self):
        report = {
            "model": "gpt-4o-mini",
            "mode": "quick",
            "egi_score": 12.3,
            "domain_scores": {
                "herb": {
                    "score": 12.3,
                    "sub_scores": {},
                    "status": "success",
                    "error_message": None,
                    "runtime_seconds": 1,
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            old = output_dir / "old_quick_20000101_000000.json"
            old.write_text(json.dumps(report))
            latest = output_dir / "new_quick_29990101_000000.json"
            latest.write_text(json.dumps({**report, "egi_score": 45.6}))
            os.utime(old, (1, 1))
            os.utime(latest, (2, 2))
            with mock.patch.object(cli, "_load_run_all_module") as load_run_all:
                run_all = mock.Mock()
                load_run_all.return_value = run_all
                exit_code = cli.main(["report", "--output-dir", str(output_dir)])
        self.assertEqual(exit_code, 0)
        run_all.print_summary.assert_called_once()
        printed_report = run_all.print_summary.call_args.args[0]
        self.assertEqual(printed_report["egi_score"], 45.6)

    def test_load_previous_runtimes_picks_latest_matching_report(self):
        run_all = cli._load_run_all_module()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            older = output_dir / "gpt-4.1-nano_quick_20260101_000000.json"
            older.write_text(json.dumps({
                "model": "gpt-4.1-nano",
                "mode": "quick",
                "domain_scores": {
                    "herb": {"runtime_seconds": 9999.0},
                    "userbench": {"runtime_seconds": 1234.0},
                },
            }))

            latest = output_dir / "gpt-4.1-nano_quick_20260201_000000.json"
            latest.write_text(json.dumps({
                "model": "gpt-4.1-nano",
                "mode": "quick",
                "domain_scores": {
                    "herb": {"runtime_seconds": 2003.1},
                    "userbench": {"runtime_seconds": 87.4},
                    "mcpeval": {"runtime_seconds": None},
                },
            }))

            other_model = output_dir / "gpt-4o-mini_quick_20260301_000000.json"
            other_model.write_text(json.dumps({
                "domain_scores": {"herb": {"runtime_seconds": 42.0}},
            }))

            os.utime(older, (1, 1))
            os.utime(latest, (2, 2))
            os.utime(other_model, (3, 3))

            runtimes = run_all.load_previous_runtimes(
                str(output_dir), "gpt-4.1-nano", "quick",
                ["herb", "userbench", "mcpeval", "missing"],
            )

        self.assertEqual(runtimes["herb"], 2003.1)
        self.assertEqual(runtimes["userbench"], 87.4)
        self.assertIsNone(runtimes["mcpeval"])
        self.assertIsNone(runtimes["missing"])

    def test_load_previous_runtimes_skips_rescored_reports(self):
        # Real run preserves runtimes; subsequent rescored reports (tagged
        # ``run_kind: "rescore"``) must be skipped so their bogus near-zero
        # runtimes don't replace the original real-run values.
        run_all = cli._load_run_all_module()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            real_run = output_dir / "gpt-4.1-nano_quick_20260101_000000.json"
            real_run.write_text(json.dumps({
                "run_kind": "run",
                "domain_scores": {
                    "herb": {"runtime_seconds": 2003.1},
                    "userbench": {"runtime_seconds": 87.4},
                    "crmarena": {"runtime_seconds": 0.0},
                },
            }))

            rescored = output_dir / "gpt-4.1-nano_quick_20260102_000000.json"
            rescored.write_text(json.dumps({
                "run_kind": "rescore",
                "domain_scores": {
                    "herb": {"runtime_seconds": 0.8},
                    "userbench": {"runtime_seconds": 0.0},
                    "crmarena": {"runtime_seconds": 0.0},
                },
            }))

            os.utime(real_run, (1, 1))
            os.utime(rescored, (2, 2))

            runtimes = run_all.load_previous_runtimes(
                str(output_dir), "gpt-4.1-nano", "quick",
                ["herb", "userbench", "crmarena"],
            )

        self.assertEqual(runtimes["herb"], 2003.1)
        self.assertEqual(runtimes["userbench"], 87.4)
        # No positive value anywhere; falls back to the newest run-kind value.
        self.assertEqual(runtimes["crmarena"], 0.0)

    def test_load_previous_runtimes_treats_legacy_reports_as_runs(self):
        # Reports without a ``run_kind`` field predate this fix and must
        # remain eligible as runtime sources for backward compatibility.
        run_all = cli._load_run_all_module()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            legacy = output_dir / "gpt-4.1-nano_quick_20260101_000000.json"
            legacy.write_text(json.dumps({
                "domain_scores": {"herb": {"runtime_seconds": 2003.1}},
            }))
            os.utime(legacy, (1, 1))
            runtimes = run_all.load_previous_runtimes(
                str(output_dir), "gpt-4.1-nano", "quick", ["herb"],
            )
        self.assertEqual(runtimes["herb"], 2003.1)

    def test_aggregate_scores_records_run_kind(self):
        run_all = cli._load_run_all_module()
        results = {
            "herb": run_all.BenchmarkResult(
                name="herb", score=10.0, status="success", runtime_seconds=12.5,
            ),
        }
        run_report = run_all.aggregate_scores(
            results, model="m", mode="quick",
            required_benchmarks=["herb"],
        )
        rescore_report = run_all.aggregate_scores(
            results, model="m", mode="quick",
            required_benchmarks=["herb"], run_kind="rescore",
        )
        self.assertEqual(run_report["run_kind"], "run")
        self.assertEqual(rescore_report["run_kind"], "rescore")

    def test_load_previous_runtimes_handles_missing_dir(self):
        run_all = cli._load_run_all_module()
        runtimes = run_all.load_previous_runtimes(
            "/nonexistent/path/does/not/exist", "m", "quick", ["herb"],
        )
        self.assertEqual(runtimes, {"herb": None})

    def test_aggregate_scores_records_total_runtime_seconds(self):
        # Wall-clock total is a top-level field rounded to 1 decimal place;
        # ``None`` is preserved as ``None`` (e.g. legacy/unknown).
        run_all = cli._load_run_all_module()
        results = {
            "herb": run_all.BenchmarkResult(
                name="herb", score=10.0, status="success", runtime_seconds=12.5,
            ),
        }
        with_total = run_all.aggregate_scores(
            results, model="m", mode="quick",
            required_benchmarks=["herb"], total_runtime_seconds=123.456,
        )
        without_total = run_all.aggregate_scores(
            results, model="m", mode="quick",
            required_benchmarks=["herb"],
        )
        self.assertEqual(with_total["total_runtime_seconds"], 123.5)
        self.assertIsNone(without_total["total_runtime_seconds"])

    def test_load_previous_total_runtime_skips_rescored_reports(self):
        # Rescored reports must not pollute the inherited total — the helper
        # walks newest-first and returns the first positive total from a
        # real run (or legacy report without ``run_kind``).
        run_all = cli._load_run_all_module()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            real_run = output_dir / "gpt-4.1-nano_quick_20260101_000000.json"
            real_run.write_text(json.dumps({
                "run_kind": "run",
                "total_runtime_seconds": 1234.5,
                "domain_scores": {},
            }))

            rescored = output_dir / "gpt-4.1-nano_quick_20260102_000000.json"
            rescored.write_text(json.dumps({
                "run_kind": "rescore",
                "total_runtime_seconds": 0.4,
                "domain_scores": {},
            }))

            os.utime(real_run, (1, 1))
            os.utime(rescored, (2, 2))

            total = run_all.load_previous_total_runtime(
                str(output_dir), "gpt-4.1-nano", "quick",
            )

        self.assertEqual(total, 1234.5)

    def test_load_previous_total_runtime_handles_missing_dir(self):
        run_all = cli._load_run_all_module()
        self.assertIsNone(
            run_all.load_previous_total_runtime(
                "/nonexistent/path/does/not/exist", "m", "quick",
            )
        )

    def test_aggregate_scores_emits_null_runtime_for_unknown(self):
        run_all = cli._load_run_all_module()
        results = {
            "herb": run_all.BenchmarkResult(
                name="herb", score=10.0, status="success", runtime_seconds=None,
            ),
            "userbench": run_all.BenchmarkResult(
                name="userbench", score=20.0, status="success", runtime_seconds=42.5,
            ),
        }
        report = run_all.aggregate_scores(
            results,
            model="m", mode="quick",
            required_benchmarks=["herb", "userbench"],
        )
        self.assertIsNone(report["domain_scores"]["herb"]["runtime_seconds"])
        self.assertEqual(report["domain_scores"]["userbench"]["runtime_seconds"], 42.5)

    def test_score_userbench_uses_mode_scoped_file(self):
        # Quick mode (with --max_tasks_per_env 60) and deep mode must read
        # different result files so the smaller quick cache cannot be
        # silently scored as a deep run.
        run_all = cli._load_run_all_module()
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "UserBench" / "outputs"
            outputs.mkdir(parents=True)
            (outputs / "results_unified_test-model_quick.json").write_text(json.dumps({
                "travel22": {"1": {"micro_avg": 0.10}},
            }))
            (outputs / "results_unified_test-model_deep.json").write_text(json.dumps({
                "travel22": {"1": {"micro_avg": 0.20}},
                "travel2222": {"1": {"micro_avg": 0.30}},
            }))
            config = {"benchmarks": {"userbench": {"dir": "UserBench"}}}
            with mock.patch.object(run_all, "REPO_ROOT", Path(tmp)):
                quick = run_all.score_userbench(config, "test-model", "quick")
                deep = run_all.score_userbench(config, "test-model", "deep")
        self.assertEqual(quick.sub_scores, {"travel22_micro_avg": 10.0})
        self.assertEqual(
            deep.sub_scores,
            {"travel22_micro_avg": 20.0, "travel2222_micro_avg": 30.0},
        )

    def test_score_userbench_falls_back_to_legacy_filename(self):
        # Pre-mode-scope runs only wrote ``results_unified_<model>.json``;
        # the scorer must still load it so existing data can be rescored.
        run_all = cli._load_run_all_module()
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "UserBench" / "outputs"
            outputs.mkdir(parents=True)
            (outputs / "results_unified_test-model.json").write_text(json.dumps({
                "travel22": {"1": {"micro_avg": 0.05}},
            }))
            config = {"benchmarks": {"userbench": {"dir": "UserBench"}}}
            with mock.patch.object(run_all, "REPO_ROOT", Path(tmp)):
                result = run_all.score_userbench(config, "test-model", "deep")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.sub_scores, {"travel22_micro_avg": 5.0})

    # ----- EGI weight configuration / overrides -----------------------

    def test_parse_egi_weight_overrides_partial_and_case_insensitive(self):
        run_all = cli._load_run_all_module()
        parsed = run_all.parse_egi_weight_overrides("M1=0.5,m5=0.2")
        self.assertEqual(parsed, {"M1": 0.5, "M5": 0.2})

    def test_parse_egi_weight_overrides_rejects_unknown_bucket(self):
        run_all = cli._load_run_all_module()
        with self.assertRaises(Exception) as ctx:
            run_all.parse_egi_weight_overrides("M7=0.1")
        self.assertIn("M7", str(ctx.exception))

    def test_parse_egi_weight_overrides_rejects_negative_weight(self):
        run_all = cli._load_run_all_module()
        with self.assertRaises(Exception) as ctx:
            run_all.parse_egi_weight_overrides("M1=-0.5")
        self.assertIn("non-negative", str(ctx.exception))

    def test_resolve_egi_weights_uses_defaults_when_yaml_missing(self):
        run_all = cli._load_run_all_module()
        weights = run_all.resolve_egi_weights({}, None)
        self.assertEqual(weights, run_all.DEFAULT_EGI_WEIGHTS)

    def test_resolve_egi_weights_yaml_overrides_defaults(self):
        run_all = cli._load_run_all_module()
        weights = run_all.resolve_egi_weights(
            {"egi_weights": {"M1": 0.40, "M5": 0.20}}, None
        )
        self.assertEqual(weights["M1"], 0.40)
        self.assertEqual(weights["M5"], 0.20)
        # Unspecified Ms inherit defaults so callers always see all 6.
        self.assertEqual(weights["M2"], run_all.DEFAULT_EGI_WEIGHTS["M2"])

    def test_resolve_egi_weights_cli_overrides_yaml(self):
        run_all = cli._load_run_all_module()
        weights = run_all.resolve_egi_weights(
            {"egi_weights": {"M1": 0.40, "M5": 0.20}},
            {"M1": 0.50},
        )
        self.assertEqual(weights["M1"], 0.50)
        self.assertEqual(weights["M5"], 0.20)

    def test_resolve_egi_weights_rejects_all_zero(self):
        run_all = cli._load_run_all_module()
        with self.assertRaises(SystemExit):
            run_all.resolve_egi_weights(
                {"egi_weights": {m: 0.0 for m in run_all.EGI_METRIC_NAMES}}, None
            )

    def test_resolve_egi_weights_rejects_unknown_yaml_key(self):
        run_all = cli._load_run_all_module()
        with self.assertRaises(SystemExit) as ctx:
            run_all.resolve_egi_weights({"egi_weights": {"M9": 0.1}}, None)
        self.assertIn("M9", str(ctx.exception))

    def test_compute_egi_metrics_respects_custom_weights(self):
        # With custom weights, EGI Score must reflect the supplied weighting,
        # not the module-level defaults. We construct a result that lights up
        # both M1 (locobench.functional_correctness) and M5
        # (herb._unanswerable) so the rebalance is observable.
        run_all = cli._load_run_all_module()
        results = {
            "locobench": run_all.BenchmarkResult(
                name="locobench", score=80.0, status="success",
                sub_scores={"functional_correctness": 80.0},
            ),
            "herb": run_all.BenchmarkResult(
                name="herb", score=20.0, status="success",
                sub_scores={"BAAI_x-1-unans_unanswerable": 20.0},
            ),
        }
        # Only M1 and M5 have contributors; weights renormalize over those.
        # default_weights -> egi = (80 * 0.28 + 20 * 0.14) / (0.28 + 0.14)
        #                       = (22.4 + 2.8) / 0.42 = 60.0
        default_block = run_all.compute_egi_metrics(results)
        self.assertEqual(default_block["egi_score"], 60.0)

        # safety-heavy override: M1=0.10, M5=0.50
        # egi = (80 * 0.10 + 20 * 0.50) / 0.60 = (8 + 10) / 0.60 = 30.0
        safety_block = run_all.compute_egi_metrics(
            results, egi_weights={**run_all.DEFAULT_EGI_WEIGHTS, "M1": 0.10, "M5": 0.50}
        )
        self.assertEqual(safety_block["egi_score"], 30.0)
        self.assertEqual(safety_block["egi_metrics"]["M1"]["weight"], 0.10)
        self.assertEqual(safety_block["egi_metrics"]["M5"]["weight"], 0.50)

    def test_run_forwards_egi_weights_to_runner(self):
        with mock.patch.object(cli, "_load_run_all_module") as load_run_all:
            run_all = mock.Mock()
            load_run_all.return_value = run_all
            exit_code = cli.main(
                [
                    "run",
                    "--model",
                    "gpt-4o-mini",
                    "--mode",
                    "quick",
                    "--egi-weights",
                    "M1=0.5,M5=0.2",
                ]
            )
        self.assertEqual(exit_code, 0)
        forwarded = run_all.main.call_args.args[0]
        self.assertIn("--egi-weights", forwarded)
        self.assertEqual(
            forwarded[forwarded.index("--egi-weights") + 1],
            "M1=0.5,M5=0.2",
        )

    def test_report_rescore_forwards_egi_weights(self):
        with mock.patch.object(cli, "_load_run_all_module") as load_run_all:
            run_all = mock.Mock()
            load_run_all.return_value = run_all
            exit_code = cli.main(
                [
                    "report",
                    "--rescore",
                    "--model",
                    "gpt-4o-mini",
                    "--mode",
                    "quick",
                    "--egi-weights",
                    "M1=0.5",
                ]
            )
        self.assertEqual(exit_code, 0)
        forwarded = run_all.main.call_args.args[0]
        self.assertIn("--egi-weights", forwarded)
        self.assertEqual(
            forwarded[forwarded.index("--egi-weights") + 1], "M1=0.5"
        )

    def test_report_without_rescore_rejects_egi_weights(self):
        with mock.patch.object(cli, "_load_run_all_module") as load_run_all:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main(["report", "--egi-weights", "M1=0.5"])
        self.assertEqual(exit_code, 2)
        self.assertIn("only apply with --rescore", stderr.getvalue())
        load_run_all.assert_not_called()

    def test_load_run_all_from_outside_repo_without_repo_on_syspath(self):
        old_cwd = os.getcwd()
        old_path = list(sys.path)
        sys.modules.pop("egi_bench._run_all", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                sys.path = [
                    entry
                    for entry in old_path
                    if entry and Path(entry).resolve() != cli.REPO_ROOT
                ]
                module = cli._load_run_all_module()
        finally:
            os.chdir(old_cwd)
            sys.path = old_path
            sys.modules.pop("egi_bench._run_all", None)
        self.assertTrue(hasattr(module, "main"))
        self.assertTrue(hasattr(module, "print_summary"))


if __name__ == "__main__":
    unittest.main()
