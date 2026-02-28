"""Entry point: python3 -m mcp_server [--transport sse --port 8001]"""

from __future__ import annotations

import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="WarmPath Agent MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--port", type=int, default=8001, help="Port for SSE transport (default: 8001)"
    )
    args = parser.parse_args()

    from mcp_server.server import mcp, register_tools

    register_tools()

    if args.transport == "sse":
        mcp.settings.host = "0.0.0.0"  # bind all interfaces (container-accessible)
        mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
