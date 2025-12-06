from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field




def extract_page_title(page_obj: Dict[str, Any]) -> str:
    """Best-effort title extraction from a Notion page object."""
    props = page_obj.get("properties", {})
    for prop in props.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            texts = prop.get("title") or []
            return "".join((t.get("plain_text", "") for t in texts)).strip()
    # Fallback for older shapes
    if "title" in page_obj:
        return "".join((t.get("plain_text", "") for t in page_obj["title"])).strip()
    return ""


def extract_database_title(db_obj: Dict[str, Any]) -> str:
    texts = db_obj.get("title") or []
    title = "".join((t.get("plain_text", "") for t in texts)).strip()
    return title or "(untitled db)"


def page_id_from_url(url: str) -> str:
    """Extract dashed UUID from common Notion URLs."""
    m = re.search(r"([0-9a-fA-F]{32})", url)
    if m:
        raw = m.group(1)
        return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", url)
    if not m:
        raise ValueError("Could not parse Notion page id from URL")
    return m.group(1)


def rich_text_to_string(rt) -> str:
    """Turn Notion rich_text (or variants) into a single string."""
    if rt is None:
        return ""
    if isinstance(rt, str):
        return rt
    if isinstance(rt, dict):
        return rt.get("plain_text", "")
    if isinstance(rt, list):
        return "".join((t.get("plain_text", "") if isinstance(t, dict) else str(t)) for t in rt)
    return ""
