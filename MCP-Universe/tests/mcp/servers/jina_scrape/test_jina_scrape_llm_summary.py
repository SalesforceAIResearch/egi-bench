import unittest
from mcpuniverse.mcp.servers.jina_scrape_llm_summary.server import build_server
import os
class TestJinaScrapeLlmSummary(unittest.IsolatedAsyncioTestCase):
    
    def setUp(self):
        self.server = build_server(port=12345)
    
    async def test_server_tools(self):
        tools = await self.server.list_tools()
        tool_names = [tool.name for tool in tools]
        
        self.assertIn("scrape_and_extract_info", tool_names)

    async def test_scrape_and_extract_info(self):
        result = await self.server.call_tool("scrape_and_extract_info", 
            arguments={
                "url": "https://arxiv.org/pdf/1706.03762",
                "info_to_extract": "the authors of the paper",
            }
        )
        print(result)


if __name__ == "__main__":
    unittest.main()

