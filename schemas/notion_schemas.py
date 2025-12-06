from __future__ import annotations
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
from typing import Dict, List



class RichText(BaseModel):
    plain_text: str = ""


class TitlePropertyValue(BaseModel):
    type: str = "title"
    title: List[RichText] = Field(default_factory=list)


class PageObject(BaseModel):
    object: str = "page"
    id: str
    url: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)


class DatabaseObject(BaseModel):
    object: str = "database"
    id: str
    url: Optional[str] = None
    title: List[RichText] = Field(default_factory=list)


class ListResponse(BaseModel):
    object: str = "list"
    results: List[Dict[str, Any]] = Field(default_factory=list)
    has_more: bool = False
    next_cursor: Optional[str] = None




class NotionHTTPError(Exception):
    """
    Raised when the Notion API responds with a non-success status code that is not retried.

    Attributes
    ----------
    status : int
        HTTP status code (or 0 for client-side failures during decoding/timeouts).
    message : str
        Short description or HTTP reason phrase.
    body : Any
        Raw response body or additional error payload, when available.
    """

    def __init__(self, status: int, message: str, body: Any = None) -> None:
        super().__init__(f"Notion API error {status}: {message}")
        self.status: int = status
        self.body: Any = body


class NotionRateLimitError(NotionHTTPError):
    """Raised when the Notion API returns HTTP 429 (rate limited)."""
    pass




