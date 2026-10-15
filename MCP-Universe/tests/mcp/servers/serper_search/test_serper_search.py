import unittest
from mcpuniverse.mcp.servers.serper_search.server import build_server


class TestSerperSearch(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.server = build_server(port=12345)
    
    async def test_server_tools(self):
        tools = await self.server.list_tools()
        tool_names = [tool.name for tool in tools]
        
        self.assertIn("google_search", tool_names)

    async def test_serper_search(self):
        result = await self.server.call_tool(
            "google_search", 
            arguments={
                "q": "What is the capital of France?",
                "gl": "us",
                "hl": "en",
                "num": 5
            }
        )
        print(result)


if __name__ == "__main__":
    unittest.main()

