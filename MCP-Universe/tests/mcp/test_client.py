import unittest
import os
import socket
from mcpuniverse.mcp.manager import MCPManager


class TestMCPClient(unittest.IsolatedAsyncioTestCase):
    """Test cases for the MCPClient"""

    async def test_client_stdio(self):
        """Test stdio transport with the client"""
        manager = MCPManager()
        
        # Create client
        client = await manager.build_client(server_name="weather", transport="stdio")
        
        # Test listing tools
        tools = await client.list_tools()
        self.assertEqual(tools[0].name, "get_alerts")
        self.assertEqual(tools[1].name, "get_forecast")
        
        # Cleanup
        await client.cleanup()

    async def test_client_sse(self):
        """Test SSE transport with the client"""
        # Check if gateway server is running
        gateway_address = os.environ.get("MCP_GATEWAY_ADDRESS", "http://localhost:8000")
        # Extract port from address
        try:
            if "://" in gateway_address:
                host_port = gateway_address.split("://")[1].split("/")[0]
                host, port = host_port.split(":") if ":" in host_port else (host_port, "8000")
            else:
                host, port = "localhost", "8000"
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex((host, int(port))) != 0:
                    # Gateway server not running, skip test
                    return
        except Exception:
            # If we can't check, try to connect anyway
            pass
        
        # Test weather server
        manager = MCPManager()
        client = await manager.build_client(server_name="weather", transport="sse")
        
        tools = await client.list_tools()
        self.assertEqual(tools[0].name, "get_alerts")
        self.assertEqual(tools[1].name, "get_forecast")
        await client.cleanup()

        # Test echo server
        client = await manager.build_client(server_name="echo", transport="sse")
        
        tools = await client.list_tools()
        self.assertEqual(tools[0].name, "echo_tool")
        
        output = await client.execute_tool(
            tool_name="echo_tool",
            arguments={"text": "Hello world!"}
        )
        self.assertEqual(output.content[0].text, "Hello world!")
        await client.cleanup()

if __name__ == "__main__":
    unittest.main()
