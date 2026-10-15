"""
Tests for WrapperManager and WrappedMCPClient

Tests the MCP client wrapping functionality with post-processing.
"""
import pytest
import json
from unittest.mock import AsyncMock, Mock, patch
from mcp.types import TextContent, CallToolResult, Tool

from mcpuniverse.extensions.mcpplus.wrapper.wrapper_manager import (
    MCPWrapperManager,
    WrappedMCPClient,
    WrapperConfig
)
from mcpuniverse.extensions.mcpplus.utils.stats import PostProcessStats


class MockLLM:
    """Mock LLM for testing."""

    def __init__(self):
        self.config = Mock()
        self.config.model_name = "gpt-4o-mini"

    async def generate_async(self, messages, tracer=None, timeout=None):
        """Mock async generate."""
        # Return a valid dual extraction response
        return json.dumps({
            "direct_extraction": "Extracted information",
            "code": "result = 'code result'"
        })

    def dump_config(self):
        """Mock dump_config method."""
        return {"type": "mock", "model_name": "gpt-4o-mini"}


class MockPostProcessor:
    """Mock post-processor for testing."""

    def __init__(self):
        self._model_name = "gpt-4o-mini"

    async def initialize(self):
        """Mock initialize."""
        pass

    async def execute(self, message, tracer=None):
        """Mock execute that returns filtered output."""
        # Parse input to get original tool output
        input_data = json.loads(message)
        tool_output = input_data.get("tool_output", "")

        # Return shortened output
        filtered_output = "Filtered: " + tool_output[:50]

        response_data = {
            "filtered_output": filtered_output,
            "stats": {
                "postprocessor_iterations": 1,
                "original_chars": len(tool_output),
                "filtered_chars": len(filtered_output),
                "chars_reduced": len(tool_output) - len(filtered_output),
                "original_tokens": len(tool_output) // 4,  # Rough estimate
                "filtered_tokens": len(filtered_output) // 4,
                "tokens_reduced": (len(tool_output) - len(filtered_output)) // 4,
                "success": True
            }
        }

        mock_response = Mock()
        mock_response.response = json.dumps(response_data)
        mock_response.trace_id = "test-trace-id"
        return mock_response


class TestWrapperConfig:
    """Test suite for WrapperConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = WrapperConfig()
        assert config.enabled is False
        assert config.token_threshold == 2000
        assert config.post_process_llm == {"type": "openai", "model_name": "gpt-5-mini"}
        assert config.llm_timeout == 500
        assert config.max_iterations == 3
        assert config.skip_iteration_on_size_failure is False

    def test_custom_config(self):
        """Test custom configuration values."""
        config = WrapperConfig(
            enabled=True,
            token_threshold=1500,
            post_process_llm={"type": "openai", "model": "gpt-4o-mini"},
            llm_timeout=600,
            max_iterations=5,
            skip_iteration_on_size_failure=True
        )
        assert config.enabled is True
        assert config.token_threshold == 1500
        assert config.post_process_llm["type"] == "openai"
        assert config.llm_timeout == 600
        assert config.max_iterations == 5
        assert config.skip_iteration_on_size_failure is True


class TestWrappedMCPClient:
    """Test suite for WrappedMCPClient."""

    def test_initialization(self):
        """Test WrappedMCPClient initialization."""
        config = WrapperConfig(enabled=True)
        post_processor = MockPostProcessor()

        client = WrappedMCPClient(
            name="test-client",
            config=config,
            post_processor=post_processor
        )

        assert client._wrapper_config == config
        assert client._post_processor == post_processor
        assert client._postprocessor_stats["tool_calls_processed"] == 0

    @pytest.mark.asyncio
    async def test_list_tools_adds_expected_info(self):
        """Test that list_tools adds expected_info parameter to tools."""
        config = WrapperConfig(enabled=True)
        client = WrappedMCPClient(name="test-client", config=config)

        # Mock the parent list_tools to return sample tools
        mock_tool = Tool(
            name="test_tool",
            description="Test tool",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                }
            }
        )

        with patch.object(client.__class__.__bases__[0], 'list_tools', return_value=[mock_tool]):
            tools = await client.list_tools()

        # Verify expected_info was added
        assert len(tools) == 1
        assert "expected_info" in tools[0].inputSchema["properties"]
        assert "description" in tools[0].inputSchema["properties"]["expected_info"]

    @pytest.mark.asyncio
    async def test_list_tools_without_wrapper(self):
        """Test that list_tools doesn't modify tools when wrapper is disabled."""
        config = WrapperConfig(enabled=False)
        client = WrappedMCPClient(name="test-client", config=config)

        mock_tool = Tool(
            name="test_tool",
            description="Test tool",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                }
            }
        )

        with patch.object(client.__class__.__bases__[0], 'list_tools', return_value=[mock_tool]):
            tools = await client.list_tools()

        # Verify expected_info was NOT added
        assert "expected_info" not in tools[0].inputSchema["properties"]

    @pytest.mark.asyncio
    async def test_execute_tool_without_wrapper(self):
        """Test tool execution without wrapper (passthrough)."""
        config = WrapperConfig(enabled=False)
        client = WrappedMCPClient(name="test-client", config=config)

        # Mock parent execute_tool
        expected_result = CallToolResult(
            content=[TextContent(type="text", text="Test result")],
            isError=False
        )

        with patch.object(
            client.__class__.__bases__[0],
            'execute_tool',
            return_value=expected_result
        ):
            result = await client.execute_tool(
                tool_name="test_tool",
                arguments={"query": "test"}
            )

        assert result == expected_result

    @pytest.mark.asyncio
    async def test_execute_tool_below_threshold(self):
        """Test that post-processing is skipped for outputs below token threshold."""
        config = WrapperConfig(enabled=True, token_threshold=2000)
        post_processor = MockPostProcessor()
        client = WrappedMCPClient(
            name="test-client",
            config=config,
            post_processor=post_processor
        )

        # Short output below threshold
        short_text = "Short result"
        expected_result = CallToolResult(
            content=[TextContent(type="text", text=short_text)],
            isError=False
        )

        with patch.object(
            client.__class__.__bases__[0],
            'execute_tool',
            return_value=expected_result
        ):
            result = await client.execute_tool(
                tool_name="test_tool",
                arguments={"query": "test", "expected_info": "test info"}
            )

        # Should return original result (not post-processed)
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_execute_tool_with_post_processing(self):
        """Test tool execution with post-processing."""
        config = WrapperConfig(enabled=True, token_threshold=100)
        post_processor = MockPostProcessor()

        # Create a proper mock manager with tracer support
        from mcpuniverse.tracer import Tracer
        manager = Mock()
        manager._aggregated_stats = {
            "total_iterations": 0,
            "total_chars_reduced": 0,
            "total_tokens_reduced": 0,
            "original_chars": 0,
            "filtered_chars": 0,
            "original_tokens": 0,
            "filtered_tokens": 0,
            "tool_calls_processed": 0
        }
        manager._postprocessor_tracer = Tracer()
        manager._trace_collector = None

        client = WrappedMCPClient(
            name="test-client",
            config=config,
            post_processor=post_processor,
            manager=manager
        )

        # Long output above threshold
        long_text = "This is a very long output. " * 50  # ~1400 chars
        original_result = CallToolResult(
            content=[TextContent(type="text", text=long_text)],
            isError=False
        )

        # Mock list_tools to return empty list (no tool description)
        with patch.object(client, 'list_tools', return_value=[]):
            with patch.object(
                client.__class__.__bases__[0],
                'execute_tool',
                return_value=original_result
            ):
                result = await client.execute_tool(
                    tool_name="test_tool",
                    arguments={"query": "test", "expected_info": "specific information"}
                )

        # Should return post-processed result
        assert isinstance(result, CallToolResult)
        result_text = result.content[0].text
        assert result_text.startswith("Filtered:")
        assert len(result_text) < len(long_text)

        # Verify stats were updated
        assert client._postprocessor_stats["tool_calls_processed"] == 1

    @pytest.mark.asyncio
    async def test_execute_tool_without_expected_info(self):
        """Test that post-processing is skipped without expected_info."""
        config = WrapperConfig(enabled=True, token_threshold=100)
        post_processor = MockPostProcessor()
        client = WrappedMCPClient(
            name="test-client",
            config=config,
            post_processor=post_processor
        )

        long_text = "This is a very long output. " * 50
        expected_result = CallToolResult(
            content=[TextContent(type="text", text=long_text)],
            isError=False
        )

        with patch.object(
            client.__class__.__bases__[0],
            'execute_tool',
            return_value=expected_result
        ):
            # No expected_info parameter
            result = await client.execute_tool(
                tool_name="test_tool",
                arguments={"query": "test"}
            )

        # Should return original result (not post-processed)
        assert result == expected_result

    @pytest.mark.asyncio
    async def test_post_processing_failure_fallback(self):
        """Test that original result is returned if post-processing fails."""
        config = WrapperConfig(enabled=True, token_threshold=100)

        # Mock post-processor that fails
        failing_processor = MockPostProcessor()
        async def failing_execute(*args, **kwargs):
            raise ValueError("Post-processing failed")
        failing_processor.execute = failing_execute

        # Create a proper mock manager with tracer support
        from mcpuniverse.tracer import Tracer
        manager = Mock()
        manager._aggregated_stats = {
            "total_iterations": 0,
            "total_chars_reduced": 0,
            "total_tokens_reduced": 0,
            "original_chars": 0,
            "filtered_chars": 0,
            "original_tokens": 0,
            "filtered_tokens": 0,
            "tool_calls_processed": 0
        }
        manager._postprocessor_tracer = Tracer()
        manager._trace_collector = None

        client = WrappedMCPClient(
            name="test-client",
            config=config,
            post_processor=failing_processor,
            manager=manager
        )

        long_text = "This is a very long output. " * 50
        original_result = CallToolResult(
            content=[TextContent(type="text", text=long_text)],
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

        # Should return original result on failure
        assert result == original_result

    def test_extract_text_content(self):
        """Test text extraction from MCP result."""
        config = WrapperConfig()
        client = WrappedMCPClient(name="test-client", config=config)

        # Test with CallToolResult
        result = CallToolResult(
            content=[TextContent(type="text", text="Test content")],
            isError=False
        )
        text = client._extract_text_content(result)
        assert text == "Test content"

        # Test with string fallback
        text = client._extract_text_content("Plain string")
        assert text == "Plain string"


class TestMCPWrapperManager:
    """Test suite for MCPWrapperManager."""

    def test_initialization_with_dict_config(self):
        """Test initialization with dictionary wrapper config."""
        wrapper_config = {
            "enabled": True,
            "token_threshold": 1500
        }

        manager = MCPWrapperManager(
            config=None,
            wrapper_config=wrapper_config
        )

        assert manager._wrapper_config.enabled is True
        assert manager._wrapper_config.token_threshold == 1500

    def test_initialization_with_config_object(self):
        """Test initialization with WrapperConfig object."""
        wrapper_config = WrapperConfig(enabled=True, token_threshold=1500)

        manager = MCPWrapperManager(
            config=None,
            wrapper_config=wrapper_config
        )

        assert manager._wrapper_config == wrapper_config

    def test_set_llm(self):
        """Test setting LLM for post-processing."""
        manager = MCPWrapperManager(config=None)
        llm = MockLLM()

        manager.set_llm(llm)
        assert manager._llm == llm

    def test_get_postprocessor_stats_initial(self):
        """Test getting initial stats (all zeros)."""
        manager = MCPWrapperManager(config=None)
        stats = manager.get_all_postprocessor_stats()

        assert stats["total_iterations"] == 0
        assert stats["total_chars_reduced"] == 0
        assert stats["total_tokens_reduced"] == 0
        assert stats["tool_calls_processed"] == 0

    def test_reset_postprocessor_stats(self):
        """Test resetting stats."""
        manager = MCPWrapperManager(config=None)

        # Modify stats
        manager._aggregated_stats["total_iterations"] = 10
        manager._aggregated_stats["tool_calls_processed"] = 5

        # Reset
        manager.reset_all_postprocessor_stats()
        stats = manager.get_all_postprocessor_stats()

        assert stats["total_iterations"] == 0
        assert stats["tool_calls_processed"] == 0

    def test_is_wrapper_enabled(self):
        """Test wrapper enabled check."""
        # No wrapper config
        manager1 = MCPWrapperManager(config=None)
        assert manager1._is_wrapper_enabled() is False

        # Wrapper disabled
        manager2 = MCPWrapperManager(
            config=None,
            wrapper_config=WrapperConfig(enabled=False)
        )
        assert manager2._is_wrapper_enabled() is False

        # Wrapper enabled
        manager3 = MCPWrapperManager(
            config=None,
            wrapper_config=WrapperConfig(enabled=True)
        )
        assert manager3._is_wrapper_enabled() is True

    @pytest.mark.asyncio
    async def test_build_client_without_wrapper(self):
        """Test building standard client when wrapper is disabled."""
        manager = MCPWrapperManager(
            config=None,
            wrapper_config=WrapperConfig(enabled=False)
        )

        # Mock the parent build_client
        mock_client = Mock()
        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_client
        ):
            client = await manager.build_client(server_name="test-server")

        # Should return standard client
        assert client == mock_client

    @pytest.mark.asyncio
    async def test_build_wrapped_client_without_llm(self):
        """Test that building wrapped client fails without LLM."""
        manager = MCPWrapperManager(
            config=None,
            wrapper_config=WrapperConfig(enabled=True)
        )

        # Should raise error because LLM is not set
        with pytest.raises(RuntimeError, match="LLM must be set"):
            await manager.build_wrapped_client(server_name="test-server")

    @pytest.mark.asyncio
    async def test_build_wrapped_client_success(self):
        """Test successfully building a wrapped client."""
        wrapper_config = WrapperConfig(enabled=True, token_threshold=100)
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        # Set LLM
        llm = MockLLM()
        manager.set_llm(llm)

        # Mock parent build_client
        mock_client = Mock()
        mock_client._name = "test-server"
        mock_client._session = None
        mock_client._exit_stack = None
        mock_client._cleanup_lock = None
        mock_client._project_id = None
        mock_client._stdio_context = None
        mock_client._server_params = None

        with patch.object(
            manager.__class__.__bases__[0],
            'build_client',
            return_value=mock_client
        ):
            client = await manager.build_wrapped_client(server_name="test-server")

        # Should return wrapped client
        assert isinstance(client, WrappedMCPClient)
        assert client._name == "test-server"
        assert client._post_processor is not None

    @pytest.mark.asyncio
    async def test_initialize_post_processor(self):
        """Test post-processor initialization."""
        wrapper_config = WrapperConfig(
            enabled=True,
            llm_timeout=600,
            max_iterations=5
        )
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        llm = MockLLM()
        manager.set_llm(llm)

        await manager._initialize_post_processor()

        # Verify post-processor was created
        assert manager._post_processor is not None

    def test_reset_postprocessor_tracer(self):
        """Test resetting post-processor tracer."""
        manager = MCPWrapperManager(config=None)

        # Set tracer attributes
        manager._postprocessor_tracer = Mock()
        manager._postprocessor_trace_id = "test-id"

        # Reset
        manager.reset_postprocessor_tracer()

        # Verify attributes were removed
        assert not hasattr(manager, '_postprocessor_tracer')
        assert not hasattr(manager, '_postprocessor_trace_id')

    def test_get_postprocessor_trace_id(self):
        """Test getting post-processor trace ID."""
        manager = MCPWrapperManager(config=None)

        # No trace ID initially
        assert manager.get_postprocessor_trace_id() is None

        # Set trace ID
        manager._postprocessor_trace_id = "test-trace-123"
        assert manager.get_postprocessor_trace_id() == "test-trace-123"

    def test_wrap_client(self):
        """Test wrapping an MCP client."""
        wrapper_config = WrapperConfig(enabled=True)
        manager = MCPWrapperManager(config=None, wrapper_config=wrapper_config)

        # Create mock client
        mock_client = Mock()
        mock_client._name = "test-server"
        mock_client._session = "session"
        mock_client._exit_stack = "exit_stack"
        mock_client._cleanup_lock = "cleanup_lock"
        mock_client._project_id = "project_id"
        mock_client._stdio_context = "stdio_context"
        mock_client._server_params = "server_params"

        # Create mock post-processor
        manager._post_processor = MockPostProcessor()

        # Wrap the client
        wrapped = manager._wrap_client(mock_client)

        # Verify wrapped client
        assert isinstance(wrapped, WrappedMCPClient)
        assert wrapped._name == "test-server"
        assert wrapped._session == "session"
        assert wrapped._exit_stack == "exit_stack"
        assert wrapped._post_processor == manager._post_processor
