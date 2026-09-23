"""Local Florence-2 OCR adapter."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from app.services.local_ocr import extract_fields, fill_missing_values

logger = logging.getLogger(__name__)
_MODEL = None
_PROCESSOR = None


def _model_directory() -> Path:
    configured = os.getenv("LOCAL_OCR_MODEL_DIR", "models/Florence-2-base")
    path = Path(configured)
    return path if path.is_absolute() else Path(__file__).resolve().parents[2] / path


def _load_model() -> tuple[Any, Any] | None:
    global _MODEL, _PROCESSOR
    if _MODEL is not None and _PROCESSOR is not None:
        return _MODEL, _PROCESSOR

    model_dir = _model_directory()
    if not (model_dir / "config.json").exists():
        return None

    try:
        from transformers import AutoModelForCausalLM, AutoProcessor

        _PROCESSOR = AutoProcessor.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=True)
        _MODEL = AutoModelForCausalLM.from_pretrained(
            str(model_dir),
            torch_dtype="auto",
            local_files_only=True,
            trust_remote_code=True,
        )
        _MODEL.eval()
        return _MODEL, _PROCESSOR
    except Exception as exc:
        logger.warning("Local Florence-2 could not be loaded: %s", exc)
        _MODEL = None
        _PROCESSOR = None
        return None


def run_local_florence(path: str, schema: dict[str, Any], reason: str) -> dict[str, Any] | None:
    loaded = _load_model()
    if not loaded:
        return None

    model, processor = loaded
    image_path = Path(path)
    temporary_path: Path | None = None
    try:
        if image_path.suffix.lower() == ".pdf":
            import pymupdf

            with pymupdf.open(path) as document:
                pixmap = document[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                temporary_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                temporary_path = Path(temporary_file.name)
                temporary_file.close()
                pixmap.save(str(temporary_path))
            image_path = temporary_path

        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        task_prompt = "<OCR>"
        inputs = processor(text=task_prompt, images=image, return_tensors="pt")
        generated_ids = model.generate(**inputs, max_new_tokens=2048, num_beams=3)
        text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        try:
            text = processor.post_process_generation(text, task=task_prompt, image_size=image.size)
            if isinstance(text, dict):
                text = text.get(task_prompt, next(iter(text.values()), ""))
        except Exception:
            pass
        text = str(text).strip()
        if not text:
            return None

        return {
            "extracted_text": text,
            "fields": fill_missing_values(extract_fields(text, schema)),
            "method": "local_florence_ocr",
            "error": reason,
            "error_code": "fallback_used",
        }
    except Exception as exc:
        logger.warning("Local Florence-2 inference failed: %s", exc)
        return None
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
