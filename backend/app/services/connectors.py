"""Backward-compatible facade for configured data-source connectors."""

from __future__ import annotations

from typing import Any

from app.services.integrations.registry import configured_connectors


def export_to_configured_sources(payload: dict[str, Any]) -> dict[str, Any]:
    """Write confirmed data to explicitly configured connector sinks."""
    result = {"webhook": "Not configured", "csv": "Not configured"}
    for connector in configured_connectors():
        result[connector.name] = connector.write_record(payload).as_status()
    return result
