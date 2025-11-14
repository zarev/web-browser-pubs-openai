"""Process downloaded PDFs into Markdown and embeddings."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from pipelines.send_to_gemini import markdown_from_pdf


async def process_downloaded_pdfs(pdf_directory: str = "data/raw_pdfs") -> List[dict]:
    """Convert PDFs into Markdown chunks using Gemini."""
    pdf_dir = Path(pdf_directory)
    outputs: List[dict] = []
    if not pdf_dir.exists():
        return outputs

    for pdf_path in pdf_dir.glob("*.pdf"):
        markdown = await markdown_from_pdf(pdf_path)
        outputs.append({"path": str(pdf_path), "markdown": markdown})
    return outputs
