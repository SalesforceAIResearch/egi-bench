import unittest
import pytest
from mcpuniverse.mcp.manager import MCPManager


class TestLLMSandbox(unittest.IsolatedAsyncioTestCase):

    async def test_client(self):

        manager = MCPManager()
        client = await manager.build_client(server_name="python-code-sandbox")
        tools = await client.list_tools()
        print(tools)
        r = await client.execute_tool(
            "execute_python_code", arguments={"code": "print('Hello, World!')"})
        print(r)
        await client.cleanup()


if __name__ == "__main__":
    unittest.main()