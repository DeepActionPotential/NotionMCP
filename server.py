from __future__ import annotations
from mcp.server.fastmcp import FastMCP

# Single shared app for the whole process
app = FastMCP("NotionMCPServer")

# Import tool modules AFTER creating `app`
import tools.search_tools as search_tools
import tools.read_tools as read_tools
import tools.ai_tools as ai_tools

# Register tools (synchronous)
search_tools.register(app)
read_tools.register(app)
ai_tools.register(app)

if __name__ == "__main__":
    app.run()
