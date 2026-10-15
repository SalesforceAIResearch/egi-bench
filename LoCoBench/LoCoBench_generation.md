# LoCoBench Generation Pipeline (Phases 1-4)

This guide covers how to generate custom evaluation scenarios using LoCoBench's 5-phase pipeline. For evaluation only, see the main [README.md](README.md).

## Overview

LoCoBench's generation pipeline creates comprehensive evaluation scenarios through 4 systematic phases:

1. **Phase 1**: Project Specification Generation
2. **Phase 2**: Codebase Generation  
3. **Phase 3**: Evaluation Scenario Creation
4. **Phase 4**: Validation and Quality Assurance

## Prerequisites

### System Requirements

- Python 3.8+
- Docker (for code validation)
- At least 16GB RAM (32GB recommended for large-scale generation)
- 100GB+ free disk space

### Additional Dependencies

```bash
# Install generation-specific dependencies
pip install -r requirements-generation.txt

# Install language-specific compilers and tools
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y gcc g++ openjdk-17-jdk nodejs npm python3-dev

# macOS
brew install gcc openjdk@17 node python@3.11

# Install language-specific linters and analyzers
pip install flake8 mypy bandit
npm install -g eslint @typescript-eslint/parser
```

## Phase 1: Project Specification Generation

Generate diverse project specifications across programming languages and domains.

### Basic Usage

```bash
# Generate 100 specifications per language (1,000 total)
locobench generate --phase 1 --config-path config.yaml

# Generate for specific languages only
locobench generate --phase 1 --languages python,java,cpp --count 50

# Generate with custom parameters
locobench generate --phase 1 \
    --languages python \
    --domains web_applications,ml_systems \
    --complexity-levels easy,medium \
    --count 100
```

### Configuration

Edit `config.yaml` for generation settings:

```yaml
generation:
  phase1:
    specifications_per_language: 100
    domains:
      - web_applications
      - api_services
      - data_systems
      - ml_ai_systems
      - gaming_simulation
      - blockchain_systems
      - desktop_applications
      - mobile_applications
      - system_infrastructure
      - financial_technology
    
    complexity_distribution:
      easy: 0.25
      medium: 0.25
      hard: 0.25
      expert: 0.25
    
    architecture_patterns:
      - monolithic
      - microservices
      - serverless
      - event_driven
      - layered
      - clean_architecture
      - hexagonal
      - mvc
      - mvvm
      - component_based
    
    themes:
      - business
      - education
      - healthcare
      - entertainment
      - productivity
      - social
      - utility
      - creative
```

### Output

Phase 1 generates specifications in `data/generated/specifications/`:

```
data/generated/specifications/
├── python_web_ecommerce_easy_001.json
├── java_api_graphql_medium_002.json
├── cpp_system_monitoring_hard_003.json
└── rust_data_analytics_expert_004.json
```

Each specification contains:

```json
{
  "unique_id": "python_web_ecommerce_easy_001",
  "name": "E-commerce Platform",
  "description": "A comprehensive e-commerce solution...",
  "domain": "web_ecommerce",
  "complexity": "easy",
  "language": "python",
  "architecture": "mvc",
  "theme": "business",
  "target_file_count": 25,
  "target_token_count": 45000,
  "features": ["user_auth", "payment_processing", "inventory_management"],
  "architecture_patterns": ["MVC", "Repository_Pattern", "Service_Layer"]
}
```

## Phase 2: Codebase Generation

Transform specifications into complete, executable codebases.

### Basic Usage

```bash
# Generate codebases from all specifications
locobench generate --phase 2 --config-path config.yaml

# Generate with parallel processing
locobench generate --phase 2 --config-path config.yaml -j 10

# Generate for specific specifications
locobench generate --phase 2 --input-specs data/generated/specifications/python_*.json
```

### Advanced Configuration

```yaml
generation:
  phase2:
    max_concurrent: 10
    timeout_per_project: 1800  # 30 minutes
    
    # Language-specific settings
    language_configs:
      python:
        framework_preferences: ["django", "flask", "fastapi"]
        testing_framework: "pytest"
        style_guide: "pep8"
      
      java:
        framework_preferences: ["spring", "quarkus"]
        build_system: "maven"
        java_version: 17
      
      cpp:
        standard: "c++17"
        build_system: "cmake"
        compiler: "gcc"
    
    # Quality thresholds
    quality_gates:
      min_compilation_success: 0.95
      max_cyclomatic_complexity: 10
      min_documentation_coverage: 0.7
```

### Monitoring Generation

```bash
# Monitor generation progress
locobench monitor --phase 2

# View detailed generation logs
tail -f logs/generation_phase2.log

# Check generation statistics
locobench stats --phase 2
```

### Output

Phase 2 generates complete codebases in `data/generated/codebases/`:

```
data/generated/codebases/
├── python_web_ecommerce_easy_001/
│   ├── manage.py
│   ├── requirements.txt
│   ├── ecommerce_project/
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── apps/
│   │   ├── accounts/
│   │   ├── products/
│   │   └── orders/
│   └── tests/
└── java_api_graphql_medium_002/
    ├── pom.xml
    ├── src/main/java/
    └── src/test/java/
```

## Phase 3: Evaluation Scenario Creation

Convert codebases into targeted evaluation scenarios.

### Basic Usage

```bash
# Generate scenarios from all codebases
locobench generate --phase 3 --config-path config.yaml

# Generate specific task categories
locobench generate --phase 3 --task-categories architectural_understanding,bug_investigation

# Generate with custom difficulty scaling
locobench generate --phase 3 --difficulty-scaling custom --config custom_difficulty.yaml
```

### Task Categories

LoCoBench supports 8 task categories:

1. **Architectural Understanding**: System design pattern recognition
2. **Cross-File Refactoring**: Multi-file code restructuring
3. **Feature Implementation**: New functionality integration
4. **Bug Investigation**: Systematic debugging and root cause analysis
5. **Multi-Session Development**: Context retention across sessions
6. **Code Comprehension**: Deep codebase understanding
7. **Integration Testing**: Component interaction testing
8. **Security Analysis**: Vulnerability assessment

### Context Selection Configuration

```yaml
generation:
  phase3:
    context_selection:
      algorithm: "graph_theoretic"  # Options: random, importance_based, graph_theoretic
      
      # Context length targets by difficulty
      context_targets:
        easy: [10000, 100000]      # 10K-100K tokens
        medium: [100000, 200000]   # 100K-200K tokens  
        hard: [200000, 500000]     # 200K-500K tokens
        expert: [500000, 1000000]  # 500K-1M tokens
      
      # File selection criteria
      selection_criteria:
        dependency_centrality: 0.4
        architectural_importance: 0.3
        task_relevance: 0.2
        information_density: 0.1
      
      # Quality thresholds
      min_information_coverage: 0.7
      max_redundancy_ratio: 0.3
```

### Advanced Scenario Customization

```python
# Custom scenario generation script
from locobench.generation.scenario_generator import ScenarioGenerator

generator = ScenarioGenerator(config_path="custom_config.yaml")

# Generate scenarios with custom parameters
scenarios = generator.generate_scenarios(
    codebase_path="data/generated/codebases/python_web_ecommerce_easy_001",
    task_categories=["architectural_understanding", "feature_implementation"],
    difficulty_levels=["medium", "hard"],
    custom_prompts={
        "architectural_understanding": "Focus on microservices patterns...",
        "feature_implementation": "Implement OAuth2 authentication..."
    }
)
```

### Output

Phase 3 generates scenarios in `data/generated/scenarios/`:

```
data/generated/scenarios/
├── python_web_ecommerce_easy_001_architectural_understanding_medium.json
├── python_web_ecommerce_easy_001_feature_implementation_hard.json
├── java_api_graphql_medium_002_bug_investigation_expert.json
└── ...
```

Each scenario contains:

```json
{
  "id": "python_web_ecommerce_easy_001_architectural_understanding_medium",
  "task_category": "architectural_understanding",
  "difficulty": "medium",
  "title": "Identify Authentication Architecture Pattern",
  "description": "Analyze the authentication system...",
  "context_files": [
    "apps/accounts/models.py",
    "apps/accounts/views.py",
    "apps/accounts/serializers.py"
  ],
  "context_length": 125000,
  "task_prompt": "Based on the provided files, identify...",
  "expected_approach": "An expert developer would...",
  "evaluation_criteria": ["Correct pattern identification", "Understanding of flow"]
}
```

## Phase 4: Validation and Quality Assurance

Ensure generated scenarios meet quality standards.

### Basic Usage

```bash
# Validate all generated scenarios
locobench validate --config-path config.yaml

# Validate with parallel processing
locobench validate --config-path config.yaml --max-concurrent 20

# Validate specific scenarios
locobench validate --input-scenarios "data/generated/scenarios/python_*.json"
```

### Validation Pipeline

Phase 4 performs comprehensive validation:

1. **Compilation Validation**
   ```bash
   # Language-specific compilation checks
   python -m py_compile *.py                    # Python
   javac -cp classpath *.java                  # Java
   g++ -std=c++17 -Wall -Wextra *.cpp         # C++
   cargo check --all-targets                   # Rust
   ```

2. **Code Quality Analysis**
   ```bash
   # Static analysis and linting
   flake8 --max-line-length=100 *.py          # Python style
   eslint --ext .js,.ts src/                   # JavaScript/TypeScript
   cppcheck --enable=all src/                  # C++ static analysis
   ```

3. **Architectural Consistency**
   ```bash
   # Verify architectural patterns
   locobench analyze-architecture --codebase path/to/codebase --expected-pattern mvc
   ```

4. **Information Coverage**
   ```bash
   # Analyze scenario information coverage
   locobench analyze-coverage --scenario path/to/scenario.json --min-coverage 0.7
   ```

### Quality Configuration

```yaml
validation:
  compilation:
    required_success_rate: 0.95
    timeout_per_file: 30
    
  complexity:
    max_cyclomatic_complexity: 15
    max_nesting_depth: 6
    
  coverage:
    min_information_coverage: 0.7
    max_redundancy_ratio: 0.3
    
  bias_detection:
    check_naming_patterns: true
    check_structural_uniformity: true
    check_content_repetition: true
    
  filtering:
    auto_remove_failed: true
    manual_review_threshold: 0.8
```

### Validation Reports

Phase 4 generates detailed validation reports:

```
data/validation/
├── validation_summary.html
├── compilation_results.json
├── quality_metrics.csv
├── failed_scenarios.json
└── bias_analysis.json
```

### Handling Validation Failures

```bash
# Review failed scenarios
locobench review-failures --input data/validation/failed_scenarios.json

# Regenerate failed scenarios
locobench regenerate --input data/validation/failed_scenarios.json --phase 2,3

# Manual quality review
locobench manual-review --scenarios data/generated/scenarios/ --reviewer-mode
```

## Complete Pipeline Execution

### Run All Phases

```bash
# Execute complete generation pipeline
locobench generate-all --config-path config.yaml --output-dir custom_benchmark

# With custom parameters
locobench generate-all \
    --config-path config.yaml \
    --languages python,java,cpp \
    --count-per-language 50 \
    --parallel-jobs 8 \
    --output-dir my_locobench
```

### Pipeline Monitoring

```bash
# Monitor entire pipeline
locobench monitor-pipeline --pipeline-id pipeline_20240115_143022

# View comprehensive statistics
locobench pipeline-stats --pipeline-id pipeline_20240115_143022
```

### Resume Interrupted Pipeline

```bash
# Resume from checkpoint
locobench generate-all --resume-from checkpoint_phase2_20240115_143022.json

# Resume specific phase
locobench generate --phase 3 --resume-from data/checkpoints/phase2_complete.json
```

## Performance Optimization

### Parallel Processing

```bash
# Optimize for your hardware
locobench generate-all \
    --parallel-jobs $(nproc) \
    --memory-limit 32GB \
    --disk-cache-size 10GB
```

### Resource Monitoring

```bash
# Monitor resource usage
locobench monitor-resources --pipeline-id current

# Set resource limits
locobench generate --phase 2 --memory-limit 16GB --cpu-limit 8
```

## Troubleshooting

### Common Issues

1. **Out of Memory**
   ```bash
   # Reduce parallel jobs and enable disk caching
   locobench generate --phase 2 -j 4 --disk-cache --memory-limit 8GB
   ```

2. **Compilation Failures**
   ```bash
   # Debug compilation issues
   locobench debug-compilation --codebase path/to/failing/codebase --verbose
   ```

3. **Context Selection Issues**
   ```bash
   # Adjust context selection parameters
   locobench generate --phase 3 --context-algorithm importance_based --min-coverage 0.6
   ```

### Getting Help

- Check the [main README](README.md) for general troubleshooting
- Open an issue on [GitHub](https://github.com/SalesforceAIResearch/LoCoBench/issues)
- Join discussions on [GitHub Discussions](https://github.com/SalesforceAIResearch/LoCoBench/discussions)

## Custom Extensions

### Adding New Programming Languages

```python
# Extend language support
from locobench.generation.language_config import LanguageConfig

class GoLanguageConfig(LanguageConfig):
    def __init__(self):
        super().__init__("go")
        self.file_extension = ".go"
        self.compiler_command = "go build"
        self.test_framework = "testing"
        self.style_checker = "gofmt"
```

### Custom Task Categories

```python
# Add new task category
from locobench.generation.task_generator import TaskGenerator

class CustomTaskGenerator(TaskGenerator):
    def generate_performance_optimization_task(self, codebase, difficulty):
        # Implement custom task generation logic
        pass
```

### Integration with CI/CD

```yaml
# GitHub Actions example
name: LoCoBench Generation
on: [push]
jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install LoCoBench
        run: pip install -e .
      - name: Generate Scenarios
        run: locobench generate-all --config ci_config.yaml
```

---

This completes the comprehensive generation guide. For evaluation and analysis, see the main [README.md](README.md).
