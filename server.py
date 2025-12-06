from __future__ import annotations
from mcp.server.fastmcp import FastMCP

# Shared app instance
mcp = FastMCP(
    name="NotionMCPServer",
    stateless_http=True,
)

# Import tools after creating app
import tools.search_tools as search_tools
import tools.read_tools as read_tools
import tools.ai_tools as ai_tools

# Register tools
search_tools.register(mcp)
read_tools.register(mcp)
ai_tools.register(mcp)

if __name__ == "__main__":
    # Run using SSE transport so ChatGPT can connect
    mcp.run(transport="stdio")
