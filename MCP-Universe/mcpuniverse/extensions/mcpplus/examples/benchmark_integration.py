"""
MCPPlus Benchmark Integration Example

This example demonstrates how to run MCP-Universe benchmarks with MCPPlus
post-processing enabled.

Prerequisites:
- MCP-Universe installed: pip install mcpuniverse
- Benchmark config file (see examples/configs/benchmark_with_wrapper.yaml)
- API keys set in .env file
"""
import asyncio
from mcpuniverse.extensions.mcpplus.benchmark.benchmark_runner import BenchmarkRunnerWithWrapper
from mcpuniverse.tracer.collectors import MemoryCollector
from mcpuniverse.callbacks.handlers.vprint import get_vprint_callbacks


async def main():
    """
    Run a benchmark with MCPPlus post-processing enabled.

    The benchmark config includes wrapper configuration, which will
    automatically enable post-processing for all tool calls during the benchmark.
    """
    print("=" * 80)
    print("MCPPlus Benchmark Integration Example")
    print("=" * 80)

    # Step 1: Initialize trace collector
    print("\n1. Initializing trace collector...")
    trace_collector = MemoryCollector()
    print("   ✓ Memory collector ready")

    # Step 2: Load benchmark with wrapper config
    print("\n2. Loading benchmark configuration...")
    # This config includes wrapper configuration
    benchmark = BenchmarkRunnerWithWrapper("examples/configs/benchmark_with_wrapper.yaml")
    print("   ✓ Benchmark loaded")

    # Display benchmark info
    if benchmark._benchmark_configs:
        first_benchmark = benchmark._benchmark_configs[0]
        print(f"   Agent: {first_benchmark.agent}")
        print(f"   Tasks: {len(first_benchmark.tasks)} tasks")

    # Step 3: Run the benchmark
    print("\n3. Running benchmark with post-processing...")
    print("   This may take a few minutes depending on task complexity")
    print("-" * 80)

    # Get verbose print callbacks for nice formatting
    vprint_callbacks = get_vprint_callbacks()

    try:
        results = await benchmark.run(
            trace_collector=trace_collector,
            callbacks=vprint_callbacks
        )

        print("-" * 80)
        print("\n4. Benchmark Results:")
        print(f"   Total benchmarks: {len(results)}")

        # Display results (results are BenchmarkResult objects with task_results)
        for i, result in enumerate(results, 1):
            print(f"\n   Benchmark {i}:")
            if hasattr(result, 'task_results') and result.task_results:
                passed = 0
                total = len(result.task_results)
                for task_path, task_data in result.task_results.items():
                    task_name = task_path.split('/')[-1]
                    eval_results = task_data.get("evaluation_results", [])
                    if eval_results and all(r.passed for r in eval_results):
                        passed += 1
                        print(f"     ✓ {task_name}")
                    else:
                        print(f"     ✗ {task_name}")

                success_rate = (passed / total) * 100 if total > 0 else 0
                print(f"   Tasks passed: {passed}/{total} ({success_rate:.1f}%)")

    except Exception as e:
        print(f"\n❌ Benchmark failed: {e}")
        print("   Check:")
        print("   - Benchmark config is valid")
        print("   - MCP servers are accessible")
        print("   - API keys are configured")
        return

    # Step 5: Analyze post-processing statistics
    print("\n5. Post-Processing Statistics:")

    # Aggregate statistics from task results
    if results and results[0].task_results:
        total_main_tokens = 0
        total_pp_tokens = 0
        total_main_cost = 0.0
        total_pp_cost = 0.0
        total_pp_iterations = 0
        task_count = 0

        for result in results:
            for task_data in result.task_results.values():
                stats = task_data.get("statistics", {})
                total_main_tokens += stats.get("main_agent_total_tokens", 0)
                total_pp_tokens += stats.get("postprocessor_total_tokens", 0)
                total_main_cost += stats.get("main_agent_total_cost", 0.0)
                total_pp_cost += stats.get("postprocessor_total_cost", 0.0)
                total_pp_iterations += stats.get("postprocessor_iterations", 0)
                task_count += 1

        print(f"   Total tasks: {task_count}")
        print(f"   Main agent tokens: {total_main_tokens:,}")
        print(f"   Postprocessor tokens: {total_pp_tokens:,}")
        print(f"   Total tokens: {total_main_tokens + total_pp_tokens:,}")
        print(f"   Main agent cost: ${total_main_cost:.4f}")
        print(f"   Postprocessor cost: ${total_pp_cost:.4f}")
        print(f"   Total cost: ${total_main_cost + total_pp_cost:.4f}")
        print(f"   Postprocessor iterations: {total_pp_iterations}")

        if total_pp_cost > 0:
            cost_ratio = (total_pp_cost / (total_main_cost + total_pp_cost)) * 100
            print(f"   Postprocessor cost ratio: {cost_ratio:.1f}%")
    else:
        print("   No statistics available")

    # Step 6: Analyze traces
    print("\n6. Trace Analysis:")
    if results:
        # Get first task's trace
        first_result = results[0]
        if hasattr(first_result, 'task_trace_ids') and first_result.task_trace_ids:
            first_task = list(first_result.task_trace_ids.keys())[0]
            trace_id = first_result.task_trace_ids[first_task]
            trace_records = trace_collector.get(trace_id)

            print(f"   Trace records for first task: {len(trace_records)}")
            print(f"   Trace ID: {trace_id}")

            # Count different record types
            record_types = {}
            for trace_record in trace_records:
                # TraceRecord has a 'records' field containing actual execution records
                if hasattr(trace_record, 'records'):
                    for record in trace_record.records:
                        data = record.data if hasattr(record, 'data') else record
                        record_type = data.get('type', 'unknown')
                        record_types[record_type] = record_types.get(record_type, 0) + 1

            if record_types:
                print("   Record types:")
                for rtype, count in record_types.items():
                    print(f"     - {rtype}: {count}")
            else:
                print("   No record data available")
        else:
            print("   No trace IDs available")
    else:
        print("   No results to analyze")

    # Step 7: Generate report (optional)
    print("\n7. Generating Report:")
    try:
        from mcpuniverse.extensions.mcpplus.benchmark.report import BenchmarkReportWithWrapper

        report = BenchmarkReportWithWrapper(benchmark, trace_collector=trace_collector)
        report_path = report.dump()
        print(f"   ✓ Report saved to: {report_path}")
    except Exception as e:
        print(f"   ⚠️  Could not generate report: {e}")

    print("\n" + "=" * 80)
    print("Benchmark complete!")
    print("\nKey Takeaways:")
    print("- MCPPlus automatically post-processes tool outputs during benchmarks")
    print("- Token savings are tracked and included in statistics")
    print("- No changes needed to benchmark tasks or agent code")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
