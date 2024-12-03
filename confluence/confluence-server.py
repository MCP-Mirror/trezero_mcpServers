import os
import json
import logging
import base64
from typing import Any, List
import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import Resource, Tool
from pydantic import AnyUrl

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("confluence-server")

CONFLUENCE_URL = os.getenv("CONFLUENCE_URL")
EMAIL = os.getenv("CONFLUENCE_EMAIL")
API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")

if not all([CONFLUENCE_URL, EMAIL, API_TOKEN]):
    raise ValueError("CONFLUENCE_URL, CONFLUENCE_EMAIL, and CONFLUENCE_API_TOKEN environment variables required")

# Create base64 encoded auth header
auth_string = f"{EMAIL}:{API_TOKEN}"
auth_bytes = auth_string.encode('ascii')
base64_auth = base64.b64encode(auth_bytes).decode('ascii')

headers = {
    "Authorization": f"Basic {base64_auth}",
    "Content-Type": "application/json"
}

async def search_confluence(query: str) -> List[dict]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{CONFLUENCE_URL}/wiki/rest/api/search",
            headers=headers,
            params={"cql": query}
        )
        response.raise_for_status()
        return response.json()["results"]

async def get_page_content(page_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{CONFLUENCE_URL}/wiki/rest/api/content/{page_id}?expand=body.storage",
            headers=headers
        )
        response.raise_for_status()
        return response.json()

server = Server("confluence-server")

@server.list_resources()
async def list_resources() -> list[Resource]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{CONFLUENCE_URL}/wiki/rest/api/space",
            headers=headers
        )
        spaces_data = response.json()["results"]
        
    return [
        Resource(
            uri=AnyUrl(f"confluence://spaces/{space['key']}"),
            name=f"Space: {space['name']}",
            description=space.get('description', {}).get('plain', {}).get('value', ''),
            mimeType="application/json"
        ) for space in spaces_data
    ]

@server.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    uri_str = str(uri)
    if uri_str.startswith("confluence://spaces/"):
        space_key = uri_str.split("/")[-1]
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{CONFLUENCE_URL}/wiki/rest/api/space/{space_key}/content",
                headers=headers
            )
            return json.dumps(response.json(), indent=2)
    elif uri_str.startswith("confluence://pages/"):
        page_id = uri_str.split("/")[-1]
        content = await get_page_content(page_id)
        return json.dumps(content, indent=2)
    raise ValueError(f"Unknown resource: {uri}")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_content",
            description="Search Confluence content using CQL",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Confluence Query Language (CQL) query"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_page",
            description="Get Confluence page content by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_id": {
                        "type": "string",
                        "description": "Confluence page ID"
                    }
                },
                "required": ["page_id"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: Any) -> str:
    if name == "search_content":
        query = arguments.get("query")
        if not query:
            raise ValueError("Query parameter is required")
        results = await search_confluence(query)
        return json.dumps(results, indent=2)
    elif name == "get_page":
        page_id = arguments.get("page_id")
        if not page_id:
            raise ValueError("Page ID parameter is required")
        content = await get_page_content(page_id)
        return json.dumps(content, indent=2)
    raise ValueError(f"Unknown tool: {name}")

if __name__ == "__main__":
    server.run_stdio()