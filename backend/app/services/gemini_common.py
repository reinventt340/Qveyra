from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from app.services.local_ocr import fill_missing_values, run_local_fallback

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env", override=True)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def get_env_value(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def clean_json_block(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    return cleaned.strip()


def parse_response_json(response_text: str) -> dict[str, Any]:
    cleaned = clean_json_block(response_text)
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
    raise ValueError("The Groq response was not valid JSON.")


def normalize_provider_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Map richer provider party objects into the stable application schema."""
    normalized = dict(fields)
    supplier = normalized.get("supplier")
    if isinstance(supplier, dict):
        supplier_obj = dict(supplier)
        normalized["supplier"] = supplier_obj
        normalized["supplier_address"] = supplier_obj.get("address", normalized.get("supplier_address"))
        normalized["supplier_contact"] = supplier_obj.get("contact", normalized.get("supplier_contact"))
        normalized["supplier_tax_id"] = supplier_obj.get("tax_id", normalized.get("supplier_tax_id"))
        normalized["supplier_gstin"] = supplier_obj.get("gstin", normalized.get("supplier_gstin"))
        normalized["supplier_pan"] = supplier_obj.get("pan", normalized.get("supplier_pan"))
        normalized["supplier_state_code"] = supplier_obj.get("state_code", normalized.get("supplier_state_code"))
    customer = normalized.get("customer")
    if isinstance(customer, dict):
        customer_obj = dict(customer)
        normalized["customer"] = customer_obj
        normalized["billing_address"] = customer_obj.get("address", normalized.get("billing_address"))
        normalized["customer_gstin"] = customer_obj.get("gstin", normalized.get("customer_gstin"))
        normalized["customer_pan"] = customer_obj.get("pan", normalized.get("customer_pan"))
    return normalized


def run_fallbacks(path: str, schema: dict[str, Any], reason: str) -> dict[str, Any]:
    return run_local_fallback(path, schema, reason)


def _image_payload(path: str) -> tuple[str, str]:
    source_path = Path(path)
    if source_path.suffix.lower() == ".pdf":
        import tempfile
        import pymupdf

        with pymupdf.open(path) as document:
            pixmap = document[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            temporary_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            temporary_path = Path(temporary_file.name)
            temporary_file.close()
            pixmap.save(str(temporary_path))
        file_data = temporary_path.read_bytes()
        temporary_path.unlink(missing_ok=True)
        return "image/png", base64.b64encode(file_data).decode("ascii")

    file_data = source_path.read_bytes()
    mime_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(Path(path).suffix.lower(), "application/octet-stream")
    return mime_type, base64.b64encode(file_data).decode("ascii")


def process_file_with_prompt(path: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    api_key = get_env_value("GROQ_API_KEY")
    if not api_key:
        return run_fallbacks(path, schema, "Groq is not configured; PDF/OCR fallback was used.")

    try:
        mime_type, encoded_data = _image_payload(path)
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        response = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{prompt}\n\nReturn JSON only. Use null for absent or unreadable values."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_data}"}},
                ],
            }],
            temperature=0,
            max_completion_tokens=4096,
            response_format={"type": "json_object"},
        )
        finish_reason = getattr(response.choices[0], "finish_reason", None)
        usage = getattr(response, "usage", None)
        usage_diagnostics = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
            "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
            "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
        }
        response_text = response.choices[0].message.content or ""
        parsed_fields = parse_response_json(response_text)
        fields = fill_missing_values(normalize_provider_fields(parsed_fields))
        return {
            "extracted_text": response_text,
            "fields": fields,
            "method": "groq_vision",
            "error": "Not available",
            "error_code": "Not available",
            "groq_diagnostics": {
                "finish_reason": finish_reason,
                **usage_diagnostics,
                "response_json_keys": list(parsed_fields.keys()),
            },
        }
    except Exception as exc:
        logger.warning("Groq extraction failed: %s", exc)
        return run_fallbacks(path, schema, "Groq extraction failed; PDF/OCR fallback was used.")
