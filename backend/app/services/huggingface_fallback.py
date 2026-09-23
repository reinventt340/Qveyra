"""Optional Hugging Face vision-model fallback for document extraction."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from app.services.local_ocr import extract_fields, fill_missing_values

logger = logging.getLogger(__name__)
DEFAULT_MODEL = "zai-org/GLM-OCR"


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

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

    raise ValueError("The vision fallback returned an unreadable response.")


def _mime_type(path: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(Path(path).suffix.lower(), "application/octet-stream")


def run_huggingface_fallback(
    path: str,
    prompt: str,
    schema: dict[str, Any],
    reason: str,
) -> dict[str, Any] | None:
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    if not token:
        logger.info("HF_TOKEN is not configured; skipping vision-model fallback")
        return None

    try:
        from huggingface_hub import InferenceClient

        with open(path, "rb") as file_obj:
            encoded = base64.b64encode(file_obj.read()).decode("ascii")

        model_id = os.getenv("HF_MODEL_ID", DEFAULT_MODEL)
        endpoint_url = os.getenv("HF_INFERENCE_ENDPOINT_URL")
        if endpoint_url:
            client = InferenceClient(base_url=endpoint_url, token=token)
        else:
            provider = os.getenv("HF_PROVIDER") or "auto"
            client = InferenceClient(model=model_id, provider=provider, token=token)
        response = client.image_to_text(path, model=model_id)
        response_text = getattr(response, "generated_text", None) or getattr(response, "text", None) or str(response)
        parsed = extract_fields(response_text, schema)
        return {
            "extracted_text": response_text,
            "fields": fill_missing_values(parsed),
            "method": "vision_ocr_fallback",
            "error": reason,
            "error_code": "fallback_used",
        }
    except Exception as exc:
        logger.warning("Vision-model fallback failed: %s", exc)
        return None
