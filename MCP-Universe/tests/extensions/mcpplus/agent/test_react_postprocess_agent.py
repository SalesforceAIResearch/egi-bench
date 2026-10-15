"""
Tests for PostProcessAgent

Tests the dual extraction agent that generates both direct extraction and code.
"""
import pytest
import json
from unittest.mock import AsyncMock, Mock, patch
from mcpuniverse.extensions.mcpplus.agent.react_postprocess_agent import (
    PostProcessAgent,
    PostProcessAgentConfig
)
from mcpuniverse.extensions.mcpplus.utils.safe_executor import SafeCodeExecutor


class MockLLM:
    """Mock LLM for testing."""

    def __init__(self, responses=None):
        """Initialize with preset responses."""
        self.responses = responses or []
        self.call_count = 0
        self.config = Mock()
        self.config.model_name = "gpt-4o-mini"

    async def generate_async(self, messages, tracer=None, timeout=None):
        """Mock async generate."""
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        raise ValueError("No more mock responses available")

    def dump_config(self):
        """Mock dump_config method."""
        return {"type": "mock", "model_name": "gpt-4o-mini"}


class TestPostProcessAgentConfig:
    """Test suite for PostProcessAgentConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = PostProcessAgentConfig()
        assert config.max_iterations == 3
        assert config.llm_timeout == 500
        assert config.skip_iteration_on_size_failure is False

    def test_custom_config(self):
        """Test custom configuration values."""
        config = PostProcessAgentConfig(
            max_iterations=5,
            llm_timeout=600,
            skip_iteration_on_size_failure=True
        )
        assert config.max_iterations == 5
        assert config.llm_timeout == 600
        assert config.skip_iteration_on_size_failure is True


class TestPostProcessAgentInitialization:
    """Test suite for PostProcessAgent initialization."""

    def test_init_with_dict_config(self):
        """Test initialization with dictionary config."""
        llm = MockLLM()
        executor = SafeCodeExecutor()
        config = {"max_iterations": 5, "llm_timeout": 600}

        agent = PostProcessAgent(llm=llm, safe_executor=executor, config=config)
        assert agent._config.max_iterations == 5
        assert agent._config.llm_timeout == 600

    def test_init_with_config_object(self):
        """Test initialization with PostProcessAgentConfig object."""
        llm = MockLLM()
        executor = SafeCodeExecutor()
        config = PostProcessAgentConfig(max_iterations=2)

        agent = PostProcessAgent(llm=llm, safe_executor=executor, config=config)
        assert agent._config.max_iterations == 2

    def test_init_with_no_config(self):
        """Test initialization with no config (defaults)."""
        llm = MockLLM()
        executor = SafeCodeExecutor()

        agent = PostProcessAgent(llm=llm, safe_executor=executor)
        assert agent._config.max_iterations == 3


@pytest.mark.asyncio
class TestPostProcessAgentExecution:
    """Test suite for PostProcessAgent execution."""

    async def test_successful_dual_extraction(self):
        """Test successful extraction with both methods."""
        # Mock LLM response with both direct and code extraction
        llm_response = json.dumps({
            "direct_extraction": "The weather is sunny and 75 degrees.",
            "code": "result = data.split('Temperature:')[1].strip().split()[0]"
        })

        llm = MockLLM(responses=[llm_response])
        executor = SafeCodeExecutor()
        agent = PostProcessAgent(llm=llm, safe_executor=executor)

        # Prepare input message
        input_message = json.dumps({
            "tool_name": "get_weather",
            "tool_description": "Gets current weather",
            "tool_output": "Weather Report\nTemperature: 75F\nConditions: Sunny\nHumidity: 60%",
            "expected_info": "current temperature"
        })

        # Execute
        await agent.initialize()
        response = await agent.execute(message=input_message)

        # Verify response
        assert response.response is not None
        response_data = json.loads(response.response)
        assert "filtered_output" in response_data
        assert "DIRECT EXTRACTION" in response_data["filtered_output"]
        assert "CODE-BASED EXTRACTION" in response_data["filtered_output"]
        assert response_data["stats"]["success"] is True
        assert response_data["stats"]["postprocessor_iterations"] == 1

    async def test_invalid_json_input(self):
        """Test handling of invalid JSON input."""
        llm = MockLLM()
        executor = SafeCodeExecutor()
        agent = PostProcessAgent(llm=llm, safe_executor=executor)

        # Invalid JSON input
        await agent.initialize()
        response = await agent.execute(message="not json")

        assert "ERROR" in response.response

    async def test_empty_direct_extraction(self):
        """Test when direct extraction is empty but code succeeds."""
        # First attempt: empty direct extraction
        # Second attempt: both succeed
        responses = [
            json.dumps({
                "direct_extraction": "",
                "code": "result = 'extracted'"
            }),
            json.dumps({
                "direct_extraction": "Direct result",
                "code": "result = 'code result'"
            })
        ]

        llm = MockLLM(responses=responses)
        executor = SafeCodeExecutor()
        agent = PostProcessAgent(llm=llm, safe_executor=executor)

        input_message = json.dumps({
            "tool_name": "test_tool",
            "tool_description": "",
            "tool_output": "test data",
            "expected_info": "test info"
        })

        await agent.initialize()
        response = await agent.execute(message=input_message)

        response_data = json.loads(response.response)
        # Should have retried (implementation may take 2-3 iterations)
        assert response_data["stats"]["postprocessor_iterations"] in [2, 3]

    async def test_code_execution_failure(self):
        """Test when code execution fails."""
        # First attempt: code fails
        # Second attempt: both succeed
        responses = [
            json.dumps({
                "direct_extraction": "Direct result",
                "code": "result = undefined_variable"  # Will fail
            }),
            json.dumps({
                "direct_extraction": "Direct result",
                "code": "result = 'success'"
            })
        ]

        llm = MockLLM(responses=responses)
        executor = SafeCodeExecutor()
        agent = PostProcessAgent(llm=llm, safe_executor=executor)

        input_message = json.dumps({
            "tool_name": "test_tool",
            "tool_description": "",
            "tool_output": "test data",
            "expected_info": "test info"
        })

        await agent.initialize()
        response = await agent.execute(message=input_message)

        response_data = json.loads(response.response)
        # Should have retried due to code failure
        assert response_data["stats"]["postprocessor_iterations"] == 2

    async def test_invalid_llm_json_response(self):
        """Test handling of invalid JSON from LLM."""
        # First attempt: invalid JSON
        # Second attempt: valid JSON
        responses = [
            "not valid json",
            json.dumps({
                "direct_extraction": "Result",
                "code": "result = 'success'"
            })
        ]

        llm = MockLLM(responses=responses)
        executor = SafeCodeExecutor()
        agent = PostProcessAgent(llm=llm, safe_executor=executor)

        input_message = json.dumps({
            "tool_name": "test_tool",
            "tool_description": "",
            "tool_output": "test data",
            "expected_info": "test info"
        })

        await agent.initialize()
        response = await agent.execute(message=input_message)

        response_data = json.loads(response.response)
        # Should have retried
        assert response_data["stats"]["postprocessor_iterations"] == 2

    async def test_max_iterations_exhausted(self):
        """Test when all iterations are exhausted."""
        # All attempts fail
        responses = [
            json.dumps({"direct_extraction": "", "code": ""}),
            json.dumps({"direct_extraction": "", "code": ""}),
            json.dumps({"direct_extraction": "", "code": ""})
        ]

        llm = MockLLM(responses=responses)
        executor = SafeCodeExecutor()
        config = PostProcessAgentConfig(max_iterations=3)
        agent = PostProcessAgent(llm=llm, safe_executor=executor, config=config)

        input_message = json.dumps({
            "tool_name": "test_tool",
            "tool_description": "",
            "tool_output": "original output",
            "expected_info": "test info"
        })

        await agent.initialize()
        response = await agent.execute(message=input_message)

        response_data = json.loads(response.response)
        # Should return original output after all iterations
        assert "original output" in response_data["filtered_output"]
        assert response_data["stats"]["postprocessor_iterations"] == 3

    async def test_markdown_code_block_stripping(self):
        """Test that markdown code blocks are stripped from LLM response."""
        # LLM returns JSON wrapped in markdown code block
        llm_response = """```json
{
  "direct_extraction": "Result",
  "code": "result = 'test'"
}
```"""

        llm = MockLLM(responses=[llm_response])
        executor = SafeCodeExecutor()
        agent = PostProcessAgent(llm=llm, safe_executor=executor)

        input_message = json.dumps({
            "tool_name": "test_tool",
            "tool_description": "",
            "tool_output": "test data",
            "expected_info": "test info"
        })

        await agent.initialize()
        response = await agent.execute(message=input_message)

        response_data = json.loads(response.response)
        assert response_data["stats"]["success"] is True

    async def test_output_size_check_both_too_large(self):
        """Test when both outputs are too large (> 50% of input)."""
        # Create large output that exceeds 50% threshold
        large_input = "x" * 10000  # 10k chars

        # Both outputs are large (> 50% of input)
        llm_response = json.dumps({
            "direct_extraction": "y" * 6000,  # 60% of input
            "code": "result = 'z' * 6000"  # Will produce 60% of input
        })

        llm = MockLLM(responses=[llm_response])
        executor = SafeCodeExecutor()
        config = PostProcessAgentConfig(skip_iteration_on_size_failure=True)
        agent = PostProcessAgent(llm=llm, safe_executor=executor, config=config)

        input_message = json.dumps({
            "tool_name": "test_tool",
            "tool_description": "",
            "tool_output": large_input,
            "expected_info": "test info"
        })

        await agent.initialize()
        response = await agent.execute(message=input_message)

        response_data = json.loads(response.response)
        # Should return original due to size failure and skip_iteration flag
        assert large_input in response_data["filtered_output"]

    async def test_partial_success_direct_only(self):
        """Test when only direct extraction succeeds."""
        # Only direct extraction works across all iterations
        responses = [
            json.dumps({
                "direct_extraction": "Direct result works",
                "code": ""
            }),
            json.dumps({
                "direct_extraction": "Direct result works again",
                "code": ""
            }),
            json.dumps({
                "direct_extraction": "Direct result final",
                "code": ""
            })
        ]

        llm = MockLLM(responses=responses)
        executor = SafeCodeExecutor()
        config = PostProcessAgentConfig(max_iterations=3)
        agent = PostProcessAgent(llm=llm, safe_executor=executor, config=config)

        input_message = json.dumps({
            "tool_name": "test_tool",
            "tool_description": "",
            "tool_output": "test data",
            "expected_info": "test info"
        })

        await agent.initialize()
        response = await agent.execute(message=input_message)

        response_data = json.loads(response.response)
        # Should return best direct extraction result
        assert "Direct result final" in response_data["filtered_output"]
        assert response_data["stats"]["postprocessor_iterations"] == 3

    async def test_stats_tracking(self):
        """Test that statistics are properly tracked."""
        llm_response = json.dumps({
            "direct_extraction": "Short result",
            "code": "result = 'Short code result'"
        })

        llm = MockLLM(responses=[llm_response])
        executor = SafeCodeExecutor()
        agent = PostProcessAgent(llm=llm, safe_executor=executor)

        long_output = "This is a long tool output that will be compressed. " * 50

        input_message = json.dumps({
            "tool_name": "test_tool",
            "tool_description": "Test tool",
            "tool_output": long_output,
            "expected_info": "short summary"
        })

        await agent.initialize()
        response = await agent.execute(message=input_message)

        response_data = json.loads(response.response)
        stats = response_data["stats"]

        # Verify all stats fields are present
        assert "postprocessor_iterations" in stats
        assert "original_chars" in stats
        assert "filtered_chars" in stats
        assert "chars_reduced" in stats
        assert "original_tokens" in stats
        assert "filtered_tokens" in stats
        assert "tokens_reduced" in stats
        assert "success" in stats

        # Verify token reduction occurred
        assert stats["original_tokens"] > stats["filtered_tokens"]
        assert stats["tokens_reduced"] > 0
        assert stats["success"] is True

    async def test_list_message_input(self):
        """Test handling of list-format message input."""
        llm_response = json.dumps({
            "direct_extraction": "Result",
            "code": "result = 'test'"
        })

        llm = MockLLM(responses=[llm_response])
        executor = SafeCodeExecutor()
        agent = PostProcessAgent(llm=llm, safe_executor=executor)

        # Input as list instead of string
        input_message = [json.dumps({
            "tool_name": "test_tool",
            "tool_description": "",
            "tool_output": "test data",
            "expected_info": "test info"
        })]

        await agent.initialize()
        response = await agent.execute(message=input_message)

        response_data = json.loads(response.response)
        assert response_data["stats"]["success"] is True

    async def test_thought_field_in_response(self):
        """Test that optional 'thought' field is handled."""
        llm_response = json.dumps({
            "thought": "I will extract the temperature from the data",
            "direct_extraction": "Temperature is 75F",
            "code": "result = data.split('Temperature:')[1].split()[0]"
        })

        llm = MockLLM(responses=[llm_response])
        executor = SafeCodeExecutor()
        agent = PostProcessAgent(llm=llm, safe_executor=executor)

        input_message = json.dumps({
            "tool_name": "test_tool",
            "tool_description": "",
            "tool_output": "Temperature: 75F",
            "expected_info": "temperature"
        })

        await agent.initialize()
        response = await agent.execute(message=input_message)

        response_data = json.loads(response.response)
        assert response_data["stats"]["success"] is True
