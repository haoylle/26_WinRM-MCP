from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools import register_all_tools

APP_NAME = "winrm-mcp"

mcp = FastMCP(APP_NAME)
register_all_tools(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
