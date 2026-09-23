"""Gemini-based invoice extraction service."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from app.schemas.invoice import get_invoice_schema_template, normalize_invoice_fields

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env", override=False)

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
logger = logging.getLogger(__name__)


def get_env_value(*names: str) -> Optional[str]:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


try:
    from google import genai
except Exception:  # pragma: no cover - dependency may not be installed at import time
    genai = None


def clean_json_block(text: str) -> str:
    if not text:
        return text
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    return cleaned.strip()


def parse_response_json(response_text: str) -> dict[str, Any]:
    cleaned = clean_json_block(response_text)
    if not cleaned:
        raise ValueError("Gemini returned an empty response.")

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"Unable to parse JSON from Gemini response: {cleaned[:200]}")


def sanitize_fields(fields: dict[str, Any] | None) -> dict[str, Any]:
    return normalize_invoice_fields(fields)


def process_file(path: str) -> dict[str, Any]:
    """Extract invoice/receipt information from a file using Gemini."""
    result: dict[str, Any] = {
        "extracted_text": "",
        "fields": get_invoice_schema_template(),
        "method": None,
        "error": None,
    }

    logger.info("=== Processing file: %s ===", path)

    if not genai:
        logger.error("Gemini package is not available")
        return result

    api_key = get_env_value("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not api_key:
        logger.error("No Gemini API key was found in environment variables")
        return result

    try:
        client = genai.Client(api_key=api_key)

        with open(path, "rb") as file_obj:
            file_data = file_obj.read()

        file_ext = Path(path).suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
        }
        mime_type = mime_types.get(file_ext, "application/octet-stream")

        prompt = (
            "Extract all invoice or receipt data from this document and return ONLY valid JSON. "
            "Use the exact structure below and set any missing values to null. "
            "Do not add any explanation outside JSON.\n"
            + json.dumps(get_invoice_schema_template(), ensure_ascii=False)
        )

        encoded_data = base64.standard_b64encode(file_data).decode("utf-8")
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[
                prompt,
                {"inline_data": {"mime_type": mime_type, "data": encoded_data}},
            ],
        )

        response_text = (
            getattr(response, "text", None)
            or getattr(response, "output_text", None)
            or str(response)
        )
        logger.info("Gemini response: %s", response_text[:500])

        parsed_fields = parse_response_json(response_text)
        result["extracted_text"] = response_text
        result["method"] = "gemini"
        result["fields"] = sanitize_fields(parsed_fields)
        logger.info("SUCCESS: %s", result["fields"])
        return result

    except Exception as exc:  # pragma: no cover - runtime-specific issue path
        logger.error("ERROR: %s", exc, exc_info=True)
        result["error"] = str(exc)
        result["method"] = "error"
        return result
