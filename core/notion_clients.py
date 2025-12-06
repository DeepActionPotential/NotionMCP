from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, Optional, Tuple, List
import httpx

from services.summarization_service import T5TextSummarizer
from schemas.ai_tools_schemas import EmotionDetector, EmotionResult
from schemas.notion_schemas import NotionHTTPError, NotionRateLimitError
from utils.helpers import extract_page_title
from .config import settings




_DEFAULT_PAGE_SIZE: int = 50


class BaseNotionClient:
    """
    Base async Notion client providing shared lifecycle management, headers, retries,
    and a unified request method with exponential backoff.

    Parameters
    ----------
    verbose : bool
        When True, prints simple retry/backoff diagnostics to stdout.
    """

    def __init__(self, *, verbose: bool = False) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self.verbose: bool = verbose

    async def _ensure_client(self) -> httpx.AsyncClient:
        """
        Ensure an underlying httpx.AsyncClient exists and return it.

        Returns
        -------
        httpx.AsyncClient
            A live async client configured with base URL, timeout, and headers.
        """
        async with self._lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    base_url=settings.notion_api_base,
                    timeout=settings.timeout_seconds,
                    headers=self._headers(),
                )
            return self._client

    async def aclose(self) -> None:
        """
        Close the underlying HTTP client, if any, and reset the handle.
        """
        async with self._lock:
            if self._client:
                await self._client.aclose()
                self._client = None

    async def __aenter__(self) -> "BaseNotionClient":
        """
        Enter the async context manager, ensuring the client is ready.

        Returns
        -------
        BaseNotionClient
            The client instance.
        """
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """
        Exit the async context manager, closing the client.
        """
        await self.aclose()

    def _headers(self) -> Dict[str, str]:
        """
        Build default headers for all Notion API requests.

        Returns
        -------
        Dict[str, str]
            HTTP headers including authorization and API version.
        """
        return {
            "Authorization": f"Bearer {settings.notion_token}",
            "Notion-Version": settings.notion_version,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 4,
    ) -> Dict[str, Any]:
        """
        Perform an HTTP request with retry/backoff logic for rate limiting, timeouts,
        and transient server errors.

        Parameters
        ----------
        method : str
            HTTP method (e.g., "GET", "POST").
        path : str
            API path (e.g., "/search").
        json_data : Optional[Dict[str, Any]]
            JSON body for the request, if applicable.
        params : Optional[Dict[str, Any]]
            Query parameters for the request.
        max_retries : int
            Maximum retry attempts for transient failures.

        Returns
        -------
        Dict[str, Any]
            Decoded JSON response.

        Raises
        ------
        NotionHTTPError
            If the request ultimately fails or returns invalid JSON.
        """
        client = await self._ensure_client()
        attempt: int = 0
        delay: float = 1.0

        while True:
            try:
                r = await client.request(method, path, json=json_data, params=params)

                if r.is_success:
                    return r.json()

                if r.status_code == 429:
                    retry_after = float(r.headers.get("Retry-After", delay))
                    if self.verbose:
                        print(f"[429] Rate limited — sleeping {retry_after:.1f}s...")
                    await asyncio.sleep(retry_after)
                    attempt += 1
                    continue

                if r.status_code >= 500 and attempt < max_retries:
                    if self.verbose:
                        print(f"[{r.status_code}] server error — retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    delay *= 2.0
                    attempt += 1
                    continue

                raise NotionHTTPError(r.status_code, r.reason_phrase or "Unknown", r.text)

            except httpx.ConnectTimeout:
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    attempt += 1
                    continue
                raise NotionHTTPError(0, "Connection timeout")

            except httpx.ReadTimeout:
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
                    attempt += 1
                    continue
                raise NotionHTTPError(0, "Read timeout")

            except json.JSONDecodeError as e:
                raise NotionHTTPError(getattr(r, "status_code", 0), f"Invalid JSON: {e}")


class SearchNotionClient(BaseNotionClient):
    """
    Client focused on identity and search endpoints.

    Inherits
    --------
    BaseNotionClient
        Provides lifecycle and request behavior.
    """

    async def whoami(self) -> Dict[str, Any]:
        """
        Fetch the bot/integration user object for the current token.

        Returns
        -------
        Dict[str, Any]
            Notion user payload for the integration.
        """
        return await self._request("GET", "/users/me")

    async def search(
        self,
        query: Optional[str] = None,
        *,
        filter_value: Optional[str] = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        start_cursor: Optional[str] = None,
        sort: Optional[Dict[str, str]] = None,) -> Dict[str, Any]:
        """
        Perform a Notion unified search over pages and databases.

        Parameters
        ----------
        query : Optional[str]
            Search query string. If None, returns recent items.
        filter_value : Optional[str]
            "page" to restrict to pages, "database" to restrict to databases, or None for both.
        page_size : int
            Page size (max 100).
        start_cursor : Optional[str]
            Pagination cursor for the next page.
        sort : Optional[Dict[str, str]]
            Sort descriptor, e.g. {"direction":"descending","timestamp":"last_edited_time"}.

        Returns
        -------
        Dict[str, Any]
            List payload with results, has_more, and next_cursor.
        """
        payload: Dict[str, Any] = {"page_size": page_size}
        if query:
            payload["query"] = query
        if filter_value:
            payload["filter"] = {"property": "object", "value": filter_value}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        if sort:
            payload["sort"] = sort
        return await self._request("POST", "/search", json_data=payload)

    async def iter_search(
        self,
        *,
        query: Optional[str] = None,
        filter_value: Optional[str] = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        sort: Optional[Dict[str, str]] = None,) -> AsyncIterator[Dict[str, Any]]:
        """
        Iterate over all search pages until exhaustion.

        Yields
        ------
        Dict[str, Any]
            A page of results from the search endpoint.
        """
        cursor: Optional[str] = None
        while True:
            data = await self.search(
                query=query,
                filter_value=filter_value,
                page_size=page_size,
                start_cursor=cursor,
                sort=sort,
            )
            yield data
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    async def search_pages(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Search restricted to page objects.

        Returns
        -------
        Dict[str, Any]
            List response containing pages.
        """
        return await self.search(filter_value="page", **kwargs)

    async def iter_search_pages(self, **kwargs: Any) -> AsyncIterator[Dict[str, Any]]:
        """
        Iterate over search results restricted to page objects.

        Yields
        ------
        Dict[str, Any]
            A page of page results.
        """
        async for chunk in self.iter_search(filter_value="page", **kwargs):
            yield chunk

    async def search_databases(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Search restricted to database objects.

        Returns
        -------
        Dict[str, Any]
            List response containing databases.
        """
        return await self.search(filter_value="database", **kwargs)

    async def iter_search_databases(self, **kwargs: Any) -> AsyncIterator[Dict[str, Any]]:
        """
        Iterate over search results restricted to database objects.

        Yields
        ------
        Dict[str, Any]
            A page of database results.
        """
        async for chunk in self.iter_search(filter_value="database", **kwargs):
            yield chunk
    

    async def list_users(
        self,
        *,
        page_size: int = 100,
        start_cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """GET /users (single page)."""
        params: Dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor
        return await self._request("GET", "/users", params=params)

    async def iter_users(self, *, page_size: int = 100) -> AsyncIterator[Dict[str, Any]]:
        """Iterate all users."""
        cursor: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"page_size": page_size}
            if cursor:
                params["start_cursor"] = cursor
            page = await self._request("GET", "/users", params=params)
            yield page
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")

    async def get_user(self, user_id: str) -> Dict[str, Any]:
        """GET /users/{id}"""
        return await self._request("GET", f"/users/{user_id}")

    async def search_titles(self, query: str, *, page_size: int = 20) -> Dict[str, Any]:
        """
        Convenience: search pages (and DBs) and return (id, title) pairs where possible.
        """
        data = await self.search(query=query, page_size=page_size)
        items = []
        for obj in data.get("results", []):
            oid = obj.get("id")
            title = extract_page_title(obj) or ""
            items.append({"id": oid, "title": title})
        return {"results": items, "raw": data}





class ReadNotionClient(BaseNotionClient):
    """
    Client focused on reading page/block content via block-children endpoints.

    Supports fetching by page ID or, when `by_name=True`, by resolving a page title first.
    """

    async def get_page_content(
        self,
        page_id: str,
        *,
        page_size: int = 100,
        start_cursor: Optional[str] = None,
        by_name: bool = False,) -> Dict[str, Any]:
        """Retrieve a single page of block children for a given page ID or name."""
        resolved_id = page_id
        if by_name:
            search_client = SearchNotionClient(verbose=self.verbose)
            async with search_client:
                result = await search_client.search_pages(query=page_id, page_size=5)
                pages = result.get("results", [])
                if not pages:
                    raise NotionHTTPError(404, f"Page named '{page_id}' not found.")
                resolved_id = pages[0]["id"]

        params: Dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor

        return await self._request("GET", f"/blocks/{resolved_id}/children", params=params)

    async def iter_page_content(
        self,
        page_id: str,
        *,
        page_size: int = 100,
        by_name: bool = False) -> AsyncIterator[Dict[str, Any]]:
        """Iterate through all block children for a given page."""
        resolved_id = page_id
        if by_name:
            search_client = SearchNotionClient(verbose=self.verbose)
            async with search_client:
                result = await search_client.search_pages(query=page_id, page_size=5)
                pages = result.get("results", [])
                if not pages:
                    raise NotionHTTPError(404, f"Page named '{page_id}' not found.")
                resolved_id = pages[0]["id"]

        cursor: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"page_size": page_size}
            if cursor:
                params["start_cursor"] = cursor
            page = await self._request("GET", f"/blocks/{resolved_id}/children", params=params)
            yield page
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")

    async def get_page_text(
        self,
        page_id: str,
        *,
        by_name: bool = False,
        limit: Optional[int] = None) -> str:
        """
        Retrieve and concatenate readable text content from a Notion page.

        Parameters
        ----------
        page_id : str
            The Notion page ID, or title if `by_name=True`.
        by_name : bool, optional
            If True, resolve the given name to an ID via /search. Default is False.
        limit : Optional[int], optional
            Limit number of text lines returned (for debugging or previews).

        Returns
        -------
        str
            All readable text concatenated with newlines.
        """

        def _extract_text(block: Dict[str, Any]) -> Optional[str]:
            """Extract readable text from a single block."""
            btype = block.get("type")
            if not btype:
                return None

            data = block.get(btype, {})
            if not isinstance(data, dict):
                return None

            rt = data.get("rich_text") or []
            text = "".join(t.get("plain_text", "") for t in rt if isinstance(t, dict))

            if btype == "to_do":
                prefix = "✓ " if data.get("checked") else "□ "
                text = prefix + text
            elif btype.startswith("heading_"):
                text = f"# {text}"
            elif btype in ("bulleted_list_item", "numbered_list_item"):
                text = f"- {text}"
            elif btype == "quote":
                text = f"> {text}"
            elif btype == "callout":
                text = f"💡 {text}"

            if text.strip():
                return text.strip()
            return None

        lines: List[str] = []
        async for chunk in self.iter_page_content(page_id, by_name=by_name):
            for block in chunk.get("results", []):
                line = _extract_text(block)
                if line:
                    lines.append(line)
                    if limit and len(lines) >= limit:
                        return "\n".join(lines)
        return "\n".join(lines)
    


    async def get_page(self, page_id: str) -> Dict[str, Any]:
        """GET /pages/{page_id}"""
        return await self._request("GET", f"/pages/{page_id}")

    async def get_database(self, database_id: str) -> Dict[str, Any]:
        """GET /databases/{database_id}"""
        return await self._request("GET", f"/databases/{database_id}")

    async def query_database(
        self,
        database_id: str,
        *,
        filter: Optional[Dict[str, Any]] = None,
        sorts: Optional[list] = None,
        page_size: int = 100,
        start_cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """POST /databases/{id}/query (one page)."""
        payload: Dict[str, Any] = {"page_size": page_size}
        if filter is not None:
            payload["filter"] = filter
        if sorts is not None:
            payload["sorts"] = sorts
        if start_cursor:
            payload["start_cursor"] = start_cursor
        return await self._request("POST", f"/databases/{database_id}/query", json_data=payload)

    async def iter_query_database(
        self,
        database_id: str,
        *,
        filter: Optional[Dict[str, Any]] = None,
        sorts: Optional[list] = None,
        page_size: int = 100,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Iterate a database query across pages."""
        cursor: Optional[str] = None
        while True:
            page = await self.query_database(
                database_id,
                filter=filter,
                sorts=sorts,
                page_size=page_size,
                start_cursor=cursor,
            )
            yield page
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")

    async def get_block(self, block_id: str) -> Dict[str, Any]:
        """GET /blocks/{block_id}"""
        return await self._request("GET", f"/blocks/{block_id}")

    async def list_child_pages(
        self,
        page_id: str,
        *,
        by_name: bool = False,
        page_size: int = 100,
        max_pages: int = 20,
    ) -> Dict[str, Any]:
        """
        Scan block children and return child_page blocks (title + id).
        """
        results: list = []
        pages = 0
        async for ch in self.iter_page_content(page_id, page_size=page_size, by_name=by_name):
            for b in ch.get("results", []):
                if b.get("type") == "child_page":
                    title = (b.get("child_page", {}) or {}).get("title") or ""
                    results.append({"id": b.get("id"), "title": title})
            pages += 1
            if pages >= max_pages or not ch.get("has_more"):
                break
        return {"results": results, "pages": pages, "count": len(results)}






class AINotionClient(BaseNotionClient):
    """
    AI-enabled Notion client that can summarize page text and analyze its sentiment/emotion.

    Parameters
    ----------
    summarizer : T5TextSummarizer
        Summarizer instance used to generate abstractive summaries.
    emotion_detector : EmotionDetector
        Emotion detector instance used to analyze page text.
    verbose : bool
        Enable simple retry/backoff diagnostics in the underlying BaseNotionClient.
    """

    def __init__(
        self,
        summarizer: T5TextSummarizer,
        emotion_detector: EmotionDetector,
        *,
        verbose: bool = False,
    ) -> None:
        super().__init__(verbose=verbose)
        self.summarizer: T5TextSummarizer = summarizer
        self.emotion_detector: EmotionDetector = emotion_detector

    async def _resolve_page(
        self,
        page: str,
        *,
        by_name: bool,
    ) -> Tuple[str, Optional[str]]:
        """
        Resolve a page identifier to a concrete Notion page ID and best-effort title.

        Parameters
        ----------
        page : str
            A page UUID (if by_name=False) or a page title (if by_name=True).
        by_name : bool
            When True, resolves the provided title into a page ID via /search.

        Returns
        -------
        Tuple[str, Optional[str]]
            (page_id, page_title) — title may be None if not cheaply discoverable.

        Raises
        ------
        ValueError
            If the page cannot be found or is not shared with the integration.
        """
        if by_name:
            async with SearchNotionClient(verbose=self.verbose) as s:
                async for chunk in s.iter_search_pages(query=page, page_size=50):
                    for p in chunk.get("results", []):
                        title = (extract_page_title(p) or "").strip()
                        if title.lower() == page.strip().lower():
                            return p["id"], title
                first = await s.search_pages(query=page, page_size=1)
                if first.get("results"):
                    p = first["results"][0]
                    return p["id"], (extract_page_title(p) or "").strip()
                raise ValueError(f"Page named '{page}' not found or not shared with the integration.")
        else:
            page_id = page
            title: Optional[str] = None
            try:
                async with SearchNotionClient(verbose=self.verbose) as s:
                    first = await s.search_pages(query=None, page_size=20)
                    for p in first.get("results", []):
                        if p.get("id") == page_id:
                            title = (extract_page_title(p) or "").strip() or None
                            break
            except Exception:
                pass
            return page_id, title

    async def summarize_page_text(
        self,
        page: str,
        *,
        by_name: bool = True,
        max_summary_length: int = 200,
        preview_lines: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Resolve a page (by name or ID), fetch its readable TEXT, and return an abstractive summary.

        Parameters
        ----------
        page : str
            Page title (if by_name=True) or page ID (UUID) if by_name=False.
        by_name : bool, optional
            Resolve `page` by title using search when True. Default: True.
        max_summary_length : int, optional
            Max token length for the generated summary. Default: 200.
        preview_lines : Optional[int], optional
            If provided, limit the number of text lines fetched before summarizing.

        Returns
        -------
        Dict[str, Any]
            {
              "page_id": str,
              "page_title": Optional[str],
              "summary": str,
              "text_stats": {"chars": int, "lines": int}
            }
        """
        page_id, page_title = await self._resolve_page(page, by_name=by_name)
        async with ReadNotionClient(verbose=self.verbose) as r:
            text = await r.get_page_text(page_id, by_name=False, limit=preview_lines)

        summary = await self.summarizer.summarize(text, max_length=max_summary_length)

        return {
            "page_id": page_id,
            "page_title": page_title,
            "summary": summary,
            "text_stats": {
                "chars": len(text),
                "lines": text.count("\n") + (1 if text else 0),
            },
        }

    async def get_page_sentiment(
        self,
        page: str,
        *,
        by_name: bool = True,
        preview_lines: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Resolve a page (by name or ID), fetch its readable TEXT, and analyze sentiment/emotions.

        Parameters
        ----------
        page : str
            Page title (if by_name=True) or page ID (UUID) if by_name=False.
        by_name : bool, optional
            Resolve `page` by title using search when True. Default: True.
        preview_lines : Optional[int], optional
            If provided, limit the number of text lines fetched before analysis.

        Returns
        -------
        Dict[str, Any]
            {
              "page_id": str,
              "page_title": Optional[str],
              "emotion": {
                  "dominant_emotion": str,
                  "confidence": float,
                  "all_scores": Dict[str, float]
              },
              "text_stats": {"chars": int, "lines": int}
            }
        """
        page_id, page_title = await self._resolve_page(page, by_name=by_name)
        async with ReadNotionClient(verbose=self.verbose) as r:
            text = await r.get_page_text(page_id, by_name=False, limit=preview_lines)

        emotion: EmotionResult = self.emotion_detector.analyze(text)

        return {
            "page_id": page_id,
            "page_title": page_title,
            "emotion": {
                "dominant_emotion": emotion.dominant_emotion,
                "confidence": emotion.confidence,
                "all_scores": emotion.all_scores,
            },
            "text_stats": {
                "chars": len(text),
                "lines": text.count("\n") + (1 if text else 0),
            },
        }
