from abc import ABC, abstractmethod
from typing import Optional


class TextSummarizer(ABC):
    """
    Abstract base class for text summarization models.
    """

    @abstractmethod
    async def summarize(self, text: str, *, max_length: Optional[int] = 200) -> str:
        """
        Summarize a given text asynchronously.

        Parameters
        ----------
        text : str
            Input text to summarize.
        max_length : Optional[int], optional
            Maximum token length of the summary. Default is 200.

        Returns
        -------
        str
            Summarized text.
        """
        ...
