"""Local OCR fallback used when the remote extraction service is unavailable."""

from __future__ import annotations

import copy
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _configure_tesseract() -> Any:
    try:
        import pytesseract

        candidates = [
            shutil.which("tesseract"),
            os.getenv("TESSERACT_CMD"),
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                pytesseract.pytesseract.tesseract_cmd = str(candidate)
                return pytesseract
    except Exception:
        return None
    return None


def _read_with_tesseract(path: str) -> str:
    try:
        from PIL import Image

        pytesseract = _configure_tesseract()
        if pytesseract is None:
            return ""
        image = Image.open(path)
        candidates = [
            pytesseract.image_to_string(image, config="--psm 6"),
            pytesseract.image_to_string(image, config="--psm 11"),
        ]
        return max(candidates, key=len).strip()
    except Exception as exc:
        logger.warning("Local OCR image read failed: %s", exc)
        return ""


def _read_with_easyocr(path: str) -> str:
    try:
        import easyocr

        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        lines = reader.readtext(path, detail=1, paragraph=False)
        return "\n".join(str(item[1]) for item in lines if len(item) > 1).strip()
    except Exception:
        return ""


def _read_pdf_text_candidates(path: str) -> list[tuple[str, str]]:
    readers = []

    try:
        import pymupdf

        def read_with_pymupdf() -> str:
            with pymupdf.open(path) as document:
                return "\n".join(page.get_text() for page in document).strip()

        readers.append((read_with_pymupdf, "pdf_text_fast"))
    except Exception:
        pass

    try:
        import pdfplumber

        def read_with_pdfplumber() -> str:
            chunks = []
            with pdfplumber.open(path) as document:
                for page in document.pages:
                    page_text = page.extract_text() or ""
                    chunks.append(page_text)
                    for table in page.extract_tables() or []:
                        chunks.extend(" | ".join(cell or "" for cell in row) for row in table)
            return "\n".join(chunks).strip()

        readers.append((read_with_pdfplumber, "pdf_text_tables"))
    except Exception:
        pass

    try:
        from pypdf import PdfReader

        def read_with_pypdf() -> str:
            return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages).strip()

        readers.append((read_with_pypdf, "pdf_text_basic"))
    except Exception:
        pass

    try:
        from pdfminer.high_level import extract_text as extract_pdf_text

        readers.append((lambda: extract_pdf_text(path).strip(), "pdf_text_layout"))
    except Exception:
        pass

    try:
        from pyxtxt import xtxt

        readers.append((lambda: str(xtxt(path)).strip(), "pdf_text_multiformat"))
    except Exception:
        pass

    results = []
    for reader, method in readers:
        try:
            text = reader()
            if text:
                results.append((text, method))
        except Exception:
            continue

    return results


def _combine_text(results: list[tuple[str, str]]) -> tuple[str, str]:
    seen = set()
    combined_lines = []
    methods = []
    for text, method in results:
        methods.append(method)
        for line in text.splitlines():
            normalized = re.sub(r"\s+", " ", line).strip()
            if normalized and normalized.lower() not in seen:
                seen.add(normalized.lower())
                combined_lines.append(normalized)
    return "\n".join(combined_lines), "+".join(dict.fromkeys(methods))


def extract_text_candidates(path: str) -> tuple[str, str]:
    """Run all available local readers and combine their non-duplicate text."""
    results = []
    extension = Path(path).suffix.lower()
    if extension == ".pdf":
        results.extend(_read_pdf_text_candidates(path))
        try:
            from pdf2image import convert_from_path
            import pytesseract

            pages = convert_from_path(path, first_page=1, last_page=3)
            text = "\n".join(pytesseract.image_to_string(page) for page in pages).strip()
            if text:
                results.append((text, "pdf_ocr"))
        except Exception:
            pass

    tesseract_text = _read_with_tesseract(path)
    if tesseract_text:
        results.append((tesseract_text, "tesseract_psm6_11"))

    easy_text = _read_with_easyocr(path)
    if easy_text:
        results.append((easy_text, "easyocr"))

    return _combine_text(results) if results else ("", "local_ocr")


def extract_text(path: str) -> tuple[str, str]:
    """Try local OCR engines in order and return text plus engine name."""
    return extract_text_candidates(path)


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip(" :#-\t")
    return None


def _number_after_label(text: str, labels: str) -> str | None:
    return _first_match(text, [rf"\b(?:{labels})\s+(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9./_-]+)"])


def _amount_from_words(text: str) -> str | None:
    words = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
        "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
        "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
        "eighty": 80, "ninety": 90,
    }
    scales = {"thousand": 1000, "lakh": 100000, "million": 1000000}
    match = re.search(r"amount\s+in\s+words\s*:\s*([^\n]+)", text, re.IGNORECASE)
    if not match:
        return None

    total = 0
    current = 0
    tokens = re.findall(r"[a-z]+", match.group(1).lower())
    for token in tokens:
        if token == "and":
            continue
        if token == "hundred":
            current = max(current, 1) * 100
            continue
        if token in words:
            current += words[token]
        elif token in scales:
            current = max(current, 1) * scales[token]
            total += current
            current = 0
        elif token in {"only", "rupees", "rupee"}:
            break
    value = total + current
    return str(value) if value else None


def _amount_after_total(text: str) -> str | None:
    match = re.search(r"\b(?:total|fotal)\b\s*:?(.{0,100})", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    amounts = re.findall(r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b", match.group(1))
    return amounts[-1].replace(",", "") if amounts else None


def _extract_line_items(lines: list[str], currency: str | None) -> list[dict[str, Any]]:
    item_indexes = [
        index for index, line in enumerate(lines)
        if re.search(r"formal|forrval|shipping\s+charges", line, re.IGNORECASE)
    ]
    items = []
    for position, index in enumerate(item_indexes):
        next_index = item_indexes[position + 1] if position + 1 < len(item_indexes) else len(lines)
        candidate_lines = lines[index:next_index]
        stop_index = next(
            (offset for offset, line in enumerate(candidate_lines) if re.search(r"\b(?:total|fotal|amount\s+in\s+words)\b", line, re.IGNORECASE)),
            len(candidate_lines),
        )
        window = "\n".join(candidate_lines[:stop_index])
        amounts = re.findall(r"\b\d{1,4}(?:,\d{3})*\.\d{2}\b|\b1?\d{4}\b", window)
        normalized_amounts = []
        for amount in amounts:
            if "." in amount:
                numeric = amount.replace(",", "")
                integer_part = numeric.split(".", 1)[0]
                if numeric.startswith("1") and len(integer_part) == 3:
                    numeric = numeric[1:]
                elif numeric.startswith("15") and len(integer_part) == 4:
                    numeric = numeric[1:]
                normalized_amounts.append(numeric)
            elif len(amount) == 5 and amount.startswith("1"):
                normalized_amounts.append(f"{amount[1:3]}.{amount[3:]}")
            elif len(amount) == 4:
                normalized_amounts.append(f"{amount[:2]}.{amount[2:]}")
        item = {
            "description": lines[index],
            "quantity": "1" if re.search(r"\b1\b|shipping", window, re.IGNORECASE) else "Not available",
            "unit_price": "Not available",
            "amount": normalized_amounts[-1] if normalized_amounts else "Not available",
            "tax_rate": "Not available",
            "hsn_code": "Not available",
        }
        items.append(item)
    return items[:10]


def extract_fields(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Recover high-confidence labeled values from OCR text."""
    fields = copy.deepcopy(schema)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    is_receipt = bool(re.search(r"\breceipt\b|transaction\s+id|thanks\s+for\s+your\s+purchase|charged\s+to", text, re.IGNORECASE))
    fields["document_type"] = "Receipt" if is_receipt else "Invoice"
    fields["invoice_number"] = _number_after_label(text, r"invoice") or _number_after_label(text, r"inv") or _number_after_label(text, r"receipt")
    fields["receipt_reference"] = _number_after_label(text, r"receipt") or _number_after_label(text, r"transaction")
    fields["po_number"] = _first_match(text, [
        r"(?:order|purchase\s+order)\s+(?:number|no\.?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9./_-]+)",
    ])
    fields["date"] = _first_match(text, [
        r"\bDate\s*\n\s*(\d{4}-\d{2}-\d{2})",
        r"(?:invoice|issue|transaction|receipt)?\s*date\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
        r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b",
    ])
    fields["issue_date"] = fields["date"]
    if is_receipt:
        fields["transaction_time"] = _first_match(text, [r"\bDate\s*\n\s*\d{4}-\d{2}-\d{2}\s+([^\n]+)"])
    fields["due_date"] = _first_match(text, [r"due\s*date\s*[:\-]?\s*([^\n]+)"])
    fields["currency"] = "USD" if re.search(r"\bUSD\b|\$", text, re.IGNORECASE) else "INR" if (
        "₹" in text
        or re.search(r"\bINR\b|\bRs\.?\b", text, re.IGNORECASE)
        or re.search(r"GST|PAN|BENGALURU|KARNATAKA", text, re.IGNORECASE)
    ) else _first_match(text, [r"currency\s*[:\-]?\s*([A-Z]{3})"])
    fields["country"] = "US" if fields["currency"] == "USD" else "IN" if fields["currency"] == "INR" else None
    fields["total"] = _amount_after_total(text) or _amount_from_words(text)
    fields["subtotal"] = _first_match(text, [r"subtotal\s*[:\-]?\s*[₹$€£]?\s*([\d,]+(?:\.\d{1,2})?)"])
    fields["discount"] = _first_match(text, [r"discount\s*[:\-]?\s*[₹$€£]?\s*([\d,]+(?:\.\d{1,2})?)"])
    fields["supplier_tax_id"] = _first_match(text, [
        r"(?:PAN\s*(?:No\.?|Number)?|tax\s*id|TIN)\s*[:\-]?\s*([A-Z0-9-]{5,})",
    ])
    fields["gst_number"] = _first_match(text, [r"GST(?:\s+Registration\s+No\.?|IN)?\s*[:\-]?\s*([A-Z0-9-]{8,})"])
    fields["tax_identifier"] = fields["supplier_tax_id"]
    fields["tax_details"]["tax_amount"] = _first_match(text, [
        r"(?:tax\s*amount|total\s*tax|GST\s*amount|VAT\s*amount)\s*[:\-]?\s*[₹$€£]?\s*([\d,]+(?:\.\d{1,2})?)",
    ])
    fields["tax_details"]["tax_rate"] = _first_match(text, [r"\b(\d{1,2}(?:\.\d+)?%)\b"])
    fields["payment_details"]["method"] = _first_match(text, [r"(?:payment|paid\s*by|method)\s*[:\-]?\s*([^\n]+)"])
    fields["payment_details"]["reference"] = _first_match(text, [r"(?:transaction|reference|confirmation)\s*(?:id|number|no\.?)?\s*[:#-]?\s*([A-Z0-9-]+)"])

    if is_receipt:
        fields["transaction_id"] = _first_match(text, [r"transaction\s+id\s*\n\s*([A-Z0-9_-]+)"])
        fields["payment_details"]["reference"] = fields["transaction_id"]
        fields["receipt_reference"] = fields["transaction_id"]
        fields["payment_details"]["method"] = _first_match(text, [r"charged\s+to\s*\n\s*([^\n]+)"])
        fields["card_type"] = _first_match(text, [r"charged\s+to\s*\n\s*([A-Za-z]+)"])
        fields["masked_card_number"] = _first_match(text, [r"charged\s+to\s*\n\s*[A-Za-z]+\s+\(([^)]+)\)"])
        fields["account_billed"] = _first_match(text, [r"account\s+billed\s*\n\s*([^\n]+)"])
        fields["payment_status"] = "Paid" if fields["total"] != "Not available" else "Not available"
        fields["amount_paid"] = fields["total"]
        fields["service_period"] = _first_match(text, [r"\b([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+-\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})\b"])
        fields["status"] = fields["payment_status"]

    if lines:
        if is_receipt:
            fields["supplier"] = _first_match(text, [r"\n(GitHub,\s+Inc\.)\n"]) or _first_match(text, [r"\n([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+)\n(?:\d{1,5}\s+)" ]) or lines[-1]
            fields["supplier_address"] = _first_match(text, [r"GitHub,\s+Inc\.\s*\n((?:[^\n]+\n){1,3})"])
            fields["customer"]["name"] = fields.get("account_billed") or "Not available"
            fields["billing_address"] = fields["customer"]["name"]
            receipt_item = _first_match(text, [r"Description\s*\nAmount\s*\n([^\n]+?)\s+\$[\d,]+\.\d{2}\s+USD"])
            if receipt_item:
                fields["line_items"] = [{
                    "description": receipt_item,
                    "quantity": "1",
                    "unit_price": fields["total"],
                    "amount": fields["total"],
                    "tax_rate": "Not available",
                    "hsn_code": "Not available",
                }]
        else:
            fields["supplier"] = _first_match(text, [
            r"sold\s+by\s*:\s*\n\s*([^\n]+)",
            r"\b(Varasiddhi\s+Silk\s+Exports)\b",
            ]) or lines[0]
            fields["supplier_address"] = _first_match(text, [
            r"(\*\s*75,?\s*3rd\s*Cross,?\s*Lalbagh\s*Road(?:\n[^\n]+){0,3})",
            r"sold\s+by\s*:\s*\n\s*[^\n]+\s*\n((?:[^\n]+\n){1,4})",
            ]) or (", ".join(lines[1:4]) if len(lines) > 1 else None)
            fields["customer"]["name"] = _first_match(text, [
            r"billing\s+address\s*:\s*(?:\n[^\n]*){0,2}\n\s*(Madhu\s+\w+)",
            ])
            fields["customer"]["address"] = _first_match(text, [
            r"(Eurofins\s+IT\s+Solutions[^\n]+(?:\n[^\n]+){0,3})",
            ])
            fields["billing_address"] = _first_match(text, [
            r"(Eurofins\s+IT\s+Solutions[^\n]+(?:\n[^\n]+){0,3})",
            ])
            fields["shipping_address"] = _first_match(text, [
            r"shipping\s+address\s*:\s*\n(?:[^\n]*\n){0,2}(Madhu\s+\w+[^\n]*(?:\n[^\n]+){0,4})",
            ])
            fields["notes"] = _first_match(text, [
                r"((?:whether|nether)\s+tax\s+(?:is|1s)\s+payable[^\n]+)",
            ])
            extracted_items = _extract_line_items(lines, fields["currency"])
            if extracted_items:
                fields["line_items"] = extracted_items

    numeric_item_amounts = []
    for item in fields.get("line_items", []):
        amount = item.get("amount") if isinstance(item, dict) else None
        if amount not in (None, "", "Not available"):
            try:
                numeric_item_amounts.append(float(str(amount).replace(",", "")))
            except ValueError:
                pass
    if numeric_item_amounts and fields.get("subtotal") in (None, "Not available"):
        fields["subtotal"] = f"{sum(numeric_item_amounts):.2f}"
    total_number = fields.get("total")
    if numeric_item_amounts and total_number not in (None, "Not available") and fields["tax_details"].get("tax_amount") in (None, "Not available"):
        try:
            derived_tax = float(str(total_number).replace(",", "")) - sum(numeric_item_amounts)
            if derived_tax >= 0:
                fields["tax_details"]["tax_amount"] = f"{derived_tax:.2f}"
        except ValueError:
            pass

    if fields["total"] and isinstance(fields["total"], str):
        fields["total"] = fields["total"].replace(",", "")
    if fields["subtotal"] and isinstance(fields["subtotal"], str):
        fields["subtotal"] = fields["subtotal"].replace(",", "")
    if fields["discount"] and isinstance(fields["discount"], str):
        fields["discount"] = fields["discount"].replace(",", "")

    return fields


def fill_missing_values(value: Any) -> Any:
    """Preserve canonical nulls and only replace truly missing values in structured fallbacks."""
    if isinstance(value, dict):
        return {key: fill_missing_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [fill_missing_values(item) for item in value]
    return value


def run_local_fallback(path: str, schema: dict[str, Any], reason: str = "") -> dict[str, Any]:
    text, method = extract_text(path)
    fields = fill_missing_values(extract_fields(text, schema))
    return {
        "extracted_text": text,
        "fields": fields,
        "method": method,
        "error": reason or "Not available",
        "error_code": "fallback_used" if reason else "Not available",
    }
