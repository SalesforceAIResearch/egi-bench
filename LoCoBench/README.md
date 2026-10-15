# LoCoBench: A Benchmark for Long-Context Large Language Models in Complex Software Engineering

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![arXiv](https://img.shields.io/badge/arXiv-2509.09614-b31b1b.svg)](https://arxiv.org/abs/2509.09614)

**LoCoBench** is a comprehensive benchmark specifically designed to evaluate long-context Large Language Models (LLMs) in complex software development scenarios. It provides **8,000 evaluation scenarios** across **10 programming languages** with context lengths spanning **10K to 1M tokens**.

- **Paper**: [arXiv:2509.09614](https://arxiv.org/abs/2509.09614)
- **Original repo**: [SalesforceAIResearch/LoCoBench](https://github.com/SalesforceAIResearch/LoCoBench)

## Running via egi-bench (recommended)

LoCoBench is registered as a benchmark in the [EGI-Bench](../README.md) suite.
From the repository root, after [`egi-bench setup`](../README.md#5-install-benchmark-environments)
provisions `LoCoBench/.venv`, downloads the evaluation data, and the
[local LiteLLM proxy is running](../README.md#4-start-the-local-litellm-proxy):

```bash
# Quick mode: easy difficulty, 30 scenarios, all categories
egi-bench run --model gpt-4o-mini --mode quick --benchmarks locobench

# Deep mode: all difficulties, 300 scenarios, all categories
egi-bench run --model gpt-4o-mini --mode deep --benchmarks locobench
```

Per-mode `difficulty`, `num_scenarios`, `task_categories`,
`max_concurrent_scenarios`, and `timeout_seconds` live in
[`benchmark_config.yaml`](../benchmark_config.yaml) under
`benchmarks.locobench`.

## Standalone Quick Start

Use these steps only when developing LoCoBench in isolation;
`egi-bench setup` already runs the `uv venv` + dependency install + data
download for you.

### Prerequisites

- Python 3.12+ and `uv` package manager
- Local LiteLLM proxy running at `http://localhost:8008` (see `../litellm_proxy/`)

### Setup

```bash
cd LoCoBench

# Create virtual environment and install dependencies
uv venv
uv pip install -r requirements.txt
uv pip install -e .

# Download evaluation data (250MB)
uv pip install gdown
uv run gdown 'https://drive.google.com/uc?id=1pK1M1sRrVZUDMKYcwh49CdXug0UzStvl'
unzip data.zip && rm data.zip
```

### Run Evaluation via the local LiteLLM proxy

The wrapper script routes through the LiteLLM proxy described in
[`../litellm_proxy/README.md`](../litellm_proxy/README.md).

```bash
# Quick test (easy difficulty, default gpt-5-nano)
uv run python run_eval_litellm.py

# Custom model and difficulty
uv run python run_eval_litellm.py --model gpt-5-nano --difficulty medium

# Specific task category
uv run python run_eval_litellm.py --model gpt-5-nano --task-category bug_investigation

# Full evaluation (all difficulties, all categories)
uv run python run_eval_litellm.py --model gpt-5-nano --full
```

### Run Evaluation via CLI (Direct API Keys)

```bash
# Configure API keys
cp api.sh.template api.sh
# Edit api.sh with your keys, then:
source api.sh

# Evaluate a single model
uv run locobench evaluate --model gpt-4o --config-path config.yaml

# Evaluate specific task categories
uv run locobench evaluate --model claude-sonnet-4 --task-category architectural_understanding --difficulty hard
```

## Benchmark Overview

### Scale

- **8,000** evaluation scenarios
- **10** programming languages: Python, C++, Java, C, C#, JavaScript, TypeScript, Go, Rust, PHP
- **8** task categories across 4 difficulty levels
- Context lengths: **10K to 1M tokens**

### Task Categories

| Category                    | Description                       |
| --------------------------- | --------------------------------- |
| Architectural Understanding | Deep architectural analysis       |
| Cross-File Refactoring      | Multi-file code restructuring     |
| Feature Implementation      | Complex feature development       |
| Bug Investigation           | Real-world debugging scenarios    |
| Multi-Session Development   | Long-term development projects    |
| Code Comprehension          | Large codebase understanding      |
| Integration Testing         | System integration validation     |
| Security Analysis           | Security vulnerability assessment |

### LoCoBench Score (LCBS)

Unified score (0-5 scale) combining 17 metrics across 4 dimensions:

| Dimension                       | Weight | Metrics                                         |
| ------------------------------- | ------ | ----------------------------------------------- |
| Software Engineering Excellence | 40%    | ACS, DTA, CFRD, STS, RS, CS, IS, SES            |
| Functional Correctness          | 30%    | Compilation, Unit Tests, Integration Tests, IDC |
| Code Quality Assessment         | 20%    | Security Analysis, Code Issues, Style Adherence |
| Long-Context Utilization        | 10%    | ICU, MMR                                        |

### Difficulty Levels

| Level  | Context Range      |
| ------ | ------------------ |
| Easy   | 10K - 100K tokens  |
| Medium | 100K - 200K tokens |
| Hard   | 200K - 500K tokens |
| Expert | 500K - 1M tokens   |

## File Structure

```
LoCoBench/
├── README.md                       # This file
├── run_eval_litellm.py             # LiteLLM-proxy evaluation wrapper
├── config.yaml                     # Pipeline configuration
├── api.sh.template                 # API key template
├── requirements.txt                # Python dependencies
├── setup.py                        # Package setup
├── locobench/                      # Core package
│   ├── cli.py                      # CLI entry point (locobench command)
│   ├── core/                       # Config, task definitions, metrics
│   ├── evaluation/                 # Evaluation pipeline
│   ├── generation/                 # Scenario generation (Phases 1-4)
│   ├── analysis/                   # AST, complexity, dependency analysis
│   ├── utils/                      # LLM parsing, rate limiting
│   └── validation/                 # Code validation
├── data/                           # Evaluation data (downloaded separately)
│   ├── generated/                  # Generated codebases (1,000 projects)
│   └── output/scenarios/           # 8,000 evaluation scenarios
├── evaluation_results/             # Output directory for results
├── LoCoBench_generation.md         # Generation pipeline guide
└── LICENSE.txt                     # Apache 2.0
```

## Results

Results are saved in `evaluation_results/`:

```
evaluation_results/
├── <model>_evaluation_results.json          # Detailed results
└── <model>_evaluation_results_summary.md    # Human-readable summary
```

## Citation

```bibtex
@article{Qiu2025LoCoBenchAB,
  title={LoCoBench: A Benchmark for Long-Context Large Language Models in Complex Software Engineering},
  author={Jielin Qiu and Zuxin Liu and Zhiwei Liu and Rithesh Murthy and Jianguo Zhang and Haolin Chen and Shiyu Wang and Ming Zhu and Liangwei Yang and Juntao Tan and Zhepeng Cen and Cheng Qian and Shelby Heinecke and Weiran Yao and Silvio Savarese and Caiming Xiong and Huan Wang},
  journal={ArXiv},
  year={2025},
  volume={abs/2509.09614}
}
```

## License

Apache License 2.0 - see [LICENSE.txt](LICENSE.txt).
