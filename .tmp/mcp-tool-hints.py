"""List a live MCP server's tools and print the descriptions of the named ones (no auth header; public demo servers)."""
import asyncio
import sys

from fastmcp import Client


async def main(url: str, names: list[str]) -> None:
    async with Client(url) as client:
        tools = await client.list_tools()
        print(f"{url}: {len(tools)} tools")
        for tool in tools:
            if tool.name in names:
                caller = (tool.inputSchema or {}).get("properties", {})
                print(f"- {tool.name}: {tool.description[:600]!r}")
                print(f"  params: {sorted(caller)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
