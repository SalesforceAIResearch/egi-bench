# MCP+ Examples

This directory contains practical examples demonstrating how to use MCP+ with MCP-Universe.

## Quick Start

All examples assume you have:
1. ✅ MCP-Universe installed: `pip install mcpuniverse`
2. ✅ MCP servers configured in `configs/server_list.json`
3. ✅ API keys set in `.env` file

## Examples

### 1. Basic Wrapper Usage
**File:** [basic_wrapper.py](basic_wrapper.py)

Minimal example showing how to wrap an MCP client with post-processing.

```bash
python examples/basic_wrapper.py
```

**What it demonstrates:**
- Creating a `WrapperConfig`
- Initializing `MCPWrapperManager`
- Setting a post-processing LLM
- Building wrapped clients
- Using `expected_info` parameter
- Viewing post-processing statistics

**Key takeaway:** Drop-in replacement for standard MCP clients.

---

### 2. Benchmark Integration
**File:** [benchmark_integration.py](benchmark_integration.py)

Run MCP-Universe benchmarks with MCP+ post-processing enabled.

```bash
python examples/benchmark_integration.py
```

**What it demonstrates:**
- Loading benchmark configs with wrapper settings
- Running benchmarks with automatic post-processing
- Analyzing token savings
- Generating reports with statistics
- Estimating cost savings

**Key takeaway:** No agent code changes needed - just add wrapper config to YAML.

---

## Configuration Examples

### Minimal Wrapper Config
**File:** [configs/simple_wrapper.yaml](configs/simple_wrapper.yaml)

```yaml
kind: llm
spec:
  name: llm-postprocess
  type: openai
  config:
    model_name: gpt-5-mini

---
kind: wrapper
spec:
  enabled: true
  token_threshold: 2000
  post_process_llm: llm-postprocess
  max_iterations: 3
  llm_timeout: 500
```

**When to use:** Adding post-processing to any MCP client setup.

---

### Full Benchmark Config
**File:** [configs/benchmark_with_wrapper.yaml](configs/benchmark_with_wrapper.yaml)

Complete benchmark configuration with:
- Main LLM for agent (`gpt-4o`)
- Separate post-processing LLM (`gpt-4o-mini`)
- Wrapper configuration
- Agent and task definitions

**When to use:** Running benchmarks with cost optimization.

**Key difference from standard config:**
```yaml
# Standard MCP-Universe benchmark: Just llm-main
# MCPPlus benchmark: Adds these blocks:

kind: llm
spec:
  name: llm-postprocess        # New: cheaper LLM for filtering
  type: openai
  config:
    model_name: gpt-5-mini

---
kind: wrapper                  # New: enable post-processing
spec:
  enabled: true
  post_process_llm: llm-postprocess
```

Everything else stays the same!

---

## Understanding `expected_info`

MCPPlus adds an `expected_info` parameter to all tool calls. The quality of post-processing depends on clear descriptions.  

### Good Examples

✅ **Specific + Purpose + Context:**
```python
"expected_info": "Extract the top 5 product names and prices from the search results, needed to compare options for user"
```

✅ **Clear scope:**
```python
"expected_info": "Get only the article title and publish date from the page header, needed to cite the source"
```

✅ **All information needed:**
```python
"expected_info": "All information is needed because I must analyze the complete page structure to locate navigation menu"
```

### Bad Examples

❌ **Too vague:**
```python
"expected_info": "get information"
```

❌ **Missing context:**
```python
"expected_info": "price"
```

❌ **No purpose:**
```python
"expected_info": "check the page"
```

---

## Cost Optimization Tips

### 1. Use Cheaper Post-Processing LLM

```yaml
# Main agent: expensive but capable
llm-main: gpt-5

# Post-processor: cheap and sufficient
llm-postprocess: gpt-5-mini 
```

### 2. Set Appropriate Threshold

```yaml
token_threshold: 2000  # Only process large outputs
```

- Too low (e.g., 500): Process too many outputs, higher post-processing cost
- Too high (e.g., 10000): Miss optimization opportunities
- Sweet spot: 1500-2500 tokens

### 3. Monitor Statistics

```python
stats = manager.get_all_postprocessor_stats()
print(f"Tokens saved: {stats['total_tokens_reduced']}")
print(f"Cost saved: ${(stats['total_tokens_reduced'] / 1000) * 0.03:.2f}")
```

---

## Troubleshooting

### "Module 'mcp' not found"

Install MCP SDK:
```bash
pip install mcp
```

### "Module 'tiktoken' not found"

Install tiktoken for token counting:
```bash
pip install tiktoken
```

### Post-processing not triggering

Check:
1. `wrapper.enabled = True` in config
2. Tool output exceeds `token_threshold`
3. `expected_info` parameter is provided
4. LLM is set via `manager.set_llm()`

### Code execution errors

The `SafeCodeExecutor` blocks dangerous operations. If legitimate code fails:
1. Check execution timeout (default: 10s)
2. Verify code doesn't use blacklisted operations
3. Check logs for specific error messages

---

## Running the Examples

### Basic Wrapper

```bash
# Navigate to MCP+ directory
cd mcpuniverse/extensions/mcpplus

# Run example
python examples/basic_wrapper.py
```

### Benchmark Integration

```bash
# From MCP-Universe root
export PYTHONPATH=.

# Run with example config
python examples/benchmark_integration.py
```

---

## Next Steps

1. **Modify examples** - Replace server names and tasks with your own
2. **Try different LLMs** - Test various post-processing models
3. **Tune thresholds** - Find optimal token threshold for your use case
4. **Create benchmarks** - Add MCP+ to your existing benchmark configs

---

## Questions?

- 📖 [MCPPlus Documentation](../README.md)
- 🌐 [MCP-Universe Docs](../../../../README.md)
