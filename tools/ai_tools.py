from __future__ import annotations
from typing import Optional

from mcp.server.fastmcp import FastMCP
from core.notion_clients import AINotionClient
from services.summarization_service import T5TextSummarizer
from services.text_emotion_service import TransformersEmotionDetector

_AI: Optional[AINotionClient] = None

def _get_ai() -> AINotionClient:
    global _AI
    if _AI is None:
        summarizer = T5TextSummarizer(model_name="t5-small")
        emotion = TransformersEmotionDetector()
        _AI = AINotionClient(summarizer, emotion, verbose=False)
    return _AI


def register(app: FastMCP) -> None:
    @app.tool()
    async def summarize_page_text(
        page,
        by_name=True,
        max_summary_length=200,
        preview_lines=None,
    ):
        """Resolve page, fetch text, and return a T5 abstractive summary."""
        try:
            ai = _get_ai()
            data = await ai.summarize_page_text(
                page,
                by_name=by_name,
                max_summary_length=max_summary_length,
                preview_lines=preview_lines,
            )
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}

    @app.tool()
    async def get_page_sentiment(
        page,
        by_name=True,
        preview_lines=None,
    ):
        """Resolve page, fetch text, and return emotion analysis."""
        try:
            ai = _get_ai()
            data = await ai.get_page_sentiment(
                page,
                by_name=by_name,
                preview_lines=preview_lines,
            )
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "error": repr(e)}
