"""Read-only local MCP service used only by synthetic E2E tests."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lune-fixture", host="127.0.0.1", port=8767, stateless_http=True)


@mcp.tool()
def echo(value: str) -> str:
    """Return a deterministic value without any external action."""
    return "TOOL_RESULT_MARKER: " + value


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
