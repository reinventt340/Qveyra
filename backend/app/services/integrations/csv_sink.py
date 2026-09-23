"""Configuration-driven CSV export connector."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.services.integrations.base import ConnectorResult


class CsvConnector:
    name = "csv"

    def __init__(self, path: str | None, tenant_id: str | None = None) -> None:
        self._path = Path(path) if path else None
        self._tenant_id = tenant_id

    def test_connection(self) -> ConnectorResult:
        if self._path is None:
            return ConnectorResult(self.name, configured=False, connected=False)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            return ConnectorResult(self.name, configured=True, connected=True, status="Configured")
        except OSError:
            return ConnectorResult(self.name, configured=True, connected=False, status="Failed")

    def write_record(self, payload: dict[str, Any]) -> ConnectorResult:
        connection = self.test_connection()
        if not connection.connected or self._path is None:
            return connection

        fields = payload.get("result", {}).get("fields", {})
        row = {
            key: value
            for key, value in fields.items()
            if not isinstance(value, (dict, list))
        }
        if self._tenant_id:
            row["tenant_id"] = self._tenant_id

        try:
            with self._path.open("a", newline="", encoding="utf-8") as file_obj:
                writer = csv.DictWriter(file_obj, fieldnames=list(row.keys()))
                if file_obj.tell() == 0:
                    writer.writeheader()
                writer.writerow(row)
            return ConnectorResult(self.name, configured=True, connected=True, written=True, status="Delivered")
        except (OSError, csv.Error):
            return ConnectorResult(self.name, configured=True, connected=False, status="Failed")

    def read_records(self, query: dict[str, Any] | None = None) -> ConnectorResult:
        return ConnectorResult(self.name, configured=self._path is not None, connected=False, readable=False, status="Read not supported")
