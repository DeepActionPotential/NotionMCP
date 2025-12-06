from __future__ import annotations
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from core.notion_clients import ReadNotionClient, SearchNotionClient


def register(app: FastMCP) -> None:
    @app.tool()
    async def read_ping() -> Dict[str, Any]:
        """Sanity check that read tools are loaded."""
        return {"ok": True, "message": "read tools loaded"}

    # ---------- existing content/block readers ----------
    @app.tool()
    async def get_page_content(
        page,
        by_name=False,
        page_size=100,
        start_cursor=None,
    ) -> Dict[str, Any]:
        """Fetch one page of block children for a page ID or name."""
        try:
            async with ReadNotionClient() as r:
                data = await r.get_page_content(
                    page, page_size=page_size, start_cursor=start_cursor, by_name=by_name
                )
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def iter_page_content(
        page,
        by_name=False,
        page_size=100,
        max_pages=20,
    ) -> Dict[str, Any]:
        """Iterate block-children pages up to max_pages."""
        chunks = []
        pages = 0
        try:
            async with ReadNotionClient() as r:
                async for ch in r.iter_page_content(page, page_size=page_size, by_name=by_name):
                    chunks.append(ch)
                    pages += 1
                    if pages >= max_pages or not ch.get("has_more"):
                        break
            return {"ok": True, "chunks": chunks, "pages": pages}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def get_page_text(
        page,
        by_name=False,
        limit=None,
    ) -> Dict[str, Any]:
        """Extract readable text (newline-joined) from a page."""
        try:
            async with ReadNotionClient() as r:
                text = await r.get_page_text(page, by_name=by_name, limit=limit)
            return {
                "ok": True,
                "text": text,
                "text_stats": {"chars": len(text), "lines": text.count("\n") + (1 if text else 0)},
            }
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    # ---------- NEW: objects & database APIs ----------
    async def _resolve_page_id(page: str, by_name: bool) -> str:
        """Helper: resolve title -> id if needed (internal only)."""
        if not by_name:
            return page
        async with SearchNotionClient() as s:
            data = await s.search_pages(query=page, page_size=1)
            res = data.get("results", [])
            if not res:
                raise ValueError(f"Page named '{page}' not found.")
            return res[0]["id"]

    @app.tool()
    async def get_page_object(page, by_name=False) -> Dict[str, Any]:
        """GET /pages/{id} (resolve by title if requested)."""
        try:
            pid = await _resolve_page_id(page, by_name)
            async with ReadNotionClient() as r:
                data = await r.get_page(pid)
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def get_block(block_id) -> Dict[str, Any]:
        """GET /blocks/{id}"""
        try:
            async with ReadNotionClient() as r:
                data = await r.get_block(block_id)
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def list_child_pages(
        page,
        by_name=False,
        page_size=100,
        max_pages=20,
    ) -> Dict[str, Any]:
        """Return child_page blocks (id + title)."""
        try:
            pid = await _resolve_page_id(page, by_name)
            async with ReadNotionClient() as r:
                data = await r.list_child_pages(pid, by_name=False, page_size=page_size, max_pages=max_pages)
            return {"ok": True, **data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def get_database_object(database_id) -> Dict[str, Any]:
        """GET /databases/{id}"""
        try:
            async with ReadNotionClient() as r:
                data = await r.get_database(database_id)
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def query_database(
        database_id,
        filter=None,
        sorts=None,
        page_size=100,
        start_cursor=None,
    ) -> Dict[str, Any]:
        """POST /databases/{id}/query (single page)."""
        try:
            async with ReadNotionClient() as r:
                data = await r.query_database(
                    database_id,
                    filter=filter,
                    sorts=sorts,
                    page_size=page_size,
                    start_cursor=start_cursor,
                )
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def iter_query_database(
        database_id,
        filter=None,
        sorts=None,
        page_size=100,
        max_pages=20,
    ) -> Dict[str, Any]:
        """Iterate database query across pages."""
        chunks = []
        pages = 0
        try:
            async with ReadNotionClient() as r:
                async for ch in r.iter_query_database(
                    database_id,
                    filter=filter,
                    sorts=sorts,
                    page_size=page_size,
                ):
                    chunks.append(ch)
                    pages += 1
                    if pages >= max_pages or not ch.get("has_more"):
                        break

            rows = []
            for ch in chunks:
                rows.extend(ch.get("results", []))

            return {"ok": True, "chunks": chunks, "rows": rows, "pages": pages, "count": len(rows)}

        except Exception as e:
            return {"ok": False, "error": repr(e)}

    # ---------- convenience readers ----------
    @app.tool()
    async def get_page_headings(page, by_name=False, max_pages=20) -> Dict[str, Any]:
        """Collect heading_1/2/3 texts from a page."""
        headings = []
        pages = 0
        try:
            async with ReadNotionClient() as r:
                async for ch in r.iter_page_content(page, by_name=by_name):
                    for b in ch.get("results", []):
                        btype = b.get("type")
                        if isinstance(btype, str) and btype.startswith("heading_"):
                            data = b.get(btype, {}) or {}
                            rt = data.get("rich_text") or []
                            txt = "".join(
                                t.get("plain_text", "") for t in rt if isinstance(t, dict)
                            ).strip()
                            if txt:
                                headings.append({"type": btype, "text": txt})
                    pages += 1
                    if pages >= max_pages or not ch.get("has_more"):
                        break
            return {"ok": True, "headings": headings, "count": len(headings)}

        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def get_page_checklist(page, by_name=False, max_pages=20) -> Dict[str, Any]:
        """Collect to_do items and their checked status."""
        items = []
        pages = 0
        try:
            async with ReadNotionClient() as r:
                async for ch in r.iter_page_content(page, by_name=by_name):
                    for b in ch.get("results", []):
                        if b.get("type") == "to_do":
                            data = b.get("to_do", {}) or {}
                            rt = data.get("rich_text") or []
                            txt = "".join(
                                t.get("plain_text", "") for t in rt if isinstance(t, dict)
                            ).strip()
                            items.append({"text": txt, "checked": bool(data.get("checked"))})
                    pages += 1
                    if pages >= max_pages or not ch.get("has_more"):
                        break
            return {"ok": True, "items": items, "count": len(items)}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def get_page_bullets(page, by_name=False, max_pages=20) -> Dict[str, Any]:
        """Collect bulleted_list_item and numbered_list_item texts."""
        bullets = []
        pages = 0
        try:
            async with ReadNotionClient() as r:
                async for ch in r.iter_page_content(page, by_name=by_name):
                    for b in ch.get("results", []):
                        t = b.get("type")
                        if t in ("bulleted_list_item", "numbered_list_item"):
                            data = b.get(t, {}) or {}
                            rt = data.get("rich_text") or []
                            txt = "".join(
                                x.get("plain_text", "") for x in rt if isinstance(x, dict)
                            ).strip()
                            if txt:
                                bullets.append(txt)
                    pages += 1
                    if pages >= max_pages or not ch.get("has_more"):
                        break
            return {"ok": True, "bullets": bullets, "count": len(bullets)}
        except Exception as e:
            return {"ok": False, "error": repr(e)}
