"""
Basic MCPPlus Wrapper Example

This example demonstrates the simplest usage of MCPPlus to wrap an MCP client
with post-processing capabilities.

Prerequisites:
- MCP-Universe installed: pip install mcpuniverse
- MCP server configured in configs/server_list.json
- API key set: export OPENAI_API_KEY=your_key
"""
import asyncio
from mcpuniverse.extensions.mcpplus.wrapper import MCPWrapperManager, WrapperConfig
from mcpuniverse.llm import LLM


async def main():
    """
    Basic example: Create a wrapped MCP client and use it.

    The wrapper will automatically post-process tool outputs that exceed
    the token threshold, reducing token costs.
    """
    print("=" * 80)
    print("MCPPlus Basic Wrapper Example")
    print("=" * 80)

    # Step 1: Configure the wrapper
    print("\n1. Configuring wrapper...")
    wrapper_config = WrapperConfig(
        enabled=True,                    # Enable post-processing
        token_threshold=2000,            # Process outputs above 2000 tokens
        max_iterations=3,                # Max refinement attempts
        llm_timeout=500,                 # LLM API call timeout (seconds)
        skip_iteration_on_size_failure=False  # Retry if outputs are too large
    )
    print(f"   ✓ Token threshold: {wrapper_config.token_threshold}")
    print(f"   ✓ Max iterations: {wrapper_config.max_iterations}")

    # Step 2: Initialize the wrapper manager
    print("\n2. Initializing wrapper manager...")
    manager = MCPWrapperManager(
        config="configs/server_list.json",  # Your MCP server config
        wrapper_config=wrapper_config
    )
    print("   ✓ Wrapper manager initialized")

    # Step 3: Set up LLM for post-processing
    print("\n3. Setting up LLM...")
    llm = LLM(config={
        "type": "openai",
        "model_name": "gpt-5-mini"  # Using cheaper model for post-processing
    })
    manager.set_llm(llm)
    print("   ✓ LLM configured for post-processing")

    # Step 4: Build wrapped client
    print("\n4. Building wrapped MCP client...")
    # Replace "your-mcp-server" with actual server name from your config
    client = await manager.build_client("weather")  # Example: weather server
    print("   ✓ Wrapped client ready")

    # Step 5: Use the client normally
    print("\n5. Making tool call with post-processing...")
    print("   Note: Add 'expected_info' to guide post-processing")

    try:
        result = await client.execute_tool(
            tool_name="get_forecast",  # Replace with actual tool name
            arguments={
                "location": "San Francisco, CA",
                "days": 7,
                # The expected_info parameter guides post-processing
                "expected_info": (
                    "Extract only today's temperature and weather condition, "
                    "needed to answer user's question about current weather"
                )
            }
        )

        print("\n6. Result:")
        print("-" * 80)
        print(result)
        print("-" * 80)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("   Make sure:")
        print("   - MCP server is configured correctly")
        print("   - Tool name and arguments are valid")
        print("   - API keys are set")

    # Step 7: Check post-processing statistics
    print("\n7. Post-processing statistics:")
    stats = manager.get_all_postprocessor_stats()
    print(f"   Tool calls processed: {stats['tool_calls_processed']}")
    print(f"   Total tokens reduced: {stats['total_tokens_reduced']}")
    print(f"   Total iterations: {stats['total_iterations']}")

    if stats['original_tokens'] > 0:
        compression = (stats['total_tokens_reduced'] / stats['original_tokens']) * 100
        print(f"   Compression rate: {compression:.1f}%")

    print("\n" + "=" * 80)
    print("Example complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
