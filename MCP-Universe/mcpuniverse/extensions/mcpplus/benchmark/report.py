"""
Extended Benchmark Report with Wrapper Support

EXISTING (MCPUniverse BenchmarkReport):
- Expects exactly 1 LLM config
- Doesn't know about wrapper configs
- Generates markdown report with evaluation results

THIS IMPLEMENTATION:
- Handles multiple LLM configs (agent LLM + post-processor LLM)
- Filters out wrapper configs before passing to parent
- Shows wrapper information in report
- Fully compatible with standard benchmarks (no wrappers)
"""
from typing import List, Dict
from pathlib import Path
from mcpuniverse.benchmark.report import BenchmarkReport as BaseBenchmarkReport
from mcpuniverse.benchmark.runner import BenchmarkRunner
from mcpuniverse.tracer.collectors import BaseCollector


class BenchmarkReportWithWrapper(BaseBenchmarkReport):
    """
    Extended BenchmarkReport that handles wrapper configurations.

    This class filters out wrapper configs and handles multiple LLMs
    before delegating to the parent BenchmarkReport.
    """

    def __init__(self, runner: BenchmarkRunner, trace_collector: BaseCollector):
        """
        Initialize benchmark report with wrapper support.

        Args:
            runner: BenchmarkRunner instance (can be BenchmarkRunnerWithWrapper).
            trace_collector: Trace collector for detailed logs.
        """
        # Store runner reference for later use
        self._runner = runner

        # Store original configs
        self._original_agent_configs = runner._agent_configs
        self._wrapper_configs = []
        self._has_wrapper = False
        self._report_path = None  # Track the report file path for appending

        # Filter out wrapper configs and track them
        filtered_configs = []
        agent_llm_name = None

        for config in self._original_agent_configs:
            if config.get('kind') == 'wrapper':
                self._wrapper_configs.append(config)
                self._has_wrapper = True
            elif config.get('kind') == 'agent':
                # Get agent's LLM name
                agent_llm_name = config.get('spec', {}).get('config', {}).get('llm')
                filtered_configs.append(config)
            elif config.get('kind') == 'llm':
                # Keep all LLM configs for now, we'll filter to agent's LLM only
                filtered_configs.append(config)
            else:
                filtered_configs.append(config)

        # Filter LLM configs to only include the agent's LLM (for parent class compatibility)
        final_configs = []
        for config in filtered_configs:
            if config.get('kind') == 'llm':
                if config.get('spec', {}).get('name') == agent_llm_name:
                    final_configs.append(config)
            else:
                final_configs.append(config)

        # Temporarily replace runner's configs with filtered ones
        runner._agent_configs = final_configs

        # Initialize parent class
        super().__init__(runner, trace_collector)

        # Restore original configs
        runner._agent_configs = self._original_agent_configs

    def write_to_report(self, report_str):
        """
        Write report with informative filename including task type, agent types, and model names.

        Filename format: report_{timestamp}_{task_type}_{main_agent_type}_{main_model}[_pp_{pp_type}_{pp_model}]_{uuid}.md

        EXISTING: BenchmarkReport.write_to_report() uses report_{timestamp}_{uuid}.md
        THIS IMPLEMENTATION: Includes task type, agent types, and model names for easier identification
        """
        from datetime import datetime
        import uuid
        from pathlib import Path

        # Use timestamp and run_id from benchmark runner if available (for coordinated logging)
        if hasattr(self._runner, '_run_timestamp') and hasattr(self._runner, '_run_id'):
            timestamp = self._runner._run_timestamp
            unique_id = self._runner._run_id
        else:
            # Fallback to generating new ones
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]

        # Extract task type, agent types, and model names from benchmark results
        task_type = "unknown"
        main_agent_type = "unknown"
        main_model_name = "unknown"
        pp_type = None
        pp_model_name = None

        if self.benchmark_results:
            first_result = self.benchmark_results[0]

            # Extract task type from first task path
            # e.g., "test/financial_analysis/yfinance_task_0040.json" -> "yfinance"
            if hasattr(first_result, 'task_results') and first_result.task_results:
                first_task_path = next(iter(first_result.task_results.keys()))
                # Extract task type from path
                if '/' in first_task_path:
                    filename = first_task_path.split('/')[-1]  # Get filename
                    # yfinance_task_0040.json -> yfinance
                    task_type = filename.split('_')[0] if '_' in filename else filename.replace('.json', '')

                # Get agent types and model names from statistics
                first_task = next(iter(first_result.task_results.values()))
                stats = first_task.get('statistics', {})

                # Get main agent type
                main_agent_type = stats.get('main_agent_type', 'unknown')

                # Get main agent model (shorten for filename)
                main_model_full = stats.get('main_agent_model_name', 'unknown')
                main_model_name = self._shorten_model_name(main_model_full)

                # Get postprocessor type and model if present
                pp_type = stats.get('postprocessor_type')
                pp_model_full = stats.get('postprocessor_model_name')
                if pp_model_full:
                    pp_model_name = self._shorten_model_name(pp_model_full)

        # Build filename: report_{timestamp}_{task}_{agent_type}_{main_model}[_pp_{pp_type}_{pp_model}]_{uuid}.md
        if pp_type and pp_model_name:
            filename = f"report_{timestamp}_{task_type}_{main_agent_type}_{main_model_name}_pp_{pp_type}_{pp_model_name}_{unique_id}.md"
            # Store failure log filename pattern on runner for coordination
            if hasattr(self._runner, '_failure_log_filename') and self._runner._failure_log_filename is None:
                self._runner._failure_log_filename = f"failures_{timestamp}_{task_type}_{main_agent_type}_{main_model_name}_pp_{pp_type}_{pp_model_name}_{unique_id}.jsonl"
        else:
            filename = f"report_{timestamp}_{task_type}_{main_agent_type}_{main_model_name}_{unique_id}.md"
            # Store failure log filename pattern on runner for coordination
            if hasattr(self._runner, '_failure_log_filename') and self._runner._failure_log_filename is None:
                self._runner._failure_log_filename = f"failures_{timestamp}_{task_type}_{main_agent_type}_{main_model_name}_{unique_id}.jsonl"

        # Always use our custom filename format (ignore parent's log_dir/log_name)
        REPORT_FOLDER = Path("log")
        report_path = REPORT_FOLDER / filename

        # Write report
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_str)
            print(f"Report saved to: {report_path}")
            # Store the path for later appending (critical for parallel runs)
            self._report_path = str(report_path)
            return str(report_path)
        except Exception as e:
            print(f"Error writing report: {e}")
            return None

    def _shorten_model_name(self, model_name: str) -> str:
        """
        Shorten model name for filename.

        Examples:
            claude-sonnet-4-20250514-v1:0 -> claude-sonnet-4
            claude-sonnet-3.7 -> claude-sonnet-3-7
            gpt-4.1 -> gpt-4-1
            gpt-4o-mini -> gpt-4o-mini
            google/gemini-3 -> google-gemini-3
        """
        if not model_name:
            return "unknown"

        name = model_name

        # Replace path separators with dashes (critical for filenames!)
        name = name.replace('/', '-')
        name = name.replace('\\', '-')

        # Remove version suffixes
        if ':' in name:
            name = name.split(':')[0]  # Remove ":0" suffix

        # Replace dots with dashes for filename compatibility
        name = name.replace('.', '-')

        # Shorten long model names
        if 'claude-sonnet' in name:
            # claude-sonnet-4-20250514-v1 -> claude-sonnet-4
            parts = name.split('-')
            if len(parts) >= 3:
                return '-'.join(parts[:3])

        if 'claude' in name and len(name) > 20:
            # claude-3-7-sonnet-20250219-v1 -> claude-3-7-sonnet
            parts = name.split('-')
            # Keep first 4 parts (claude-3-7-sonnet)
            return '-'.join(parts[:4])

        return name

    def dump(self):
        """
        Dump the report with wrapper information and task statistics included.

        EXISTING: BenchmarkReport.dump() generates standard markdown report
        THIS IMPLEMENTATION: Adds wrapper configuration and task statistics sections

        Returns:
            Path to the generated report file.
        """
        # Call parent dump - this triggers write_to_report which stores self._report_path
        result = super().dump()

        # Use the stored report path (set by write_to_report)
        # This ensures we append to the correct file even when running in parallel
        log_file_path = self._report_path if self._report_path else result

        # Append additional information to the report
        if log_file_path:
            if self._has_wrapper:
                self._append_wrapper_info(log_file_path)
            self._append_task_statistics(log_file_path)

        return log_file_path

    def _append_wrapper_info(self, log_file_path):
        """
        Append wrapper configuration information to the generated report.

        Args:
            log_file_path: Path to the report markdown file.
        """
        try:
            with open(log_file_path, 'a', encoding='utf-8') as f:
                f.write("\n\n## Wrapper Configuration\n\n")

                for wrapper_config in self._wrapper_configs:
                    spec = wrapper_config.get('spec', {})
                    enabled = spec.get('enabled', False)

                    if enabled:
                        f.write("Post-processing was **enabled** for this benchmark.\n\n")
                    else:
                        f.write("Post-processing was **disabled** for this benchmark (wrapper config present but not enabled).\n\n")

                    f.write(f"- **Enabled:** {enabled}\n")
                    f.write(f"- **Token Threshold:** {spec.get('token_threshold', 2000)}\n")

                    post_llm = spec.get('post_process_llm', {})
                    if isinstance(post_llm, dict):
                        model_name = post_llm.get('model_name', 'gpt-5-mini')
                        f.write(f"- **Post-processor LLM:** {model_name}\n")

                    f.write(f"- **Max Iterations:** {spec.get('max_iterations', 3)}\n")
                    f.write(f"- **LLM Timeout:** {spec.get('llm_timeout', 500)}s\n")
                    f.write(f"- **Skip Iteration on Size Failure:** {spec.get('skip_iteration_on_size_failure', False)}\n\n")

        except Exception:
            # Don't fail if we can't append wrapper info
            pass

    def _append_task_statistics(self, log_file_path):
        """
        Append task statistics (iterations, tokens) to the generated report.

        Args:
            log_file_path: Path to the report markdown file.
        """
        try:
            # Get benchmark results from runner
            if not hasattr(self, '_runner'):
                return

            if not hasattr(self._runner, '_benchmark_results'):
                return

            if not self._runner._benchmark_results:
                return

            with open(log_file_path, 'a', encoding='utf-8') as f:
                f.write("\n\n## Task Statistics\n\n")
                f.write("Detailed statistics for each task including iterations and token usage.\n\n")

                for benchmark_result in self._runner._benchmark_results:
                    # Get benchmark name - try different attributes
                    benchmark_name = getattr(benchmark_result.benchmark, 'name', None) or \
                                    getattr(benchmark_result.benchmark, 'description', 'Unnamed Benchmark')
                    f.write(f"### Benchmark: {benchmark_name}\n\n")

                    # Create statistics table with token usage and costs
                    f.write("| Task | Score | Main Iter | PP Iter | "
                           "Main In Tok | Main Out Tok | Main In Cost | Main Out Cost | "
                           "PP In Tok | PP Out Tok | PP In Cost | PP Out Cost | "
                           "Total Tok | Total Cost |\n")
                    f.write("|------|-------|-----------|---------|"
                           "-------------|--------------|--------------|---------------|"
                           "-----------|------------|------------|-------------|"
                           "-----------|------------|\n")

                    for task_path, task_data in benchmark_result.task_results.items():
                        # Extract task name from path
                        task_name = task_path.split('/')[-1].replace('.yaml', '').replace('.json', '')

                        # Calculate score from evaluation results
                        eval_results = task_data.get("evaluation_results", [])
                        score_str = "N/A"
                        if isinstance(eval_results, list) and eval_results:
                            passed_count = sum(1 for result in eval_results if result.passed)
                            total_evals = len(eval_results)
                            score = passed_count / total_evals if total_evals > 0 else 0.0
                            score_str = f"{score:.2f}"

                        # Get statistics
                        stats = task_data.get("statistics", {})
                        main_iter = stats.get("main_agent_iterations", 0)
                        pp_iter = stats.get("postprocessor_iterations", 0)

                        main_in_tok = stats.get("main_agent_input_tokens", 0)
                        main_out_tok = stats.get("main_agent_output_tokens", 0)
                        main_in_cost = stats.get("main_agent_input_cost", 0.0)
                        main_out_cost = stats.get("main_agent_output_cost", 0.0)

                        pp_in_tok = stats.get("postprocessor_input_tokens", 0)
                        pp_out_tok = stats.get("postprocessor_output_tokens", 0)
                        pp_in_cost = stats.get("postprocessor_input_cost", 0.0)
                        pp_out_cost = stats.get("postprocessor_output_cost", 0.0)

                        total_tok = stats.get("total_tokens", 0)
                        total_cost = stats.get("total_cost", 0.0)

                        f.write(f"| {task_name} | {score_str} | {main_iter} | {pp_iter} | "
                               f"{main_in_tok:,} | {main_out_tok:,} | ${main_in_cost:.4f} | ${main_out_cost:.4f} | "
                               f"{pp_in_tok:,} | {pp_out_tok:,} | ${pp_in_cost:.4f} | ${pp_out_cost:.4f} | "
                               f"{total_tok:,} | ${total_cost:.4f} |\n")

                    # Add aggregate statistics
                    f.write("\n**Aggregate Statistics:**\n\n")

                    # Extract agent configuration from first task
                    first_task_stats = next(iter(benchmark_result.task_results.values())).get("statistics", {})
                    main_agent_name = first_task_stats.get("main_agent_name", "Unknown")
                    main_llm_name = first_task_stats.get("main_agent_llm_name", "Unknown")
                    main_model_name = first_task_stats.get("main_agent_model_name", "Unknown")
                    pp_llm_name = first_task_stats.get("postprocessor_llm_name")
                    pp_model_name = first_task_stats.get("postprocessor_model_name")

                    f.write("**Agent Configuration:**\n\n")
                    f.write(f"- **Main Agent:** {main_agent_name}\n")
                    f.write(f"- **Main Agent LLM:** {main_llm_name} ({main_model_name})\n")
                    if pp_llm_name:
                        f.write(f"- **Postprocessor LLM:** {pp_llm_name} ({pp_model_name})\n")
                    f.write("\n")

                    # Initialize aggregators
                    task_count = len(benchmark_result.task_results)
                    total_main_in_tok = 0
                    total_main_out_tok = 0
                    total_main_in_cost = 0.0
                    total_main_out_cost = 0.0
                    total_pp_in_tok = 0
                    total_pp_out_tok = 0
                    total_pp_in_cost = 0.0
                    total_pp_out_cost = 0.0
                    total_main_iterations = 0
                    total_pp_iterations = 0

                    # Task success tracking
                    tasks_fully_passed = 0
                    tasks_passed = 0
                    total_score = 0.0
                    scores = []

                    for task_data in benchmark_result.task_results.values():
                        # Collect statistics
                        stats = task_data.get("statistics", {})
                        total_main_in_tok += stats.get("main_agent_input_tokens", 0)
                        total_main_out_tok += stats.get("main_agent_output_tokens", 0)
                        total_main_in_cost += stats.get("main_agent_input_cost", 0.0)
                        total_main_out_cost += stats.get("main_agent_output_cost", 0.0)
                        total_pp_in_tok += stats.get("postprocessor_input_tokens", 0)
                        total_pp_out_tok += stats.get("postprocessor_output_tokens", 0)
                        total_pp_in_cost += stats.get("postprocessor_input_cost", 0.0)
                        total_pp_out_cost += stats.get("postprocessor_output_cost", 0.0)
                        total_main_iterations += stats.get("main_agent_iterations", 0)
                        total_pp_iterations += stats.get("postprocessor_iterations", 0)

                        # Track task success
                        eval_results = task_data.get("evaluation_results", [])
                        if isinstance(eval_results, list) and eval_results:
                            passed_count = sum(1 for result in eval_results if result.passed)
                            total_evals = len(eval_results)
                            score = passed_count / total_evals if total_evals > 0 else 0.0

                            scores.append(score)
                            total_score += score

                            if score >= 1.0:
                                tasks_fully_passed += 1
                            if score > 0:
                                tasks_passed += 1

                    # Calculate averages and percentages
                    avg_score = total_score / task_count if task_count > 0 else 0
                    pass_rate = (tasks_fully_passed / task_count * 100) if task_count > 0 else 0
                    partial_pass_rate = (tasks_passed / task_count * 100) if task_count > 0 else 0

                    # Success metrics
                    f.write("**Success Metrics:**\n\n")
                    f.write(f"- **Total Tasks:** {task_count}\n")
                    f.write(f"- **Tasks Fully Passed (Score 1.0):** {tasks_fully_passed} ({pass_rate:.1f}%)\n")
                    f.write(f"- **Tasks with Any Score > 0:** {tasks_passed} ({partial_pass_rate:.1f}%)\n")
                    f.write(f"- **Average Score:** {avg_score:.3f}\n")
                    if scores:
                        scores.sort()
                        median_idx = len(scores) // 2
                        median_score = scores[median_idx] if len(scores) % 2 == 1 else (scores[median_idx-1] + scores[median_idx]) / 2
                        f.write(f"- **Median Score:** {median_score:.3f}\n")
                    f.write("\n")

                    # Main agent metrics
                    f.write("**Main Agent Metrics:**\n\n")
                    f.write(f"- **Total Input Tokens:** {total_main_in_tok:,}\n")
                    f.write(f"- **Total Output Tokens:** {total_main_out_tok:,}\n")
                    f.write(f"- **Total Tokens:** {total_main_in_tok + total_main_out_tok:,}\n")
                    f.write(f"- **Input Cost:** ${total_main_in_cost:.4f}\n")
                    f.write(f"- **Output Cost:** ${total_main_out_cost:.4f}\n")
                    f.write(f"- **Total Cost:** ${total_main_in_cost + total_main_out_cost:.4f}\n")
                    f.write(f"- **Average Cost per Task:** ${(total_main_in_cost + total_main_out_cost) / task_count:.4f}\n")
                    f.write(f"- **Total Iterations:** {total_main_iterations}\n")
                    f.write(f"- **Average Iterations per Task:** {total_main_iterations / task_count if task_count > 0 else 0:.1f}\n")
                    f.write("\n")

                    # Postprocessor metrics (if used)
                    if total_pp_in_tok > 0 or total_pp_out_tok > 0:
                        f.write("**Postprocessor Metrics:**\n\n")
                        f.write(f"- **Total Input Tokens:** {total_pp_in_tok:,}\n")
                        f.write(f"- **Total Output Tokens:** {total_pp_out_tok:,}\n")
                        f.write(f"- **Total Tokens:** {total_pp_in_tok + total_pp_out_tok:,}\n")
                        f.write(f"- **Input Cost:** ${total_pp_in_cost:.4f}\n")
                        f.write(f"- **Output Cost:** ${total_pp_out_cost:.4f}\n")
                        f.write(f"- **Total Cost:** ${total_pp_in_cost + total_pp_out_cost:.4f}\n")
                        f.write(f"- **Average Cost per Task:** ${(total_pp_in_cost + total_pp_out_cost) / task_count:.4f}\n")
                        f.write(f"- **Total Iterations:** {total_pp_iterations}\n")
                        f.write(f"- **Average Iterations per Task:** {total_pp_iterations / task_count if task_count > 0 else 0:.1f}\n")
                        f.write("\n")

                    # Overall metrics
                    f.write("**Overall Metrics:**\n\n")
                    total_all_in = total_main_in_tok + total_pp_in_tok
                    total_all_out = total_main_out_tok + total_pp_out_tok
                    total_all_cost = total_main_in_cost + total_main_out_cost + total_pp_in_cost + total_pp_out_cost

                    f.write(f"- **Total Input Tokens:** {total_all_in:,}\n")
                    f.write(f"- **Total Output Tokens:** {total_all_out:,}\n")
                    f.write(f"- **Total Tokens:** {total_all_in + total_all_out:,}\n")
                    f.write(f"- **Total Input Cost:** ${total_main_in_cost + total_pp_in_cost:.4f}\n")
                    f.write(f"- **Total Output Cost:** ${total_main_out_cost + total_pp_out_cost:.4f}\n")
                    f.write(f"- **Total Cost:** ${total_all_cost:.4f}\n")
                    f.write(f"- **Average Cost per Task:** ${total_all_cost / task_count:.4f}\n")
                    f.write("\n")

                    # Cost breakdown
                    if total_all_cost > 0:
                        main_pct = (total_main_in_cost + total_main_out_cost) / total_all_cost * 100
                        pp_pct = (total_pp_in_cost + total_pp_out_cost) / total_all_cost * 100

                        f.write("**Cost Breakdown:**\n\n")
                        f.write(f"- **Main Agent:** ${total_main_in_cost + total_main_out_cost:.4f} ({main_pct:.1f}%)\n")
                        if total_pp_in_cost + total_pp_out_cost > 0:
                            f.write(f"- **Postprocessor:** ${total_pp_in_cost + total_pp_out_cost:.4f} ({pp_pct:.1f}%)\n")
                        f.write("\n")

        except Exception:
            # Don't fail if we can't append statistics
            pass
