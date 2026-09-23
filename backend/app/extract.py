"""Backward-compatible wrapper for invoice extraction."""

from app.services.invoice_extraction import process_invoice_file as process_file

__all__ = ["process_file"]
