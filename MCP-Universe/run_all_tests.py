"""
Run all MCP-Universe test configs and report results.
"""
import asyncio
import sys
import traceback
from mcpuniverse.benchmark.runner import BenchmarkRunner


TEST_CONFIGS = [
    ("location_navigation", "mcpuniverse/benchmark/configs/mcpuniverse/location_navigation_test.yaml"),
    ("financial_analysis", "mcpuniverse/benchmark/configs/mcpuniverse/financial_analysis_test.yaml"),
    ("repository_management", "mcpuniverse/benchmark/configs/mcpuniverse/repository_management_test.yaml"),
    ("browser_automation", "mcpuniverse/benchmark/configs/mcpuniverse/browser_automation_test.yaml"),
]


async def run_one(name, config_path):
    print(f"\n{'='*60}")
    print(f"  Running: {name}")
    print(f"{'='*60}")
    try:
        runner = BenchmarkRunner(config_path)
        results = await runner.run(store_folder=f"results/{name}_test")
        task_results = {}
        for br in results:
            for task_path, task_result in br.task_results.items():
                evals = task_result["evaluation_results"]
                all_passed = all(er.passed for er in evals)
                reasons = [er.reason for er in evals if er.reason]
                errors = [er.error for er in evals if er.error]
                task_results[task_path] = {
                    "passed": all_passed,
                    "reasons": reasons,
                    "errors": errors,
                    "response": evals[0].response[:200] if evals else "",
                }
        return name, task_results, None
    except Exception as e:
        traceback.print_exc()
        return name, {}, str(e)


async def main():
    # Run configs specified on command line, or all
    configs_to_run = TEST_CONFIGS
    if len(sys.argv) > 1:
        names = sys.argv[1:]
        configs_to_run = [(n, c) for n, c in TEST_CONFIGS if n in names]

    all_results = {}
    for name, config_path in configs_to_run:
        name, task_results, error = await run_one(name, config_path)
        all_results[name] = {"tasks": task_results, "error": error}

    # Print summary
    print(f"\n\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    for name, data in all_results.items():
        if data["error"]:
            print(f"\n  {name}: ERROR - {data['error']}")
            continue
        tasks = data["tasks"]
        total = len(tasks)
        passed = sum(1 for t in tasks.values() if t["passed"])
        print(f"\n  {name}: {passed}/{total} passed")
        for task_path, info in tasks.items():
            status = "PASS" if info["passed"] else "FAIL"
            short_path = task_path.split("/")[-1]
            print(f"    [{status}] {short_path}")
            if info["reasons"]:
                print(f"           Reasons: {'; '.join(info['reasons'][:2])}")
            if info["errors"]:
                print(f"           Errors: {'; '.join(info['errors'][:2])}")
            if not info["passed"]:
                print(f"           Response: {info['response'][:100]}...")

    print(f"\n{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
