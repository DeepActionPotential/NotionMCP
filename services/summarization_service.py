from __future__ import annotations

import asyncio
from typing import Optional, Tuple

from transformers import T5ForConditionalGeneration, T5Tokenizer
from schemas.base import TextSummarizer


class T5TextSummarizer(TextSummarizer):
    """
    Lightweight local text summarizer using a pretrained T5 model.

    Default model: 't5-small'
    """

    def __init__(self, model_name: str = "t5-small", device: Optional[str] = None) -> None:
        self.model_name = model_name
        self.device = device or ("cuda" if self._has_cuda() else "cpu")

        self.tokenizer = T5Tokenizer.from_pretrained(model_name)
        self.model = T5ForConditionalGeneration.from_pretrained(model_name).to(self.device)

    @staticmethod
    def _has_cuda() -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    async def summarize(self, text: str, *, max_length: Optional[int] = 200) -> str:
        """
        Summarize text asynchronously using T5 model.

        Parameters
        ----------
        text : str
            Input text to summarize.
        max_length : Optional[int]
            Maximum token length of the summary. Default is 200.

        Returns
        -------
        str
            Summarized text.
        """
        import torch

        # Move heavy blocking work to thread pool
        return await asyncio.to_thread(self._generate_summary, text, max_length)

    def _generate_summary(self, text: str, max_length: Optional[int]) -> str:
        """
        Private synchronous summarization function executed in a background thread.
        """
        input_text = "summarize: " + text.strip().replace("\n", " ")
        inputs = self.tokenizer.encode(
            input_text, return_tensors="pt", max_length=1024, truncation=True
        ).to(self.device)

        summary_ids = self.model.generate(
            inputs,
            max_length=max_length,
            min_length=30,
            length_penalty=2.0,
            num_beams=4,
            early_stopping=True,
        )

        summary = self.tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        return summary.strip()


