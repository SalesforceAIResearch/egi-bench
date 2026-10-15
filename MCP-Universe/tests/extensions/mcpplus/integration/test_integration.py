"""
Integration tests for MCPPlus

Tests the complete flow: WrappedMCPClient -> PostProcessAgent -> SafeCodeExecutor
"""
import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from mcp.types import TextContent, CallToolResult, Tool

from mcpuniverse.extensions.mcpplus.wrapper.wrapper_manager import (
    MCPWrapperManager,
    WrapperConfig
)
from mcpuniverse.extensions.mcpplus.agent.react_postprocess_agent import (
    PostProcessAgent,
    PostProcessAgentConfig
)
from mcpuniverse.extensions.mcpplus.utils.safe_executor import SafeCodeExecutor


class MockLLM:
    """Mock LLM that returns realistic dual extraction responses."""

    def __init__(self, responses=None):
        """
        Initialize with preset responses.

        Args:
            responses: List of response dictionaries or None for default behavior.
        """
        self.responses = responses or []
        self.call_count = 0
        self.config = Mock()
        self.config.model_name = "gpt-4o-mini"
        self.calls = []  # Track all calls for verification

    async def generate_async(self, messages, tracer=None, timeout=None):
        """Mock async generate with realistic responses."""
        # Track the call
        self.calls.append({
            "messages": messages,
            "tracer": tracer,
            "timeout": timeout
        })

        # Use preset response if available
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1

            # If it's a dict, convert to JSON
            if isinstance(response, dict):
                return json.dumps(response)
            return response

        # Default: extract key information from tool output
        # Parse the prompt to understand what's being asked
        prompt = messages[0]["content"] if messages else ""

        # Simple heuristic: extract first few lines as direct, create simple code
        return json.dumps({
            "direct_extraction": "Key information extracted from output",
            "code": "result = data.split('\\n')[0] if data else 'no data'"
        })

    def dump_config(self):
        """Mock dump_config method."""
        return {"type": "mock", "model_name": "gpt-4o-mini"}


@pytest.mark.asyncio
class TestEndToEndFlow:
    """Test complete flow from client to post-processing."""

    async def test_full_post_processing_flow(self):
        """Test complete flow: tool call -> wrapper -> agent -> executor."""
        # Setup: Create wrapper manager with enabled config
        wrapper_config = WrapperConfig(
            enabled=True,
            token_threshold=100,  # Low threshold to trigger post-processing
            llm_timeout=500,
            max_iterations=3
        )

        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        # Create LLM with realistic response
        llm_response = {
            "direct_extraction": "The temperature is 75 degrees Fahrenheit.",
            "code": "import re\nmatch = re.search(r'Temperature: (\\d+)', data)\nresult = match.group(1) if match else 'not found'"
        }
        llm = MockLLM(responses=[llm_response])
        manager.set_llm(llm)

        # Build wrapped client
        mock_base_client = Mock()
        mock_base_client._name = "weather-server"
        mock_base_client._session = None
        mock_base_client._exit_stack = None
        mock_base_client._cleanup_lock = None
        mock_base_client._project_id = None
        mock_base_client._stdio_context = None
        mock_base_client._server_params = None

        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_base_client
        ):
            client = await manager.build_wrapped_client(server_name="weather-server")

        # Mock the original tool execution
        long_output = """
Weather Report for San Francisco
Temperature: 75F
Conditions: Sunny
Humidity: 60%
Wind: 10 mph NW
Forecast: Clear skies expected through the weekend with temperatures in the mid-70s.
Historical data shows this is typical for this time of year.
""" * 5  # Make it long enough to exceed threshold

        original_result = CallToolResult(
            content=[TextContent(type="text", text=long_output)],
            isError=False
        )

        with patch.object(client, 'list_tools', return_value=[]):
            with patch.object(
                client.__class__.__bases__[0],
                'execute_tool',
                return_value=original_result
            ):
                # Execute tool with expected_info
                result = await client.execute_tool(
                    tool_name="get_weather",
                    arguments={
                        "location": "San Francisco",
                        "expected_info": "current temperature in Fahrenheit"
                    }
                )

        # Verify the result
        assert isinstance(result, CallToolResult)
        result_text = result.content[0].text

        # Verify post-processing occurred
        assert "DUAL EXTRACTION RESULTS" in result_text
        assert "DIRECT EXTRACTION" in result_text
        assert "CODE-BASED EXTRACTION" in result_text
        assert len(result_text) < len(long_output)

        # Verify LLM was called
        assert llm.call_count == 1

        # Verify stats were updated
        stats = manager.get_all_postprocessor_stats()
        assert stats["tool_calls_processed"] == 1
        assert stats["total_iterations"] == 1
        assert stats["total_tokens_reduced"] > 0

    async def test_multiple_tool_calls_stats_accumulation(self):
        """Test that stats accumulate across multiple tool calls."""
        wrapper_config = WrapperConfig(enabled=True, token_threshold=50)
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        llm = MockLLM(responses=[
            {"direct_extraction": "Result 1", "code": "result = 'code 1'"},
            {"direct_extraction": "Result 2", "code": "result = 'code 2'"},
            {"direct_extraction": "Result 3", "code": "result = 'code 3'"}
        ])
        manager.set_llm(llm)

        # Build wrapped client
        mock_base_client = Mock()
        mock_base_client._name = "test-server"
        mock_base_client._session = None
        mock_base_client._exit_stack = None
        mock_base_client._cleanup_lock = None
        mock_base_client._project_id = None
        mock_base_client._stdio_context = None
        mock_base_client._server_params = None

        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_base_client
        ):
            client = await manager.build_wrapped_client(server_name="test-server")

        # Make 3 tool calls
        for i in range(3):
            long_output = f"This is a long output for call {i}. " * 20
            original_result = CallToolResult(
                content=[TextContent(type="text", text=long_output)],
                isError=False
            )

            with patch.object(client, 'list_tools', return_value=[]):
                with patch.object(
                    client.__class__.__bases__[0],
                    'execute_tool',
                    return_value=original_result
                ):
                    await client.execute_tool(
                        tool_name="test_tool",
                        arguments={"query": f"query {i}", "expected_info": "info"}
                    )

        # Verify accumulated stats
        stats = manager.get_all_postprocessor_stats()
        assert stats["tool_calls_processed"] == 3
        assert stats["total_iterations"] == 3
        assert stats["total_tokens_reduced"] > 0

    async def test_retry_on_code_execution_failure(self):
        """Test that agent retries when code execution fails."""
        wrapper_config = WrapperConfig(enabled=True, token_threshold=50, max_iterations=3)
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        # First response: code that will fail
        # Second response: code that succeeds
        llm = MockLLM(responses=[
            {
                "direct_extraction": "Direct result",
                "code": "result = undefined_variable"  # Will fail
            },
            {
                "direct_extraction": "Direct result fixed",
                "code": "result = 'success'"
            }
        ])
        manager.set_llm(llm)

        # Build wrapped client
        mock_base_client = Mock()
        mock_base_client._name = "test-server"
        mock_base_client._session = None
        mock_base_client._exit_stack = None
        mock_base_client._cleanup_lock = None
        mock_base_client._project_id = None
        mock_base_client._stdio_context = None
        mock_base_client._server_params = None

        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_base_client
        ):
            client = await manager.build_wrapped_client(server_name="test-server")

        long_output = "Test data " * 50
        original_result = CallToolResult(
            content=[TextContent(type="text", text=long_output)],
            isError=False
        )

        with patch.object(client, 'list_tools', return_value=[]):
            with patch.object(
                client.__class__.__bases__[0],
                'execute_tool',
                return_value=original_result
            ):
                result = await client.execute_tool(
                    tool_name="test_tool",
                    arguments={"query": "test", "expected_info": "info"}
                )

        # Verify that it retried (2 LLM calls)
        assert llm.call_count == 2

        # Verify final result includes both extractions
        result_text = result.content[0].text
        assert "Direct result fixed" in result_text
        assert "success" in result_text

        # Verify stats show 2 iterations
        stats = manager.get_all_postprocessor_stats()
        assert stats["total_iterations"] == 2

    async def test_skips_post_processing_without_expected_info(self):
        """Test that post-processing is skipped when expected_info is missing."""
        wrapper_config = WrapperConfig(enabled=True, token_threshold=50)
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        llm = MockLLM()
        manager.set_llm(llm)

        # Build wrapped client
        mock_base_client = Mock()
        mock_base_client._name = "test-server"
        mock_base_client._session = None
        mock_base_client._exit_stack = None
        mock_base_client._cleanup_lock = None
        mock_base_client._project_id = None
        mock_base_client._stdio_context = None
        mock_base_client._server_params = None

        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_base_client
        ):
            client = await manager.build_wrapped_client(server_name="test-server")

        long_output = "Test data " * 50
        original_result = CallToolResult(
            content=[TextContent(type="text", text=long_output)],
            isError=False
        )

        with patch.object(
            client.__class__.__bases__[0],
            'execute_tool',
            return_value=original_result
        ):
            # No expected_info provided
            result = await client.execute_tool(
                tool_name="test_tool",
                arguments={"query": "test"}
            )

        # Verify LLM was NOT called
        assert llm.call_count == 0

        # Verify result is unchanged
        assert result == original_result

        # Verify no stats accumulated
        stats = manager.get_all_postprocessor_stats()
        assert stats["tool_calls_processed"] == 0

    async def test_skips_post_processing_below_threshold(self):
        """Test that post-processing is skipped for small outputs."""
        wrapper_config = WrapperConfig(enabled=True, token_threshold=2000)
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        llm = MockLLM()
        manager.set_llm(llm)

        # Build wrapped client
        mock_base_client = Mock()
        mock_base_client._name = "test-server"
        mock_base_client._session = None
        mock_base_client._exit_stack = None
        mock_base_client._cleanup_lock = None
        mock_base_client._project_id = None
        mock_base_client._stdio_context = None
        mock_base_client._server_params = None

        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_base_client
        ):
            client = await manager.build_wrapped_client(server_name="test-server")

        # Short output below threshold
        short_output = "Short result"
        original_result = CallToolResult(
            content=[TextContent(type="text", text=short_output)],
            isError=False
        )

        with patch.object(
            client.__class__.__bases__[0],
            'execute_tool',
            return_value=original_result
        ):
            result = await client.execute_tool(
                tool_name="test_tool",
                arguments={"query": "test", "expected_info": "info"}
            )

        # Verify LLM was NOT called
        assert llm.call_count == 0

        # Verify result is unchanged
        assert result == original_result

    async def test_stats_reset(self):
        """Test that stats can be reset between tasks."""
        wrapper_config = WrapperConfig(enabled=True, token_threshold=50)
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        llm = MockLLM(responses=[
            {"direct_extraction": "Result", "code": "result = 'code'"}
        ])
        manager.set_llm(llm)

        # Build wrapped client
        mock_base_client = Mock()
        mock_base_client._name = "test-server"
        mock_base_client._session = None
        mock_base_client._exit_stack = None
        mock_base_client._cleanup_lock = None
        mock_base_client._project_id = None
        mock_base_client._stdio_context = None
        mock_base_client._server_params = None

        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_base_client
        ):
            client = await manager.build_wrapped_client(server_name="test-server")

        # Make a tool call
        long_output = "Test data " * 50
        original_result = CallToolResult(
            content=[TextContent(type="text", text=long_output)],
            isError=False
        )

        with patch.object(client, 'list_tools', return_value=[]):
            with patch.object(
                client.__class__.__bases__[0],
                'execute_tool',
                return_value=original_result
            ):
                await client.execute_tool(
                    tool_name="test_tool",
                    arguments={"query": "test", "expected_info": "info"}
                )

        # Verify stats
        stats = manager.get_all_postprocessor_stats()
        assert stats["tool_calls_processed"] == 1

        # Reset stats
        manager.reset_all_postprocessor_stats()

        # Verify stats are cleared
        stats = manager.get_all_postprocessor_stats()
        assert stats["tool_calls_processed"] == 0
        assert stats["total_iterations"] == 0
        assert stats["total_tokens_reduced"] == 0

    async def test_complex_code_execution(self):
        """Test integration with complex code execution (JSON parsing, regex, etc)."""
        wrapper_config = WrapperConfig(enabled=True, token_threshold=50)
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        # LLM generates code that parses JSON
        # Provide multiple responses in case of retry due to oversized output
        llm_response = {
            "direct_extraction": "Product name is 'Laptop' and price is $999",
            "code": """
import json
parsed = json.loads(data)
result = f"Product: {parsed['name']}, Price: ${parsed['price']}"
"""
        }
        # Provide same response 2-3 times to handle potential retries
        llm = MockLLM(responses=[llm_response, llm_response, llm_response])
        manager.set_llm(llm)

        # Build wrapped client
        mock_base_client = Mock()
        mock_base_client._name = "test-server"
        mock_base_client._session = None
        mock_base_client._exit_stack = None
        mock_base_client._cleanup_lock = None
        mock_base_client._project_id = None
        mock_base_client._stdio_context = None
        mock_base_client._server_params = None

        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_base_client
        ):
            client = await manager.build_wrapped_client(server_name="test-server")

        # Tool returns JSON data (make it long enough to exceed threshold)
        json_obj = {
            "name": "Laptop",
            "price": 999,
            "description": "High-performance laptop with 16GB RAM and 512GB SSD",
            "reviews": ["Great product", "Fast delivery", "Excellent quality"],
            "specs": {
                "cpu": "Intel i7",
                "ram": "16GB",
                "storage": "512GB SSD",
                "display": "15.6 inch FHD"
            },
            "warranty": "2 years",
            "in_stock": True
        }
        # Add padding to make it long enough
        json_obj["extra_data"] = "padding " * 100
        json_output = json.dumps(json_obj)

        original_result = CallToolResult(
            content=[TextContent(type="text", text=json_output)],
            isError=False
        )

        with patch.object(client, 'list_tools', return_value=[]):
            with patch.object(
                client.__class__.__bases__[0],
                'execute_tool',
                return_value=original_result
            ):
                result = await client.execute_tool(
                    tool_name="get_product",
                    arguments={"id": "123", "expected_info": "product name and price"}
                )

        # Verify code was executed successfully
        result_text = result.content[0].text
        assert "DUAL EXTRACTION RESULTS" in result_text
        # The code result should contain the formatted product info
        assert "Product: Laptop" in result_text
        assert "Price: $999" in result_text

        # Verify significant compression
        assert len(result_text) < len(json_output) * 0.5


@pytest.mark.asyncio
class TestErrorHandling:
    """Test error handling in integration scenarios."""

    async def test_graceful_degradation_on_post_processor_failure(self):
        """Test that system gracefully falls back to original output on failure."""
        wrapper_config = WrapperConfig(enabled=True, token_threshold=50)
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        # LLM that raises an error
        llm = Mock()
        llm.config = Mock()
        llm.config.model_name = "gpt-4o-mini"
        llm.generate_async = AsyncMock(side_effect=ValueError("LLM error"))

        manager.set_llm(llm)

        # Build wrapped client
        mock_base_client = Mock()
        mock_base_client._name = "test-server"
        mock_base_client._session = None
        mock_base_client._exit_stack = None
        mock_base_client._cleanup_lock = None
        mock_base_client._project_id = None
        mock_base_client._stdio_context = None
        mock_base_client._server_params = None

        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_base_client
        ):
            client = await manager.build_wrapped_client(server_name="test-server")

        long_output = "Test data " * 50
        original_result = CallToolResult(
            content=[TextContent(type="text", text=long_output)],
            isError=False
        )

        with patch.object(client, 'list_tools', return_value=[]):
            with patch.object(
                client.__class__.__bases__[0],
                'execute_tool',
                return_value=original_result
            ):
                result = await client.execute_tool(
                    tool_name="test_tool",
                    arguments={"query": "test", "expected_info": "info"}
                )

        # Should return original result despite error
        assert result == original_result

    async def test_security_blocking_in_integration(self):
        """Test that dangerous code is blocked in integration flow."""
        wrapper_config = WrapperConfig(enabled=True, token_threshold=50)
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        # LLM generates dangerous code
        llm_response = {
            "direct_extraction": "Result",
            "code": "import os; result = os.system('ls')"
        }
        llm = MockLLM(responses=[llm_response, {
            "direct_extraction": "Safe result",
            "code": "result = 'safe'"
        }])
        manager.set_llm(llm)

        # Build wrapped client
        mock_base_client = Mock()
        mock_base_client._name = "test-server"
        mock_base_client._session = None
        mock_base_client._exit_stack = None
        mock_base_client._cleanup_lock = None
        mock_base_client._project_id = None
        mock_base_client._stdio_context = None
        mock_base_client._server_params = None

        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_base_client
        ):
            client = await manager.build_wrapped_client(server_name="test-server")

        long_output = "Test data " * 50
        original_result = CallToolResult(
            content=[TextContent(type="text", text=long_output)],
            isError=False
        )

        with patch.object(client, 'list_tools', return_value=[]):
            with patch.object(
                client.__class__.__bases__[0],
                'execute_tool',
                return_value=original_result
            ):
                result = await client.execute_tool(
                    tool_name="test_tool",
                    arguments={"query": "test", "expected_info": "info"}
                )

        # Should have retried after dangerous code was blocked
        assert llm.call_count == 2

        # Final result should include safe code output
        result_text = result.content[0].text
        assert "safe" in result_text
