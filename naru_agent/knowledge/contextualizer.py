"""Contextual Retrieval: enrich chunks with situational context at ingest time."""

from __future__ import annotations


class ChunkContextualizer:
    """在 ingestion 時用 LLM 為每個 chunk 補充定位上下文。

    Anthropic 實測：搭配 BM25 降低 49% 檢索失敗率，搭配 reranker 降低 67%。
    成本：只在建庫時執行一次，查詢時零額外開銷。

    Args:
        model: LiteLLM 相容的模型 ID（預設輕量模型）
        api_key: 模型 API key（可從環境變數讀取）
    """

    PROMPT_TEMPLATE = """\
<document>
{document}
</document>

以下是要定位的 chunk：
<chunk>
{chunk}
</chunk>

請用一到三句話說明這個 chunk 在整份文件中的位置和背景脈絡，\
目的是改善向量搜索的準確度。只輸出這段說明，不要其他內容。"""

    def __init__(
        self,
        model: str = "gemini/gemini-2.5-flash-lite",
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key

    def contextualize(self, chunk: str, full_document: str) -> str:
        """為單一 chunk 生成定位上下文，回傳「上下文 + 原始 chunk」的合併文字。"""
        import litellm

        prompt = self.PROMPT_TEMPLATE.format(document=full_document, chunk=chunk)
        kwargs: dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        response = litellm.completion(**kwargs)
        context = response.choices[0].message.content.strip()
        return f"{context}\n{chunk}"
