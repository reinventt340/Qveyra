"""Helpers for saving invoice extraction outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def save_output_json(filename: str, result: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Persist extraction result to output JSON file and return metadata payload."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"{Path(filename).stem}.json"
    out_path = output_dir / out_name

    payload = {
        "filename": filename,
        "output_file": out_name,
        "result": result,
    }

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    return payload


def load_output_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
