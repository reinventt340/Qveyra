"""Detect whether an uploaded financial document is an invoice or a receipt."""

from __future__ import annotations

from pathlib import Path


def detect_document_type(file_path: str) -> str:
    """Return the document type by filename heuristics.

    This is a lightweight router before the Gemini prompt is chosen.
    """
    name = (Path(file_path).name or "").lower()
    receipt_keywords = [
        "receipt",
        "bill",
        "pos",
        "cash",
        "transaction",
        "payment",
        "store",
        "restaurant",
        "supermarket",
        "shop",
        "retail",
        "invoice_receipt",
    ]

    invoice_keywords = [
        "invoice",
        "tax",
        "commercial",
        "purchase",
        "quotation",
        "order",
        "statement",
        "vendor",
    ]

    if any(keyword in name for keyword in receipt_keywords):
        return "receipt"
    if any(keyword in name for keyword in invoice_keywords):
        return "invoice"
    return "invoice"
