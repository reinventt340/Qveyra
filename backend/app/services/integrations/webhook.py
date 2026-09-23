"""Configuration-driven webhook connector."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from app.services.integrations.base import ConnectorResult


class WebhookConnector:
    name = "webhook"

    def __init__(self, url: str | None, tenant_id: str | None = None) -> None:
        self._url = url
        self._tenant_id = tenant_id

    def _payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._tenant_id:
            return payload
        return {"tenant_id": self._tenant_id, "record": payload}

    def test_connection(self) -> ConnectorResult:
        if not self._url:
            return ConnectorResult(self.name, configured=False, connected=False)
        return ConnectorResult(self.name, configured=True, connected=True, status="Configured")

    def write_record(self, payload: dict[str, Any]) -> ConnectorResult:
        if not self._url:
            return ConnectorResult(self.name, configured=False, connected=False)
        request = urllib.request.Request(
            self._url,
            data=json.dumps(self._payload(payload)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10):
                return ConnectorResult(self.name, configured=True, connected=True, written=True, status="Delivered")
        except Exception:
            return ConnectorResult(self.name, configured=True, connected=False, status="Failed")

    def read_records(self, query: dict[str, Any] | None = None) -> ConnectorResult:
        return ConnectorResult(self.name, configured=bool(self._url), connected=False, readable=False, status="Read not supported")
