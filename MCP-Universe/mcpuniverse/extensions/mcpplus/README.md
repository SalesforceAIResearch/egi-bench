# MCP+

> Intelligent post-processing for MCP tool outputs. Reduce token costs by up to 75%.

[![MCP-Universe](https://img.shields.io/badge/MCP-Universe-blue)]()
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)]()

## 🚀 Quick Start (CLI)

**Prerequisites:** Python 3.10+, OpenAI API key (or any other LLM provider)

```bash
# Install MCP-Universe
pip install mcpuniverse

# Set your API key
export OPENAI_API_KEY=sk-...

# Wrap your existing MCP servers
mcp-build-plus --mcp-config ~/.cursor/mcp.json

# This creates -plus versions of all your MCP servers
# (e.g., github → github-plus)
```

You must **Restart Cursor/Claude Code.** Your servers now have `-plus` versions with intelligent filtering.

### CLI Options

```bash
# Wrap specific servers only
mcp-build-plus --mcp-config ~/.cursor/mcp.json --servers github

# Adjust token threshold (MCP+ invoked for responses beyond this length)
mcp-build-plus --mcp-config ~/.cursor/mcp.json --token-threshold 500

# Add MCP Server specific token threshold
mcp-build-plus --mcp-config ~/.cursor/mcp.json --servers playwright --token-threshold 2000

# Use a different/cheaper model (default: gpt-4.1)
mcp-build-plus --mcp-config ~/.cursor/mcp.json --llm-model gpt-5-mini

# Use Gemini instead of OpenAI
mcp-build-plus --mcp-config ~/.cursor/mcp.json \
    --llm-provider gemini \
    --llm-model gemini-2.5-flash \
    --llm-api-key-env GOOGLE_API_KEY

# Use Anthropic instead of OpenAI
mcp-build-plus --mcp-config ~/.cursor/mcp.json \
    --llm-provider anthropic \
    --llm-model claude-haiku-4-5-20251001 \
    --llm-api-key-env ANTHROPIC_API_KEY

# Preview changes without applying
mcp-build-plus --mcp-config ~/.cursor/mcp.json --dry-run
```

| Option | Description | Default |
|--------|-------------|---------|
| `--mcp-config` | Path to your mcp.json config file | Required |
| `--servers` | Specific server names to wrap (space-separated) | All servers |
| `--llm-provider` | LLM provider: openai, gemini, anthropic, etc. | `openai` |
| `--llm-model` | LLM model for post-processing | `gpt-4.1` |
| `--llm-api-key-env` | Environment variable name for API key | `OPENAI_API_KEY` |
| `--token-threshold` | Min tokens to trigger post-processing | `500` |
| `--output` | Path to write updated config | Overwrite input |
| `--dry-run` | Preview changes without writing | - |
| `-y, --yes` | Skip confirmation prompt | - |

---

## 🎯 What is MCPPlus?

MCPPlus is a post-processing extension for MCP-Universe that intelligently filters and compresses tool outputs before they reach your LLM, dramatically reducing token costs without sacrificing quality.

### The Problem

MCP tools often return large, verbose outputs (web pages, API responses, file contents). Sending these directly to your LLM:
- 🧠 **Wastes context** - LLM sees irrelevant data, context is blocked through all agent iterations
- 💸 **Costs money** - Large context windows are expensive

### The Solution

MCPPlus wraps your MCP clients and uses a **dual post-processing agent** to perform:
1. **Direct Extraction** - LLM extracts key information directly as text
2. **Code Generation** - LLM generates Python code to filter/parse data
3. **Best of Both** - Returns both methods for robustness

**Result:** 50-70% token reduction with minimal quality loss.

---

## 📖 Programmatic Usage

For integration into your own code:

```python
from mcpuniverse.extensions.mcpplus.wrapper import MCPWrapperManager, WrapperConfig

# Create wrapper config
wrapper_config = WrapperConfig(
    enabled=True,
    token_threshold=2000,
    max_iterations=3
)

# Initialize manager
manager = MCPWrapperManager(
    config="path/to/server_config.json",
    wrapper_config=wrapper_config
)

# Your LLM
from mcpuniverse.llm import LLM
llm = LLM(config={"model_name": "gpt-5-mini"})
manager.set_llm(llm)

# Build wrapped client
client = await manager.build_client("your-mcp-server")

# Use normally - post-processing happens automatically!
result = await client.execute_tool(
    tool_name="fetch_webpage",
    arguments={
        "url": "https://example.com",
        "expected_info": "Extract the main article title and publish date"
    }
)
```

---

## 📖 Features

### Dual Post-Processing Agent

Generates **two** extraction methods in a single LLM call:

```python
# Direct extraction output:
"Title: 'Introduction to MCP'
Published: 2024-02-05"

# Code-based output:
{
  "title": "Introduction to MCP",
  "date": "2024-02-05"
}
```

### Transparent Wrapping

Drop-in replacement for standard MCP clients:

```python
# Before (standard MCP)
client = await manager.build_client("server")

# After (with MCPPlus)
manager = MCPWrapperManager(..., wrapper_config=config)
client = await manager.build_client("server")  # Same API!
```

### Intelligent Filtering

- **Token-aware** - Only processes outputs above threshold
- **Iterative refinement** - Retries if output is empty or too large
- **Safe execution** - Sandboxed code execution with timeout
- **Fallback handling** - Returns original output on failure

---

## ⚙️ Configuration

### WrapperConfig

```python
WrapperConfig(
    enabled: bool = False,                      # Enable wrapper
    token_threshold: int = 2000,                # Min tokens to trigger processing
    post_process_llm: Dict = gpt-5-mini,       # LLM for post-processing (defaults to gpt-5-mini)
    llm_timeout: int = 500,                     # LLM API call timeout (seconds)
    max_iterations: int = 3,                    # Max refinement iterations
    skip_iteration_on_size_failure: bool = False  # Return original if both outputs too large
)
```

### Expected Info Parameter

MCPPlus adds an `expected_info` parameter to all tools:

```python
result = await client.execute_tool(
    tool_name="search_web",
    arguments={
        "query": "Python tutorials",
        "expected_info": "List of tutorial URLs and their titles, needed to visit each page"
    }
)
```

---

## 🏗️ Architecture

```
┌─────────────┐
│   Agent     │
│   (GPT-5)   │
└──────┬──────┘
       │ Uses tool with expected_info
       ▼
┌─────────────────────────────────┐
│  MCPWrapperManager              │
│  ┌───────────────────────────┐ │
│  │ WrappedMCPClient          │ │
│  │  ├─ Call original tool    │ │
│  │  ├─ Check token threshold │ │
│  │  └─ Post-process if needed│ │
│  └───────────────────────────┘ │
└───────────────┬─────────────────┘
                │ Large output
                ▼
┌─────────────────────────────────┐
│  PostProcessAgent               │
│  ├─ Generate direct extraction  │
│  ├─ Generate filtering code     │
│  └─ Execute & return both       │
└───────────────┬─────────────────┘
                │ Filtered output
                ▼
┌─────────────┐
│   Agent     │ <- Receives concise result
└─────────────┘
```

### Components

**PostProcessAgent** (`agent/react_postprocess_agent.py`)
- Receives tool output and expected information
- Generates both direct extraction and Python code in one LLM call
- Executes code safely and returns formatted results
- Iterates if outputs are empty or too large

**MCPWrapperManager** (`wrapper/wrapper_manager.py`)
- Extends MCPManager from MCP-Universe
- Builds wrapped MCP clients with post-processing
- Manages LLM instances and configuration

**WrappedMCPClient** (`wrapper/wrapper_manager.py`)
- Wraps standard MCPClient
- Intercepts tool calls and extracts `expected_info`
- Triggers post-processing for large outputs
- Tracks statistics (tokens saved, iterations, etc.)

**SafeCodeExecutor** (`utils/safe_executor.py`)
- Sandboxed Python code execution
- Blacklist-based security (blocks eval, exec, os operations)
- Timeout protection
- Error handling with detailed context

---

## 📁 Project Structure

```
mcpuniverse/extensions/mcpplus/
├── agent/                          # Post-processing agent
│   ├── __init__.py
│   └── react_postprocess_agent.py  # Dual extraction agent
├── mcp/                            # MCP server components
│   ├── __init__.py
│   └── proxy_server.py             # FastMCP proxy for standalone operation
├── tools/                          # CLI tools
│   ├── __init__.py
│   └── wrap_mcp_config.py          # mcp-build-plus CLI tool
├── wrapper/                        # MCP client wrapper
│   ├── __init__.py
│   └── wrapper_manager.py          # Wrapper manager & client
├── benchmark/                      # Benchmark integration
│   ├── runner.py                   # Enhanced benchmark runner
│   ├── builder.py                  # Builder utilities
│   └── report.py                   # Report generation
├── utils/                          # Utilities
│   ├── __init__.py
│   ├── safe_executor.py            # Code execution sandbox
│   ├── stats.py                    # Token counting & stats
│   ├── tracer_analyzer.py          # Trace analysis
│   └── tracking_llm.py             # LLM usage tracking
├── examples/                       # Usage examples
│   ├── README.md
│   ├── basic_wrapper.py
│   ├── benchmark_integration.py
│   └── configs/
└── README.md                       # This file
```

---

## 📚 Examples

See [examples/](examples/) for complete examples:

- **[basic_wrapper.py](examples/basic_wrapper.py)** - Simple wrapper usage
- **[benchmark_integration.py](examples/benchmark_integration.py)** - Use with MCP-Universe benchmarks
- **[configs/simple_wrapper.yaml](examples/configs/simple_wrapper.yaml)** - Minimal configuration
- **[configs/benchmark_with_wrapper.yaml](examples/configs/benchmark_with_wrapper.yaml)** - Full benchmark config

---

## 🧪 Testing

Run tests:

```bash
# All MCPPlus tests
pytest tests/extensions/mcpplus/

# Specific component
pytest tests/extensions/mcpplus/agent/
pytest tests/extensions/mcpplus/wrapper/
pytest tests/extensions/mcpplus/utils/
```

---

## 📊 Benchmarking with MCPPlus

MCPPlus integrates seamlessly with MCP-Universe benchmarks. Add wrapper configuration to your benchmark YAML:

```yaml
kind: llm
spec:
  name: postprocessor-agent
  type: openai
  config:
    model_name: gpt-5-mini

---
kind: wrapper
spec:
  enabled: true
  token_threshold: 2000
  post_process_llm: postprocessor-agent
  max_iterations: 3
  llm_timeout: 500
  skip_iteration_on_size_failure: false

---
kind: llm
spec:
  name: main-agent
  type: openai
  config:
    model_name: gpt-5

---
kind: agent
spec:
  name: ReAct-agent
  type: react
  config:
    llm: main-agent
    instruction: You are a helpful assistant.
    servers:
      - name: your-mcp-server

---
kind: benchmark
spec:
  description: Test with MCPPlus post-processing
  agent: ReAct-agent
  tasks:
    - path/to/tasks/
```

The benchmark runner will automatically:
- Initialize MCPWrapperManager with your config
- Track post-processing statistics
- Include token savings in reports

---

## 🔬 How It Works: Detailed Walkthrough

### 1. Agent Makes Tool Call

```python
result = await client.execute_tool(
    tool_name="fetch_webpage",
    arguments={
        "url": "https://example.com/article",
        "expected_info": "Extract article title and publish date"
    }
)
```

### 2. WrappedMCPClient Intercepts

- Extracts `expected_info` parameter
- Calls original MCP tool
- Receives large HTML output (e.g., 50,000 characters)

### 3. Token Check

- Counts tokens in output (e.g., 12,000 tokens)
- Compares to `token_threshold` (2,000)
- If above threshold → trigger post-processing

### 4. PostProcessAgent Processes

Sends to LLM:
```
Tool: fetch_webpage
Output: [50,000 chars of HTML]
Agent's Goal: Extract article title and publish date

Provide BOTH extraction methods in JSON:
{
  "direct_extraction": "<text>",
  "code": "<python code>"
}
```

LLM Response:
```json
{
  "direct_extraction": "Title: 'Getting Started with MCP'\nPublished: 2024-02-05",
  "code": "import re\nhtml_content = data\ntitle = re.search(r'<h1>(.*?)</h1>', html_content).group(1)\ndate = re.search(r'Published: ([\\d-]+)', html_content).group(1)\nresult = f'Title: {title}\\nDate: {date}'"
}
```

### 5. Code Execution

- SafeCodeExecutor runs the generated code
- Returns: `"Title: Getting Started with MCP\nDate: 2024-02-05"`

### 6. Format & Return

```
================================================================================
DUAL EXTRACTION RESULTS
================================================================================

Two extraction methods were used. You can use either result,
or combine information from both as appropriate.

--------------------------------------------------------------------------------
DIRECT EXTRACTION:
--------------------------------------------------------------------------------
Title: 'Getting Started with MCP'
Published: 2024-02-05

--------------------------------------------------------------------------------
CODE-BASED EXTRACTION:
--------------------------------------------------------------------------------
Title: Getting Started with MCP
Date: 2024-02-05

================================================================================
```

**Token Savings:** 12,000 → 150 tokens (98.75% reduction!)

---

## 🤝 Contributing

MCPPlus is part of MCP-Universe. Check
[here](https://github.com/SalesforceAIResearch/MCP-Universe/blob/main/CONTRIBUTING.md).

---

## 🔗 Links

- [MCP-Universe Main Repository](../../../)
- [MCP-Universe Documentation](../../../README.md)
- [MCP Specification](https://spec.modelcontextprotocol.io)

---

### When to Use MCPPlus

✅ **Use when:**
- Tool outputs are large (>2000 tokens)
- You need specific information from verbose responses
- Token costs are a concern
- You're working with structured data (HTML, JSON, XML)

❌ **Skip when:**
- Tool outputs are already concise (<500 tokens)
- You need ALL information from the output
- Processing overhead exceeds token savings
- Real-time performance is critical

### Monitoring Performance

Track post-processing statistics:

```python
# Get aggregated stats
stats = manager.get_all_postprocessor_stats()

print(f"Tool calls processed: {stats['tool_calls_processed']}")
print(f"Total tokens saved: {stats['total_tokens_reduced']}")
print(f"Total iterations: {stats['total_iterations']}")
print(f"Average compression: {stats['tokens_reduced'] / stats['original_tokens'] * 100:.1f}%")
```

---

## ❓ FAQ

**Q: Does MCP+ work with all MCP servers?**
A: Yes! MCP+ wraps the MCP client layer, so it works with any MCP server regardless of implementation.

**Q: Does MCP+ work with all kinds of agents?**
A: Yes! MCP+ only intercepts the tool calls, so any agent using the standard MCP tool calls can use it.

**Q: What if post-processing fails?**
A: MCP+ always falls back to the original tool output. Your agent never receives an error due to post-processing failure.

**Q: Can I use a different LLM for post-processing?**
A: Yes! Post-processing defaults to `gpt-5-mini` for cost optimization. You can override this by setting `post_process_llm` in WrapperConfig to use a different model.

**Q: How much does post-processing cost?**
A: Each post-processing call uses ~1000-2000 tokens (prompt + response). However, if you save 10,000+ tokens on the main agent call, the net savings are substantial. See https://mcp-plus.github.io/#results for a detailed comparison of the input costs.

