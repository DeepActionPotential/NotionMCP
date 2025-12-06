from __future__ import annotations
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP
from core.notion_clients import SearchNotionClient
from utils.helpers import extract_page_title


def register(app: FastMCP) -> None:
    @app.tool()
    async def search_ping() -> Dict[str, Any]:
        """Sanity check that search tools are loaded."""
        return {"ok": True, "message": "search tools loaded"}

    @app.tool()
    async def whoami() -> Dict[str, Any]:
        """Return integration identity for the current Notion token."""
        try:
            async with SearchNotionClient() as s:
                data = await s.whoami()
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def list_users(page_size=100, max_pages=10) -> Dict[str, Any]:
        """List Notion users (paginated)."""
        chunks = []
        pages = 0
        try:
            async with SearchNotionClient() as s:
                async for ch in s.iter_users(page_size=page_size):
                    chunks.append(ch)
                    pages += 1
                    if pages >= max_pages or not ch.get("has_more"):
                        break

            users = []
            for ch in chunks:
                users.extend(ch.get("results", []))

            return {"ok": True, "users": users, "pages": pages, "count": len(users)}

        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def get_user(user_id) -> Dict[str, Any]:
        """Get a single user by ID."""
        try:
            async with SearchNotionClient() as s:
                data = await s.get_user(user_id)
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def search(
        query=None,
        filter_value=None,
        page_size=50,
        start_cursor=None,
        sort_direction=None,
        sort_timestamp=None,
    ) -> Dict[str, Any]:
        """Run Notion unified /search once."""
        sort = (
            {"direction": sort_direction, "timestamp": sort_timestamp}
            if sort_direction and sort_timestamp else None
        )
        try:
            async with SearchNotionClient() as s:
                data = await s.search(
                    query=query,
                    filter_value=filter_value,
                    page_size=page_size,
                    start_cursor=start_cursor,
                    sort=sort,
                )
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def iter_search(
        query=None,
        filter_value=None,
        page_size=50,
        max_pages=10,
        sort_direction=None,
        sort_timestamp=None,
    ) -> Dict[str, Any]:
        """Iterate /search up to max_pages; returns a list of chunks."""
        sort = (
            {"direction": sort_direction, "timestamp": sort_timestamp}
            if sort_direction and sort_timestamp else None
        )
        chunks = []
        pages = 0
        try:
            async with SearchNotionClient() as s:
                async for ch in s.iter_search(
                    query=query,
                    filter_value=filter_value,
                    page_size=page_size,
                    sort=sort,
                ):
                    chunks.append(ch)
                    pages += 1
                    if pages >= max_pages or not ch.get("has_more"):
                        break

            return {"ok": True, "chunks": chunks, "pages": pages}

        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def search_titles(query, page_size=20) -> Dict[str, Any]:
        """Return compact (id, title) pairs for a query."""
        try:
            async with SearchNotionClient() as s:
                data = await s.search_titles(query, page_size=page_size)
            return {"ok": True, **data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def find_page_by_title(title, case_sensitive=False) -> Dict[str, Any]:
        """Find the first page whose title exactly matches `title`."""
        try:
            async with SearchNotionClient() as s:
                first = await s.search_pages(query=title, page_size=10)
                candidates = first.get("results", [])

                wanted = title if case_sensitive else title.lower()

                for p in candidates:
                    t = (extract_page_title(p) or "").strip()
                    k = t if case_sensitive else t.lower()
                    if k == wanted:
                        return {"ok": True, "match": {"id": p.get("id"), "title": t}, "candidates": candidates}

                return {"ok": True, "match": None, "candidates": candidates}

        except Exception as e:
            return {"ok": False, "error": repr(e)}
