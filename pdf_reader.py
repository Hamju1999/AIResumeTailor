"""
PDF Reader - extracts plain text from PDF files.

Uses pypdf (pure Python, no system-level C libs needed - Termux safe).
Falls back page-by-page and skips pages with no extractable text
so a single bad page doesn't blow up the whole read.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("pdf_reader")


def extract_text(pdf_path: Path) -> str:
    """
    Extract all text from a PDF and return as a single string.
    Raises FileNotFoundError if the path doesn't exist.
    Raises RuntimeError if no text could be extracted at all
    (e.g. scanned image PDF with no OCR layer).
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        import pypdf  # type: ignore
    except ImportError:
        raise ImportError(
            "pypdf is required to read PDFs.\n"
            "Install it with:  pip install pypdf"
        )

    reader = pypdf.PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    log.info(f"Reading PDF: {pdf_path.name} ({total_pages} pages)")

    extracted: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
            text = text.strip()
            if text:
                extracted.append(text)
            else:
                log.debug(f"  Page {i+1}: no text extracted (image-only page?)")
        except Exception as e:
            log.warning(f"  Page {i+1}: extraction error - {e}")

    if not extracted:
        raise RuntimeError(
            f"No text could be extracted from {pdf_path.name}.\n"
            "The PDF may be a scanned image without an OCR layer.\n"
            "Try opening in Adobe Acrobat → File → Export → Text, "
            "or use an online PDF-to-text converter and save the result as .txt."
        )

    full_text = "\n\n".join(extracted)
    log.info(f"  Extracted {len(full_text):,} characters from {pdf_path.name}")
    return full_text
