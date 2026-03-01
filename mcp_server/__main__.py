"""Entry point: python3 -m mcp_server [--transport sse --port 8001]"""

from __future__ import annotations

import argparse
import logging
import os

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
        from mcp.server.transport_security import TransportSecuritySettings

        mcp.settings.host = "0.0.0.0"  # bind all interfaces (container-accessible)
        mcp.settings.port = args.port

        # Railway (and other reverse proxies) forward requests with the
        # public hostname as the Host header.  The MCP SDK's default DNS
        # rebinding protection rejects anything that isn't localhost,
        # returning 421.  Whitelist the Railway domain via env var.
        railway_host = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
        allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
        if railway_host:
            allowed_hosts.append(f"{railway_host}:*")
            allowed_hosts.append(railway_host)
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
        )

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
