"""Local GLM-OCR inference adapter."""

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
    configured = os.getenv("LOCAL_OCR_MODEL_DIR", "models/GLM-OCR")
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
        import torch
        from transformers import AutoProcessor, GlmOcrForConditionalGeneration

        if not torch.cuda.is_available() and os.getenv("ALLOW_CPU_LOCAL_MODEL", "false").lower() != "true":
            logger.warning("CUDA is unavailable; skipping GLM-OCR to avoid slow CPU inference")
            return None

        _PROCESSOR = AutoProcessor.from_pretrained(str(model_dir), local_files_only=True)
        use_cuda = torch.cuda.is_available()
        device = "cuda" if use_cuda else "cpu"
        logger.info("Loading local GLM-OCR on %s", device)
        _MODEL = GlmOcrForConditionalGeneration.from_pretrained(
            str(model_dir),
            device_map="auto" if use_cuda else "cpu",
            torch_dtype=torch.float16 if use_cuda else torch.float32,
            local_files_only=True,
        )
        return _MODEL, _PROCESSOR
    except Exception as exc:
        logger.warning("Local GLM-OCR could not be loaded: %s", exc)
        _MODEL = None
        _PROCESSOR = None
        return None


def run_local_glm_ocr(path: str, schema: dict[str, Any], reason: str) -> dict[str, Any] | None:
    loaded = _load_model()
    if not loaded:
        return None

    model, processor = loaded
    image_path = Path(path)
    temporary_path: Path | None = None
    try:
        if image_path.suffix.lower() == ".pdf":
            import pymupdf
            from PIL import Image

            with pymupdf.open(path) as document:
                page = document[0]
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                temporary_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                temporary_path = Path(temporary_file.name)
                temporary_file.close()
                pixmap.save(str(temporary_path))
            image_path = temporary_path

        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "url": str(image_path.resolve())},
                {"type": "text", "text": "Text Recognition:"},
            ],
        }]
        inputs = processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        inputs = inputs.to(model.device)
        generated = model.generate(**inputs, max_new_tokens=1024)
        generated_trimmed = [output[len(source):] for source, output in zip(inputs.input_ids, generated)]
        text = processor.batch_decode(generated_trimmed, skip_special_tokens=True)[0].strip()
        if not text:
            return None

        return {
            "extracted_text": text,
            "fields": fill_missing_values(extract_fields(text, schema)),
            "method": "local_glm_ocr",
            "error": reason,
            "error_code": "fallback_used",
        }
    except Exception as exc:
        logger.warning("Local GLM-OCR inference failed: %s", exc)
        return None
    finally:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
